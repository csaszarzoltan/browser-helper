# Perf Phase 2 — v1.28.4 → v1.29.0 terv

> Kiinduló állapot: **v1.28.4** élő (1641ms BH vs 3163ms PW = 1.9×). Következő ugrás **3×** PW fölé.
> Forrás: éles mérés (navigate 299 + observe 467 + act 347 + verify 528).

## Prioritás és hatás

| # | Tétel | Hatás journey-nként | Effort | Függőség |
|---|---|---|---|---|
| P1-4 | `POST /agent/observe?include=console,network,screenshot` bundling | **~500ms** (3→1 kör) | 1 nap | önálló |
| P2-8 | keep-warm tab `http://127.0.0.1:8080` mindig nyitva | ~400ms cold-start megtakarítás | 2 óra | önálló |
| P2-9 | `GET /metrics` + `GET /status` p50/p95 latency | benchmark hitelesség | 2 óra | P1-4 után érdemes |
| P1-5 | `fleet/run_batch` sharding 4 workerre verifikáció | **30s→6s** 5 journeynél | 1 nap | önálló |
| NEW | snapshot 304 fingerprint cache (If-None-Match) | ~200ms verify-nél | 1 nap | P1-4 után |

## 1. P1-4 bundling — a legnagyobb ROI

**Most:** `observe 467 + /agent/console 320 + /network/requests 300 + screenshot` = 3 kör, 1.1s.
**Terv:** `POST /agent/observe` body `include: ["console","network","screenshot"]` → egy válaszban `nodes + console_entries + network_failures + screenshot_b64`. Szerver oldalon `asyncio.gather` a 3 CDP callra.

API:
```json
POST /agent/observe {"mode":"accessibility","max_nodes":50,"include":["console","network"]}
→ {"data":{"snapshot_id":"...","nodes":[...],"console":{"count":2,"errors":[...]},"network":{"failures":[...]}}}
```

Back-compat: `include` hiányában mai viselkedés, nincs breaking change.

## 2. Keep-warm + metrics

- `systemd` `ExecStartPost=curl -s http://127.0.0.1:8020/session/new?url=http://127.0.0.1:8020/` — vagy BH belső `background_task` a `lifespan` végén.
- `GET /status` mellé `latency_p50_ms: {navigate,observe,act}`, `uptime_s`.
- `GET /metrics` Prometheus text — `bh_cdp_duration_seconds{op="observe"}` histogram.

## 3. Fleet verifikáció

- `POST /fleet/run_batch` már létezik — élő 5-journey sharding mérés, doc `docs/perf-prioritized.md` kiegészítés.

## 4. 304 cache

- `POST /agent/observe {"since_snapshot_id":"snap_...","if_none_match":true}` → ha fingerprint egyezik, `304 {unchanged:true, snapshot_id}` (20ms vs 500ms). Verifynél különösen hasznos.

## Megvalósítási sorrend ebben a PR-ban

1. **P1-4 bundling** (kód + test + élő mérés)
2. **keep-warm + metrics** (kód + test)
3. Docs frissítés (`docs/perf-prioritized.md`, `CHANGELOG`, `README` marad 47 tool)

Fleet és 304 külön PR — ez a PR marad fókuszált és reviewozható.
