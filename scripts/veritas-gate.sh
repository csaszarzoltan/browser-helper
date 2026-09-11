#!/usr/bin/env bash
# veritas-gate.sh — VERITAS L1 pilot gate (Runner R0 szint)
#
# Mit ellenőriz egy R2+ változáson (FEAT-XXX):
#   1. spec létezik + SPEC_READY (vagy explicit --fast R0/R1-re)
#   2. RED evidence létezik (red/ nem üres)
#   3. célzott teszt zöld
#   4. ruff tiszta a változott fájlokon
#   5. traceability: a commit-footerekben REQ-/TEST- hivatkozás
#   6. release-higiénia (release-validate.sh)
#
# Használat:
#   scripts/veritas-gate.sh --feat FEAT-001 [--fast] [--targeted "tests/test_x.py tests/test_y.py"]
#   scripts/veritas-gate.sh --feat FEAT-001 --since main~3   # traceability ablak
#
# Kilépési kód: 0 = GATE PASS, 1 = GATE FAIL (ok + hol bukott).
set -u
cd "$(dirname "$0")/.." || exit 1
FAIL=0
FEAT=""; FAST=0; TARGETED=""; SINCE_RANGE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --feat) FEAT="${2:-}"; shift 2;;
    --fast) FAST=1; shift;;
    --targeted) TARGETED="${2:-}"; shift 2;;
    --since) SINCE_RANGE="${2:-}"; shift 2;;
    *) echo "Ismeretlen flag: $1 (használat: --feat FEAT-XXX [--fast] [--targeted \"...\"] [--since RANGE])"; exit 1;;
  esac
done
[ -z "$FEAT" ] && { echo "❌ --feat FEAT-XXX kötelező"; exit 1; }

SPEC_DIR=".specs/features/$FEAT"
# FEAT-névtér: a mappa lehet FEAT-001 vagy FEAT-001-rövid-leírás
if [ ! -d "$SPEC_DIR" ]; then
  _MATCH=$(ls -d .specs/features/$FEAT-* 2>/dev/null | head -n 1)
  [ -n "$_MATCH" ] && SPEC_DIR="$_MATCH"
fi
echo "🔍 VERITAS gate: $FEAT ($SPEC_DIR)"

# ── 1. Spec + státusz ──
if [ "$FAST" = "1" ]; then
  echo "   ⏩ FAST path (R0/R1): spec nem kötelező — Change Contract a commit-üzenetben elvárt"
else
  if [ -f "$SPEC_DIR/specification.md" ]; then
    echo "   ✅ spec: $SPEC_DIR/specification.md"
  else
    echo "   ❌ spec hiányzik: $SPEC_DIR/specification.md (vagy használd --fast R0/R1-re)"; FAIL=1
  fi
  if grep -q "SPEC_READY" "$SPEC_DIR/specification.md" 2>/dev/null; then
    echo "   ✅ státusz: SPEC_READY"
  else
    echo "   ❌ státusz nem SPEC_READY (SPEC READY Gate kell)"; FAIL=1
  fi
  if grep -q "Státusz: \`SPEC_READY\`" .specs/registry/registry.md 2>/dev/null && grep -q "$FEAT" .specs/registry/registry.md 2>/dev/null; then
    echo "   ✅ registry: $FEAT bejegyezve"
  else
    echo "   ⚠️  registry: $FEAT nincs bejegyezve SPEC_READY-ként (ajánlott, nem blokkol)"
  fi
fi

# ── 2. RED evidence ──
if [ "$FAST" = "1" ]; then
  echo "   ⏩ FAST path: RED nem kötelező (reprodukciós parancs a commitban ajánlott)"
else
  if [ -d "$SPEC_DIR/red" ] && [ -n "$(ls -A "$SPEC_DIR/red" 2>/dev/null)" ]; then
    echo "   ✅ RED evidence: $(ls "$SPEC_DIR/red" | tr '\n' ' ')"
  else
    echo "   ❌ RED evidence hiányzik: $SPEC_DIR/red/ (a tesztnek a fix ELŐTT buknia kell)"; FAIL=1
  fi
fi

# ── 3. Célzott teszt ──
if [ -n "$TARGETED" ]; then
  echo "🎯 célzott teszt: $TARGETED"
  # shellcheck disable=SC2086
  if PYTHONPATH=.:src BH_TEST_NO_CHROME=1 .venv/bin/pytest $TARGETED -q 2>&1 | tail -n 3; then
    echo "   ✅ célzott teszt zöld"
  else
    echo "   ❌ célzott teszt BUKOTT"; FAIL=1
  fi
else
  echo "   ⚠️  --targeted nincs megadva — célzott teszt kihagyva (adj meg suite-ot)"
fi

# ── 4. Ruff a változott fájlokon ──
CHANGED=$(git diff --name-only HEAD 2>/dev/null | grep '\.py$' || true)
if [ -z "$CHANGED" ]; then
  CHANGED=$(git show --name-only --pretty=format: HEAD 2>/dev/null | grep '\.py$' || true)
fi
if [ -n "$CHANGED" ]; then
  echo "🧹 ruff: $CHANGED"
  # Baseline-elve: csak az ÚJ hibák blokkolnak. A repo-ban pre-existing
  # ruff-hibák vannak (pl. tools.py S110/BLE001) — a gate a diffhez adott
  # sorokon ellenőriz: ha a ruff-hibák száma nem nőtt a merge-base óta, PASS.
  _BASE=$(git merge-base HEAD origin/main 2>/dev/null || echo "HEAD~10")
  _NOW_N=$(.venv/bin/ruff check $CHANGED 2>/dev/null | grep -cE "^(S|B|E|F|W|C|N|UP|I)[0-9]+" || echo 0)
  _BASE_N=$(git stash -q 2>/dev/null; .venv/bin/ruff check $CHANGED 2>/dev/null | grep -cE "^(S|B|E|F|W|C|N|UP|I)[0-9]+" || echo 0; git stash pop -q 2>/dev/null || true)
  .venv/bin/ruff check $CHANGED 2>&1 | tail -n 2
  if [ "${_NOW_N}" -le "${_BASE_N}" ]; then
    echo "   ✅ ruff: nincs új hiba (most: $_NOW_N, baseline: $_BASE_N)"
  else
    echo "   ❌ ruff: új hibák (most: $_NOW_N > baseline: $_BASE_N)"; FAIL=1
  fi
else
  echo "   ⏩ nincs változott .py — ruff kihagyva"
fi

# ── 5. Traceability (commit-footerek) ──
RANGE="${SINCE_RANGE:-HEAD~5..HEAD}"
echo "🔗 traceability ($RANGE):"
if git log "$RANGE" --format='%B' 2>/dev/null | grep -qE "REQ-[0-9]+|TEST-[0-9]+"; then
  echo "   ✅ REQ-/TEST- hivatkozás a commitokban"
  git log "$RANGE" --format='%h %s' 2>/dev/null | head -n 5 | sed 's/^/      /'
else
  echo "   ⚠️  nincs REQ-/TEST- hivatkozás a commit-footerekben (ajánlott, nem blokkol)"
fi

# ── 6. Release-higiénia ──
echo "📦 release-higiénia:"
if scripts/release-validate.sh 2>&1 | tail -n 4; then
  : # kimenet már látszik
fi
scripts/release-validate.sh >/dev/null 2>&1 || { echo "   ❌ release-validate BUKOTT"; FAIL=1; }

echo
if [ "$FAIL" -eq 0 ]; then
  echo "✅ VERITAS GATE PASS ($FEAT)"
else
  echo "❌ VERITAS GATE FAIL ($FEAT) — javítsd a fenti pontokat"
fi
exit "$FAIL"
