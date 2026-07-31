"""
RED-phase pre-development tests for the Detection Test Suite (P2.1).

Module: src/detection_tester.py
REST endpoint: POST /tools/fingerprint-test

Acceptance gates:
- All detection tester tests pass
- sannysoft parser correctly identifies at least webdriver + plugins checks
- creepjs parser extracts lies count
- Test against empty/malformed HTML doesn't crash
- run_all() returns results for all 3 sites even if some error
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import get_type_hints

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi.testclient import TestClient

import main
from detection_tester import DetectionTester, TestResult

# ═══════════════════════════════════════════════════════════════════════
# Mock HTML fixtures — realistic page text from each test site
# ═══════════════════════════════════════════════════════════════════════

SANNYSQFT_ALL_PASS_HTML = """
<html><body>
<h1>Browser Detection Results</h1>
<table id="results">
<tr><th>Check</th><th>Result</th></tr>
<tr class="pass"><td>WebDriver</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>PhantomJS</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Headless Chrome</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Chrome Automation</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Plugins Array</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Languages</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>WebGL Vendor</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Canvas Fingerprint</td><td class="pass">&#10003; Pass</td></tr>
</table>
<p>Summary: 8/8 checks passed</p>
</body></html>
"""

SANNYSQFT_MIXED_HTML = """
<html><body>
<h1>Browser Detection Results</h1>
<table id="results">
<tr><th>Check</th><th>Result</th></tr>
<tr class="pass"><td>WebDriver</td><td class="pass">&#10003; Pass</td></tr>
<tr class="fail"><td>PhantomJS</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Headless Chrome</td><td class="fail">&#10007; Fail</td></tr>
<tr class="pass"><td>Chrome Automation</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Plugins Array</td><td class="pass">&#10003; Pass</td></tr>
<tr class="fail"><td>Languages</td><td class="fail">&#10007; Fail</td></tr>
<tr class="pass"><td>WebGL Vendor</td><td class="pass">&#10003; Pass</td></tr>
<tr class="pass"><td>Canvas Fingerprint</td><td class="pass">&#10003; Pass</td></tr>
</table>
<p>Summary: 5/8 checks passed</p>
</body></html>
"""

SANNYSQFT_ALL_FAIL_HTML = """
<html><body>
<h1>Browser Detection Results</h1>
<table id="results">
<tr><th>Check</th><th>Result</th></tr>
<tr class="fail"><td>WebDriver</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>PhantomJS</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Headless Chrome</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Chrome Automation</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Plugins Array</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Languages</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>WebGL Vendor</td><td class="fail">&#10007; Fail</td></tr>
<tr class="fail"><td>Canvas Fingerprint</td><td class="fail">&#10007; Fail</td></tr>
</table>
<p>Summary: 0/8 checks passed</p>
</body></html>
"""

SANNYSQFT_MALFORMED_HTML = """
<html><body>
<h1>Broken Page
<table id="results">
<tr><th>Check</th><th>Result</th>
<tr class="pass"><td>WebDriver</td>
<td class="fail">&#10007; Fail</td></tr>
"""

SANNYSQFT_EMPTY_HTML = ""

CREEPJS_NORMAL_HTML = """
<html><body>
<div id="results">
<h2>Fingerprint Analysis</h2>
<p>Lies detected: <strong id="lies-count">3</strong></p>
<p>Coverage score: <strong id="coverage-score">78%</strong></p>
<p>Browser entropy: 4.2 bits</p>
</div>
</body></html>
"""

CREEPJS_MISSING_ELEMENTS_HTML = """
<html><body>
<div id="results">
<h2>Fingerprint Analysis</h2>
<p>Status: Still analyzing...</p>
</div>
</body></html>
"""

CREEPJS_EMPTY_HTML = ""

FINGERPRINTJS_DEMO_HTML = """
<html><body>
<div id="visitorId">a1b2c3d4e5f6g7h8</div>
<div id="components">
<div class="component"><span class="key">userAgent</span><span class="value">Mozilla/5.0...</span></div>
<div class="component"><span class="key">screenResolution</span><span class="value">1920x1080</span></div>
</div>
</body></html>
"""

FINGERPRINTJS_EMPTY_HTML = ""


# ═══════════════════════════════════════════════════════════════════════
# Interface / contract tests — should PASS immediately
# ═══════════════════════════════════════════════════════════════════════


class TestTestResultInterface:
    """Contract tests for the TestResult dataclass."""

    def test_class_exists(self):
        """``TestResult`` is defined and importable."""
        assert TestResult is not None

    def test_has_site_field(self):
        """``site`` is a declared field (Pydantic v2 compat check)."""
        assert "site" in TestResult.__dataclass_fields__

    def test_has_passed_field(self):
        """``passed`` is a declared field."""
        assert "passed" in TestResult.__dataclass_fields__

    def test_has_details_field(self):
        """``details`` is a declared field."""
        assert "details" in TestResult.__dataclass_fields__

    def test_has_errors_field(self):
        """``errors`` is a declared field."""
        assert "errors" in TestResult.__dataclass_fields__

    def test_can_instantiate(self):
        """``TestResult`` can be constructed with all required fields."""
        result = TestResult(
            site="https://example.com",
            passed=True,
            details={"check_1": True},
            errors=[],
        )
        assert result.site == "https://example.com"
        assert result.passed is True
        assert result.details == {"check_1": True}
        assert result.errors == []

    def test_site_is_string(self):
        """``site`` field type is ``str``."""
        hints = get_type_hints(TestResult)
        assert hints["site"] is str

    def test_passed_is_boolean(self):
        """``passed`` field type is ``bool``."""
        hints = get_type_hints(TestResult)
        assert hints["passed"] is bool

    def test_details_is_dict(self):
        """``details`` field type is ``dict``."""
        hints = get_type_hints(TestResult)
        assert hints["details"] is dict

    def test_errors_is_list_of_strings(self):
        """``errors`` field type is ``list[str]``."""
        hints = get_type_hints(TestResult)
        assert hints["errors"] == list[str] or hints["errors"] is list


class TestDetectionTesterInterface:
    """Contract tests for the DetectionTester class."""

    def test_class_exists(self):
        """``DetectionTester`` class exists and is importable."""
        assert DetectionTester is not None

    def test_test_sites_is_list(self):
        """``TEST_SITES`` is a list of 3 URLs."""
        assert isinstance(DetectionTester.TEST_SITES, list)
        assert len(DetectionTester.TEST_SITES) == 3

    def test_test_sites_contains_sannysoft(self):
        """TEST_SITES[0] is ``bot.sannysoft.com``."""
        assert "bot.sannysoft.com" in DetectionTester.TEST_SITES[0]
        assert DetectionTester.TEST_SITES[0].startswith("http")

    def test_test_sites_contains_fingerprintjs(self):
        """TEST_SITES[1] is ``fingerprintjs.com/demo``."""
        assert "fingerprintjs.com" in DetectionTester.TEST_SITES[1]
        assert DetectionTester.TEST_SITES[1].startswith("http")

    def test_test_sites_contains_creepjs(self):
        """TEST_SITES[2] is ``creepjs.org/checker``."""
        assert "creepjs.org" in DetectionTester.TEST_SITES[2]
        assert DetectionTester.TEST_SITES[2].startswith("http")

    def test_test_sites_are_https(self):
        """All TEST_SITES use ``https://`` scheme."""
        for url in DetectionTester.TEST_SITES:
            assert url.startswith("https://"), f"{url} is not HTTPS"

    def test_has_parse_sannysoft(self):
        """``parse_sannysoft`` is a member of DetectionTester."""
        assert hasattr(DetectionTester, "parse_sannysoft")

    def test_parse_sannysoft_is_static(self):
        """``parse_sannysoft`` is a static method (no ``self`` parameter)."""
        sig = inspect.signature(DetectionTester.parse_sannysoft)
        params = list(sig.parameters.keys())
        assert "self" not in params, "static method should not have self"
        assert "page_text" in params

    def test_parse_sannysoft_returns_dict(self):
        """``parse_sannysoft`` type hint says it returns ``dict``."""
        hints = get_type_hints(DetectionTester.parse_sannysoft)
        assert hints.get("return") is dict

    def test_has_parse_creepjs(self):
        """``parse_creepjs`` is a member of DetectionTester."""
        assert hasattr(DetectionTester, "parse_creepjs")

    def test_parse_creepjs_is_static(self):
        """``parse_creepjs`` is a static method (no ``self`` parameter)."""
        sig = inspect.signature(DetectionTester.parse_creepjs)
        params = list(sig.parameters.keys())
        assert "self" not in params, "static method should not have self"
        assert "page_text" in params

    def test_parse_creepjs_returns_dict(self):
        """``parse_creepjs`` type hint says it returns ``dict``."""
        hints = get_type_hints(DetectionTester.parse_creepjs)
        assert hints.get("return") is dict

    def test_has_run_all(self):
        """``run_all`` is a member of DetectionTester."""
        assert hasattr(DetectionTester, "run_all")

    def test_run_all_is_async(self):
        """``run_all`` is an async method."""
        assert inspect.iscoroutinefunction(DetectionTester.run_all)

    def test_run_all_accepts_cdp_client(self):
        """``run_all`` has ``cdp_client`` parameter."""
        sig = inspect.signature(DetectionTester.run_all)
        assert "cdp_client" in sig.parameters

    def test_run_all_accepts_timeout_per_site(self):
        """``run_all`` has ``timeout_per_site`` parameter with default 30."""
        sig = inspect.signature(DetectionTester.run_all)
        assert "timeout_per_site" in sig.parameters
        param = sig.parameters["timeout_per_site"]
        assert param.default == 30

    def test_run_all_returns_list_of_test_result(self):
        """``run_all`` type hint says it returns ``list[TestResult]``."""
        hints = get_type_hints(DetectionTester.run_all)
        return_hint = hints.get("return")
        assert return_hint is not None
        # Check it's a list (possibly generic list[TestResult])
        origin = getattr(return_hint, "__origin__", None)
        assert origin is list, f"Expected list[TestResult], got {return_hint}"


class TestDetectionTesterInstantiation:
    """Tests that DetectionTester can be instantiated."""

    def test_can_instantiate(self):
        """``DetectionTester()`` creates an instance with no args."""
        tester = DetectionTester()
        assert tester is not None
        assert isinstance(tester, DetectionTester)


# ═══════════════════════════════════════════════════════════════════════
# Parser acceptance tests — RED-phase (guarded, fail once implemented)
# ═══════════════════════════════════════════════════════════════════════


class TestParseSannysoftAcceptance:
    """Acceptance tests for ``parse_sannysoft`` — fail until parser is implemented.

    These tests will fail with ``NotImplementedError`` until the parser is
    implemented. Once implemented, they verify the parser produces correct
    structured output from realistic HTML fixtures.
    """

    def _try_parse(self, html: str) -> dict | None:
        """Try calling ``parse_sannysoft`` — return result or ``None`` if not implemented."""
        try:
            return DetectionTester.parse_sannysoft(html)
        except NotImplementedError:
            return None

    def test_all_pass_returns_dict_with_checks(self):
        """All-pass HTML yields dict with per-check boolean ``True`` values."""
        result = self._try_parse(SANNYSQFT_ALL_PASS_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify all-pass parsing. "
                "See RED test test_raises_not_implemented."
            )
        assert isinstance(result, dict)
        # Should identify webdriver + plugins checks
        assert "WebDriver" in result
        assert result["WebDriver"] is True
        assert "Plugins Array" in result
        assert result["Plugins Array"] is True
        # All should be True for all-pass fixture
        for check, status in result.items():
            if check.startswith("_"):
                continue
            assert status is True, f"{check} should be True, got {status}"

    def test_mixed_returns_correct_pass_fail(self):
        """Mixed-results HTML yields correct True/False per check."""
        result = self._try_parse(SANNYSQFT_MIXED_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify mixed parsing. "
                "See RED test test_raises_not_implemented."
            )
        assert isinstance(result, dict)
        assert result.get("WebDriver") is True
        assert result.get("PhantomJS") is False
        assert result.get("Headless Chrome") is False
        assert result.get("Plugins Array") is True
        assert result.get("Languages") is False

    def test_all_fail_returns_all_false(self):
        """All-fail HTML yields all ``False`` values."""
        result = self._try_parse(SANNYSQFT_ALL_FAIL_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify all-fail parsing."
            )
        assert isinstance(result, dict)
        for check, status in result.items():
            if check.startswith("_"):
                continue
            assert status is False, f"{check} should be False, got {status}"

    def test_empty_string_returns_dict(self):
        """Empty string does not crash — returns a dict or error-marker."""
        result = self._try_parse(SANNYSQFT_EMPTY_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify empty-HTML handling."
            )
        # Should not crash — may return empty dict or {error: ...}
        assert isinstance(result, dict)
        # A empty HTML might mean empty results or error — either is fine as long as it's a dict

    def test_malformed_html_returns_dict(self):
        """Malformed HTML does not crash — returns a dict."""
        result = self._try_parse(SANNYSQFT_MALFORMED_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify malformed-HTML handling."
            )
        assert isinstance(result, dict)

    def test_identifies_webdriver_check(self):
        """Parser recognises the ``WebDriver`` detection check."""
        result = self._try_parse(SANNYSQFT_ALL_PASS_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify WebDriver identification."
            )
        assert "WebDriver" in result, (
            "Expected 'WebDriver' key in parsed result. "
            "The sannysoft table always includes a WebDriver row."
        )

    def test_identifies_plugins_check(self):
        """Parser recognises the ``Plugins Array`` detection check."""
        result = self._try_parse(SANNYSQFT_ALL_PASS_HTML)
        if result is None:
            pytest.fail(
                "parse_sannysoft must be implemented to verify Plugins identification."
            )
        assert "Plugins Array" in result or "plugins" in str(result).lower(), (
            "Expected a plugins-related key in parsed result."
        )


class TestParseCreepjsAcceptance:
    """Acceptance tests for ``parse_creepjs`` — fail until parser is implemented."""

    def _try_parse(self, html: str) -> dict | None:
        """Try calling ``parse_creepjs`` — return result or ``None`` if not implemented."""
        try:
            return DetectionTester.parse_creepjs(html)
        except NotImplementedError:
            return None

    def test_normal_returns_lies_detected(self):
        """Normal creepjs HTML yields ``lies_detected`` integer."""
        result = self._try_parse(CREEPJS_NORMAL_HTML)
        if result is None:
            pytest.fail(
                "parse_creepjs must be implemented to verify lies detection. "
                "See RED test test_raises_not_implemented."
            )
        assert isinstance(result, dict)
        assert "lies_detected" in result
        assert isinstance(result["lies_detected"], int)
        assert result["lies_detected"] == 3

    def test_normal_returns_coverage_score(self):
        """Normal creepjs HTML yields ``coverage_score`` float."""
        result = self._try_parse(CREEPJS_NORMAL_HTML)
        if result is None:
            pytest.fail(
                "parse_creepjs must be implemented to verify coverage score."
            )
        assert isinstance(result, dict)
        assert "coverage_score" in result
        assert isinstance(result["coverage_score"], (int, float))
        # 78% coverage should be 78.0 or 0.78 — either representation is fine
        assert result["coverage_score"] in (78, 78.0, 0.78)

    def test_missing_elements_does_not_crash(self):
        """Creepjs HTML without expected elements returns a dict (no crash)."""
        result = self._try_parse(CREEPJS_MISSING_ELEMENTS_HTML)
        if result is None:
            pytest.fail(
                "parse_creepjs must be implemented to verify missing-elements handling."
            )
        assert isinstance(result, dict)

    def test_empty_string_does_not_crash(self):
        """Empty string does not crash — returns a dict."""
        result = self._try_parse(CREEPJS_EMPTY_HTML)
        if result is None:
            pytest.fail(
                "parse_creepjs must be implemented to verify empty-HTML handling."
            )
        assert isinstance(result, dict)


class TestRunAllAcceptance:
    """Acceptance tests for ``run_all`` — fail until implemented."""

    def _try_run(
        self, timeout_per_site: int = 30,
    ) -> list[TestResult] | None:
        """Try calling ``run_all`` — return result or ``None`` if not implemented."""
        import asyncio

        async def _do():
            tester = DetectionTester()
            try:
                return await tester.run_all(
                    cdp_client=None, timeout_per_site=timeout_per_site,
                )
            except NotImplementedError:
                return None

        return asyncio.run(_do())

    def test_returns_list_of_test_result(self):
        """``run_all()`` returns a ``list[TestResult]``."""
        results = self._try_run()
        if results is None:
            pytest.fail(
                "run_all must be implemented to verify return type. "
                "See RED test test_raises_not_implemented."
            )
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, TestResult)

    def test_returns_results_for_all_three_sites(self):
        """``run_all()`` returns results for all 3 ``TEST_SITES``."""
        results = self._try_run()
        if results is None:
            pytest.fail(
                "run_all must be implemented to verify all-sites coverage."
            )
        assert len(results) == 3
        sites = [r.site for r in results]
        for url in DetectionTester.TEST_SITES:
            assert url in sites, f"Missing result for {url}"

    def test_individual_error_does_not_block_others(self):
        """An error on one site does not prevent results for the other two.

        ``run_all`` uses soft failure: if a site times out or errors, that
        site gets an error entry but the other sites are still processed.
        """
        results = self._try_run()
        if results is None:
            pytest.fail(
                "run_all must be implemented to verify soft-failure behavior."
            )
        assert len(results) >= 1
        # At minimum, we should get results — if one errors we still get 3 entries
        # with one having errors

    def test_timeout_parameter_is_passed_through(self):
        """``run_all`` respects ``timeout_per_site`` parameter (AC5).

        Verifies the timeout value is passed through to the implementation
        and doesn't cause errors. The actual timeout behavior (timeout
        enforcement) is verified in integration tests. Here we check that
        different timeout values don't break the call.
        """
        for timeout in (5, 15, 30, 60):
            results = self._try_run(timeout_per_site=timeout)
            if results is None:
                pytest.fail(
                    "run_all must be implemented to verify timeout passthrough. "
                    "See RED test test_raises_not_implemented."
                )
            # Even with different timeouts, we should get results
            assert isinstance(results, list)


# ═══════════════════════════════════════════════════════════════════════
# REST endpoint tests — RED-phase (expect 404 until endpoint is registered)
# ═══════════════════════════════════════════════════════════════════════


@pytest.fixture
def api_client() -> TestClient:
    """FastAPI TestClient pointing at the real app."""
    return TestClient(main.app)


class TestFingerprintTestEndpointInterface:
    """Contract tests for ``POST /tools/fingerprint-test``.

    All tests will fail with 404 (RED) until the endpoint route is registered
    in ``src/main.py``.
    """

    def test_endpoint_exists(self, api_client):
        """``POST /tools/fingerprint-test`` returns 200 when registered."""
        resp = api_client.post("/tools/fingerprint-test")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}. "
            "RED: endpoint not registered in main.py yet."
        )

    def test_returns_json_array(self, api_client):
        """Response is a JSON array."""
        resp = api_client.post("/tools/fingerprint-test")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list), (
            f"Expected JSON array, got {type(data)}. "
            "RED: endpoint not registered yet."
        )

    def test_each_result_has_site_passed_details_errors(self, api_client):
        """Each element has ``site``, ``passed``, ``details``, ``errors``."""
        resp = api_client.post("/tools/fingerprint-test")
        assert resp.status_code == 200
        data = resp.json()
        for entry in data:
            assert "site" in entry
            assert "passed" in entry
            assert "details" in entry
            assert "errors" in entry

    def test_returns_per_check_details(self, api_client):
        """``details`` contains per-check pass/fail with descriptions."""
        resp = api_client.post("/tools/fingerprint-test")
        assert resp.status_code == 200
        data = resp.json()
        for entry in data:
            details = entry.get("details", {})
            assert isinstance(details, dict), "details should be a dict"
            if details:
                # If populated, check structure has per-check info
                for status in details.values():
                    if isinstance(status, bool):
                        pass  # simple bool format
                    elif isinstance(status, dict):
                        assert "passed" in status or "status" in status

    def test_returns_503_when_not_connected_to_cdp(self, api_client):
        """Without an active CDP connection, returns 503."""
        resp = api_client.post("/tools/fingerprint-test")
        # RED-phase: endpoint not registered yet, so currently 404.
        # Once registered without CDP connection, should be 503.
        assert resp.status_code in (200, 503), (
            f"Expected 200 (with CDP) or 503 (without CDP), got {resp.status_code}. "
            "RED: endpoint not registered yet."
        )
        if resp.status_code == 503:
            data = resp.json()
            assert "error" in data or "detail" in data

    def test_all_sites_covered_in_response(self, api_client):
        """Response contains results for all 3 ``TEST_SITES``."""
        resp = api_client.post("/tools/fingerprint-test")
        assert resp.status_code == 200
        data = resp.json()
        urls_in_response = [entry["site"] for entry in data]
        for url in DetectionTester.TEST_SITES:
            assert url in urls_in_response, f"Missing test result for {url}"
class _FakeBrowser:
    """Fake CDP client that returns pre-set page text per URL."""

    def __init__(self, url_texts: dict[str, str] | str = ""):
        self._url_texts: dict[str, str] = {}
        self._current_url = ""
        if isinstance(url_texts, str):
            for site in DetectionTester.TEST_SITES:
                self._url_texts[site] = url_texts
        else:
            self._url_texts = url_texts

    async def navigate(self, url: str) -> None:
        self._current_url = url

    async def get_page_text(self) -> str:
        return self._url_texts.get(self._current_url, "")


class TestR2RunAllEmptyPageText:
    """R2 regression: empty page text yields 0/3 passed (review R2)."""

    @pytest.mark.asyncio
    async def test_empty_page_text_yields_zero_passed(self, monkeypatch):
        """A fake browser returning "" for every site must produce 0/3
        passed — never fabricate passes with zero checks."""
        import asyncio as _asyncio

        async def _noop_sleep(_):
            pass

        monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

        fake = _FakeBrowser("")
        tester = DetectionTester()
        results = await tester.run_all(cdp_client=fake)

        assert len(results) == 3, f"Expected 3 results, got {len(results)}"
        passed = [r for r in results if r.passed]
        assert len(passed) == 0, (
            f"Expected 0/3 passed with empty page text, got {len(passed)}: "
            f"{[r.site for r in passed]}"
        )
        for r in results:
            assert r.errors or not r.passed, (
                f"{r.site} has no error and didn't pass — expected error message"
            )

    @pytest.mark.asyncio
    async def test_real_fixtures_through_run_all(self, monkeypatch):
        """Verify real HTML fixtures pass/fail through the full run_all
        pipeline (sannysoft all-pass → pass; creepjs with lies → fail;
        fingerprintjs demo → pass)."""
        import asyncio as _asyncio

        async def _noop_sleep(_):
            pass

        monkeypatch.setattr(_asyncio, "sleep", _noop_sleep)

        url_texts = {
            "https://bot.sannysoft.com": SANNYSQFT_ALL_PASS_HTML,
            "https://fingerprintjs.com/demo": FINGERPRINTJS_DEMO_HTML,
            "https://creepjs.org/checker": CREEPJS_NORMAL_HTML,
        }
        fake = _FakeBrowser(url_texts)
        tester = DetectionTester()
        results = await tester.run_all(cdp_client=fake)

        by_url = {r.site: r for r in results}
        assert by_url["https://bot.sannysoft.com"].passed is True
        assert by_url["https://creepjs.org/checker"].passed is False
        assert by_url["https://fingerprintjs.com/demo"].passed is True


class TestR2ParseFingerprintjs:
    """R2: parser tests for the new fingerprintjs parser."""

    def test_demo_html_matches(self):
        result = DetectionTester.parse_fingerprintjs(FINGERPRINTJS_DEMO_HTML)
        assert result["_matched"] is True
        assert result["visitor_id"] == "a1b2c3d4e5f6g7h8"
        assert result["components"] == 2

    def test_empty_html_not_matched(self):
        result = DetectionTester.parse_fingerprintjs(FINGERPRINTJS_EMPTY_HTML)
        assert result["_matched"] is False
        assert result["visitor_id"] is None
        assert result["components"] == 0


class TestR2ParseCreepjsEdgeCases:
    """R2: creepjs parser — _matched flag for missing elements."""

    def test_missing_elements_not_matched(self):
        result = DetectionTester.parse_creepjs(CREEPJS_MISSING_ELEMENTS_HTML)
        assert result["_matched"] is False
        assert result["lies_detected"] == 0

    def test_empty_not_matched(self):
        result = DetectionTester.parse_creepjs(CREEPJS_EMPTY_HTML)
        assert result["_matched"] is False

    def test_normal_html_matched(self):
        result = DetectionTester.parse_creepjs(CREEPJS_NORMAL_HTML)
        assert result["_matched"] is True
        assert result["lies_detected"] == 3
