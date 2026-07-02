#!/usr/bin/env python3
"""Вставить location /v2/api/ в 443-блок tzar в центральном proxy.conf (идемпотентно)."""
import shutil, sys, time

P = "/srv/infrastructure/proxy.conf"
s = open(P).read()
if "/v2/api/" in s:
    print("already present, nothing to do")
    sys.exit(0)

bak = P + ".bak." + str(int(time.time()))
shutil.copy(P, bak)

lines = s.split("\n")
# 443-блок tzar: строка server_name tzar..., в 3 строках выше которой есть listen 443
idx = None
for i, ln in enumerate(lines):
    if "server_name tzar.ostrov-vezeniya.ru" in ln:
        if "443" in "\n".join(lines[max(0, i - 3):i + 1]):
            idx = i
            break
if idx is None:
    print("ERROR: tzar 443 block not found")
    sys.exit(1)

loc = None
for j in range(idx, min(idx + 40, len(lines))):
    if lines[j].strip().startswith("location / {"):
        loc = j
        break
if loc is None:
    print("ERROR: location / not found after tzar 443 server_name")
    sys.exit(1)

block = """    location /v2/api/ {
        proxy_pass http://172.17.0.1:8086/;
        client_max_body_size 512m;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_request_buffering off;
        proxy_set_header Host $host;
    }"""
lines[loc:loc] = [block]
open(P, "w").write("\n".join(lines))
print("inserted at line %d, backup: %s" % (loc + 1, bak))
