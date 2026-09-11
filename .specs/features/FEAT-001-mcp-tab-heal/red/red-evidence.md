# RED evidence — FEAT-001 (2026-09-02, fix előtt rögzítve)

> A teszt a hiányzó funkció miatt bukik — a puszta fájl-lét nem bizonyíték.
> Reprodukció élő rendszeren, a `9380e03`/`4859745` fixek előtt.

## RED-001: stale tab → page/text 503

```bash
R=$(curl -s -X POST 'http://127.0.0.1:8020/session/new?url=about:blank')
S=$(echo $R | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['session_id'])")
T=$(echo $R | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['tab_id'])")
curl -s -m 3 "http://127.0.0.1:9557/json/close/$T"
curl -s -m 25 -X POST http://127.0.0.1:8020/page/text \
  -H 'Content-Type: application/json' -H "X-Session-ID: $S" -d '{}'
```

Várt (RED): `{"detail":"Chrome unavailable: could not launch/connect to CDP
at http://127.0.0.1:9557: Tab not found: CF806C54... The tab may have been
closed..."}` (HTTP 503) — a service-logban `auto-connect to local chrome
failed: Tab not found` stack.

Fix után (GREEN): `{"status":"ok","operation":"get_page_text",
"data":{"status":"ok","text":"",...}}` — a heal új tabot mint és
reconnectel.

## RED-002: act observe 422

```bash
curl -s -m 10 -X POST http://127.0.0.1:8020/agent/act \
  -H 'Content-Type: application/json' -H 'X-Session-Auto: 1' \
  -d '{"action":"observe"}'
```

Várt (RED): `{"code":"unknown_action","message":"Unknown action: observe"}`.
Fix után (GREEN): `{"status":"ok",...,"nodes":5,...}` élő oldalon.
