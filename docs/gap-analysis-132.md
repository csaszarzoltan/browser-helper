# BH 1.32 — Gap Analysis: Tesztelés és információszerzés hatékonyság
> 2026-08-25 · AI_prod_engine E2E csapat + BH fejlesztők

---

## 1. Használati hőtérkép (mi mozog a legtöbbet)

| Hívás                     | Darabszám | Típus | Fő probléma |
|:--------------------------|----------:|:------|:------------|
| `/status`                 | 2565      | CTRL  | — (egészség, konstans) |
| `/health`                 | 2044      | CTRL  | — |
| `/screenshot`             | 861       | TEST  | Összehasonlítás kézzel, `screenshot_diff` hash-különbség, diff jelek nincsenek struktúrálva |
| `/navigate`               | 851       | CTRL  | `waitUntil` nincs felajánlva elég korai hendikep; SPA loading spin-szenzor hiányzik |
| `/eval`                   | 466       | CTRL  | `expression` alias 1.31 óta megvan, de gyakran `document.title` / `innerText` workaround |
| `/sessions`               | 414       | CTRL  | Párhuzamos teszt: `session.save` + restore nincs automatizálva |
| `/tabs`                   | 265       | CTRL  | `deep-scan` drága, `/tabs` riport nem jelez tab-szám-változást |
| `/agent/act`              | 125       | TEST  | Selector click 1.32-ig `Uncaught`; `text` workaround; magyar nav map (+30 sor) |
| `/agent/observe`          | 119       | TEST  | `nodes` vs `elements` váltás 1.31-ig; AX tree flat struktúra |
| `/page/text`              | 60        | TEST  | `wait_ready=true` beragad (SPA-loop); `/page/visible-text` 1.32-ra jött |
| `/fleet/run-batch`        | 56        | TEST  | x3 parallel x12/12 → 91%; izoláció 1.32-ben javítva |
| `/agent/console`          | 55        | INFO  | Kulcs-váltás: `errors` vs `console_errors` + `failures` (1.32 alias fix) |

**Fő csúcs:** 65%-ban health/status screenshot navigate → kontroll; 35%-ban éles teszt+info (agent/observe, console, text). A legtöbb hiba a hídvonalból jön (visszaigazolás POST-után).

---

## 2. Amit a BH 1.32-ben MÁR tud (és a harness nem használ ki)

### 2a. `/assert` — beépített DOM-ellenőrzés (F2, v1.27)
```bash
# exists|not_exists|count|contains × selector|text|url
curl -H "X-Session-ID: $SID" -d '{"kind":"selector","value":"[data-view='research']","condition":"exists"}' /assert
# Válasz: {"passed":true, "found":true, "count":1, ...}
```
**Miért nem használja:** `execution.py:475` helyettesíti Python-oldali `len(text) > 100 or bool(_ax_text)` cikkel — 50%-kal több hálóhívás.

### 2b. `/page/diff` — két lapállapot összehasonlítása
Három lépés: (1) `/page/diff` snapshot, (2) cselekvés, (3) `/page/diff {previous_snapshot}` → "mi változott".  
**Nincs használatban:** a harness baseline-t visz Pythonban (`_dark_mode_html_report`).

### 2c. `/agent/diff` — két kép vizuális összehasonlítása (VLM-assisted)
`url_a` + `url_b` → `diff_image` + `vlm` (vision LLM értékelés).  
**Kihasználatlan:** 6168 sor `geolocation` anti-detection, de nincs REST-outbound geo-mock teszthez.

### 2d. `POST /session/save` — auth state csomag (cookies+localStorage+sessionStorage)
Pillanatnyilag `session.clone` hanya a cookie-kat másolja át, de `session.save` a localStorage-ot is (3956 sor).  
**Gap:** `clone` nem használja `session.save`-et — `sessionStorage`-tartalmak nem jutnak át auth-klónnál.

### 2e. `POST /agent/record` + `/agent/replay` — workflow rögzítés
Teljes click/fill/navigate lánc visszajátszható `recording_id`-vel.  
**Nincs használatban:** harness minden alkalommal kézzel rakja össze a lépéseket.

---

## 3. Valós rés (gap) funkciók — ahol a BH NEM segít (és a harness körbe van húzva)

### P0 — Törés a tesztelés alapfolyamatában

| Gap                         | Mi hiányzik                                                                                      | Mi történik most                                                    |
|:----------------------------|:-------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------|
| **selector wait+click**     | `act({click, selector, wait_until_visible:true})` — SPA render után kattintás                    | Harness 2 külön hívás: `wait` + `act` (race possible)              |
| **snapshot drift gate**     | `observe → assert → act` lánc biztosítása: ha a lap state `snapshot_id` megszűnt, az act ne fusson | Harness `auto_recover`-t használ, de selector-ágban nincs beépítve   |
| **SPA hydration wait**      | `act(wait_js:{condition:"document.querySelector('[data-view]')"})` beépítve egy kattintásnál    | Harness `POST /wait/js` külön hívás; indirekt                      |

### P1 — Információszerzés megbízhatatlansága

| Gap                         | Mi hiányzik                                                                                      | Mi történik most                                                    |
|:----------------------------|:-------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------|
| **content dedup snapshot**  | `observe {if_none_match_snapshot_id:X, if_none_match_content_hash:Y}` — text+node hash egyben     | `if_none_match_snapshot_id` létezik, de content-hash nincs          |
| **structured errors**       | Hiba长征: `Uncaught` / `action_failed` 503 helyett `404 element_not_found` + `candidates` (1.32) | 1.32-ben részben javítva, de `text`/`ref` ágban nincs `candidates` |
| **network assertion**       | `assert {kind:network, url:pattern, status:4xx/5xx, count:0}` — API-hívás ellenőrzés             | `read_network_failures` + Python-cikl → 2 hívás                     |

### P2 — Párhuzamos és egymásra épülő tesztek

| Gap                         | Mi hiányzik                                                                                      | Mi történik most                                                    |
|:----------------------------|:-------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------|
| **parallel session guard**  | `POST /fleet/run-batch` izolációja 1.32 után OK, de `session.clone` nem ad isolated `profile_dir` | `clone` ugyanazt a cookie- tárat használja; localStorage ütközés   |
| **trace timeline export**   | `GET /agent/trace/{run_id}` — lépésenkénti idő + kimenet JSON-ben                                | Harness `_record_agent_step` memóriában; visszaállítás kézzel       |
| **auth_profile_persist**    | `POST /session/auth-profile {name, sid}` → `GET /session/auth-profiles` — névvel ellátott auth state | `clone`/`save/restore` létezik, de nincs név+metadata               |

### P3 — Analitika és benchmark

| Gap                         | Mi hiányzik                                                                                      | Mi történik most                                                    |
|:----------------------------|:-------------------------------------------------------------------------------------------------|:--------------------------------------------------------------------|
| **operation_p50_p95 live**  | `GET /service/metrics?format=json` + per-operation breakdown (navigate, observe, act)             | `GET /service/metrics?format=prometheus` létezik, JSON nincs        |
| **step timing trace**       | `POST /agent/act` → `data.elapsed_ms` + `data.waited_ms` + `data.click_ms`                       | Csak összesített `duration_ms`                                    |
| **screenshot delta JSON**   | `/screenshot/compare` → `pixel_delta` + `diff_image` base64 + `changed_elements` struktúrálva     | `ScreenshotDiffEngine.diff` ad, de `changed_elements` nincs          |

---

## 4. Javasolt fejlesztési roadmap (BH 1.33–1.35)

### 1.33 — Tesztelési alapok megszilárdítása (P0)
- `POST /agent/act` bővítés: `{selector, wait_until_visible:true, wait_ms:5000}` — egy hívásban vár+kattint
- `POST /assert` használatának bemutatása a harness-ben (`execution.py` → `/assert` lecserélése)
- `snapshot_drift_gate` beépítése: `agent/act` `snapshot_id` lejáratkor automatikusan re-observe + retry
- `GET /service/metrics?format=json` — szabványos JSON reply (régi Prometheus mellett)

### 1.34 — Információszerzés hatékonysága (P1)
- `observe {content_hash: true}` — text+node canonical fingerprint egyben
- `assert` / network: `POST /assert {kind:"network", url:"/api/v1/", status:500, count:0}` — API hibák száma
- `POST /agent/trace/{run_id}` — lépésenkénti idő + kimenet + screenshot artifact id JSON
- `GET /session/auth-profiles` + `POST /session/auth-profile {name}` — névvel ellátott, újrafelhasználható auth state

### 1.35 — Specifikus hiányosságok (P2)
- `/agent/act` selector ágba `document.querySelectorAll(sel).length` + candidates visszaadása (most 1.32-ben `0`, `unknown`)
- `POST /page/diff` — baseline-el történő `diff_elements` (`[{selector, type: added|removed}]`)
- `/fleet/run-batch` → `profile_dir` izoláció: `session.clone({profile:"test-worker-1"})` per-worker
- `POST /geo/mock {lat,lng,accuracy}` — REST-ben elérhető geolocation override (anti_detection-ből)
- `POST /screenshot/diff {url_a, url_b}` → `changed_regions: [{x,y,w,h,label}]` bbox-okkal

### 1.36 — További opciók (futó ötletek)
- `POST /agent/act {action:"type", target:{selector}, value:"...", debounce:200}` — SPA debounce
- `GET /page/overflow-x` — vízszintes görgetés mérése (16×16 px gomb = unclickable hiba elkerülés)
- `POST /session/{id}/snapshot-diff` — session-összehasonlítás (két snapshot_id diffje)

---

## 5. Konklúzió

A BH 1.32 integrációs fájdalompontok (6/6) megoldása a tesztelés alapjait stabilizálta. A következő lépés a **tesztelési folyamat hatékonysága**: a beépített funkciók (`/assert`, `/page/diff`, `/agent/record+replay`, `/session/save`) teljes kihasználása 30-50%-kal csökkentheti a harness Python-oldali kódját és a hálóköröket. A P0 (selector wait+click, drift gate) 1-2 napi munka, és a harness 100%-ra viszi a párhuzamos teszteredményt.

*Utolsó frissítés: 2026-08-25, BH 1.32.0 él (127.0.0.1:8020, 69 tests passed, 12/12 live validator).*
