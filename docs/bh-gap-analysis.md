# Browser Helper — Gap Analysis: Tesztelés és Információszerzés Hatékonyság

> **Cél:** feltárni, mi az amit a BH nem tud (vagy nem jól tud), és milyen
> funkciók fejlesztése tenné hatékonyabbá a tesztelést és
> információszerzést rajta keresztül — a harness, az E2E executor, és a
> mindennapi használat alapján.
>
> **Dátum:** 2026-08-25 · BH v1.32.0 · 208 REST endpoint · 47 MCP tool

---

## 1. Mi a BH-ban VAN, de a harness nem használja ki

### 1.1 Nem használt agent API-k (éles)

| Végpont | Miért van | Miért nem használjuk |
|---------|-----------|---------------------|
| `POST /assert` | DOM feltétel: `kind × condition × expected` — egyszeri hívás, nem kell Python-ciklus | Adapter nem MAP-el rá |
| `POST /page/diff` | Baseline → action → diff: `added/removed elements`, `url_changed`, `text_changed` | Kézi screenshot diff van most |
| `POST /agent/diff` | `url_a` + `url_b` → VLM-assisted diff (pixel + leírás) | Nem használjuk, mert a harnessnek egyszerűbb screenshot comparison |
| `POST /agent/record` + `/agent/replay` | Workflow rögzítés, visszajátszás | Kézi steps összerakás van most |
| `POST /agent/extract` | Determinisztikus schema kinyerés: `{schema:{properties:{name,title}}}` → `{data:{name:"AI",title:"..."}}` | Nem próbáltuk ki |
| `POST /agent/forms/discover` + `/agent/forms/fill` | Form felfedezés + kitöltés: `semantic_type` alapján: `email`, `password`, `country` stb. | Manuális type action van |
| `POST /agent/available-actions` | Aktív régió, elérhető formok, kötelező mezők | Nem használjuk |
| `POST /agent/execute-task` | Egyszerű micro-workflow: goal → observe → fill → verify, egy hívás | Túl specifikus |
| `POST /session/save` + `/session/restore` | Cookies + localStorage + sessionStorage csomag, JSON-ben | Session clone alkalmanként nem_restore-ol |

### 1.2 Nem használt session management

| Funkció | Leírás | Miért hiányzik a használatból |
|---------|--------|-------------------------------|
| `POST /session/{id}/clone` | Session klónozás (cookies másolás) | 3 worker egymást éri el: `api.py` global `list[str]` cache — **thread-local fix-eltük** de a clone-t nem használja a harness |
| `GET /sessions` + `GET /session/{id}` | Session l states | Nem ellenőrizzük a session állapotot teszt előtt |

### 1.3 Nem használt network/notify

| Funkció | Leírás | Miért nem használjuk |
|---------|--------|---------------------|
| `POST /network/mock` | Request interception: visszatérít `status:200 + body` bármilyen URL-re | Nem ismerjük, nem próbáltuk |
| `POST /network/block` | Request blokkolás: URL regex → hálózati hiba | Nem próbáltuk |
| `POST /notifications/start` | Toast/alert/notification DOM observer | Nem használjuk, mert nem követjük az SPA notifikációkat |

---

## 2. Mihiányzik a BH-ból (valós gap-ek teszteléshez)

### 2.1 Session izoláció (P0 — a legnagyobb fájdalom)

**Probléma:** Egy tab, több worker → a `x3` parallel 11/12 bukik.

**Amit csinálunk:** `concurrency=1` (soros, lassú).

**Amit BH tudna adni:** `POST /session/{id}/navigate` — session-scoped navigate
(fejlesztés alatt: a `run_op` session-affinitás megoldja, de a harness `BrowserHelperAdapter` egyetlen `session_id`-t használ.)

**Ajánlott megoldás:**
```
POST /fleet/run-batch → session per-worker → isolated tab per test
```
Már megvan a `fleet` intézet, de a harness nem használja a `run-batch`-t
(stock test executor `concurrency` paraméterrel futtatja: `ThreadPoolExecutor(max_workers=concurrency)`).

---

### 2.2 Selector click reliability (P0)

**Probléma:**
- `[data-view='research']` → `Uncaught` volt 1.32-ig, most `404 element_not_found`
  de `matches: 0` — mert a tab `about:blank`-en van, nem a `http://127.0.0.1:8080`-on.
- `{"ref":"e4"}` → `click requires an element reference` — nincs snapshot_id, nincs érvényes ref.

**A harness hozzáállása:** `{"target":{"text":"Kutatás"}}` megy — de a magyar nav mapet kell hozzá:
```python
_HUNGARIAN_NAV = {"research":"kutatás", "portfolio":"portfólió", ...}
```

**Gap:** nincs `selector`-ből intelligens keresés, ha nem talál:
```python
# Most: Először text, ha nem megy → selector
{"target":{"text":"Kutatás"}}  # megy
{"target":{"selector":"[data-view='research']"}}  # 404, nincs candidates-lista
```

**Amit a BH-ban csinálni kéne:**
1. `POST /agent/act click` selector-nál: ha nem talál → nézzen körül, adjon `available_candidates`
2. `POST /page/find` ← már létezik, de nem használjuk
3. `selector` → `DOM.querySelector` + ha `offsetParent === null` → `scrollIntoView` → retry

---

### 2.3 Stale snapshot utáni act (P1)

**Probléma:**
```
observe → snap_abc (snapshot_id)
[SPA frissít, snap lejárt]
act click → 409 StaleSnapshotError
```

**Amit csinálunk:** `auto_recover=True` — de ez csak `ref`-nél működik,
`selector`-nál nincs auto-recovery.

**Gap:** `agent/act` + `selector` + `auto_recover` → ha 409, re-observe + retry.

---

### 2.4 evidence bundling nem használja a harness (P1)

**Amit BH tud:**
```
POST /agent/observe?include=console,network,screenshot → egy hívásban
{
  "data": {
    "snapshot_id": "snap_...",
    "nodes": [...],
    "console": {"count": 2, "errors": [...]},
    "network": {"count": 10, "failures": [...]},
    "screenshot": {"data": "base64...", "format": "jpeg"}
  }
}
```

**Amit csinálunk most (3 külön hívás):**
```python
adapter.invoke("read_console_errors", ...)
adapter.invoke("read_network_failures", ...)
adapter.invoke("capture_screenshot", ...)
```

**Gap:** `BrowserHelperAdapter` nem kínál `observe_evidence()`-t.

---

### 2.5 Fast visible text read (P1)

**Probléma:** `GET /page/text` timeout-tal dolgozik (`wait_ready=true` → 30s).

**Amit BH 1.32 kínál:**
```
GET /page/visible-text → document.body.innerText, 0ms idle-wait
```

**Amit csinálunk:** `adapter.invoke("read_visible_text", ...)` → `/eval {js: document.body.innerText}` — workaround.

**Gap:** a harness `invoke` mappingben nincs `read_visible_text` gyors útvonal.

---

### 2.6 geolocation mock (P2)

**Probléma:** location-aware appok (pl. időjárás, fizetés) teszteléséhez geolocation override kell.

**Amit BH tud:** `anti_detection` csomagban `geolocation` signal — de nincs REST endpoint:
```
POST /geo/mock {"lat": 47.3769, "lng": 8.5417, "accuracy": 100}
```

**Amit csinálunk:** nem tudjuk tesztelni a geolocation-függő route-ot.

---

### 2.7 localStorage / sessionStorage scoped restore (P2)

**Probléma:** `POST /session/save` elment mindent, de `clone` nem hozza át.

**Amit csinálunk:** `clone` után újra be kell jelentkezni — nem tartja a localStorage state-et.

**Gap:** `POST /session/{id}/clone` → `session.save` + `session.restore` chain.

---

## 3. Mi kellene az internetes / ipari best practice-k alapján

### 3.1 Playwright-szintű assertion API (competitor comparison)

| BH | Playwright | Gap |
|----|------------|-----|
| `POST /assert {kind, value, condition}` | `expect(locator).toHaveText()` | Nincs `toHaveAttribute`, `toHaveClass`, `toHaveCSS` |
| `POST /page/diff` | `toHaveScreenshot()` | Nincs visual regression alapból |
| `POST /agent/act {action:"wait_for_element"}` | `page.waitForSelector()` | Nincs `state:"attached\|detached\|visible\|hidden"` |
| `POST /agent/act {action:"click"}` | `locator.click({timeout})` | Nincs `force:true`, `noWaitAfter` |

### 3.2 Sentry/Graylog-szintű structured logging (observability)

| Hiány | Megoldás |
|-------|----------|
| Nincs `trace_id` request szintjén | `X-Trace-ID` header → minden logba bekerül |
| Nincs `span_id` action szintjén | `observe→act→assert` belső timing, `X-Span-ID` header |
| Nincs structured JSON log | `{"ts":"...","op":"navigate","dur_ms":400,"trace_id":"..."}` |
| Nincs log search API | `GET /logs?op=observe&since=...&trace_id=...` |

### 3.3 Auth state porting (SSO login automation)

| Hiány | Megoldás |
|-------|----------|
| Nincs `profile_name` → saved state | `POST /session/profile {name:"production"} → save/restore` |
| Nincs cross-tab auth | Auth state export → import másik tabba |

---

## 4. Mi a legnagyobb hatás, mely funkciókkal fejleszthető

### 🔴 P0 — Sürgős, a harness jelenleg nem tud x3-at futtatni

1. **`POST /session/{id}/navigate`** — session-scoped navigate, ne globális tab
2. **Selector click retry** — `auto_recover` + re-observe selector-nál is
3. **`BrowserHelperAdapter.observe_evidence()`** — egy hívásban console+network+screenshot
4. **Thread-local session isolation** — runner + apiInvoker (✅ megvan 1.32-ben)

### 🟡 P1 — Javítja a harness megbízhatóságát

5. **`/page/visible-text`** gyors beépítés a harnessba (már van, nem használjuk)
6. **Assertion types** — `toHaveAttribute`, `toHaveClass` — általánosabb DOM feltételek
7. **`/agent/record` → `/agent/replay`** beépítés a harnessba — workflow playback
8. **`/agent/extract`** structure extraction — bizonyos tesztnél érték kinyerés

### 🟢 P2 — Fejlesztési hatékonyság, observability

9. **Structured logging** — `X-Trace-ID`, `X-Span-ID` → log search API
10. **Auth state porting** — `profile save/restore` cross-tab
11. **Geolocation mock** — `POST /geo/mock` REST endpoint
12. **Visual regression beépítés** — `POST /screenshot/compare` → `diff_score`

---

## 5. Hogyan lehetne a legtöbbet kihozni a meglévőből (no-code/low-code)

| Megoldás | Mennyi effort | Hatás |
|----------|---------------|-------|
| `BrowserHelperAdapter.observe_evidence()` használata | 1 óra | 3→1 hálókör, -500ms/test |
| `/page/visible-text` beépítése `read_visible_text`-ként | 0.5 óra | idle-wait elkerülés |
| `/assert` beépítés a harnessba (selector exists/not_exists) | 2 óra | Egyszerűbb assertion, nincs Python-ciklus |
| `x3` parallel használata session isolation után | 0.5 óra | 3× gyorsabb sorosnál |
| `/agent/record` → `/agent/replay` beépítés | 3 óra | Workflow repetition automatizálás |

---

## 6. Priorizált fejlesztési terv (hogy hatékonyabb legyen a tesztelés)

### Sprint 1: Stabilizáció (1 hét)
- Thread-local session isolation véglegesítése ✅
- `BrowserHelperAdapter.observe_evidence()` implementálás
- `select` + `auto_recover` → re-observe + retry selector-nál

### Sprint 2: Harness korszerűsítés (2 hét)
- `/page/visible-text` gyors útvonal beépítés
- `assert` endpoint beépítés a harnessba
- `x3` parallel tesztelés valós appon

### Sprint 3: Observability (2 hét)
- Structured JSON log (trace_id + span_id)
- `/logs` search API
- Performance dashboard (per-operation p50/p95)

### Sprint 4: Geolocation + Auth state (3 hét)
- `POST /geo/mock` REST endpoint
- `POST /session/profile {name}` — auth state save/restore per name
- Cross-tab auth state import

---

*Gap analysis 2026-08-25, BH v1.32.0, 208 endpoints, 47 MCP tools, 69 tests passed, 12/12 live validator.*
