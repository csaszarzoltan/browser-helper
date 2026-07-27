# Tab Auto-Activation

**Since:** v0.7.0

Every interactive CDP operation in Browser Helper transparently activates the current tab before execution via Chrome's `Target.activateTarget`. This ensures the tab is awake (not in Chrome's memory-discard state) and ready to receive commands.

## How It Works

The private method `_activate_current()` sends `Target.activateTarget` with the current tab's target ID before every interactive operation, followed by a 100ms sleep to allow Chrome to complete the activation:

```python
async def _activate_current(self) -> None:
    if self._active_tab_id:
        try:
            await self._send_command("Target.activateTarget",
                                     {"targetId": self._active_tab_id})
            await asyncio.sleep(0.1)
        except Exception:
            pass  # Best-effort — tab might already be active
```

## Which Operations Activate

All operations that interact with the page call `_activate_current()` before doing their work:

| Category | Operations |
|----------|-----------|
| Navigation | `navigate` |
| JavaScript | `evaluate`, `evaluate_js` |
| Click | `click`, `click_by_text`, `click_label` |
| Type | `type_text` |
| Screenshot | `screenshot`, `full_page_screenshot`, `element_screenshot` |
| Form | `smart_form_fill`, `checkbox_set_state`, `form_select`, `upload_files` |
| Wait | `wait_for_element`, `wait_for_text`, `wait_for_navigation`, `wait_for_network_idle` |
| Text | `get_page_text` |
| DOM | `dom_query`, `dom_click_all` |
| Cookies | `get_cookies`, `set_cookie`, `clear_cookies` |
| PDF | `pdf` |
| Tab Management | `open_new_tab`, `close_tab`, `switch_tab` |
| Iframes | `get_iframe_text`, `switch_to_iframe` |
| Analysis | `analyze_page`, `analyze_page_condensed`, `get_page_outline`, `page_diff`, `find_element_by_text`, `deep_scan_tab` |

## Manual Activation

You can also manually activate a specific tab via the REST API:

```http
POST /activate-tab/{tab_id}
```

**Response:**
```json
{
  "status": "ok",
  "operation": "activate_tab",
  "result": {
    "status": "ok",
    "tab_id": "ABC123"
  }
}
```

## Why It Matters

Chrome may discard inactive tabs to save memory. Without activation, a command sent to a discarded tab can fail or hang. Browser Helper's transparent activation eliminates this failure mode — all operations just work regardless of tab state.

## No Configuration Needed

Tab auto-activation is **always on** — there is no opt-out and no configuration required. It is a transparent internal mechanism.
