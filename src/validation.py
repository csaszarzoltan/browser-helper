"""Input validation and sanitization for browser-helper.

Provides ``sanitize_js()`` to validate JavaScript code snippets
before they reach the CDP evaluation endpoint (P0-B).
"""

import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MAX_JS_LENGTH = 10000

# Patterns that are considered dangerous in user-supplied JS
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:document|window)\s*\.\s*cookie", re.IGNORECASE),
    re.compile(r"(?:document|window)\s*\.\s*localStorage", re.IGNORECASE),
    re.compile(r"(?:document|window)\s*\.\s*sessionStorage", re.IGNORECASE),
    re.compile(r"\bnew\s+Function\s*\(", re.IGNORECASE),
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bsetTimeout\s*\(", re.IGNORECASE),
    re.compile(r"\bsetInterval\s*\(", re.IGNORECASE),
    re.compile(r"\bimport\s*\(", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\s*\(", re.IGNORECASE),
    re.compile(r"\bWebSocket\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:alert|confirm|prompt)\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:open|close)\s*\(", re.IGNORECASE),
    re.compile(r"(?:location|navigator)", re.IGNORECASE),
    re.compile(r"\b(?:execScript|createElement|write|writeln)\s*\(", re.IGNORECASE),
    re.compile(r"(?:\.\s*src\s*=)", re.IGNORECASE),
    re.compile(r"(?:\.\s*innerHTML\s*=)", re.IGNORECASE),
    re.compile(r"(?:\.\s*outerHTML\s*=)", re.IGNORECASE),
    re.compile(r"(?:\.\s*insertAdjacentHTML)", re.IGNORECASE),
]


def sanitize_js(js_code: str, max_length: int | None = None) -> str:
    """Validate and sanitize a JavaScript code snippet.

    Args:
        js_code: The JavaScript expression to validate.
        max_length: Maximum allowed length (defaults to ``DEFAULT_MAX_JS_LENGTH``).

    Returns:
        The validated JS code (unchanged if valid).

    Raises:
        ValueError: If the code is empty, too long, or contains dangerous patterns.

    Example:
        >>> sanitize_js("document.title")
        'document.title'
    """
    if not js_code or not js_code.strip():
        msg = "JavaScript code must not be empty"
        raise ValueError(msg)

    max_len = max_length if max_length is not None else DEFAULT_MAX_JS_LENGTH
    if len(js_code) > max_len:
        msg = f"JavaScript code exceeds maximum length of {max_len} characters"
        raise ValueError(msg)

    for pattern in _DANGEROUS_PATTERNS:
        match = pattern.search(js_code)
        if match:
            matched_text = match.group()[:40]
            msg = f"Dangerous JavaScript pattern detected: {matched_text}"
            raise ValueError(msg)

    return js_code
