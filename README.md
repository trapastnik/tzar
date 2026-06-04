# tzar — 3D-вьюер model3 (FBX ↔ STL)

Сравнительный 3D-просмотрщик: слева фотограмметрия (FBX + PBR-текстуры),
справа очищенная геометрия (STL). Полностью офлайн — three.js и загрузчики в `vendor/`.

## Локально
```bash
python3 -m http.server 8000   # затем http://localhost:8000/
```

## Деплой (сервер ostrov)
```bash
docker compose up -d          # nginx:alpine, порт 8097 → проксируется на tzar.ostrov-vezeniya.ru
```
