"""Pre-development interface + content validation for browser-helper SKILL.md.

╔══════════════════════════════════════════════════════════════════════╗
║  RED-PHASE PRE-DEV TESTS                                           ║
║                                                                    ║
║  Interface tests (green checkmark) → assert pass immediately        ║
║  Content tests (green checkmark)   → validate SKILL.md structure    ║
║  Coverage tests (green checkmark)  → ensure all routes documented   ║
║                                                                    ║
║  Designed to pass once SKILL.md exists at repo root.               ║
╚══════════════════════════════════════════════════════════════════════╝
║  Current v0.7 state: 87 routes registered, SKILL.md absent.       ║
║  v0.8 additions (not yet routed):                                 ║
║    P0: POST /click/coordinates, POST /dropdown/select,            ║
║        POST /wait/visible                                         ║
║    P1: POST /click/label (enhanced), POST /form/fill (enhanced),  ║
║        POST /page/analyze (modal enrichment), API aliases          ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import re
import sys
from pathlib import Path
from typing import ClassVar

import pytest

# ── Paths ────────────────────────────────────────────────────────────────────


# Mark as quick (unit tests with mocks)
pytestmark = pytest.mark.quick

REPO_ROOT = Path(__file__).parent.parent
SKILL_MD_PATH = REPO_ROOT / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "src"))


# ── Helpers ──────────────────────────────────────────────────────────────────


def load_skill_md() -> str:
    """Return SKILL.md content or raise if missing."""
    if not SKILL_MD_PATH.exists():
        raise FileNotFoundError(f"SKILL.md not found at {SKILL_MD_PATH}")
    return SKILL_MD_PATH.read_text(encoding="utf-8")


def extract_markdown_headings(text: str, level: int = 2) -> list[str]:
    """Extract heading texts at given level (## for level 2)."""
    prefix = "#" * level
    return [
        line.strip().lstrip("#").strip()
        for line in text.splitlines()
        if line.strip().startswith(prefix + " ")
        or line.strip().startswith(prefix + "\t")
    ]


def extract_code_fences(text: str) -> tuple[list[str], list[str]]:
    """Extract content inside fenced code blocks.

    Returns (languages, code_contents).
    """
    matches = re.findall(r"```(\w*)\n(.*?)```", text, re.DOTALL)
    return ([lang for lang, _ in matches], [code for _, code in matches])


def count_occurrences(text: str, pattern: str) -> int:
    """Count overlapping occurrences of a pattern in text."""
    return len(re.findall(re.escape(pattern), text))


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — EXISTENCE & STRUCTURE (should pass immediately)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSKILLMDExists:
    """SKILL.md must be present at repo root."""

    def test_skil_md_exists(self):
        """File SKILL.md exists at repo root."""
        assert SKILL_MD_PATH.is_file(), (
            f"SKILL.md not found at {SKILL_MD_PATH}. "
            "Create it with the required structure before running these tests."
        )

    def test_skil_md_is_not_empty(self):
        """SKILL.md must contain content."""
        content = load_skill_md()
        assert len(content.strip()) > 200, "SKILL.md appears to be only a stub"


class TestRequiredSections:
    """SKILL.md must contain all required top-level sections."""

    REQUIRED_SECTIONS: ClassVar[list[str]] = [
        "Trigger",
        "Setup",
        "Endpoints",
        "CDP Connection Lifecycle",
        "Common Patterns",
    ]

    @pytest.fixture(autouse=True)
    def _load_content(self):
        self.content = load_skill_md()
        self.headings_h2 = extract_markdown_headings(self.content, level=2)

    def test_has_title_section(self):
        """SKILL.md starts with # browser-helper title."""
        first_line = self.content.splitlines()[0].strip()
        assert first_line.startswith("# "), "First line must be an H1 title"

    def test_required_h2_sections_present(self):
        """All required ## sections exist."""
        missing = [
            s
            for s in self.REQUIRED_SECTIONS
            if s not in self.headings_h2
        ]
        assert not missing, (
            f"Missing required ## sections: {missing}. "
            f"Found: {self.headings_h2}"
        )

    def test_endpoints_has_subcategories(self):
        """## Endpoints section should contain ### sub-sections for categories."""
        h3_headings = extract_markdown_headings(self.content, level=3)
        assert len(h3_headings) >= 4, (
            f"Expected at least 4 endpoint categories, got {len(h3_headings)}: "
            f"{h3_headings[:10]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — ENDPOINT COVERAGE (route inventory check)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAllRoutesDocumented:
    """Every route registered on the FastAPI app must be mentioned in SKILL.md."""

    # Routes that are auto-generated by FastAPI and don't need documenting
    DOCS_ROUTES: ClassVar[set[str]] = {
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }

    # Routes that are trivial admin endpoints, documented inline
    TRIVIAL_ROUTES: ClassVar[set[str]] = {
        "/",
        "/health",
        "/ready",
        "/status",
        "/metrics",
        "/upload",
    }

    # Internal routes not meant for end-user documentation
    INTERNAL_ROUTES: ClassVar[set[str]] = {
        "/ws",
        "/static",
    }

    @pytest.fixture(autouse=True)
    def _setup(self):
        from main import app

        self.skill_md = load_skill_md()
        self.skill_md_lower = self.skill_md.lower()

        # Collect all non-doc routes from the app
        self.app_routes = set()
        for r in app.routes:
            path = getattr(r, "path", None)
            if path and path not in self.DOCS_ROUTES:
                self.app_routes.add(path)

    def test_all_app_routes_mentioned(self):
        """Every app route (excluding docs) is referenced in SKILL.md content."""
        missing = sorted(
            p for p in self.app_routes if (
                p not in self.TRIVIAL_ROUTES
                and p not in self.INTERNAL_ROUTES
                and p.lower() not in self.skill_md_lower
            )
        )
        # Allow trivial routes to be undocumented
        missing_but_trivial = [p for p in missing if p in self.TRIVIAL_ROUTES]
        missing_critical = [p for p in missing if p not in self.TRIVIAL_ROUTES]

        if missing_but_trivial:
            print(
                f"ℹ️  Trivial routes not individually documented (OK): "
                f"{missing_but_trivial}"
            )

        assert not missing_critical, (
            f"These routes exist in the app but are NOT mentioned in SKILL.md: "
            f"{missing_critical}"
        )

    def test_v07_routes_covered(self):
        """Key v0.7 endpoints are explicitly documented in SKILL.md."""
        v07_key_routes = [
            "/connect",
            "/navigate",
            "/click",
            "/click/text",
            "/click/label",
            "/type",
            "/form/fill",
            "/form/select",
            "/wait",
            "/wait/text",
            "/wait/navigation",
            "/wait/network-idle",
            "/page/analyze",
            "/page/text",
            "/page/find",
            "/page/outline",
            "/page/diff",
            "/page/iframe-text",
            "/page/iframe/switch",
            "/checkbox/select",
            "/checkbox/deselect",
            "/screenshot",
            "/full_screenshot",
            "/element_screenshot",
            "/pdf",
            "/tabs",
            "/tabs/scan",
            "/tabs/deep-scan/{tab_id}",
            "/tab/new",
            "/tab/close/{tab_id}",
            "/switch_tab/{tab_id}",
            "/activate-tab/{tab_id}",
            "/cookies",
            "/set_cookie",
            "/clear_cookies",
            "/network/start",
            "/network/stop",
            "/network/log",
            "/network/clear",
            "/session/save",
            "/session/restore",
            "/dom_query",
            "/dom_click_all",
            "/script",
            "/browser/launch",
            "/browser/stop",
            "/browser/status",
            "/settings",
            "/screenshot/baseline",
            "/screenshot/compare",
            "/screenshot/baselines",
            "/screenshot/baseline",  # DELETE variant
            "/headless/launch",
            "/headless/close",
            "/headless/sessions",
            "/headless/navigate",
            "/headless/eval",
            "/headless/screenshot",
            "/headless/batch-screenshot",
            "/headless/health",
            "/profiles",
            "/profiles/{name}",
            "/profiles/{name}/export",
            "/profiles/{name}/extensions",
            "/profiles/import",
            "/confirm-action",
            "/javascript/disable",
            "/javascript/enable",
            "/eval",
            "/get_text",
            "/disconnect",
        ]
        content_lower = self.skill_md_lower

        # Normalise path params: {tab_id} → variable name
        missing_v07 = []
        for route in v07_key_routes:
            # Try exact, then with placeholder-like fragments
            route_for_search = route.lower()
            if route_for_search not in content_lower:
                # Try without path params for routes with {param}
                path_stem = route_for_search.split("/{")[0] if "{" in route_for_search else None
                if path_stem and path_stem not in content_lower or not path_stem:
                    missing_v07.append(route)

        assert not missing_v07, (
            f"Expected v0.7 routes not documented: {missing_v07}"
        )

    def test_v08_new_endpoints_documented(self):
        """All v0.8 P0 and P1 endpoints are documented in SKILL.md.

        These endpoints may not exist in the app yet (they are P0/P1 tasks
        not yet implemented), but the SKILL.md must document them as planned
        endpoints per v0.8 release.
        """
        v08_endpoints = [
            "/click/coordinates",
            "/dropdown/select",
            "/wait/visible",
        ]
        content_lower = self.skill_md_lower
        missing_v08 = [
            ep for ep in v08_endpoints if ep.lower() not in content_lower
        ]
        assert not missing_v08, (
            f"New v0.8 endpoints not documented in SKILL.md: {missing_v08}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — CODE BLOCK & FORMAT VALIDITY
# ═══════════════════════════════════════════════════════════════════════════════


class TestMarkdownFormatting:
    """SKILL.md must be well-formed markdown with valid code blocks."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = load_skill_md()

    def test_fenced_code_blocks_balanced(self):
        """Every ``` must be closed — count opening/closing fences."""
        openings = self.content.count("```")
        assert openings % 2 == 0, (
            f"Unbalanced code fences: {openings} ``` markers (expected even)"
        )

    def test_more_than_zero_code_blocks(self):
        """At least one code block must exist for curl examples."""
        langs, _ = extract_code_fences(self.content)
        assert len(langs) >= 5, (
            f"Expected at least 5 code blocks, got {len(langs)}"
        )

    def test_curl_examples_present(self):
        """SKILL.md must contain curl command examples for key endpoints."""
        curl_count = count_occurrences(self.content, "curl")
        assert curl_count >= 10, (
            f"Expected at least 10 'curl' references for example commands, "
            f"got {curl_count}"
        )

    def test_json_code_blocks_present(self):
        """JSON request/response examples in code blocks exist."""
        langs, codes = extract_code_fences(self.content)
        json_blocks = [c for l, c in zip(langs, codes) if l == "json"]
        assert len(json_blocks) >= 3, (
            f"Expected at least 3 JSON code blocks, got {len(json_blocks)}"
        )

    def test_bash_code_blocks_for_curl(self):
        """Curl examples should be in bash or shell code blocks."""
        langs, codes = extract_code_fences(self.content)
        shell_langs = {"bash", "shell", "sh", "console"}
        curl_blocks = sum(
            1 for l, c in zip(langs, codes)
            if l in shell_langs and "curl" in c
        )
        assert curl_blocks >= 5, (
            f"Expected at least 5 bash/shell code blocks containing curl, "
            f"got {curl_blocks}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — COMMON PATTERNS & LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommonPatterns:
    """SKILL.md must document auth, conventions, and lifecycle."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = load_skill_md()
        self.lower = self.content.lower()

    def test_bearer_token_auth_documented(self):
        """Bearer token auth requirement is documented."""
        assert "bearer" in self.lower, (
            "Bearer token authentication not documented"
        )

    def test_auto_activate_documented(self):
        """Auto-activate behavior (interactive ops activate tab first) is documented."""
        phrases = ["auto-activate", "auto activate", "activates the tab", "activate tab"]
        assert any(p in self.lower for p in phrases), (
            "Auto-activation behavior not documented. "
            f"Expected one of: {phrases}"
        )

    def test_response_format_documented(self):
        """Standard response format {status, operation, result} is documented."""
        assert '"status"' in self.lower or "'status'" in self.lower, (
            "Response status field not documented"
        )
        assert '"operation"' in self.lower or "'operation'" in self.lower, (
            "Response operation field not documented"
        )

    def test_confirm_query_param_documented(self):
        """?confirm=screenshot|analyze query parameter is documented."""
        assert "confirm" in self.lower, (
            "?confirm= query parameter not documented"
        )

    def test_connection_lifecycle_steps_documented(self):
        """CDP Connection Lifecycle section describes connect → navigate → interact → disconnect."""
        lifecycle_section_start = self.content.find("## CDP Connection Lifecycle")
        if lifecycle_section_start == -1:
            pytest.skip("CDP Connection Lifecycle section not found")

        lifecycle_content = self.content[lifecycle_section_start:].lower()
        expected_steps = ["connect", "navigate", "disconnect"]
        missing_steps = [
            s for s in expected_steps if s not in lifecycle_content
        ]
        assert not missing_steps, (
            f"Lifecycle section missing steps: {missing_steps}"
        )

    def test_setup_section_contains_token(self):
        """Setup section documents API token auth."""
        setup_start = self.content.find("## Setup")
        if setup_start == -1:
            pytest.skip("Setup section not found")

        setup_content = self.content[setup_start:].lower()
        assert "token" in setup_content or "api_key" in setup_content, (
            "Setup section does not document API token"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — COPY-PASTE CURL VALIDITY (syntax check)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCurlExampleSyntax:
    """Extracted curl commands must be syntactically valid."""

    MIN_CURL_EXAMPLES = 8

    @pytest.fixture(autouse=True)
    def _extract(self):
        self.content = load_skill_md()
        self.langs, self.codes = extract_code_fences(self.content)
        # Collect all curl commands from shell code blocks
        shell_langs = {"bash", "shell", "sh", "console", ""}
        self.curl_commands = []
        for lang, code in zip(self.langs, self.codes):
            if lang in shell_langs and "curl" in code:
                self.curl_commands.extend(
                    line.strip()
                    for line in code.splitlines()
                    if line.strip().startswith("curl ")
                )

    def test_minimum_curl_examples(self):
        """At least 8 curl command examples must exist."""
        assert len(self.curl_commands) >= self.MIN_CURL_EXAMPLES, (
            f"Expected at least {self.MIN_CURL_EXAMPLES} curl examples, "
            f"got {len(self.curl_commands)}"
        )

    def test_curl_examples_start_with_curl(self):
        """Each curl example must start with 'curl'."""
        invalid = [c for c in self.curl_commands if not c.startswith("curl ")]
        assert not invalid, (
            f"Lines don't start with 'curl ': {invalid[:3]}"
        )

    def test_curl_examples_have_url(self):
        """Each curl example must contain an http(s) URL."""
        url_missing = [c for c in self.curl_commands if "http" not in c]
        assert not url_missing, (
            f"Curl examples missing URL: {url_missing[:3]}"
        )

    def test_curl_examples_have_host_port(self):
        """Curl examples should reference a port (default or explicit)."""
        port_missing = [
            c for c in self.curl_commands
            if not any(p in c for p in (":8080", ":8000", "localhost", "PORT"))
        ]
        # Not a hard fail — allow, but report
        if port_missing:
            print(
                f"⚠️  {len(port_missing)} curl examples don't reference a port: "
                f"{port_missing[:3]}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SELF-DOCUMENTATION & SKILL CONTRACT
# ═══════════════════════════════════════════════════════════════════════════════


class TestSkillContract:
    """SKILL.md must follow Hermes skill conventions."""

    @pytest.fixture(autouse=True)
    def _load(self):
        self.content = load_skill_md()

    def test_has_h1_title(self):
        """First line is an H1 title matching the skill name."""
        first_line = self.content.splitlines()[0].strip()
        assert first_line.startswith("# "), "First line must be an H1"

    def test_trigger_section_exists(self):
        """Trigger section explains when to use the skill."""
        assert "## Trigger" in self.content, "## Trigger section is required"

    def test_title_contains_browser_helper(self):
        """Title mentions 'browser-helper' or 'browser helper'."""
        assert "browser" in self.content[:100].lower(), (
            "Title does not mention browser-helper"
        )

    def test_endpoint_as_table_or_list(self):
        """Endpoints section contains a table or structured list of endpoints."""
        endpoints_start = self.content.find("## Endpoints")
        if endpoints_start == -1:
            pytest.skip("Endpoints section not found")

        endpoints_content = self.content[endpoints_start:]
        # Check for markdown table (| separators) or bullet list with methods
        has_table = "|" in endpoints_content and "---" in endpoints_content[:2000]
        has_method_bullets = "POST" in endpoints_content[:5000] and (
            "- " in endpoints_content[:5000]
        )
        assert has_table or has_method_bullets, (
            "Endpoints section should contain a table or structured list "
            "with HTTP methods (POST/GET/DELETE/PUT)"
        )
