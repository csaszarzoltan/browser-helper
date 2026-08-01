# Task-oriented dashboard workspaces

The Browser Helper dashboard groups existing controls into five daily-use workspaces. This is an additive UI layer: REST and WebSocket contracts are unchanged.

## Workspaces

- **Overview**: CDP connection, readiness, and managed Chrome settings.
- **Live Browser**: quick page actions, page tools, screenshots, and tabs.
- **Automation**: script execution and browser-state save/restore.
- **Diagnostics**: operation history, network requests, cookies, and JavaScript console.
- **Agent Tools**: compact LLM observation, capability, and capture actions.

The last selected workspace is kept in browser-local storage under `browser-helper.workspace`. No page content, cookies, credentials, or action payloads are stored by this feature.

## Active context and readiness

The context bar shows whether CDP is connected and the current tab count. Browser-dependent controls are disabled while disconnected and explain why when hovered or focused. Connection controls remain available.

## Command palette

Press **Ctrl+K** or **Cmd+K**, or choose **Commands**, to search workspaces and visible actions. The palette uses the existing buttons and API calls rather than duplicating execution logic.

## Safety and accessibility

- Destructive buttons require confirmation.
- A skip link moves keyboard focus to the active workspace.
- Workspace changes are announced through an ARIA live region.
- Focus indicators are visible and reduced-motion preferences are honored.
- Status is available as text, not only color.

## Telemetry integration

The UI emits local `browser-helper:telemetry` browser events for workspace selection, command-palette use, command execution, and cancelled destructive actions. Events do not leave the browser unless a host application explicitly subscribes and forwards them. Event detail excludes page content and secrets by design.

## Guided browser flow

The Live Browser workspace starts with a guided flow for the three most repeated actions:

1. Enter a validated HTTP or HTTPS address and navigate.
2. Capture a screenshot using the existing preview workflow.
3. Request a compact agent observation and review it in Agent Tools.

The five most recently successful navigation addresses are stored locally for quick reuse. Only URLs are stored. Page content, observations, screenshots, credentials, and cookies are not placed in local storage. Controls expose busy, success, and error states and remain unavailable when Chrome is disconnected.

## Correlated session run history

Every guided action creates a run record with a correlation ID, action, permitted target, start time, duration, outcome, and short status message. The history is limited to 20 records and stored in `sessionStorage`, so it is isolated to the current browser tab and removed when the tab session ends.

Users can retry a completed or failed run, clear the current session history, or export a redacted JSON report. Screenshot payloads, observations, cookies, credentials, and response bodies are never included in these records or exports.

## Workflow assistant

The Automation workspace enhances the existing Script Runner without changing the `/script` API contract. It provides three safe starter templates, schema-oriented client validation, formatting, explicit local draft saving, and confirmed draft clearing.

Validation checks that the workflow is a non-empty array, contains no more than 100 steps, uses a supported action, and includes required fields for navigation, selector-based actions, typing, and form filling. Templates intentionally exclude arbitrary JavaScript evaluation.

Draft saving is opt-in and limited to 64 KB. Because workflow values can contain personal or secret data, the UI shows a warning before users choose to persist a draft. Saved drafts remain in browser local storage until explicitly cleared. Production deployments should avoid placing secrets directly in workflow JSON.

## Session state assistant

The Automation workspace now treats captured browser state as sensitive material. Users can capture state into the editor, validate pasted or imported JSON, import files up to 5 MB, download validated JSON, restore after an explicit impact confirmation, and clear the editor with confirmation.

The dashboard validates the JSON object shape and, when present, the types of cookies, local storage, and session storage collections. A summary reports collection counts and payload size without displaying cookie values. Session payloads are never written to local storage or session storage by the dashboard. Downloaded files remain the user's responsibility and should be stored securely.

## Diagnostics operation log assistant

The Diagnostics workspace can search operation names and details, filter by status, and display how many entries remain visible. Filtering is non-destructive and never mutates the in-memory source log.

Visible entries can be exported as redacted JSON or CSV. Exports are limited to 100 records, detail text is limited to 500 characters, and common credential markers such as authorization, cookie, token, password, secret, and API key are replaced before download. Clearing the source log requires confirmation.

## Tab management assistant

The Live Browser workspace can search loaded tabs by title, URL, or identifier and reports the visible and total counts. Filtering is non-destructive and keeps the browser's tab collection unchanged.

New-tab creation uses an inline, keyboard-friendly HTTP/HTTPS URL field instead of a blocking browser prompt. Dynamic tab controls include explicit accessible names. Closing a tab requires confirmation, including for controls rendered after initial page load, and successful switching refreshes tab state and announces the new context.

## Network diagnostics assistant

The Network Log now exposes explicit capture state, start/stop controls, request search, method filtering, HTTP status-family filtering, visible counts, and filtered JSON/CSV export. Capture controls remain synchronized with both connection and capture state.

Filtering never mutates the captured request collection. Displayed and exported URLs remove fragments and redact common sensitive query keys, including tokens, API keys, authorization values, passwords, signatures, session identifiers, and secrets. Exports are limited to 500 visible requests and do not include request or response bodies or headers.

## Cookie privacy assistant

Cookie values are masked by default and are not copied into HTML title attributes. Users can search by cookie name, domain, or path, filter secure and non-secure cookies, and see visible and total counts without revealing values.

The only supported export is metadata-only JSON. It includes name, domain, path, secure, HTTP-only, SameSite, expiry, and session flags, but never the cookie value. Export is limited to 500 visible records. Clearing all browser cookies remains a confirmed destructive action.
