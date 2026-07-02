# tzar — 3D-вьюеры сканов ГМЗ «Царское Село»

Живёт на **https://tzar.ostrov-vezeniya.ru** (VPS ostrov). Два вьюера в одном репозитории:

| URL | Что это | Файлы |
|---|---|---|
| `/` | **v1** — сплит-экран FBX (текстуры) ↔ STL (геометрия), брендинг Сбер + ГМЗ. Полностью офлайн: three.js r160 в `vendor/` | `index.html` = `viewer.html`, `source/`, `textures/`, `1 (1).stl` |
| `/v2/` | **v2** — мультимодельный просмотрщик: выпадающий список моделей, режимы Текстура / Геометрия / Wireframe (цвет линий) / Высота / Уклон / Нормали, поворот модели, **загрузка новых сканов прямо с сайта** (.glb / .stl). three.js с CDN | `v2/index.html`, `v2/*.glb`, `v2/uploads/` (runtime) |

## v2: загрузка сканов

Форма в панели вьюера («Добавить скан») или curl:

```bash
# ключ: ssh ostrov cat /srv/tzar-api.env
curl -X PUT -H "X-Upload-Token: <ключ>" --data-binary @model.glb \
  "https://tzar.ostrov-vezeniya.ru/v2/api/upload?name=Название&ext=glb"   # ext=glb|stl
```

API — `api/app.py` (stdlib-only Python, контейнер `python:3.12-alpine`, host-порт 8086,
проксируется как `/v2/api/`). Валидация: GLB — магия `glTF`; STL — бинарная структура
(80-байтный заголовок + счётчик) или ASCII `solid`. Токен — `UPLOAD_TOKEN` в
`/srv/tzar-api.env` на сервере (вне web-корня, вне git). Загруженное:
`v2/uploads/*` + `v2/models.json` — runtime-данные, в git не входят (.gitignore).
Удаление — кнопка «Удалить» во вьюере или `DELETE /upload?file=uploads/<имя>`.

## Локальная разработка

```bash
python3 -m http.server 8000            # v1: http://localhost:8000/
                                       # v2: http://localhost:8000/v2/ (без api)
# api отдельно: DATA_DIR=/tmp/x UPLOAD_TOKEN=test python3 api/app.py   # :8000
```

## Деплой

Рабочий процесс — через git, сервер является деплой-remote:

```bash
git push origin main    # GitHub (источник правды)
git push server main    # ostrov: /var/www/tzar, receive.denyCurrentBranch=updateInstead
                        # → рабочее дерево обновляется пушем, сайт живой сразу
ssh ostrov 'cd /var/www/tzar && docker compose restart api'   # только если менялся api/app.py
```

Контейнеры на сервере (`docker-compose.yml`): `web` — nginx:alpine, порт 8085 (статика,
ro-mount); `api` — python:3.12-alpine, порт 8086. Маршрутизация — центральный
`infrastructure-proxy-1` (`/srv/infrastructure/proxy.conf`): `location /` → 8085,
`location /v2/api/` → 8086 (вставлен `deploy/insert_proxy.py`). SSL — Let's Encrypt.
