# BRIEF-001: MCP tab-heal ciklus lezárása

## Probléma

A böngésző-helper Chrome-ja restart/tabhalál után az MCP-útvonalon
(`get_page_text`, `browser_get_accessibility_tree`, `observe`) nem gyógyult:
közvetlenül a (halott) session-kliensre hívtak, `run_op` →
`_ensure_browser` heal nélkül → `Not connected to Chrome CDP`, miközben a
REST-út (`page/text`, `screenshot`) ugyanakkor már healt.

## Célcsoport és használati kontextus

Agent-kliensek, amelyek MCP stdio-n át használnak megfigyelő toolokat
hosszú session-ökben (Chrome-restart túlélése kötelező).

## Kívánt, megfigyelhető eredmény

Chrome-restart vagy tabhalál után az első MCP `get_page_text` / a11y-fa /
`observe` hívás automatikusan újracsatlakozik és adatot ad, kézi
`POST /connect` nélkül.

## Sikermérés

- Stale-tab reprodukció (tab `json/close`, majd `page/text`): `status:ok`
  (előtte: `503 Chrome unavailable`).
- `act {"action":"observe"}` élő oldalon: `ok`, `nodes>0` (előtte: 422).
- `tests/test_session_registry.py` + `tests/test_mcp_server.py`: 65 zöld.

## Scope

- `src/mcp_server/tools.py`: `get_page_text`, `browser_get_accessibility_tree`,
  `observe` → `run_op`-on keresztüli heal ping.
- Validáció élő Chrome-on + regressziós suite.

## Non-scope

- Új MCP tool, API-szerződés-változás, Governor/Runner-infrastruktúra.

## Érintett rendszerek

`src/mcp_server/tools.py`, `src/main.py` (`run_op`, `_ensure_browser`),
`src/cdp_client.py` (`connect_to_target`), `tests/`.

## Kockázatok

R2: MCP megfigyelő toolok viselkedése változik (eddig hiba → most heal).
Visszafordítható egy commit-reverttel.

## Bizonytalanságok

Nincs blokkoló — a reprodukció és a fix is élő rendszeren bizonyított
(2026-09-02, 10:32 log + monitor `port=UP`).

## Kapcsolódó evidence

- Reprodukció: tab `GET /json/close/<id>` → `page/text` → 503 (fix előtt).
- Fix után: `screenshot`/`navigate`/`page/text` stale sessionön mind `ok`.
- Monitor: `/tmp/chrome-monitor.log` folyamatos `port=UP`.
