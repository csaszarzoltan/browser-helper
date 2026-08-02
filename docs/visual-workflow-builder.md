# Visual workflow builder

**Since:** v1.19.0

The Automation workspace provides an accessible visual editor for the most repeated browser workflow actions: navigate, click, type, wait for element, screenshot, analyze page, and get page text.

## Safety model

The builder only edits workflow steps. It does not execute browser actions and never bypasses the existing validation or Run control. Users explicitly choose **Update JSON**, review the generated JSON, and then choose **Run** when ready.

## Visual and JSON modes

JSON remains available for expert users and for actions that the visual editor does not yet support. Supported JSON workflows can be imported into the visual builder. Unsupported actions produce a clear message and remain unchanged in JSON mode.

## Step operations

Users can add, duplicate, move up, move down, and remove steps. Required inputs use native labels and fields. Changes are announced, and focus-visible styling identifies the active step.

## Privacy

The visual builder uses the same in-browser editor state as the existing Script Runner. It does not add persistence. Explicit draft saving remains local, opt-in, and bounded to 64 KB under the existing policy.

## Validation

The existing shared `validateWorkflowSteps` function remains authoritative on the client before execution. Server validation remains authoritative for the `/script` request.
