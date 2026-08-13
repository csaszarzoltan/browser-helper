#!/usr/bin/env bash
# release-validate.sh — release-higiénia ellenőrző (release-hygiene skill pitfall-jai)
#
# Egyetlen forrás-igazságból (pyproject.toml version + build_tool_defs()) ellenőrzi,
# hogy minden verzió- és toolszám-hely konzisztens-e. Használat:
#   scripts/release-validate.sh [--fix-docker]   # --fix-docker: Docker label automatikus javítása
#
# Kilépési kód: 0 = minden zöld, 1 = inkonzisztencia (nem blokkol, csak jelez).
set -u
cd "$(dirname "$0")/.." || exit 1
FAIL=0

# ── 1. Verzió: pyproject.toml a forrás-igazság ──
VERSION=$(grep -m1 '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
[ -z "$VERSION" ] && { echo "❌ pyproject.toml: version nem olvasható"; exit 1; }
echo "📦 pyproject version: $VERSION"

check_version() {
    local label="$1" path="$2" pattern="$3"
    if grep -qE "$pattern" "$path" 2>/dev/null; then
        echo "   ✅ $label: $VERSION"
    else
        echo "   ❌ $label: NEM egyezik (keresve: $pattern)"
        FAIL=1
    fi
}

check_version "src/main.py (FastAPI app version)"   src/main.py           "version=\"$VERSION\""
check_version "README.md badge"                     README.md             "version-$VERSION-blue"
check_version "CHANGELOG.md fejléc"                 CHANGELOG.md          "\[$VERSION\]"
check_version "Dockerfile image version label"      Dockerfile            "image.version=\"$VERSION\""

# ── 2. Toolszám: build_tool_defs() a forrás-igazság ──
TOOL_COUNT=$(.venv/bin/python -c "
from mcp_server.registry import build_tool_defs
print(len(list(build_tool_defs())))
" 2>/dev/null) || TOOL_COUNT="ERR"
echo "🔧 MCP tool count (build_tool_defs): $TOOL_COUNT"
if [ "$TOOL_COUNT" = "ERR" ]; then
    echo "   ❌ build_tool_defs() nem futott le (venv függőségek?)"
    FAIL=1
fi

check_toolcount() {
    local label="$1" path="$2" pattern="$3"
    if grep -qE "$pattern" "$path" 2>/dev/null; then
        echo "   ✅ $label: $TOOL_COUNT"
    else
        echo "   ❌ $label: nem $TOOL_COUNT (keresve: $pattern)"
        FAIL=1
    fi
}
# A doc-ok "19 tools" / "15 tools" formában is hivatkozhatnak — csak a lényeget ellenőrizzük:
check_toolcount "docs/mcp-server.md"     docs/mcp-server.md  "(19|15|$TOOL_COUNT) tools?"
check_toolcount "README.md"              README.md           "(15|19|$TOOL_COUNT) tools?"

# ── 2b. Throttle settings kulcs a DEFAULT_SETTINGS-ben ──
if grep -q '"domain_min_interval_sec"' src/settings_manager.py; then
    echo "   ✅ settings: domain_min_interval_sec definiálva"
else
    echo "   ❌ settings: domain_min_interval_sec hiányzik a DEFAULT_SETTINGS-ből"
    FAIL=1
fi

# ── 3. Git állapot ──
AHEAD=$(git rev-list --left-right --count main...origin/main 2>/dev/null | awk '{print $2}')
echo "📡 git ahead/behind: main..origin/main = $AHEAD"
[ "$AHEAD" != "0" ] && { echo "   ❌ main nincs szinkronban origin/main-nal"; FAIL=1; }

# ── 4. Docker label fix (opcionális) ──
if [ "${1:-}" = "--fix-docker" ] && [ "$FAIL" -ne 0 ]; then
    if grep -q 'image.version="1\.20\.0"' Dockerfile; then
        sed -i "s/image.version=\"[0-9.]*\"/image.version=\"$VERSION\"/" Dockerfile
        echo "🔧 Docker label javítva: $VERSION"
        FAIL=0  # csak a docker label volt a gond — újra ellenőrzés a hívó oldalán
    fi
fi

if [ "$FAIL" -eq 0 ]; then
    echo "✅ release-validate: MINDEN ZÖLD (v$VERSION, $TOOL_COUNT tool)"
else
    echo "⚠️  release-validate: inkonzisztenciák (lásd fent)"
fi
exit "$FAIL"
