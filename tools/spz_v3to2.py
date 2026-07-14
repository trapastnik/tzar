#!/usr/bin/env python3
"""spz_v3to2.py — конвертация SPZ v3 (Scaniverse 2025+) → SPZ v2.

Legacy-лоадеры (в т.ч. @mkkellogg/gaussian-splats-3d 0.4.7 на tzar/splats)
понимают только SPZ v1/v2. v3 отличается ЕДИНСТВЕННО упаковкой ротаций:
smallest-three (4 Б/сплат: 2 бита индекс наибольшей компоненты + 3×(знак+9 бит))
вместо v2 (3 Б/сплат: int8-xyz нормализованного кватерниона с w≥0).
Остальные секции (positions/alphas/colors/scales/SH) копируются байт-в-байт.
Extensions (flags&0x2), если есть, отбрасываются (v2-лоадеры их не знают).

Формат по официальным исходникам nianticlabs/spz (load-spz.cc).
Использование: python3 spz_v3to2.py in_v3.spz out_v2.spz
"""
import gzip, os, struct, sys, time
import numpy as np

MAGIC = 0x5053474E  # 'NGSP'
SQRT1_2 = 0.7071067811865476


def unpack_smallest_three(rot4):
    """(n,) uint32 → (n,4) float64 кватернионы xyzw, q[iLargest] > 0."""
    n = len(rot4)
    iL = (rot4 >> np.uint32(30)) & np.uint32(3)
    q = np.zeros((n, 4), np.float64)
    # три группы по 10 бит в порядке записи = возрастающие индексы, пропуская iL
    for k, shift in enumerate((20, 10, 0)):
        grp = (rot4 >> np.uint32(shift)) & np.uint32(0x3FF)
        val = (grp & np.uint32(0x1FF)).astype(np.float64) / 511.0 * SQRT1_2
        val[(grp >> np.uint32(9)) & np.uint32(1) == 1] *= -1
        for L in range(4):
            rest = [i for i in range(4) if i != L]
            m = iL == L
            q[m, rest[k]] = val[m]
    s2 = 1.0 - (q * q).sum(1)
    np.clip(s2, 0.0, None, out=s2)
    q[np.arange(n), iL] = np.sqrt(s2)
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    return q


def pack_first_three(q):
    """(n,4) кватернионы xyzw → (n,3) uint8 по правилу v2 (w ≥ 0)."""
    q = q.copy()
    q[q[:, 3] < 0] *= -1
    return np.clip(np.round(q[:, :3] * 127.5 + 127.5), 0, 255).astype(np.uint8)


def selftest():
    """v3-упаковка (по спеке) случайных кватернионов → распаковка → сверка."""
    rng = np.random.default_rng(7)
    q = rng.normal(size=(2000, 4))
    q /= np.linalg.norm(q, axis=1, keepdims=True)
    packed = np.zeros(len(q), np.uint32)
    for i, quat in enumerate(q):
        iL = int(np.argmax(np.abs(quat)))
        neg = quat[iL] < 0
        comp = iL
        for j in range(4):
            if j == iL:
                continue
            negbit = int((quat[j] < 0) != neg)
            mag = int(511.0 * abs(quat[j]) / SQRT1_2 + 0.5)
            comp = (comp << 10) | (negbit << 9) | mag
        packed[i] = comp
    q2 = unpack_smallest_three(packed)
    # знак кватерниона не важен: сравниваем |dot| с 1
    dots = np.abs((q2 * q).sum(1))
    err = np.degrees(2 * np.arccos(np.clip(dots, -1, 1)))
    assert err.max() < 0.35, f"самотест провален: макс. ошибка {err.max():.3f}°"
    return err.max()


def convert(src, dst):
    t0 = time.time()
    raw = gzip.open(src, "rb").read()
    magic, ver, n = struct.unpack("<III", raw[:12])
    sh, frac, flags, _ = struct.unpack("<BBBB", raw[12:16])
    if magic != MAGIC:
        sys.exit("не SPZ: нет магии NGSP после распаковки")
    if ver == 2:
        print("файл уже v2 — копирую как есть")
        open(dst, "wb").write(open(src, "rb").read())
        return
    if ver != 3:
        sys.exit(f"поддерживается только v3 (в файле v{ver})")
    shdim = (sh + 1) ** 2 - 1
    off = 16
    sizes = [n * 9, n, n * 3, n * 3, n * 4, n * shdim * 3]
    need = 16 + sum(sizes)
    if len(raw) < need:
        sys.exit(f"файл обрезан: {len(raw)} < {need} байт")
    parts = []
    for s in sizes:
        parts.append(raw[off:off + s])
        off += s
    pos, alphas, colors, scales, rot4b, shdata = parts
    if flags & 0x2:
        print("ВНИМАНИЕ: extensions отброшены (v2 их не поддерживает)")

    q = unpack_smallest_three(np.frombuffer(rot4b, dtype="<u4"))
    rot3 = pack_first_three(q).tobytes()

    hdr = struct.pack("<IIIBBBB", MAGIC, 2, n, sh, frac, flags & 0x1, 0)
    with gzip.open(dst, "wb", compresslevel=6) as f:
        f.write(hdr + pos + alphas + colors + scales + rot3 + shdata)
    print("v3 → v2: %s сплатов, SH%d, %.1f → %.1f МБ, %.1f c"
          % (format(n, ",").replace(",", " "), sh,
             os.path.getsize(src) / 1e6, os.path.getsize(dst) / 1e6, time.time() - t0))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: spz_v3to2.py in_v3.spz out_v2.spz")
    e = selftest()
    print("самотест упаковки: ok (макс. ошибка %.3f°)" % e)
    convert(sys.argv[1], sys.argv[2])
