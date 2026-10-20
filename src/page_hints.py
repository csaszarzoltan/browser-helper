"""Page probes that explain a refusal: why a control is disabled, and which suggestion matches.

Each probe is one `Runtime.evaluate`. The disabled-reason probe is best-effort: a page that cannot
answer yields no hint, never an error of its own.
"""

from __future__ import annotations

import asyncio
import json

_DISABLED_REASON_JS = """((selector, text) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    let el = null;
    if (selector) { try { el = document.querySelector(selector); } catch (e) { el = null; } }
    else if (text) {
        const want = norm(text);
        const all = [...document.querySelectorAll('button,[role=button],a,input[type=submit],input[type=button]')];
        el = all.find(e => norm(e.innerText || e.value || e.getAttribute('aria-label')) === want)
          || all.find(e => norm(e.innerText || e.value || e.getAttribute('aria-label')).includes(want));
    }
    const reasons = [];
    if (el) {
        const fs = el.closest('fieldset[disabled]');
        if (fs) reasons.push('it sits in a disabled fieldset');
        if (el.getAttribute('aria-disabled') === 'true') reasons.push('it is marked aria-disabled');
        if (el.title) reasons.push('its title says: ' + el.title.slice(0, 80));
        const form = el.form || el.closest('form');
        if (form) {
            const bad = [...form.querySelectorAll(':invalid')].filter(f => f.willValidate).slice(0, 4)
                .map(f => (f.getAttribute('aria-label') || f.name || f.id || f.tagName.toLowerCase())
                    + (f.validationMessage ? ' [' + f.validationMessage.slice(0, 60) + ']' : ''));
            if (bad.length) reasons.push('the form has invalid fields: ' + bad.join(', '));
        }
    }
    const busy = document.querySelector('[aria-busy=true],[role=progressbar],.spinner,.loading,.loader');
    if (busy && busy.getClientRects().length) reasons.push('the page shows a loading indicator');
    return reasons.join('; ');
})(%s, %s)"""


async def disabled_reason(tc, selector: str | None = None, text: str | None = None) -> str:
    """Why the control is disabled, as one short phrase ('' when nothing is found)."""
    js = _DISABLED_REASON_JS % (json.dumps(selector), json.dumps(text))
    try:
        out = await asyncio.wait_for(tc.evaluate(js), 1.0)
    except Exception:  # noqa: BLE001 - a hint, never an error
        return ""
    value = out.get("result") if isinstance(out, dict) and out.get("status") == "ok" else None
    return value if isinstance(value, str) else ""


_SUGGESTION_JS = """((text, within) => {
    const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    const root = within ? document.querySelector(within) : document;
    if (!root) return JSON.stringify({status: 'error', code: 'not_found', error: 'container not found: ' + within});
    const sel = '[role=option],[role=menuitem],[role=listbox] li,[role=listbox] > *,li[class*=suggest],li[class*=option],'
              + 'div[class*=suggest] > *,div[class*=option],.autocomplete-suggestion,.dropdown-item,.ui-menu-item';
    const seen = new Set();
    const visible = [...root.querySelectorAll(sel)].filter(e => {
        if (seen.has(e)) return false;
        seen.add(e);
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
    });
    const want = norm(text);
    const label = e => norm(e.innerText || e.textContent);
    let hits = visible.filter(e => label(e) === want);
    if (!hits.length) hits = visible.filter(e => label(e).includes(want));
    if (hits.length > 1) return JSON.stringify({status: 'error', code: 'ambiguous',
        error: hits.length + ' suggestions match ' + JSON.stringify(text) + ': '
               + hits.slice(0, 5).map(e => label(e).slice(0, 40)).join(' | ')});
    if (!hits.length) return JSON.stringify({status: 'error', code: 'not_found',
        error: 'no visible suggestion matches ' + JSON.stringify(text) + '; visible: '
               + visible.slice(0, 8).map(e => label(e).slice(0, 40)).join(' | ')});
    const e = hits[0];
    e.scrollIntoView({block: 'nearest'});
    const r = e.getBoundingClientRect();
    return JSON.stringify({status: 'ok', x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2),
                           text: label(e).slice(0, 80)});
})(%s, %s)"""


async def find_suggestion(tc, text: str, within: str | None = None) -> dict:
    """Locate the visible suggestion/option whose label matches *text*; returns x, y and its label."""
    out = await tc.evaluate(_SUGGESTION_JS % (json.dumps(text), json.dumps(within)))
    raw = out.get("result") if isinstance(out, dict) else None
    if not isinstance(raw, str):
        return {"status": "error", "code": "not_found", "error": "the page did not answer the suggestion lookup"}
    return json.loads(raw)
