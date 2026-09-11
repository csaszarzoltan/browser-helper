# VERITAS L1 Pilot — Project Policy (browser-helper)

> Státusz: PILOT (2026-09-11). Ez a repo **Project Policy** szintű VERITAS-bevezetése.
> A kanonikus lab-módszertan továbbra is a micro-saas-lab `docs/METHODOLOGY.md`-je;
> ez a dokumentum csak a VERITAS-pilot helyi szabályait rögzíti. Lab-szintű
> átvételről külön döntés születik a pilot kiértékelése után.

## Hatály

- **R2+ változásokra** (új tool, új viselkedés, API/UI/integráció-változás):
  `.specs/features/FEAT-XXX/` spec + RED + traceability kötelező.
- **R0/R1-re** (doksi, formázás, kis visszafordítható fix stabil oracle-lel):
  Fast Path — inline Change Contract a commit-üzenetben + célzott teszt.

## Kockázati osztályozás (gyors)

| Osztály | Jellemző | Pálya |
|---|---|---|
| R0 | doksi, formázás, viselkedéssemleges | Fast |
| R1 | kis, visszafordítható fix, stabil oracle, változatlan contract | Fast |
| R2 | új/módosuló viselkedés, API, UI, integráció | Standard |
| R3 | security, privacy, pénzügy, breaking contract, migráció | Standard + emberi review |
| R4 | policy/alkotmányos változás | csak emberi jóváhagyással |

Kétség esetén **felfelé** minősítünk. Lefelé minősítéshez emberi jóváhagyás kell.

## Definition of Done (R2+)

- [ ] Minden REQ implementálva (spec §5)
- [ ] RED evidence mentve (`red/` — bukó futás logja a fix előtt)
- [ ] Célzott teszt zöld (`TEST-*.py` vagy meglévő suite)
- [ ] Teljes regresszió zöld (vagy impact-indokolt rész + indoklás)
- [ ] `ruff` + `release-validate.sh` zöld
- [ ] Traceability: commit-footerekben `REQ-`, `TEST-` hivatkozás
- [ ] Emberi review ( Validity-döntés: megoldja-e a valós problémát? )
- [ ] Service health `connected:true` újraindítás után (ha runtime-ot érint)

## Szerepek ebben a pilotban

- **Product Authority / Human Authority:** a repo gazdája (te).
- **Spec Author + Test Author + Implementer:** subagentek, szétválasztva —
  az Implementer nem módosíthatja a saját tesztjét (§1/8. alkotmányos szabály).
- **Reviewer:** külön olvasó menet (ember vagy kritikus-agent).
- **Runner:** `scripts/veritas-gate.sh` + pytest (determinisztikus, R0 szint).

## Ami NEM része a pilotnak

Governor, Context Fitness formális kalibráció, R2/R3 Runner (daemon, policy
engine, microVM, dual control, aláírt policy), teljes 16 pontos spec R1-re.
Ezekről a pilot kiértékelése (§14.1 szellemében: overhead-mérés) után döntünk.
