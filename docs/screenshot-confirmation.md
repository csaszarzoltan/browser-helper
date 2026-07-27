# Screenshot Confirmation

**Since:** v0.7.0

After performing an action (click, checkbox select/deselect), you can automatically capture a screenshot or re-analyze the page state to confirm the action had the expected effect.

## How It Works

Confirmation is opt-in via the `?confirm=` query parameter on supported endpoints:

| Endpoint | `?confirm=screenshot` | `?confirm=analyze` |
|----------|----------------------|-------------------|
| `POST /click/text` | ✓ | ✓ |
| `POST /click/label` | ✓ | ✓ |
| `POST /checkbox/select` | ✓ | ✓ |
| `POST /checkbox/deselect` | ✓ | ✓ |

Additionally, a standalone `POST /confirm-action` endpoint provides confirmation for any action.

## Screenshot Confirmation (`?confirm=screenshot`)

Captures a base64-encoded JPEG screenshot after the operation completes.

**Response with confirmation:**
```json
{
  "status": "ok",
  "operation": "checkbox_select",
  "result": { /* operation result */ },
  "confirmation": {
    "screenshot": "/9j/4AAQSkZJRg…base64-encoded-jpeg-data…"
  }
}
```

## Analyze Confirmation (`?confirm=analyze`)

Compares the page's checkbox/radio visual state before and after the operation.

**Response with confirmation:**
```json
{
  "status": "ok",
  "confirmation": {
    "state_change": {
      "before": {
        "Email notifications": {"checked": true, "type": "checkbox", "value": "email"},
        "SMS notifications": {"checked": false, "type": "checkbox", "value": "sms"}
      },
      "after": {
        "Email notifications": {"checked": true, "type": "checkbox", "value": "email"},
        "SMS notifications": {"checked": true, "type": "checkbox", "value": "sms"}
      },
      "changed": true
    }
  }
}
```

Fields:

| Field | Type | Description |
|-------|------|-------------|
| `state_change.before` | `dict` | Visual state before the action (label → `{checked, type, value}`) |
| `state_change.after` | `dict` | Visual state after the action |
| `state_change.changed` | `bool` | Whether the state changed (before != after) |

## Standalone Confirmation (`POST /confirm-action`)

For operations that don't natively support `?confirm=`, use the standalone confirmation endpoint:

```http
POST /confirm-action?confirm=analyze
```

```http
POST /confirm-action?confirm=screenshot
```

**Response:**
```json
{
  "status": "ok",
  "operation": "confirm_action",
  "result": {
    "screenshot": "/9j/4AAQ…"   /* for ?confirm=screenshot */
  }
}
```

Note: The standalone endpoint uses whatever `_before_visual_state` was captured by a previous operation. For accurate state comparison, call it immediately after the action you want to confirm.

## Examples

### Click with screenshot confirmation

```bash
curl -X POST 'http://localhost:8001/click/text?confirm=screenshot' \
  -H 'Content-Type: application/json' \
  -d '{"text": "Submit"}'
```

### Select checkbox with analyze confirmation

```bash
curl -X POST 'http://localhost:8001/checkbox/select?confirm=analyze' \
  -H 'Content-Type: application/json' \
  -d '{"text": "Email notifications"}'
```

### Standalone confirm after any action

```bash
# First, do any action
curl -X POST http://localhost:8001/click/label \
  -H 'Content-Type: application/json' \
  -d '{"text": "Save settings"}'

# Then confirm with a screenshot
curl -X POST 'http://localhost:8001/confirm-action?confirm=screenshot'
```

## Opt-In Design

Confirmation is **always opt-in** via the `?confirm=` query parameter. When the parameter is absent, no confirmation block is added to the response — ensuring 100% backward compatibility with existing clients.
