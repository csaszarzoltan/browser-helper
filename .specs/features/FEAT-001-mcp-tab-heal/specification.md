# FEAT-001: MCP tab-heal ciklus lezárása — specifikáció

> Verzió: `v1` · Státusz: `SPEC_READY` · Kockázat: `R2` · Pálya: `standard`
> (A megvalósítás már megtörtént 2026-09-02-án; ez a spec a pilot
> traceability-demonstrációja: visszamenőleg rögzíti a már bizonyított
> viselkedést. Új munkánál a spec a megvalósítás ELŐTT készül.)

## 1. Cél és felhasználói eredmény

Az MCP megfigyelő toolok túlélik a Chrome-restartot/tabhalált: az első
hívás újracsatlakozik és adatot ad, kézi beavatkozás nélkül.

## 2. Kontextus és források

- User-report: "3 maradék bug" (2026-09-02) — Hiba 1
  (`get_page_text`/`browser_get_accessibility_tree` → `Not connected`).
- VERITAS-pilot: `.specs/policy/project-policy.md`.

## 3. Scope / Non-scope

Lásd `brief.md`. Implementáció: `9380e03` (+ előzmény `4859745`).

## 4. Szereplők és előfeltételek

- Előfeltétel: élő service (`browser-helper.service` 8020), Chrome 9557.
- Szereplők: MCP stdio kliens, session-registry, `_ensure_browser`.

## 5. Funkcionális követelmények

| ID | Követelmény |
|---|---|
| REQ-001-001 | `get_page_text` MCP-hívás dead WS után `run_op`-on át healt és szöveget ad |
| REQ-001-002 | `browser_get_accessibility_tree` dead WS után healt és fát ad |
| REQ-001-003 | `observe` dead WS után healt és snapshotot ad |

## 6. Nem funkcionális követelmények

| ID | Követelmény |
|---|---|
| NFR-001-001 | Regresszió: `test_session_registry` + `test_mcp_server` zöld (65 teszt) |
| NFR-001-002 | Service `health` restart után `connected:true`, monitor `port=UP` |

## 7. UI-szerződés

Nincs (backend-only).

## 8. Felhasználói és GUI-folyamat

Nincs.

## 9. Állapotmodell

Session-tab: `connected` → (Chrome-halál) → `disconnected` →
első MCP-hívás → `_ensure_browser` → `recreate+reconnect` → `connected`.

## 10. API-, esemény- és adatszerződés

Változatlan envelope (`tool_result`/`tool_error`); hibakód-változás nincs,
csak a korábbi `failed/Not connected` esetek válnak `ok`-vá.

## 11. Acceptance scenario-k

| ID | Scenario | Lefedi |
|---|---|---|
| AC-001-001 | GIVEN halott tab WHEN `page/text` THEN heal + `status:ok` | REQ-001-001 |
| AC-001-002 | GIVEN halott tab WHEN `screenshot`+`navigate` THEN heal + `ok` | REQ-001-002/003 |

## 12. Tesztleképezés

| Requirement | Scenario | Teszt |
|---|---|---|
| REQ-001-001..003 | AC-001-001/002 | TEST-001-001: `test_session_registry.py` + `test_mcp_server.py` (65 zöld) |
| REQ-001-001..003 | AC-001-001/002 | TEST-001-002: élő validáció — stale-tab heal + act observe (10:32) |

## 13. Kockázatok és emberi döntések

Emberi döntés: a heal ping minden megfigyelő hívásnál +1 `get_tabs`
kör — elfogadott overhead (idempotens, olcsó).

## 14. Nyitott kérdések

Nincs.

## 15. Rollback és megfigyelhetőség

Rollback: `git revert 9380e03`. Megfigyelhetőség: service log
(`tab reconnect failed (recreating tab)`), `/tmp/chrome-monitor.log`.

## 16. Definition of Done

Teljesítve: RED→fix→célzott+teljes regresszió (ismert 3 pre-existing
failure-rel), `ruff`/szintaxis OK, health `1.35.3 connected:true`,
emberi review (user-validáció 10:32).
