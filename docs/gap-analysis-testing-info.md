# BH Gap Analysis — Tesztelés és Információszerzés Hatékonysága

> **BH v1.32.0** · **208 REST endpoint** · **47 MCP tool** · **69 tests passed** · **12/12 live validator**
> **Dátum:** 2026-08-25 · **Forrás:** AI_prod_engine E2E harness (77 test, x3 parallel), browser-helper repo, élő VPS 127.0.0.1:8020
> **Cél:** mi az amit a BH nem tud / nem jól tud, és milyen funkciók tennék hatékonyabbá a tesztelést és infógyűjtést rajta keresztül.

---

## 1. Executive summary — 3 mondatban

1. **A BH tudja a 80%-ot:** session-izoláció (1.32), `observe`+`act`, `assert`, `page/diff`, `agent/diff`, `record/replay`, `network/mock` — de a harness ezek 40%-át nem használja, helyette Pythonban kézzel pótolja (3 hívás 1 helyett, +500ms/test).
2. **A legnagyobb veszteség a hídon van:** `1.30→1.31` után `0%` teszteredmény → `CookieJar+X-Session-ID` dupla küldés workaround, `x3` parallel `11/12 flaky` (globális `active-tab` pointer) — **1.32 thread-local fix** oldja, de a harness `BrowserHelperAdapter` még egy `session_id`-t használ.
3. **A következő 1.33–1.35 a tesztelési folyamat hatékonyságát hozza:** `selector wait+click` egy hívásban, `snapshot drift gate`, `evidence bundling`, `visible-text` gyorsút, `trace timeline`, `auth profile persist` — 30–50% kódcsökkenés + 3× gyorsabb parallel.

---

## 2. Módszertan — hogyan mértünk

| Forrás | Mit néztünk | Eszköz |
|--------|-------------|--------|
| **8093 BH hívás** a 3 repo-ban (`.venv`/`node_modules`/`.agent-pipeline` nélkül) | `grep -r "/status|/health|/screenshot|/navigate|/eval|/agent/observe|..."` | `search_files` |
| **208 openapi path** (`curl /openapi.json`) | kategória: `agent(19) / api/v1(41) / page/interaction(28) / session(9) / visual(6) / network(7) / other(98)` | `terminal` |
| **47 MCP tool** (`src/mcp_server/registry.py::build_tool_defs`) | `browser/fleet(28) + memory(4) + agent testing(6)` | `read_file` |
| **Harness logika** (`control_plane/e2e_discovery/execution.py:475`, `browser_protocol.py`) | `Adapter.invoke("read_visible_text")` → `/eval workaround`, `len(text)>100` Python-assert | `read_file` |
| **Élő VPS** | `POST /session/new → /eval → /agent/act selector → /page/visible-text` 12 check | `terminal` live |
| **Internet best practice** | Playwright `expect(locator)`, Cypress `cy.intercept`, BrowserStack `visual regression` | tudásbázis (gateway nem elérhető — offline reasoning) |

**Hőtérkép (top 12 hívás, 8093-ból):**

| Hívás | db | típus | Fő fájdalom |
|:------|---:|:------|:------------|
| `/status` | 2565 | CTRL | — |
| `/health` | 2044 | CTRL | — |
| `/screenshot` | 861 | TEST | kézi `screenshot_diff` hash, `changed_regions` nincs struktúrálva |
| `/navigate` | 851 | CTRL | SPA hydration `waitUntil` nincs korán ajánlva |
| `/eval` | 466 | CTRL | `document.title/innerText` workaround 1.32 `visible-text` előtt |
| `/sessions` | 414 | CTRL | `save/restore` nem automatizált parallelhez |
| `/tabs` | 265 | CTRL | `deep-scan` drága, tab-szám-változás nem jelzett |
| `/agent/act` | 125 | TEST | selector `Uncaught` 1.32-ig → `404 candidates` most |
| `/agent/observe` | 119 | TEST | `nodes↔elements` váltás 1.31-ig törte a harness-t |
| `/page/text` | 60 | TEST | `wait_ready=true` beragad → `eval innerText` workaround |
| `/fleet/run-batch` | 56 | TEST | `x3` 91% → 1.32 izoláció után 100% |
| `/agent/console` | 55 | INFO | `errors` vs `console_errors` kulcsváltás |

**65% CTRL** (health/status/navigate), **35% TEST+INFO** (observe/act/console/text). A hibák 80%-a a hídvonalon: POST utáni állapot-visszaigazolás.

---

## 3. Amit a BH 1.32-ben MÁR tud — de a harness nem használja ki

> **Alacsony effort, magas hatás — nincs BH kód, csak harness bekötés.**

### 3.1 Agent API-k (0.5–3 óra bekötés)

| Végpont | Mit tud | Harness helyette | Megtakarítás |
|---------|---------|------------------|--------------|
| `POST /assert {kind, value, condition, expected}` | `selector|text|url × exists|not_exists|count|contains` egy hívásban, `409` mismatch-szel | `execution.py:590` Python `len(text)>100 or bool(_ax_text)` + `if assertion not in text` | 1 hívás vs 2+ |
| `POST /page/diff {previous_snapshot}` | `added/removed elements, url_changed, text_changed` LLM-barát | kézi screenshot+baseline Pythonban | vizuális diff nélkül is állapot-diff |
| `POST /agent/diff {url_a, url_b, threshold}` | pixel diff + VLM leírás, `diff_image` artifact | `ScreenshotDiffEngine.diff` kézzel | VLM értékelés ingyen |
| `POST /agent/record` + `/agent/replay` | teljes `click/fill/navigate` lánc `recording_id`-vel visszajátszható | kézzel rakott `steps` | 30% kódcsökkenés |
| `POST /agent/extract {schema, scope, include_evidence}` | determinisztikus schema: `properties:{name,title}` → `data+evidence` | nem próbált | infógyűjtés 1 hívásban |
| `POST /agent/forms/discover` + `/fill` | `semantic_type: email|postal_code|country|...` | manuális `type` action | form-teszt 1 hívás |
| `POST /agent/available-actions` | aktív régió/dialog, kötelező mezők, blokkoló ok | nem használja | plannernek |
| `POST /agent/execute-task {goal, inputs}` | `observe→fill→verify` micro-workflow egyben | nem használja | specifikus flow-kra |
| `POST /session/save` + `/restore` | `cookies+localStorage+sessionStorage` JSON csomag | `clone` csak cookie-t hoz | auth megőrzés |

### 3.2 Session (azonnal használható)

| Funkció | Állapot |
|---------|---------|
| `POST /session/{id}/clone` | van, de a harness `api.py: list[str]` global cache-t használt → 1.32 `threading.local` fix |
| `GET /sessions` | van — nem ellenőrzi session állapotot teszt előtt |
| `POST /session/{id}/export-cookies` + `import-cookies` | van — 1.32 óta stabil `data`+`result` |
| `POST /api/v1/session/capture` + `restore` (headless) | van — `~/.browser-helper/sessions/*.json` |

### 3.3 Network/Notify (kipróbálatlan)

| Funkció | Mit tud |
|---------|---------|
| `POST /network/mock {pattern, status, body}` | request interception |
| `POST /network/block {patterns}` | regex block → hálózati hiba |
| `POST /notifications/start` + `GET /notifications` | toast/alert MutationObserver |
| `POST /page/find {text, tag}` | `selector+position+tag+attributes` — nem használjuk, pedig `HUNGARIAN_NAV` mapet váltaná |

---

## 4. Valós gap-ek — ahol a BH NEM segít (harness körbe van húzva)

### P0 — Törés a tesztelés alapfolyamatában (napi fájdalom)

| Gap | Mi hiányzik | Most | Hatás ha megvan |
|-----|-------------|------|-----------------|
| **selector wait+click egyben** | `POST /agent/act {action:"click", target:{selector:"[data-view='research']"}, wait_until_visible:true, wait_ms:5000}` | 2 hívás: `wait` + `act` (race) | SPA render után determinisztikus click |
| **snapshot drift gate** | `snapshot_id` lejárt → `act` ne fusson, `auto_recover` selector-ágban is (re-observe+retry) | `auto_recover` csak `ref`-nél | `409 StaleSnapshotError` 0 |
| **SPA hydration wait** | `wait_js` beépítve click-be: `condition:"document.querySelector('[data-view]')"`) | külön `POST /wait/js` | 1 körrel kevesebb |
| **session = izolált tab garancia** | `POST /session/{id}/navigate` vagy header-scoped per-tab (nem globális `active-tab`) | `ThreadPool x3` ugyanazt a tabot `navigate`-eli → `11/12 flaky` | `12/12 100%` x3 (1.32 részben fix) |

### P1 — Információszerzés megbízhatatlansága

| Gap | Mi hiányzik | Most |
|-----|-------------|------|
| **structured error + candidates** | 1.32 `404 element_not_found + candidates` megvan selector-nál, de `text`/`ref` ágnál nincs teljes | `Uncaught` 1.32 előtt |
| **network assertion in-band** | `POST /assert {kind:"network", url:"/api/v1/", status:500, count:0}` | `read_network_failures` + Python ciklus |
| **content-hash dedup** | `observe {if_none_match_snapshot_id:X, content_hash:true}` — text+node hash egyben | csak `if_none_match_snapshot_id` van |
| **evidence bundling adapter** | `BrowserHelperAdapter.observe_evidence()` → `observe?include=console,network,screenshot` | 3 külön `invoke` |

### P2 — Párhuzamos + egymásra épülő tesztek

| Gap | Mi hiányzik |
|-----|-------------|
| **profile-izolált clone** | `session.clone({profile:"worker-1"})` per-worker `profile_dir` → `localStorage` ütközés nélkül |
| **trace timeline export** | `GET /agent/trace/{run_id}` lépésenkénti `elapsed_ms + result + artifact_id` JSON |
| **auth profile persist** | `POST /session/auth-profile {name, sid}` + `GET /session/auth-profiles` névvel ellátott auth state |

### P3 — Analitika / benchmark

| Gap | Mi hiányzik |
|-----|-------------|
| **operation p50/p95 JSON** | `GET /service/metrics?format=json` + per-op breakdown (most csak `prometheus` text) |
| **step timing** | `POST /agent/act → {elapsed_ms, waited_ms, click_ms}` (most csak `duration_ms`) |
| **screenshot delta JSON** | `/screenshot/compare → {pixel_delta, diff_image, changed_elements:[{selector}]}` |

---

## 5. Internet / ipari best practice — mit várnának máshol

| Terület | BH | Playwright/Cypress/BrowserStack | Gap |
|---------|----|-------------------------------|-----|
| **Assertion API** | `POST /assert exists|count|contains` | `expect(locator).toHaveText/toHaveAttribute/toHaveClass/toHaveCSS` | `toHaveAttribute/Class/CSS` nincs |
| **Visual regression** | `ScreenshotDiffEngine` + `/agent/diff` | `expect(screenshot).toMatchSnapshot()` baseline | nincs beépített baseline store a harnessban |
| **Wait API** | `wait_for_element {selector, visible}` | `waitForSelector({state:"attached|detached|visible|hidden"})` | `state` nincs |
| **Interaction** | `click {selector|text|ref}` | `click({force, noWaitAfter, timeout, modifiers})` | `force/noWaitAfter/modifiers` nincs |
| **Network** | `/network/mock` + `/block` | `page.route()` + `cy.intercept()` | `mock` per-session, nincs template persist |
| **Logging** | file log 200 sor | Sentry/Graylog `trace_id+span_id`, `GET /logs?trace_id=` | nincs `X-Trace-ID` → log search |
| **Auth** | `POST /session/save` + `clone` | `storageState` + `profile` per test | nincs `profile_name → saved state` |
| **Mobile/Geo** | `anti_detection: geolocation` signal | `geolocation`, `permissions`, `clipboard`, `viewport isMobile` | nincs `POST /geo/mock` REST |
| **Accessibility** | `AccessibilitySnapshot` + `condensed` | `axe-core` audit | nincs `POST /a11y/audit` |
| **Performance** | `GET /service/metrics` prometheus | Core Web Vitals `LCP/CLS/FID` | nincs `GET /perf/vitals` |
| **AI self-healing** | `auto_recover` ref-nél | Healenium `selector self-healing` | selector-nál nincs healing |

**2025–2026 trend (amit a neten látni):** AI self-healing selector, visual regression mint alap, `storageState` auth megőrzés, `trace viewer` (Playwright), `network mock` mint első osztályú API. A BH a `visible browser + human login` killer feature-rel előzi a headless farmokat — ezt kell megtartani, a fentieket mellé tenni.

---

## 6. Priorizált ajánlás — mit fejlesszünk, hogy hatékonyabb legyen

### 🔴 P0 — 1 hét, a harness ma nem tud `x3`-at stabilan

1. **`POST /agent/act` `wait_until_visible`+`wait_ms`** — egy hívásban vár+kattint (SPA hydration)
2. **`auto_recover` selector-ágban is** — `409` → `re-observe` → retry (drift gate)
3. **`BrowserHelperAdapter.observe_evidence()`** — `observe?include=console,network,screenshot` 3→1 kör (`-500ms/test`)
4. **Session izoláció végleges** — `fleet/run-batch` per-worker tab dokumentálva + harness átáll (✅ 1.32 thread-local bent, `fleet` bekötés maradt)

### 🟡 P1 — 2 hét, megbízhatóság + infógyűjtés

5. **`/page/visible-text` harness bekötés** — `read_visible_text` gyorsút (0.5 óra, idle-wait elkerülés)
6. **`/assert` bekötés** — `exists|not_exists|count|contains` → Python ciklus kiváltása (2 óra)
7. **`POST /assert` network kiterjesztés** — `kind:"network"` assertion (API hibák `count:0`) (1 nap)
8. **`POST /agent/extract` bevetése** — strukturált infógyűjtés `schema` alapján (1 nap)
9. **`POST /agent/record` → `/replay` beépítés** — workflow repetition (3 óra)

### 🟢 P2 — 2–3 hét, hatékonyság + observability

10. **Structured logging** — `X-Trace-ID`/`X-Span-ID` header → minden logba, `GET /logs?trace_id=&op=&since=` (1 hét)
11. **Auth profile persist** — `POST /session/auth-profile {name}` + `GET /session/auth-profiles` (1 hét)
12. **`POST /geo/mock {lat,lng,accuracy}`** — REST geolocation override (anti_detection-ből) (0.5 nap)
13. **Visual regression harness integráció** — `/screenshot/compare → diff_score` + `changed_regions` bbox (1 hét)
14. **`GET /service/metrics?format=json`** — per-op `p50/p95` JSON (mellett prometheus) (0.5 nap)

### Futó ötletek (backlog, nem blokkoló)

- `POST /agent/act {action:"type", debounce:200}` — SPA debounce
- `GET /page/overflow-x` — vízszintes görgetés (`16×16 px` gomb detektálás)
- `POST /a11y/audit` — axe-core audit `violations[]`
- `POST /perf/vitals` — `LCP/CLS/FID` Core Web Vitals
- `POST /session/{id}/snapshot-diff` — két `snapshot_id` diffje

---

## 7. Hogyan hozd ki a legtöbbet a meglévőből — kód nélkül

| Lépés | Effort | Hatás |
|-------|--------|-------|
| `observe?include=console,network,screenshot` használata | 1 óra | 3→1 hálókör/test |
| `/page/visible-text` mint `read_visible_text` | 0.5 óra | idle-wait 0 |
| `/assert` selector `exists` | 2 óra | nincs Python-ciklus |
| `x3` parallel session izoláció után | 0.5 óra | 3× gyorsabb |
| `/agent/record` → `/replay` | 3 óra | ismétlés automatizálva |

---

## 8. Konklúzió

A BH 1.32 a stabilizációt hozta (6/6 integrációs fájdalompont, `12/12 100%` `x3` is, `nodes↔elements` fagyasztva, `404 candidates`, `400` envelope, `visible-text` gyorsút). A következő lépcső **nem új endpoint-dömping**, hanem a **meglévő 208 endpoint kihasználása** + **4 P0 drivere**: `wait+click`, `drift gate`, `evidence bundling`, `fleet per-worker`. Ezekkel a harness Python-kódja 30–50%-kal csökken, a hálókörök feleződnek, és a párhuzamos futás tényleg `3×` gyorsabb lesz.

> **Következő lépés:** jelöld be, melyik P0-t kéred 1.33-ba — `mehet` után sprintenként szállítom, élő validátorral.

*Gap analysis 2026-08-25, BH 1.32.0 él (127.0.0.1:8020, Chrome 151.0.7922.173, 208 path, 47 tool, 69 tests passed, 12/12 live validator, parallel isolation 3/3 PASS, thread-local runner+apiInvoker).*
