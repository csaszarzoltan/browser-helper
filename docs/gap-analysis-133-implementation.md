# BH 1.33 — Gap Analysis fejlesztések (P0–P2)

> **Forrás:** `docs/gap-analysis-testing-info.md` (2026-08-25) — az ajánlott
> fejlesztési terv mind a 9 tétele megvalósítva, tesztelve és élőben validálva.
>
> **BH v1.33.0** · 9/9 új unit teszt · 80/80 regresszió · 10/10 élő validátor

---

## P0 — Tesztelési alapfolyamat (3 tétel)

### P0-1 · `wait_until_visible` + `wait_ms` a click-ben ⭐

Egy hívásban vár+kattint — megszünteti az SPA hydration race-et.

```bash
curl -X POST http://127.0.0.1:8020/agent/act \
  -H "X-Session-ID: $SID" -H "Content-Type: application/json" \
  -d '{"action":"click","target":{"selector":"[data-view='"'"'research'"'"']"},
       "wait_until_visible": true, "wait_ms": 5000, "observe_after": false}'
```

* A selector nem látszik → legfeljebb `wait_ms`-ig pollol (200ms), utána **404**
  `selector ... not visible after Nms — wait_until_visible=true timed out`.
* Siker esetén a válasz `data.wait_until_visible = {selector, waited_ms}`.
* Default: `wait_until_visible=false`, `wait_ms=5000` (0–30000 clamp) — régi hívások változatlanok.
* **Hatás:** a harness `POST /wait/visible` + `POST /agent/act` két kör helyett egy (~200–400ms/test).

### P0-2 · Drift gate — `auto_recover` selector-ágban is

A selector-click hibánál (`status:"error"`) ha `auto_recover=true` (default):

1. bounded re-wait (`min(timeout,5)s`, visible),
2. egy retry-click,
3. siker esetén `result.auto_recovered = {selector, attempt: 2}`,
4. ha továbbra is hibás → ugyanaz a 404 + candidates út (S4), mint eddig.

**Hatás:** pillanatnyi SPA re-render (snapshot drift) már nem buktatja a tesztet.

### P0-3 · Evidence bundling a harness adapterben

`BrowserHelperAdapter.observe_evidence()` (AI_prod_engine) — az `observe +
console + network + screenshot` három külön `invoke` helyett **egy**
`inspect_page {include_evidence:"console,network,screenshot"}` hívás
(~500ms/test megtakarítás). A BH-oldali `?include=` bundling (v1.29) változatlan.

---

## P1 — Harness megbízhatóság (2 tétel)

### P1-1 · Gyors visible-text + assert bekötés

* `control_plane/api.py` invoker: `read_visible_text` mostantól a BH 1.32-es
  `GET /page/visible-text` fast-pathre megy (idle-wait nélkül), `/eval`
  fallbackkel régebbi BH mellett — a workaround eltűnt.
* Új `assert_dom()` az adapteren + `'assert_dom': '/assert'` path-map.

### P1-2 · Network assertion — `kind="network"`

```bash
curl -X POST http://127.0.0.1:8020/assert -H "X-Session-ID: $SID" \
  -d '{"kind":"network","url_pattern":"/api/v1/","status_min":400,"max_count":0}'
```

* Számolja a gyűjtött CDP request-logból a `status >= status_min` és
  `url_pattern` (substring) találatokat.
* `failure_count > max_count` → **409 assertion_failed** + `details.failures[]`.
* Pass esetén 200 `{result:{kind:"network", failure_count, failures[], passed}}`.
* A DOM-kinds (`selector|text|url`) továbbra is kötelező `value` mezővel
  (validator 422, ha hiányzik) — csak `kind=network` hagyhatja el.
* **Hatás:** „váratlan hiba nincs” assertion 1 hívásban a Python-ciklus helyett.

---

## P2 — Observability + auth + geo (3 tétel)

### P2-1 · Structured logging — `X-Trace-ID` + `GET /logs`

* A middleware minden requestnek ad trace-id-t: bejövő `X-Trace-ID` echo,
  vagy mintelt `tr_<uuid12>`; a válasz mindig visz `X-Trace-ID` headert.
* Minden `log_operation` bejegyzés tartalmazza a `trace_id`-t.
* Új endpoint:

```
GET /logs?trace_id=tr_abc123          # teljes observe→act→assert journey
GET /logs?op=navigate&limit=50
GET /logs?status=error&since=<ISO>
```

* **Hatás:** egy teszt-lépéssor hibakeresése egy lekérdezésből kiolvasható.

### P2-2 · Named auth profiles — egyszer login, korlátlan futás

```
POST /session/auth-profile/production            # save (cookies+storage bundle)
GET  /session/auth-profiles                      # lista (name, saved_at, bytes)
POST /session/auth-profile/production/restore    # restore az aktuális tabra
```

* Bundle fájl: `~/.browser-helper/auth-profiles/<name>.json` — BH restartot túléli.
* Hiányzó profil restore → **404 profile_not_found**.
* **Hatás:** a „human login” killer feature perzisztens lett — névvel ellátott,
  újrafelhasználható auth state a párhuzamos workereknek is.

### P2-3 · Geolocation mock

```
POST /geo/mock      {"lat":47.3769,"lng":8.5417,"accuracy":50}
POST /geo/mock/clear
```

* CDP `Emulation.setGeolocationOverride/clearGeolocationOverride` — a
  location-aware appok (térkép, időjárás) determinisztikusan tesztelhetők.
* Validáció: `lat∈[-90,90]`, `lng∈[-180,180]`, `accuracy>0` (422 rossz inputnál).

---

## Tesztek

**Új:** `tests/test_gap_analysis_v133.py` — 9 teszt:

| # | Teszt | Fedett funkció |
|---|-------|----------------|
| 1 | `test_act_request_accepts_wait_until_visible_fields` | P0-1 modell-mezők + defaultok |
| 2 | `test_wait_ms_bounds_rejected` | P0-1 clamp (30000 felett 422) |
| 3 | `test_assert_network_passes_with_no_failures` | P1-2 pass-ág |
| 4 | `test_assert_network_fails_409_when_failures_exceed` | P1-2 fail→409 + details |
| 5 | `test_trace_id_echoed_and_logged` | P2-1 header echo |
| 6 | `test_logs_endpoint_filters_by_op` | P2-1 `/logs` |
| 7 | `test_auth_profile_list_empty_ok` | P2-2 lista |
| 8 | `test_auth_profile_restore_missing_404` | P2-2 404 |
| 9 | `test_geo_mock_request_validation` | P2-3 validáció |

**Regresszió:** `test_parallel_session_isolation` + `test_agent_api` +
`test_mcp_server` + `test_agent_highlevel` + új suite = **80 passed**.
(A parallel-isolation `_Client` ebben a PR-ban session-mintelőre állt —
BH 1.31+ session-guardhoz illeszkedik; a teszt logika változatlan.)

**Élő validátor (VPS :8020):** 10/10 PASS —

```
P0-1 wait_until_visible timeout→404   PASS
P0-2 auto_recover drift gate          PASS
P1-2 network assert pass/fail         PASS ×2
P2-1 X-Trace-ID echo + /logs corr.    PASS
P2-2 auth profile save/list/404       PASS ×2
P2-3 geo mock set/clear               PASS
P1-2c DOM assert value-validator      PASS
```

---

## Harness-változások (AI_prod_engine)

* `browser_protocol.py`: új `BrowserHelperAdapter.observe_evidence()` és
  `.assert_dom()` — a P0-3/P1-1 bekötési pontok.
* `api.py` invoker: `read_visible_text` → `/page/visible-text` fast-path
  (+ `/eval` fallback), `assert_dom` → `/assert`.

---

## Kompatibilitás

* Minden új mező opcionális, default viselkedés változatlan (`wait_until_visible=false`,
  `include_observation`, `pin_snapshot` stb.) — régi hívók nem törnek el.
* `/assert` DOM-kinds kontraktus változatlan; a `kind=network` bővítmény.
* 47 MCP tool változatlan (REST-szintű bővítés, MCP felület érintetlen).
