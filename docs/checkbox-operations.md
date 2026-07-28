# Checkbox & Radio Operations

**Since:** v0.7.0

Browser Helper provides dedicated endpoints for selecting and deselecting checkboxes and radio buttons by their visible label text — no CSS selectors needed.

## Endpoints

### `POST /checkbox/select`

Check/select a checkbox or radio by label text.

**Single mode:**
```json
{"text": "Email notifications", "timeout": 5}
```

**Batch mode:**
```json
{"texts": ["Email notifications", "SMS notifications"], "timeout": 5}
```

### `POST /checkbox/deselect`

Uncheck/deselect a checkbox or radio by label text.

**Single mode:**
```json
{"text": "SMS notifications", "timeout": 5}
```

**Batch mode:**
```json
{"texts": ["Email", "SMS"], "timeout": 5}
```

## Response Shape

**Single mode:**
```json
{
  "status": "ok",
  "operation": "checkbox_select",
  "result": {
    "status": "ok",
    "label": "Email notifications",
    "checked": true,
    "was_already_checked": false
  }
}
```

**Batch mode:**
```json
{
  "status": "ok",
  "operation": "checkbox_select_batch",
  "result": {
    "status": "ok",
    "results": [
      {"status": "ok", "label": "Email notifications", "checked": true, "was_already_checked": false},
      {"status": "ok", "label": "SMS notifications", "checked": true, "was_already_checked": false}
    ]
  }
}
```

Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `label` | `string` | The matched label text |
| `checked` | `bool` | The new state of the checkbox/radio |
| `was_already_checked` | `bool` | Whether the element was already in the target state |

## Label Resolution Strategy

The endpoint finds the target checkbox/radio using the same strategy as `analyze_page()`:

1. **`<label for="id">`** — label targets the input by its `id` attribute
2. **Wrapping `<label>`** — the `<label>` element wraps the `<input>` directly
3. **Previous sibling `<label>`** — a `<label>` element immediately before the input
4. **`aria-label`** — the input's `aria-label` attribute
5. **Parent text** — the parent element's text content (fallback for simple layouts)

Once found, the associated `<label>` is clicked using real CDP mouse events — this ensures framework two-way binding fires correctly in React, Vue, and Symfony forms.

## Confirmation

Both endpoints support optional post-action confirmation:

- `?confirm=screenshot` — returns a base64 JPEG screenshot after the operation
- `?confirm=analyze` — returns a `state_change` with before/after `visual_state` comparison

```bash
curl -X POST 'http://localhost:8000/checkbox/select?confirm=screenshot' \
  -H 'Content-Type: application/json' \
  -d '{"text": "Email notifications"}'
```

## Examples

### Select a single checkbox

```bash
curl -X POST http://localhost:8000/checkbox/select \
  -H 'Content-Type: application/json' \
  -d '{"text": "I agree to the terms", "timeout": 5}'
```

### Select multiple checkboxes in batch

```bash
curl -X POST http://localhost:8000/checkbox/select \
  -H 'Content-Type: application/json' \
  -d '{"texts": ["Subscribe to newsletter", "Email notifications"], "timeout": 5}'
```

### Deselect a single checkbox

```bash
curl -X POST http://localhost:8000/checkbox/deselect \
  -H 'Content-Type: application/json' \
  -d '{"text": "SMS notifications"}'
```

### Deselect multiple checkboxes in batch

```bash
curl -X POST http://localhost:8000/checkbox/deselect \
  -H 'Content-Type: application/json' \
  -d '{"texts": ["SMS", "Marketing emails"]}'
```
