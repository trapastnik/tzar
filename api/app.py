#!/usr/bin/env python3
"""tzar v2 upload API — приём GLB-сканов для мультимодельного вьюера.

stdlib-only (без pip), работает в python:3.12-alpine и на локальном 3.9.
Данные: /data/uploads/*.glb + /data/models.json (только загруженные модели;
базовые 5 зашиты во вьюере). Auth: заголовок X-Upload-Token == env UPLOAD_TOKEN.

Эндпоинты (за прокси видны как /v2/api/...):
  GET    /health            → {ok, uploads}
  PUT    /upload?name=<имя>&ext=glb|stl|splat|ply|ksplat|spz → тело = сырой файл;
         валидация: glb — магия 'glTF'; stl — бинарная структура/ASCII 'solid';
         ply — магия 'ply'; spz — gzip-магия; splat/ksplat — токен и размер
  DELETE /upload?file=uploads/<slug>.<ext>
  POST   /meta?file=uploads/<slug>.<ext>&rot=x,y,z,w → сохранить ориентацию
         (кватернион) модели в models.json — вьюеры применят её у всех
"""
import json, os, re, struct, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DATA = os.environ.get("DATA_DIR", "/data")
UPLOADS = os.path.join(DATA, "uploads")
MODELS = os.path.join(DATA, "models.json")
TOKEN = os.environ.get("UPLOAD_TOKEN", "")
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "512"))
LOCK = threading.Lock()


def load_models():
    try:
        with open(MODELS, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_models(lst):
    tmp = MODELS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MODELS)  # атомарно: nginx никогда не отдаст полфайла


def slugify(name):
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-").lower()
    return s or "scan-" + str(int(time.time()))


def looks_stl(first, length):
    """Бинарный STL: 80б заголовок + uint32 n + n*50б (размер сходится). ASCII: начинается с 'solid'."""
    if first[:5].lower() == b"solid":
        return True
    if len(first) >= 84:
        n = struct.unpack("<I", first[80:84])[0]
        return 84 + 50 * n == length
    return False


class H(BaseHTTPRequestHandler):
    server_version = "tzar-api/1"

    def _json(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(b)

    def _drain(self, n):
        """Дочитать тело перед ответом-отказом, иначе клиент может не увидеть ответ."""
        left = n
        while left > 0:
            c = self.rfile.read(min(1 << 20, left))
            if not c:
                break
            left -= len(c)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self._json(200, {"ok": True, "uploads": len(load_models())})
        else:
            self._json(404, {"error": "not found"})

    def do_PUT(self):
        u = urlparse(self.path)
        if u.path != "/upload":
            return self._json(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not TOKEN or self.headers.get("X-Upload-Token", "") != TOKEN:
            if 0 < length <= MAX_MB * 1024 * 1024:
                self._drain(length)
            return self._json(401, {"error": "неверный ключ загрузки"})
        if length <= 0:
            return self._json(411, {"error": "length required"})
        if length > MAX_MB * 1024 * 1024:
            return self._json(413, {"error": "файл больше %d МБ" % MAX_MB})

        q = parse_qs(u.query)
        disp = (q.get("name", [""])[0] or "").strip() or "Скан " + time.strftime("%d.%m %H:%M")
        ext = (q.get("ext", ["glb"])[0] or "glb").lower()
        if ext not in ("glb", "stl", "usdz", "splat", "ply", "ksplat", "spz"):
            self._drain(length)
            return self._json(400, {"error": "ext должен быть glb|stl|usdz|splat|ply|ksplat|spz"})

        first = self.rfile.read(min(4096, length))
        if ext == "glb" and first[:4] != b"glTF":
            self._drain(length - len(first))
            return self._json(415, {"error": "это не GLB (нет магии glTF) — нужен бинарный .glb"})
        if ext == "stl" and not looks_stl(first, length):
            self._drain(length - len(first))
            return self._json(415, {"error": "это не STL (ни бинарная структура, ни ASCII 'solid')"})
        if ext == "ply" and first[:3].lower() != b"ply":
            self._drain(length - len(first))
            return self._json(415, {"error": "это не PLY (нет магии 'ply')"})
        if ext == "spz" and first[:2] != b"\x1f\x8b":
            self._drain(length - len(first))
            return self._json(415, {"error": "это не SPZ (нет gzip-магии)"})
        if ext == "usdz" and first[:4] != b"PK\x03\x04":
            self._drain(length - len(first))
            return self._json(415, {"error": "это не USDZ (нет zip-магии PK)"})
        # splat/ksplat магии не имеют — доверяем токену и лимиту размера

        os.makedirs(UPLOADS, exist_ok=True)
        base = slugify(disp)
        with LOCK:
            fn, i = base + "." + ext, 2
            while os.path.exists(os.path.join(UPLOADS, fn)):
                fn = "%s-%d.%s" % (base, i, ext)
                i += 1
            tmp = os.path.join(UPLOADS, "." + fn + ".part")
            got = len(first)
            with open(tmp, "wb") as f:
                f.write(first)
                while got < length:
                    chunk = self.rfile.read(min(1 << 20, length - got))
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
            if got != length:
                os.remove(tmp)
                return self._json(400, {"error": "обрыв: получено %d из %d байт" % (got, length)})
            os.replace(tmp, os.path.join(UPLOADS, fn))
            lst = load_models()
            entry = {"name": disp, ext: "uploads/" + fn,
                     "size": length, "ts": time.strftime("%Y-%m-%d %H:%M")}
            lst.append(entry)
            save_models(lst)
        self._json(200, {"ok": True, "model": entry})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/meta":
            return self._json(404, {"error": "not found"})
        if not TOKEN or self.headers.get("X-Upload-Token", "") != TOKEN:
            return self._json(401, {"error": "неверный ключ загрузки"})
        q = parse_qs(u.query)
        rel = q.get("file", [""])[0]
        if not re.fullmatch(r"uploads/[A-Za-z0-9_.-]+\.(glb|stl|usdz|splat|ply|ksplat|spz)", rel) or "/../" in rel:
            return self._json(400, {"error": "bad file"})
        try:
            rot = [float(x) for x in q.get("rot", [""])[0].split(",")]
            if len(rot) != 4:
                raise ValueError
        except ValueError:
            return self._json(400, {"error": "rot должен быть кватернионом x,y,z,w"})
        with LOCK:
            lst = load_models()
            hit = [m for m in lst if rel in (m.get("glb"), m.get("stl"), m.get("usdz"), m.get("splat"), m.get("ply"), m.get("ksplat"), m.get("spz"))]
            if not hit:
                return self._json(404, {"error": "нет в списке"})
            hit[0]["rot"] = rot
            save_models(lst)
        self._json(200, {"ok": True, "model": hit[0]})

    def do_DELETE(self):
        u = urlparse(self.path)
        if u.path != "/upload":
            return self._json(404, {"error": "not found"})
        if not TOKEN or self.headers.get("X-Upload-Token", "") != TOKEN:
            return self._json(401, {"error": "неверный ключ загрузки"})
        rel = parse_qs(u.query).get("file", [""])[0]
        # только uploads/<одно-имя>.<ext> — '/' в имени не пройдёт, traversal исключён
        if not re.fullmatch(r"uploads/[A-Za-z0-9_.-]+\.(glb|stl|usdz|splat|ply|ksplat|spz)", rel) or "/../" in rel:
            return self._json(400, {"error": "bad file"})
        with LOCK:
            lst = load_models()
            keep = [m for m in lst
                    if rel not in (m.get("glb"), m.get("stl"), m.get("usdz"), m.get("splat"), m.get("ply"), m.get("ksplat"), m.get("spz"))]
            if len(keep) == len(lst):
                return self._json(404, {"error": "нет в списке"})
            save_models(keep)
            try:
                os.remove(os.path.join(DATA, rel))
            except FileNotFoundError:
                pass
        self._json(200, {"ok": True})

    def log_message(self, fmt, *args):
        print("%s %s" % (self.address_string(), fmt % args), flush=True)


if __name__ == "__main__":
    os.makedirs(UPLOADS, exist_ok=True)
    print("tzar-api :8000 data=%s max=%dMB token=%s"
          % (DATA, MAX_MB, "set" if TOKEN else "MISSING!"), flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8000), H).serve_forever()
