# POST-TASK REVIEW — /home/zoltan/browser-helper, v1.36.18 + v1.36.19 (iteráció 5–6)

```
REPO:        /home/zoltan/browser-helper
COMMITS:     507fd61 (v1.36.18) · 4b29204 (release) · 13ac740 (v1.36.19) · ed4b201 (release) + docs
DISPATCHES:  9 a loopban + 2 audit · LEDGER: ~/.cache/claude-queue/dispatch-log/dispatch-ledger.log
ARTIFACTS:   24 a repoban commitolva (iteration5: 14, iteration6: 10)

SCORES:  brief 4 · target 4 · verification 3 · scope 5 · honesty 4 · evidence 4
VERDICT: REQUEST-CHANGES  (a `verification` 4.0 alatt)
```

## A finding, amiért a review létezik

**A v1.36.18 kapuja mérhetően vak a saját RNG-inicializálására, és semmi a repóban nem bizonyítja a
sleepet, ami a mintázott késleltetést elfogyasztja.** Mindkettőt magam mértem, in-place.

**1. A vak folt — reprodukálva.** A `RateLimiter._rng = random.Random()` (`src/cdp_client.py:78`)
egy **konstans seedre** cserélve (minden példány azonos huzással) a kapu **átengedi**:

```
$ md5sum src/cdp_client.py → 100d90b4b7b5cc218705cb5747fc8401
  [mutate] self._rng = random.Random() → random.Random(12345)
$ .venv/bin/python -m pytest tests/test_rate_limiter.py -o addopts='' -q
  43 passed, 1 warning in 4.58s        ← a kapu VAK
$ git checkout -- src/cdp_client.py ; md5sum -c → OK ; git status --short → üres
```

Az ok: a kapu `rl._rng = random.Random(20260905)`-tel **felülírja** a példány RNG-jét
(`tests/test_rate_limiter.py:265`), így az `__init__` sorát **soha nem érinti** — a teszt a Python
RNG-jét méri, nem a kódot. **És éles kontraszt, ami izolálja:** a v1.36.17 kapuja **elkapja**
ugyanezt a mutánst (`1 failed` a `test_delays_are_non_deterministic`-en), mert a `random.Random`
**osztályt** patch-eli (`tests/test_behavioral_typing.py:320-325`), nem a példányt.

**2. A fogyasztás bizonyítatlan.** A `tester` audit önállóan megfogalmazta, és egyetértek:
*"the pinned-draw gate proves the sampler, and NOTHING in the repo proves the sleep."* A
`src/cdp_client.py:665-668` — `delay_ms = self.rate_limiter.get_delay()`, majd
`await asyncio.sleep(delay_ms / 1000.0)` **csak ha `delay_ms > 0`** — egyetlen teszt sem hajtja meg.
Egy ms/s mértékegység-hiba, a `delay_ms > 0` rövidzár, vagy egy config, ami a sleepet kikapcsolja,
**mind átmenne a zöld kapun**, miközben a produkció paceletlenül küld.

Ez a v1.36.18 **célját nem érvényteleníti** (az orákulum cseréje megtörtént, dokumentáltan), de a
„suite zöld" állítás **szűkebb, mint amit olvasni lehet belőle** — ugyanaz az alak, mint a tegnapi
loop mockolt-kapu hibája, egy szinttel lejjebb.

## PART 0 — a briefek

Mind a 7 kötelező klauzula **9/9 briefben** megvan, **kivéve a 3-ast**:

```
brief                  bytes  c1  c2  c3  c4  c5  c6  c7
explore-5/review-5/...  2690-4712  yes yes yes yes yes yes yes
gate-5                  2816  yes yes  NO  yes yes yes yes
gate-6                  2690  yes yes  NO  yes yes yes yes
                                ^^^ "report every item, even if the answer is NO"
```

**A két hiányzó ugyanaz a két GATE-brief** — a skill pontosan ezt a mintát írta le korábban
(`gate-* … NO NO (all 6)`). Helyette „write the report FIRST… then refine"-t és
`not established`/`PARTIAL`-t kértem. A konzekvencia itt látható: a gate-5 és gate-6 riportok is
folyóprózát írnak, nem számozott item-válaszokat.

**Egy brief-ellentmondás, kétszer elkapva, a mai napon:** a briefjeim fejléce azt írja
*„Do not edit, commit, or run anything that writes"*, az OUTPUT klauzula pedig
*„Second copy inside the repo at …"*. **A kettő nem teljesíthető egyszerre** — és **két agent
függetlenül jelezte**: `bh-explore-5.md:12-20` („the two clauses conflict; the copy was written
because durability requires it") és `ptr2-dev.md` („the load-bearing sentence… versus the OUTPUT
clause… That interpretation is mine, not stated"). **Ez az én brief-hibám, és nem javítottam** —
a következő briefben a helyes megfogalmazás: *„your report file is the one write you may make; it is
not a code edit."*

## PART 1 — mi szállt le, és a ledger

9 dispatch, mind `verdict=OK`, `attempts=1`, `exit=0`. Szerepek: explore(2), reviewer(4),
spec-author(1), developer(2). Wall: 442–1698 s.

**A 58 B-os artifact — a skill „short artifact" szabálya élesben.** A `dev-6` (iteráció 6) artifactja
ennyi volt: `"All four edits are in. Now running the acceptance checks."` — `wall_s=442`, `attempts=1`,
`exit=0`. **Nem stall** (a queue `OK`-nak ítélte, és nincs banner-token: `grep -c 'claude-code:'` = 0).
A **diff döntött**: mind a négy szerkesztés leszállt. A `developer` audit pontosan megmondta, mi
hiányzott: *„all four were intended… zero were evidenced as run… what the developer report could have
proved is nothing beyond the fact that four edits existed."*

**Egy artefakt rossz könyvtárban.** `analysis/loop-artifacts/iteration5/bh-gate-4.out` a **v1.36.17**
kapuja (`repo: … @ c7b8f83`, `test_behavioral_typing.py`), nem a rate_limiteré — de az `iteration5/`-ben
él (az `iteration4/`-ben is megvan, helyesen). **A `tester` audit ezért idézte a v1.36.18 kapujaként**,
és vette át annak számait (`185 passed`, „0/185 flake"). Ez **pontosan az a hibaosztály, amit ma
korábban írtam a skillbe** („check whether a preserved artifact is actually FROM this repository"),
ezúttal könyvtár-elhelyezés formájában. A helyes szám a v1.36.18-hoz a `bh-gate-5.md`: `43 passed`,
M1 `1 failed`, teljes suite `2806 passed`.

**Artifact-túlélés: 24 a repóban** (a tegnapi review 9/32-t talált, 0/8-at egy korábbi loopnál).
Minden iteráció-5 és iteráció-6 brief, `.out` és riport commitolva. **Javulás, és ez az egyetlen
dimenzió, amit a mai javítások egyértelműen rendbe tettek.**

## PART 1d — load-bearingness: PASS

`src/cdp_client.py:132` épít (`self.rate_limiter = RateLimiter()`), `:665` hív
(`delay_ms = self.rate_limiter.get_delay()`) a `_send_command` úton. Nem nulla-hívós eset.
**De ez pont az, ami a findingot élessé teszi:** a symbol élesben terhelt, tehát a benne lévő
vak folt **produkciós**, nem elméleti.

## PART 1e — mandated-step audit: 2 szerep kimaradt, mindkettő indokoltan

```
nevezett: explore, reviewer, spec-author, developer, tester, test-author
lefutott: explore, reviewer, spec-author, developer
HIÁNYZIK: test-author, tester
```

A `gate-5` **magától** megjelölte (`process honesty 4/5`-re pontozva), a `gate-6` pedig 5/5 mellett
`LEGITIMATE`-nek ítélte. **A `tester` audit egyetért, és megadja az indoklást, amit egy külső review
nem tudna:** *„no mock exists in the file at all"*, egyik változás sem beszél wire-protokollt, és
*„the gate independently re-ran exactly the tester checks"*. **Ez az első eset ezen a hoston, ahol a
kihagyott szerep nem hordozott el verifikációt** — és a bizonyíték rá a `test_rate_limiter.py`
mock-mentessége, nem a pontszám.

## PART 2 — az agentek válaszai

**`developer` (12924 B, 13/13)** — a legerősebb audit eddig. Kulcs-állításai verifikálva:
a `507fd61`/`13ac740` tartalma és scope-ja reprodukálódik; a 43/43 tesztnév megvan a törölt
példányból (magam is lefuttattam); a `Q12` hívási lánca pontos (`:132`, `:665`). **Amit hozzáadott,
és amit egy diff-review nem lát:** a `Q13` kimondja, hogy semelyik riportja nem idézte a stall-tokent,
és hogy a `bh-dev-6.out` **helyes verdiktje „incomplete report", nem „no model output"**. A `Q9`
pedig feltárta az archiválás-vs-read-only ütközést, és megindokolta, hogy a **commitot dobta el**,
nem a fájlt — pontosan azt a döntést, amit egy read-only review nem hozhat meg helyette.

**`tester` (8721 B, 6/6)** — a szerep, akit nem hívtam, és aki a legtöbbet adta. Az `1.` item
őszinte: v1.36.18-ra „almost none", v1.36.19-re „none", **és megmondja, mit tenne mégis** (ismételt
futtatás determinizmus-bizonyíték n-szer, mert „a single green run does not prove a flake rate of
zero"). A `3.` item a fenti findingot fogalmazza meg; a `6.` item megnevezi **a konkrét hiányzó
tesztet** (send-path pacing integráció, loopback WebSocket, 3+ parancs, mért gap ≥ `min_delay`).
A `4.` item verifikálja a törlés biztonságát (43/43 név, `md5 a2dc186a` a proxy-páron).

**Egy hiba a tester riportjában, amit magam mértem:** a `bh-gate-4.out`-ot a v1.36.18 kapujaként
idézte, és annak számait (`0/185`) vette át. **A gyökér-ok az én artefakt-elhelyezésem**, nem az ő
gondatlansága — de a szám így is rossz fájlra mutat.

**A két audit NEM mond ellent** — a developer a saját munkájáról, a tester a hiányzó szerepről
beszél, és ugyanarra a hiányra mutatnak: *a verifikáció szűkebb, mint amit a zöld suite sugall.*

## PART 3 — a folyamat

**Scope: tiszta, mindkét commit.** `507fd61` = `tests/test_rate_limiter.py` (94+/17−) + artefaktok;
`13ac740` = pontosan 4 fájl (`M` defekt-dok, `M pyproject`, `D` két gyökér-duplikátum).
Semmi az allowliston kívül.

**Koordináció: nincs ütközés.** Egyik commit sem söpört be más nem-commitolt munkáját. A
`spec-author` most nem commitolt (a mai korrekció után), és a `13ac740` pontosan a szerzője nevét
viseli (`csaszarzoltan`), nem egy dispatchét.

**False-open: nincs.** `DEFECT-001` `Status: fixed (SPEC-6, v1.36.19)` — **a javítással egy
commitban zárva**, pontosan ahogy a szabály kéri. Egyetlen `BLOCKED*`/`*STATUS*` fájl sincs a
repóban.

**Bizonyíték, hogy a kapu tud bukni — in-place, mindkét irányban bizonyítva.** Egy mutáns **átmegy**
(`43 passed`, fent) és egy **elbukik** (`1 failed` a v1.36.17 fájlján) — a kettő együtt izolálja a
különbséget, és mindkettő byte-exact restore-tal (`md5sum -c` OK, fa tiszta).

**A verzió-állítások egyeznek.** `pyproject.toml` / `src/main.py:308` / `Dockerfile` / `README.md`
/ `CHANGELOG.md` mind `1.36.19`; a tag `v1.36.19`, a `/health` `1.36.19 connected=true`;
a README teszt-badge `2806` = a scoped suite mért száma.

## PART 4 — pontszámok

- **brief 4** — 7/7 klauzula 9/9 briefben, kivéve a `report-each`-et a **két gate-briefben**;
  plusz az archiválás-vs-read-only ellentmondás, amit **két agent jelzett** és nem javítottam.
- **target 4** — a v1.36.19 egy három hónapos, valódi defektet zárt (a bare `pytest` nem collectolt),
  a v1.36.18 egy valódi flaky orákulumot; de az utóbbi **célja szűkebb volt, mint amennyit a zöld
  suite állít** (lásd a findingot).
- **verification 3** — a szabály szellemében: *„a green suite over a mocked boundary is evidence
  about the mock"*. Itt nincs mock, **de a kapu saját orákuluma mérhetően vak** (in-place mutáns
  átmegy), és a **fogyasztó sleep bizonyítatlan**. **A megengedő olvasat 4** — a mutelelt-elkapás
  4/4 volt és in-place —, és a kettő közötti különbség maga a finding. 3, mert a „zöld" állítás
  szűkebb, mint amit a bizonyíték fed.
- **scope 5** — mindkét commit pontosan az allowlistán belül, verifikálva.
- **honesty 4** — az agentek kiemelkedően őszinték (a `dev-6` bevallotta a saját hiányát, a
  `spec-author` 5 interpretációt nevesített, az `explore` a brief-hibámat); levonás az én
  brief-hibámért és az artefakt rossz helyéért.
- **evidence 4** — 24 artefakt a repóban (nagy javulás), de a `gate-4` a rossz iterációban él, és
  néhány `.out`-nak nincs `.md` párja.

**Az összesítés nem átlagolás, hanem a leggyengébb dimenzió:** `verification 3 < 4.0` →
**REQUEST-CHANGES**.

## THE FIX — ebben a sorrendben

**1. Brief-klauzula (a legfontosabb, mert minden jövőbeli futást javít).** A két gate-briefbe, és
minden jövőbeli gate-briefbe:

> Read each numbered item and **answer it by name**, in the same order. If an item is impossible,
> answer `not established` **for that item** and say what you checked. Do not replace the numbered
> answers with a running narrative — a scored verdict with no per-item answers cannot be checked.

Miért: mérve, 2/9 brief ma, és a skill már korábban 6/6-ot mért ugyanerre a szerepre. A hiány
következménye látható: a gate-5 és gate-6 riportok folyóprózát adnak.

**2. Brief-klauzula — a read-only és az archiválás ütközése.** Cseréld a
*„Do not edit, commit, or run anything that writes"* + *„write a second copy inside the repo"*
párt erre:

> You may write exactly ONE file: your report, at the two paths named below. That is not a code
> edit and does not violate read-only. Do not edit, commit, or stage anything else.

Miért: **két agent függetlenül jelezte ma** (`bh-explore-5.md:12-20`, `ptr2-dev.md` Q9), és mindkettő
interpretációt kényszerült választani — pontosan az, amit a brief-gate hivatott megszüntetni.

**3. A `reviewer` agent-leírás vagy a gate-brief — az elhelyezés szabálya.** Az
`analysis/loop-artifacts/<iteration>/` **csak a saját iterációjának** artefaktjait tartalmazza; egy
másik iteráció riportja ott **egy hamis kapu**. Miért: mérve — a `bh-gate-4.out` az
`iteration5/`-ben a `tester` auditot **rossz számra** vezette (`0/185` a helyes `43` helyett).

**4. `~/.claude/CLAUDE.md` — a verifikáció terjedelmének kimondása.**:

> A claim that says "the suite is green" must name the command AND the surface it covers. A gate
> that pins a value inside the code under test tests the test, not the code: verify that the
> production line the test is supposed to exercise is actually reached — mutate THAT line and
> confirm the gate fails.

Miért: mérve ma — `self._rng = random.Random()` → `random.Random(12345)` **átmegy** a kapun
(`43 passed`), mert a teszt a saját seedjét írja rá; ugyanez a mutáns **elbukik** a v1.36.17
kapuján, mert az az osztályt patch-eli.

**5. Ez a skill — egy hiányzó kérdés.** A `PART 1d` a *hívót* kérdezi („van-e produkciós caller?"),
de nem kérdezi meg, hogy **a kapu a hívott sort érinti-e**. Add hozzá:

> **Does the gate reach the line it claims to test?** For each production line the change depends
> on, mutate **that line** and confirm the gate fails. A gate that overrides the value under test
> (a pinned RNG assigned onto the instance, a monkeypatched attribute) is testing its own fixture.
> Measured 2026-10-05: a pinned-draw gate passed with the rate limiter's RNG initialisation mutated
> to a constant seed, because the test assigns its own seed onto the instance after construction.

## When the review finds nothing

Nem így volt. **A kód helyes és leszállt — a kapuk zöldek és a defekt zárt.** Amit a review talál,
az a **verifikáció szűkebb hatóköre**, nem egy termékhiba.
