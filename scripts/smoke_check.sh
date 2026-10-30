#!/usr/bin/env bash
set -euo pipefail
BASE="${1:-http://127.0.0.1:8787}"
echo "== health =="
curl -sf "$BASE/api/v1/health" | head -c 200; echo
echo "== login =="
TOKEN=$(curl -sf -X POST "$BASE/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "token ok"
echo "== meta =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/meta"; echo
echo "== snapshot =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/metrics/snapshot" | python3 -c "import sys,json; d=json.load(sys.stdin); print('cpu', d.get('host',{}).get('cpu_pct'), 'fs', len(d.get('filesystems') or []))"
echo "== history =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/metrics/history?metric=cpu.pct&step=60" | python3 -c "import sys,json; d=json.load(sys.stdin); print('points', len(d.get('points') or []))"
echo "== disks =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/disks" | python3 -c "import sys,json; d=json.load(sys.stdin); print('fs', len(d.get('filesystems') or []), 'smart', len(d.get('smart') or []))"
SID=$(curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/disks" | python3 -c "import sys,json; s=json.load(sys.stdin).get('smart') or []; print(s[0]['id'] if s else '')")
if [[ -n "$SID" ]]; then
  echo "== smart detail $SID =="
  curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/disks/$SID/smart" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id'), 'healthy', d.get('healthy'))"
fi
echo "== docker =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/docker/containers" | python3 -c "import sys,json; d=json.load(sys.stdin); print('containers', len(d.get('containers') or []))"
echo "== alerts =="
curl -sf -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/alerts?limit=5" | python3 -c "import sys,json; d=json.load(sys.stdin); print('items', len(d.get('items') or []))"
echo "SMOKE OK"
