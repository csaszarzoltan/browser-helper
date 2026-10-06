# SPEC-6 — DEFECT-001: a repo-root pytest collection javítása

Status: accepted. Source: `explore` (bh-explore-6, 10530 B) + `reviewer` (bh-review-6, 20216 B),
mindkettő fuggetlenul ugyanezt a fixet adta, es az orchestrator minden allitasukat reprodukalta.

## A hiba (merve, HEAD 3cb1bf2)

A repo-gyokerben levo bare `pytest` **el sem indul**:

```
$ .venv/bin/python -m pytest --collect-only -q -p no:randomly -o addopts=''
2849 tests collected, 2 errors in 5.68s
ERROR tests/test_proxy_pool_enhanced.py
ERROR tests/test_rate_limiter.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
```

Az ok: `tests/__init__.py` nem letezik, tehat a pytest ket kulonbozo gyokerbol ugyanazon a modulneven
importalja ugyanazt a fajlnevet (`import file mismatch`). A root-duplikatumok git-kovetettek.

**Es a root `test_rate_limiter.py` elavult:** meg mindig a REGI, flaky `kstest(p > 0.05)` orakulumot
tartalmazza (`:240-252`), amit a v1.36.18 (`507fd61`) epp lecserelt — a `tests/` peldanyban. A root
peldany 431 sor / 18961 B, a `tests/` peldany 512 sor / 23028 B. Semmit nem tartalmaz, ami kell.

## Item 1 — Target Files allowlist (soronkent)

- **TORLES:** `test_proxy_pool_enhanced.py` (gyoker) — byte-identikus a `tests/` peldannyal
  (`md5 a2dc186a...` mindkettoben). Nulla egyedi tartalom.
- **TORLES:** `test_rate_limiter.py` (gyoker) — a `tests/` peldany szigoruan ujabb es jobb;
  az egyetlen elteres az `507fd61` hunk (a pinnelt kapuk) es a `:403` defaults-reset. Nulla
  egyedi, meg kivant tartalom.
- **MODOSITAS:** `pyproject.toml` — `testpaths = ["tests"]` a `[tool.pytest.ini_options]` ala.
- **MODOSITAS:** `.agent-pipeline/04_defects/DEFECT-001-repo-root-pytest-cannot-collect.md` —
  a harom elavult allitas javitasa (lasd Item 4) + Status: fixed.
- **NEM valtozik:** `tests/__init__.py` **NEM jo** (flips the import regime for ~2800 tests;
  egyedul hagyva MINDKET peldanyt collectalhatova teszi -> visszahozna a flaky root orakulumot).
  Egyetlen `src/` fajl sem valtozik.

## Item 2 — a valtozas

```bash
git rm test_proxy_pool_enhanced.py test_rate_limiter.py
```
es a `pyproject.toml` `[tool.pytest.ini_options]` blokkjaba (`:32-39`):
```toml
testpaths = ["tests"]
```

## Item 3 — acceptance criteria (FUTASSTD, mind a negy)

```bash
cd /home/zoltan/browser-helper
# A1 — a duplikatumok eltuntek
git ls-files | grep -E '^test_.*\.py$' ; echo "exit=$?"     # vart: nincs kimenet, exit=1
# A2 — a config be van allitva
grep -n 'testpaths' pyproject.toml                            # vart: testpaths = ["tests"]
# A3 — a bare-root collect MOST mar tiszta (ez volt a hiba)
timeout 200 .venv/bin/python -m pytest --collect-only -q -p no:randomly -o addopts='' 2>&1 | tail -3
#    vart: nincs "ERROR", nincs "Interrupted", exit 0
# A4 — a scoped kapu ZOLD marad
timeout 590 .venv/bin/python -m pytest tests/ -o addopts='' --no-header -q -p no:randomly \
  --ignore=tests/test_parallel_session_isolation.py 2>&1 | tail -1
#    vart: 2806 passed, 0 failed
```

## Item 4 — a DEFECT-001 fajl harom elavult allitasa (a reviewer merte)

1. **`:46` "byte-identical duplicates"** — csak a `test_proxy_pool_enhanced` par az; a
   `test_rate_limiter` par ELTERT (`cmp`: byte 10871, line 241) a `507fd61` ota.
2. **`:52-53, :74-75` a Chrome-guard** — MAR JAVITVA (`38e9def`): a
   `tests/test_parallel_session_isolation.py:112-123` `st.get("browser_available")`-t assertal
   a `try`-ban, tehat a "szolgaltatas fut, de nincs Chrome" eset `pytest.skip`, nem bukas.
   **Ne javitsd ujra.**
3. **`:14-18, :25-26` a "two failing tests"** — azok `skip`-pelnek, nem buknak.

## Item 5 — a stop command

```bash
cd /home/zoltan/browser-helper && \
  .venv/bin/python -m pytest --collect-only -q -p no:randomly -o addopts='' 2>&1 | grep -cE '^ERROR|Interrupted' && \
  git ls-files | grep -cE '^test_.*\.py$'
```
Kesz, ha: **0** ERROR/Interrupted es **0** gyoker-szintu `test_*.py`.

## Do NOT decide

- Ne javitsd ujra a Chrome-guardot (`38e9def` mar megtette).
- Ne add hozza a `tests/__init__.py`-t.
- Ne nyulj a nyitott verdikthez (`v20261005134000-741226`) — az a mockolt-suite hibat nevezi,
  es ez az item mas hibat javit.
- Ne valtoztasd a verziot (ez nem release, hanem repo-hygiene fix) — VAGY ha release, akkor
  v1.36.19, mind az 5 felulten + CHANGELOG a MERT szammal.
