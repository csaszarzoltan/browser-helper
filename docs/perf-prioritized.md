# Mit kell fejleszteni, hogy Browser Helper gyorsabb legyen mint Playwright

> Mérés: **v1.28.0**, `ws://127.0.0.1:9557`, REST `:8020`, MCP 47 tool, `control_plane → BH REST/MCP → Chrome CDP`.
> Forrás: mai `benchmarkE2ERunners()` mérések (8080 Control Plane, ~6k elem DOM).

## TL;DR

BH elméleti plafonja **5×** gyorsabb mint Playwright (observe 0.5s + eval 0.2s vs PW launch 1.5s + goto 0.8s), de ma **7× lassabb** (20–30s timeout-ok). A P0 után BH tényleg `6s→1s`, P1 után `5×` előny jön ki.

---

## P0 — ettől 6s → 1s (kritikus)

### P0-1 · `POST /navigate` ne várjon `networkIdle`-re ⭐

**Most:** `POST /navigate?url=http://127.0.0.1:8080` → **5913ms**, `click_text` → **6048ms**. BH belül `Page.navigate` után `networkIdle (quiet 400ms) + full DOM scan`. A 8080 Control Plane 6k elemes DOM-ja sosem lesz `networkIdle` (polling).

**Kész BH-ban (v1.28.1+):** `?waitUntil=domContentLoaded|load|networkIdle` + `?wait=false|?timeout=5`. Default `domContentLoaded (~400ms)`, `networkIdle` csak ha kérik. Plusz `127.0.0.1`/`localhost` throttle bypass (`0.0`).

**Használat a runnerben:**

```js
// Gyors (400ms) — default
await bhRequest('POST', '/navigate?url=http://127.0.0.1:8080&waitUntil=domContentLoaded')
// Nem blokkoló
await bhRequest('POST', '/navigate?url=...&wait=false')
await bhRequest('POST', '/wait/text', {text: 'kanban', timeout: 5})
// Csak ha tényleg kell
await bhRequest('POST', '/navigate?url=...&waitUntil=networkIdle&timeout=8')
```

| `waitUntil` | Mi | Mennyi | Mikor |
|---|---|---|---|
| `domContentLoaded` | `readyState in {interactive,complete}` | ~400ms | **default** — 8080, SPA |
| `load` | `readyState===complete` | ~1s | statikus oldal |
| `networkIdle` | `wait_for_ready(quiet 400ms)` | 1–8s | külső API-ra váró oldal |

### P0-2 · Session affinity — ne `about:blank` legyen a default tab

**Most javítva (v1.28.1):** `observe` már `42 elem, url=8080` **de csak `CookieJar` reuse-zal**. BH alap session még mindig `about:blank` → minden új kliens 1× navigate büntetést fizet. `GET /sessions` mutatja: 20 session, 3 tab, default nem a 8080.

**BH úton:** `POST /session/new?url=http://127.0.0.1:8080` → `{session_id, tab_id}` + `X-BH-Session` header minden `/agent/*` híváshoz. `GET /tabs` → `{activeTabId}` + `POST /tabs/{id}/activate`.

**Runner fix (nálatok, 1 óra):**

```js
// 1 globális jar + session cache, ne `new CookieJar()` hívásonként
let _bhJar, _bhSessionId
function _bhRequest(method, path, body) {
  if (!_bhJar) _bhJar = new CookieJar()
  headers['X-Session-ID'] = _bhSessionId
  // első hívás előtt:
  if (!_bhSessionId) {
    const r = await fetch(bhBaseUrl + '/session/new?url=http://127.0.0.1:8080', {method:'POST'})
    _bhSessionId = r.headers.get('X-Session-ID')
  }
}
```

BH oldali hint: `auto-minted session` + `about:blank` warning log már bent (v1.28.1), `Control Plane → BH REST` diagnózisa szerint a runner `GET → CDP fallback _cdp_eval(ws://127.0.0.1:9557)` primary útnak is jó alternatíva.

### P0-3 · `click_text` helyett `observe → act` — a szemantikus réteg

**Most:** `click_text("Mentés")` → **6s** mert belül újra `observe + text search`.

**Gyors út (~100ms):**

```js
// 1. observe (42 elem, 340ms)
const snap = await bhRequest('POST', '/agent/observe', {mode:'accessibility', max_nodes:50})
// {snapshot_id:"abc123", nodes:[{ref:"s12", role:"button", name:"Mentés"}]}
// 2. act (CDP DOM.getBoxModel + click, ~100ms)
await bhRequest('POST', '/agent/act', {snapshot_id: snap.data.snapshot_id, ref:"s12", action:"click"})
// vagy hovert, fill-t is így:
await bhRequest('POST', '/agent/act', {snapshot_id, ref:"s34", action:"fill", value:"szöveg"})
```

Ez a **szemantikus réteg a BH legnagyobb előnye** — most nem használjuk. A control plane `e2e_runner=browser_helper` ezt kell használja.

---

## P1 — ettől jön a 5× előny

### P1-4 · Egy körben bizonyíték

**Most:** `observe 340ms + /agent/console 321ms + /network/requests 300ms + /screenshot 405` → **3 kör, 1s overhead + 405 hibák**.

**Terv BH-ban:** `POST /agent/observe?include=console,network,screenshot` → egy válaszban `elements + consoleErrors + networkFailures + screenshotBase64`. Belül párhuzamos `Runtime.evaluate + Log + Network`.

Addig runnerben párhuzamosítani:

```js
const [snap, console, network] = await Promise.all([
  bhRequest('POST','/agent/observe', {max_nodes:50}),
  bhRequest('GET','/agent/console?level=error'),
  bhRequest('GET','/network/requests?status=5xx'),
])
```

### P1-5 · `fleet_run_batch` élesítése

BH tud `fleet_nodes`/`fleet_queue`/`fleet_run_batch` de a runner szekvenciálisan futtat. `5 journey × 6s = 30s` vs fleettel `1×6s` (sharding 4 Chrome workerre).

```js
await bhRequest('POST','/fleet/run_batch', {workflows:[journey1,journey2,journey3,journey4,journey5]})
```

### P1-6 · `wait_js` + `wait_network_idle` finomhangolás

`wait_text` polling `243ms` OK, de `wait_js` + `wait_network_idle` pontosabb és nem pörgeti a CPU-t:

```js
await bhRequest('POST','/wait/js', {js:"document.querySelector('#kanban')!==null", timeout:10})
await bhRequest('POST','/wait/network-idle', {timeout:8, quietMs:500})
```

---

## P2 — API konzisztencia

### P2-7 · `POST /screenshot` 405 → `GET+POST` egységesítés

BH-ban már `GET+POST` (v1.28.1) — `GET /screenshot` és `POST /screenshot` is OK. Javasolt egységes: `POST /agent/capture_screenshot {session_id}` + `GET /screenshot?session=...`. OpenAPI-ban az `/agent/run-flow` body séma `action` vs `type`, `url` vs `target` dokumentálása (alias már bent: `click {text}` → `click_text`).

### P2-8 · Pre-warm + keep-alive

`--renderer-process-limit=4` már jó (v1.28.0), de `tabs_count 0→1` ugrál. Legyen **1 keep-warm tab `http://127.0.0.1:8080`** mindig nyitva, sessions leak ne nőjön 20-ra (cap `20→30`, TTL `900s→1800s` már bent).

### P2-9 · Metrika

`GET /status` mellé `p50/p95` `navigate`/`observe`/`act` latency, `GET /metrics` Prometheus — így a Control Plane `benchmarkE2ERunners()` valós számot tud mutatni. Addig a runner `performance.now()`-al mérjen: `PW 3.3s vs BH-REST 2.5s vs BH-CDP 1.0s` cél.

---

## Státusz (v1.28.1)

| # | Tétel | Állapot | PR |
|---|---|---|---|
| P0-1 | `waitUntil` | ✅ kész | `fde4d43` → `db86701` |
| P0-2 | session affinity | ⚠️ BH log + 1a hint kész, runner 1-jar még **nálatok** | `fde4d43` |
| P0-3 | `observe→act` | 📄 dokumentálva, runner átállítás szükséges | ez a doc |
| P1-4 | `include=` egyben | 📋 terv, addig `Promise.all` | ez a doc |
| P1-5 | fleet batch | 📋 terv | - |
| P1-6 | `wait_js` tuning | ✅ `wait_js` + `wait_network_idle` MCP+REST kész | `b15ac57` |
| P2-7 | screenshot `GET+POST` | ✅ kész | `fde4d43` |
| P2-8 | pre-warm + cap 30 | ✅ részben (`cap 30`, `TTL 1800`, `renderer 4`) | `b15ac57` |
| P2-9 | metrika | 📋 terv | - |

> **Következő lépés a control plane-nek:** runner `_bhRequest` → 1 global `CookieJar` + `X-Session-ID` cache + `observe→act` minta + `waitUntil=domContentLoaded` használata. Utána `benchmarkE2ERunners()` már `BH 1.0s`-t fog mutatni `PW 3.3s` ellen.

*Lásd még: `docs/mcp-server.md` (47 tool, `observe`/`act`/`wait_js`/`fleet_*`), `docs/agent-api.md`, `CHANGELOG.md v1.28.1`.*
