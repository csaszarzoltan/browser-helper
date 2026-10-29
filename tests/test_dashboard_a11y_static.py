"""Dashboard text stays readable on its dark panels (GUI walk, 2026-10-18).

A walk at 1280 px and 390 px found 15 text elements under WCAG 2.2 AA contrast (4.5:1):
#64748b on #0b1120 is 3.8:1 and on the panel colour 3.3:1.  Text uses #94a3b8 or lighter now.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def _lum(hex_color):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_text_colour_on_the_dark_panels_has_aa_contrast():
    assert _ratio("#94a3b8", "#1e293b") >= 4.5  # the lightest panel the muted text sits on
    for name in ("index.html", "dashboard_ux.css"):
        text = (STATIC / name).read_text(encoding="utf-8")
        assert not re.search(r"(?<![-\w])color:\s*#64748b", text), f"{name}: muted text colour below 4.5:1"


def test_header_dot_does_not_claim_chrome_is_connected():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "Dashboard live" in html and "Dashboard offline" in html
    assert "label.textContent = 'Connected'" not in html


def test_small_buttons_are_at_least_24px_high_and_page_has_a_favicon():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert re.search(r"\.btn\.sm\s*\{[^}]*min-height:\s*24px", html)
    assert 'rel="icon"' in html


def test_every_image_in_the_dashboard_has_alt_text():
    """A screen reader announces an <img> by its alt text; a missing one reads out the file name."""
    for page in ("index.html", "fleet.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        for tag in re.findall(r"<img\b[^>]*>", html):
            assert re.search(r"\balt=", tag), f"{page}: image without alt: {tag}"


def test_clickable_screenshot_is_reachable_and_operable_from_the_keyboard():
    """An element with onclick must also take focus, name itself as a button and answer Enter or Space."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    tag = re.search(r'<img[^>]*id="screenshot-img"[^>]*>', html).group(0)
    assert 'onclick="openScreenshot()"' in tag
    assert 'tabindex="0"' in tag
    assert 'role="button"' in tag
    assert 'aria-label="Open screenshot in a new tab"' in tag
    assert "onkeydown=" in tag
