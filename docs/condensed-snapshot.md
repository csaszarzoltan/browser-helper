# Condensed Snapshot Mode

**Since:** v0.7.0

`POST /page/analyze?condensed=true` returns a focused page snapshot that strips out navigation bars, sidebars, footers, and other chrome — leaving only the main content area with its interactive elements.

## Use Case

When an AI agent analyzes a page to decide what to do next, the navigation elements (nav, sidebar, footer) add noise. Condensed mode returns only the main content, making it cheaper and faster for LLM consumption.

## How It Works

1. If a main content container (`<main>`, `<article>`, `[role=main]`, `.content`, `#content`) is found, the analysis **only** looks inside it.
2. If no main container is found, the whole page is scanned but elements matching the exclude list are filtered out.
3. The response includes a `condensed_fallback: true` flag when no main container was found.

**Excluded elements:** `<nav>`, `<aside>`, `<footer>`, `<header>`, `.sidebar`, `.breadcrumb`, `.menu`

## Response

Same shape as the regular `/page/analyze` response, with additional summary counts:

```json
{
  "status": "ok",
  "operation": "page_analyze_condensed",
  "result": {
    "page": {
      "url": "https://example.com/form",
      "title": "My Form",
      "condensed_fallback": false,
      "buttons": [ /* main-content buttons only */ ],
      "modals": [],
      "form_fields": [ /* main-content fields only */ ],
      "alerts": [],
      "text_preview": "Main content text…",
      "text_length": 1234,
      "selected_options": [],
      "visual_state": {},
      "field_count": 5,
      "button_count": 2,
      "checkbox_count": 1,
      "radio_count": 0,
      "modal_count": 0
    }
  }
}
```

### Additional Fields

| Field | Type | Description |
|-------|------|-------------|
| `condensed_fallback` | `bool` | `true` when no main container was found (excludes nav elements instead) |
| `field_count` | `int` | Number of form fields in the condensed view |
| `button_count` | `int` | Number of buttons in the condensed view |
| `checkbox_count` | `int` | Number of checkboxes in the condensed view |
| `radio_count` | `int` | Number of radio buttons in the condensed view |
| `modal_count` | `int` | Number of open modals detected |

## Example

```bash
# Full snapshot (includes nav, sidebar, footer)
curl -s -X POST http://localhost:8001/page/analyze | python -m json.tool

# Condensed snapshot (main content only)
curl -s -X POST 'http://localhost:8001/page/analyze?condensed=true' | python -m json.tool
```

## Notes

- Condensed mode still returns `selected_options` and `visual_state` for checkbox/radio fields inside the main content area.
- The regular `/page/analyze` (without `?condensed=true`) is completely unchanged.
