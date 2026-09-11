# ID-registry (pilot)

> Minden új FEAT/REQ/AC/TEST azonosítót itt kell bejegyezni a duplikáció
> elkerülésére. Formátum: `ID | cím | státusz`.

| ID | Cím | Státusz |
|---|---|---|
| FEAT-000 | Sablon (nem valós feature) | TEMPLATE |
| FEAT-001 | MCP tab-heal ciklus lezárása (pilot feature) | GATE_PASS 2026-09-11 |
| REQ-001-001 | get_page_text heal ping run_op-on át dead WS után | GATE_PASS 2026-09-11 |
| REQ-001-002 | a11y tree heal ping run_op-on át dead WS után | GATE_PASS 2026-09-11 |
| REQ-001-003 | observe heal ping run_op-on át dead WS után | GATE_PASS 2026-09-11 |
| AC-001-001 | GIVEN halott tab WHEN page/text THEN heal + ok | GATE_PASS 2026-09-11 |
| AC-001-002 | GIVEN halott tab WHEN screenshot/navigate THEN heal + ok | GATE_PASS 2026-09-11 |
| TEST-001-001 | tests/test_session_registry.py + tests/test_mcp_server.py zöld (65) | GATE_PASS 2026-09-11 |
| TEST-001-002 | Élő validáció: stale-tab heal + act observe (10:32 log) | GATE_PASS 2026-09-11 |
