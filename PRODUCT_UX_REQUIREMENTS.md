# Browser Helper Next-Version Product, UX, and Requirements Report

**Source reviewed:** `ZipPrompt.md` opened as a ZIP archive  
**Assessment date:** 2026-08-01  
**Assessment method:** Static product and code review of the complete archive, including the FastAPI application, dashboard HTML/CSS/JavaScript, tests, changelog, implementation report, operator documentation, examples, and test-results history.

> **Evidence note:** “Observed” statements are supported directly by the supplied project. “Inference” statements describe likely behavior or needs that should be validated with users. No live Chrome target, production telemetry, interview data, or moderated usability sessions were supplied, so behavioral conclusions are hypotheses rather than measured facts.

## Executive summary

Browser Helper is a local browser-automation control plane for technical users. It connects to Chrome through CDP and offers a large REST/WebSocket surface, a manual dashboard, LLM-oriented semantic browser APIs, headless and cloud sessions, profiles, diagnostics, visual regression, and anti-detection capabilities.

The latest dashboard work significantly improves an earlier component-heavy interface by introducing five task-oriented workspaces, connection-aware controls, a command palette, guided actions, privacy-safe diagnostics, and accessibility foundations. The strongest current experience is the repeated visible-browser loop: connect, navigate, capture or observe, inspect feedback, diagnose, and retry.

The main next-version problem is no longer a shortage of isolated commands. It is fragmentation across execution models and an uneven gap between what the documentation presents as available and what the code and full regression evidence show as incomplete. The product should first become trustworthy and coherent: expose capability readiness honestly, unify runs and errors, make active browser/session/profile context unmistakable, and bring the major backend domains into usable task-centered UI workspaces. Durable parameterized workflows should follow once execution status and context are reliable.

---

# 1. Product understanding

## 1.1 What the application appears to do

### Observed

Browser Helper is a Python/FastAPI application that acts as a local or remote-control proxy for Chrome. Its core value proposition is to let automation clients and AI agents send compact, high-level commands instead of moving large raw CDP payloads over a tunnel.

The project includes:

- A 141-route FastAPI API surface plus WebSocket updates.
- Visible-browser connection and lifecycle controls.
- Navigation, clicking, typing, form filling, waits, page analysis, screenshots, PDF output, tabs, cookies, network capture, JavaScript evaluation, and batch scripts.
- An LLM Agent API using observations, accessibility semantics, snapshot-scoped references, verified actions, extraction evidence, and bounded task execution.
- Headless session management, profiles, resource monitoring, visual regression, proxy management, fingerprinting, session persistence, anti-detection composition, cloud-provider adapters, and enterprise operations primitives.
- A single-page dashboard with five workspaces: **Overview**, **Live Browser**, **Automation**, **Diagnostics**, and **Agent Tools**.

The product is therefore best understood as a **browser automation operations console and API gateway**, not simply a browser helper utility.

## 1.2 Likely users and user segments

### Primary segments

1. **Automation and integration developers**  
   Build scripts, call REST endpoints, troubleshoot selectors, and need reproducible execution evidence.

2. **AI-agent developers and operators**  
   Use semantic observations and verified actions, monitor agent behavior, and need low-token, reliable browser grounding.

3. **QA and test engineers**  
   Run repeatable browser workflows, capture screenshots, compare baselines, inspect console/network failures, and require deterministic results.

4. **Technical browser-operations users**  
   Manage tabs, profiles, sessions, proxies, browser processes, and diagnostic state across repeated runs.

### Secondary segments

- Platform or enterprise administrators managing policy, quotas, fleet nodes, and evaluation gates.
- Data-extraction users who need resilient form/navigation/table operations.
- Developers evaluating fingerprint, proxy, or cloud-browser configurations.

### Inference

The current dashboard is not aimed at non-technical end users. Labels such as CDP, JSON, selector, session state, accessibility observation, and network status assume technical knowledge. A future product may support a low-code operator segment, but that should be an explicit persona and mode rather than an attempt to make every advanced control universally simple.

## 1.3 Main workflows and usage scenarios

### Workflow A: Connect and verify readiness

1. Open the dashboard.
2. Review CDP connection and tab count in the active-context area.
3. Connect to or launch Chrome.
4. Confirm that browser-dependent controls are enabled.

**User goal:** Establish a valid execution context quickly and know what browser/tab commands will affect.

### Workflow B: Guided browser operation

1. Enter or reuse an HTTP/HTTPS URL.
2. Navigate.
3. Capture a screenshot or request a compact agent observation.
4. Review success/error feedback.
5. Retry or export the session-scoped run history.

**User goal:** Complete frequent actions without constructing raw requests.

### Workflow C: Direct browser interaction

1. Navigate to a page.
2. Use quick or advanced actions such as click, form fill, page text, screenshots, iframe operations, or PDF.
3. Inspect preview and operation feedback.
4. Switch or manage tabs as needed.

**User goal:** Interact with a live browser and inspect results with minimal context switching.

### Workflow D: Build and run automation

1. Select a starter workflow or enter a JSON action array.
2. Validate and format it.
3. Optionally save a bounded local draft.
4. Run the workflow.
5. Diagnose failures using operation, network, and console information.

**User goal:** Create repeatable multi-step automation without writing a separate client.

### Workflow E: Capture and restore sensitive state

1. Capture browser cookies and storage into the editor.
2. Validate or import JSON.
3. Download the state if needed.
4. Restore after impact confirmation.
5. Clear sensitive editor content.

**User goal:** Continue authenticated or configured browser states safely.

### Workflow F: Diagnose a failed action

1. Search/filter operation records.
2. Inspect network capture and status families.
3. Review masked cookie metadata and JavaScript console output.
4. Export bounded, redacted evidence.
5. Retry the relevant action.

**User goal:** Determine what failed without leaking credentials or losing the working context.

### Workflow G: Agent-driven semantic automation

1. Observe the page in compact or accessibility mode.
2. Discover forms and available actions.
3. Act using snapshot-scoped or backend-node references.
4. Verify the outcome.
5. Re-observe or recover from stale state.

**User goal:** Reduce brittle selectors and false-success claims in AI browser actions.

### Workflow H: Advanced environment management

1. Configure profiles, proxies, fingerprint templates, anti-detection bundles, or cloud sessions.
2. Launch a headless or managed session.
3. Monitor health, resources, costs, or detection results.
4. Export or reuse configuration.

**User goal:** Operate scalable or specialized browser environments.

**Observed gap:** These advanced domains are mainly reachable through APIs and documentation, not through equivalent task-centered dashboard workspaces.

---

# 2. UI/UX analysis

## 2.1 Strengths

### Task-oriented information architecture

The five-workspace model is a strong improvement over a single long component grid. It maps reasonably well to user intent: establish context, operate the browser, automate, diagnose, or use agent tools.

### Fast-path support for frequent actions

The guided browser flow makes navigation, screenshot capture, and semantic observation prominent. Recent successful URLs and Enter-to-submit behavior support repeated daily use.

### Clear operational safeguards

Browser-dependent controls are gated when disconnected. Destructive actions such as clearing logs, cookies, session content, or closing tabs use confirmation. This reduces avoidable errors.

### Privacy-aware diagnostics

Cookie values are masked; exports omit values. Network URLs are redacted. Operation export is bounded and scrubbed. Sensitive session state is not persisted by the dashboard. These choices align the UI with the product’s technical risk profile.

### Accessibility foundations

The dashboard includes landmarks, skip navigation, ARIA live feedback, keyboard access, visible focus, textual status, and reduced-motion support. Dynamic action labels and inline validation are also present.

### Local responsiveness

Workspace filtering, command search, validation, and most UI helpers run client-side. Users get immediate feedback without adding API latency.

## 2.2 Weaknesses

### Information architecture still reflects implementation boundaries

The top-level workspaces help, but individual cards remain organized around technical subsystems. Users still need to understand whether an issue belongs to operations, network, cookies, console, agent observation, session state, or a separate API family.

### Active context is too shallow for a multi-runtime product

The context bar shows connection and tabs, but the application supports visible Chrome, headless sessions, cloud-provider sessions, profiles, proxy selection, agent snapshots, and enterprise tenants. Users can plausibly act on the wrong runtime or assume a profile/proxy is active when it is not.

### Feedback is distributed

Results can appear in guided status, toasts, screenshot preview, operation log, tables, agent output, or console. Users must scan several areas to reconstruct one run. A retry may also lack the complete inputs, outputs, timing, evidence, and context needed to understand whether it is safe.

### The dashboard underrepresents major capabilities

Profiles, proxies, fingerprint templates, anti-detection composition, headless/cloud sessions, visual regression, and enterprise objects are prominent in the API and documentation but not first-class dashboard experiences. This creates a gap between perceived and usable capability.

### JSON remains a frequent interaction device

The workflow and session assistants improve safety, but raw JSON is still central. For a repeated operator workflow, this adds syntax burden, discourages parameterization, and makes errors harder to localize to a step or field.

### Capability maturity is not visible

The archive contains contradictory signals: release documentation describes complete v1.8 features, while code includes explicit pre-development stubs and the recorded full suite still has 221 baseline failures. A user cannot tell which feature is production-ready, experimental, unavailable, or merely documented.

### Confirmation quality is inconsistent

Several confirmations are generic yes/no dialogs. High-impact actions should explain scope and consequences, for example which browser, tab, session, cookie set, or log collection will be affected, and whether recovery is possible.

## 2.3 Confusing elements

- **Visible, headless, agent, and cloud execution models** are adjacent in the product but not clearly separated in the dashboard.
- **Session save/restore** and the newer `/api/v1/session` persistence model can be interpreted as the same concept even though they have different contracts and lifecycle semantics.
- **Profile names and fingerprint template names** vary across versions, increasing selection and migration errors.
- **“Success” can mean transport success rather than verified user-goal success** unless a verification option is chosen.
- **Local storage versus session storage versus server-side persistence** varies by feature and is explained in several places rather than summarized as a consistent product policy.
- **The command palette searches existing visible actions**, but it is not a full global object/action search and may not expose API-only capabilities.

## 2.4 Friction points

1. Re-establishing the correct context before each run.
2. Moving between Live Browser, Agent Tools, and Diagnostics to understand one action.
3. Editing long workflow JSON without a step-level builder or field-level errors.
4. Re-entering values when replaying a workflow because durable parameterization is limited.
5. Discovering features that exist only in documentation or API routes.
6. Determining whether a feature is complete, experimental, or currently unavailable.
7. Exporting evidence from several separate panels rather than one run bundle.
8. Managing many tabs, sessions, profiles, or proxies without saved views, labels, or a unified object browser.
9. Distinguishing a successful command from a verified outcome.
10. Recovering after stale state, disconnected Chrome, invalid selectors, or partial workflow completion.

## 2.5 Navigation and workflow observations

- The workspace model should remain. It is a useful stable shell.
- “Overview” should evolve into an operational home with readiness, active context, recent runs, alerts, and recommended next actions.
- “Live Browser” should focus on the current target and direct manipulation.
- “Automation” should own durable workflows, parameters, schedules or triggers only if later justified, and execution history.
- “Diagnostics” should pivot from separate logs to run-centered investigation.
- “Agent Tools” should make observation freshness, snapshot scope, verification status, and recovery visible.
- Advanced runtime/configuration domains likely need a new **Environments** workspace or a coherent admin area rather than being scattered across existing cards.

---

# 3. User behavior analysis

## 3.1 Likely user habits

### Inference: repeated connect-act-inspect loops

Users are likely to keep the dashboard open while iterating on a page or automation. They will perform a small action, inspect the result, adjust, and retry rather than design a perfect workflow first.

### Inference: reuse of recent targets and configurations

Users will revisit the same URLs, tabs, profiles, proxy groups, session states, and workflow shapes. The existing recent-URL feature supports this, but reuse is not consistently available across the product.

### Inference: progressive escalation

Users likely start with the guided or direct action, then escalate to page analysis, agent observation, logs, network data, screenshots, and raw JavaScript only when needed.

### Inference: copy-modify-run workflow authoring

Technical users commonly duplicate a previous JSON workflow, change a few values, and rerun it. This creates demand for parameters, versions, comparison, and reusable templates.

### Inference: reliance on visual and semantic confirmation

Because browser automation can fail silently or hit the wrong element, users will seek screenshots, changed text, URLs, element states, or agent observations as proof.

## 3.2 Repeated actions

- Connect, disconnect, or launch browser.
- Navigate to a known URL.
- Select or switch tab.
- Capture screenshot.
- Observe/analyze page.
- Run or retry workflow.
- Search recent operation and network records.
- Edit one field in JSON.
- Restore a known session.
- Export evidence for debugging or collaboration.
- Re-check readiness after an error.

## 3.3 Likely pain points

- Losing confidence about which tab/session/profile is active.
- Treating an API-level success response as task completion.
- Reconstructing causal order from multiple logs.
- Encountering documented capabilities that are incomplete in the runtime.
- Re-entering repeated values and secrets.
- Debugging one failed workflow step inside a large JSON array.
- Understanding whether retries are idempotent or may repeat a destructive action.
- Switching to curl/OpenAPI for major capabilities absent from the dashboard.
- Comparing two runs or environments manually.

## 3.4 Usage bottlenecks

1. **Context acquisition:** users need more than connected/disconnected state.
2. **Failure diagnosis:** evidence is panel-centric rather than run-centric.
3. **Workflow authoring:** JSON scales poorly as workflows become longer or reusable.
4. **Trust calibration:** incomplete capability status and test contradictions create adoption risk.
5. **Environment management:** API-only configuration slows operators and increases mistakes.
6. **Cross-session continuity:** useful recent state is either deliberately ephemeral or fragmented across browser storage and server files.

## 3.5 Expected but missing interactions

- Pin or name an active execution context.
- Open a unified run detail showing inputs, steps, evidence, errors, and retry options.
- Retry from the failed step with side-effect warnings.
- Save a workflow as a versioned, parameterized object.
- Compare two runs or visual results.
- Search all product objects and actions from one command interface.
- See feature readiness and dependency health before attempting an action.
- Manage profiles, proxies, headless/cloud sessions, and anti-detection bundles visually.
- Generate a support bundle for a selected run.
- Receive guided recovery actions tailored to the error type.

---

# 4. What should be improved

## 4.1 Critical improvements

### 1. Establish truthful feature readiness

Reconcile release claims, route availability, stubs, and test status. Expose capability maturity and dependencies in both API and UI. This is foundational for user trust.

### 2. Expand active context into an execution-context model

Always show runtime type, browser/session ID, active tab, URL, profile, proxy or provider, connection health, and agent snapshot freshness where relevant.

### 3. Create a unified run timeline

Correlate guided actions, direct API operations, workflow steps, agent actions, screenshots, network events, and errors under one run ID. Make run detail the primary diagnostic unit.

### 4. Make verified outcome the default for risky or mutating actions

Differentiate command accepted, browser action executed, state changed, and user goal verified. Present uncertainty explicitly.

### 5. Normalize error and recovery behavior

Provide consistent error codes, user-readable messages, preserved context, recommended recovery, and safe retry semantics across API families.

### 6. Close major implementation/documentation gaps

Complete or explicitly disable stubbed session, compositor, fingerprint database, behavioral typing/scroll, and provider paths. Do not expose unfinished features as normal production options.

## 4.2 Medium-priority improvements

### 7. Durable parameterized workflow library

Replace copy-modify-run behavior with named workflows, versions, typed parameters, validation, and step-level execution results.

### 8. Visual step builder alongside JSON

Offer forms for common actions while preserving an advanced JSON view. Keep both representations synchronized.

### 9. Environment management workspace

Provide task-centered management for profiles, proxies, fingerprints, bundles, headless sessions, and cloud providers.

### 10. Run-centered diagnostics and support bundles

Filter diagnostics by run, step, tab, or session. Export one redacted bundle rather than several unrelated files.

### 11. Global object and action search

Extend the command palette to workflows, sessions, profiles, tabs, runs, and available actions, with context-aware enablement.

### 12. Stronger onboarding and empty states

Use dependency checks and progressive instructions to move a new user from no Chrome connection to first verified action.

## 4.3 Nice-to-have improvements

- Saved diagnostic views and filter presets.
- Run comparison and visual step diff.
- Shareable, redacted troubleshooting links in managed deployments.
- Keyboard-first quick switcher for tabs, sessions, profiles, and workflows.
- Optional local usage analytics dashboard built from privacy-safe events.
- Role-based simplified versus advanced dashboard modes after persona validation.

---

# 5. Requirements

## BR-01: Trustworthy capability readiness

- **Type:** Business requirement
- **Description:** The product shall present a single, accurate view of which capabilities are ready, experimental, unavailable, or blocked by missing dependencies.
- **User value:** Users avoid failed setup attempts and can trust product claims.
- **Priority:** **Must have**
- **Rationale:** The supplied release documentation describes complete features while source and test evidence contain explicit stubs and 221 baseline failures.
- **Acceptance criteria:**
  1. A machine-readable capability endpoint returns capability ID, maturity, enabled state, dependency status, and reason when unavailable.
  2. Dashboard actions for unavailable capabilities are hidden or disabled with an explanation.
  3. Documentation is generated from or validated against the same capability registry.
  4. CI fails when a production-ready capability points to a stub or missing route.
  5. Experimental capabilities are visually labeled and excluded from default production flows.

## BR-02: Reduce time to a verified successful action

- **Type:** Business requirement
- **Description:** The next version shall optimize the path from opening the dashboard to completing and verifying a browser action.
- **User value:** Faster onboarding and higher daily productivity.
- **Priority:** **Must have**
- **Rationale:** The core repeated behavior is connect, act, inspect, and retry.
- **Acceptance criteria:**
  1. A first-time user can reach a verified navigation or screenshot from the Overview workspace without consulting external documentation.
  2. Readiness checks identify missing Chrome, CDP, authentication, or network prerequisites before execution.
  3. The UI reports completion separately from verification.
  4. Product telemetry can measure time from dashboard load to first verified action without capturing page content or secrets.

## UR-01: Persistent, explicit execution context

- **Type:** User requirement
- **Description:** As an operator, I need to know exactly which runtime, browser session, tab, profile, and network identity my next action will affect.
- **User value:** Prevents wrong-target actions and reduces repeated context checking.
- **Priority:** **Must have**
- **Rationale:** Current context primarily exposes connection and tab count despite multiple runtime models.
- **Acceptance criteria:**
  1. The context bar shows runtime type, connection health, session/browser ID, active tab title and URL, and profile where applicable.
  2. Proxy/provider and snapshot freshness are displayed when relevant.
  3. Context changes are announced accessibly and recorded in the run timeline.
  4. Actions display the target context before destructive confirmation.
  5. Stale or disconnected context prevents execution and offers a recovery action.

## UR-02: Unified run history and detail

- **Type:** User requirement
- **Description:** As a user, I need one place to understand what happened during an action or workflow.
- **User value:** Faster diagnosis, safer retry, and better collaboration.
- **Priority:** **Must have**
- **Rationale:** Current evidence is distributed across guided history, operation log, screenshot, network, console, and agent outputs.
- **Acceptance criteria:**
  1. Every action receives a correlation ID shared by frontend, API, agent, and diagnostic events.
  2. Run detail shows start/end time, context, inputs with secrets redacted, steps, status, verification, artifacts, and errors.
  3. Users can filter by run, session, workflow, status, and date.
  4. Retention limits and storage scope are visible.
  5. A run can be exported as one redacted support bundle.

## UR-03: Safe and understandable recovery

- **Type:** User requirement
- **Description:** As a user, I need errors to explain what failed, what was preserved, and what I can safely do next.
- **User value:** Reduces trial-and-error and accidental duplicate actions.
- **Priority:** **Must have**
- **Rationale:** Browser failures include stale state, disconnection, selector ambiguity, timeout, partial workflow completion, and unavailable dependencies.
- **Acceptance criteria:**
  1. Errors include category, affected step, human-readable explanation, technical detail, and recommended recovery.
  2. Retry controls indicate whether the action is safe, potentially duplicative, or unavailable.
  3. Partial workflow completion is preserved and visible.
  4. Users can resume from a failed step only when prerequisites and side-effect rules allow it.
  5. Focus moves to the error summary and associated control accessibly.

## FR-01: Unified run correlation service

- **Type:** Functional requirement
- **Description:** The system shall create and persist normalized run and event records across guided, direct, workflow, agent, headless, and enterprise execution paths.
- **User value:** Enables coherent history and diagnostics.
- **Priority:** **Must have**
- **Rationale:** Existing guided correlation is limited to a browser-tab session and does not span API families.
- **Acceptance criteria:**
  1. A run contains ordered events with timestamps and parent/child step relationships.
  2. Correlation IDs propagate through logs, artifacts, network records, and WebSocket updates.
  3. Records exclude or redact credentials, cookie values, authorization headers, and configured sensitive fields.
  4. Interrupted runs are marked incomplete rather than successful.
  5. Retention and deletion are configurable and test-covered.

## FR-02: Capability and dependency registry

- **Type:** Functional requirement
- **Description:** The application shall compute runtime capability availability from implementation status, configuration, service health, and provider credentials.
- **User value:** Prevents users from attempting unavailable actions.
- **Priority:** **Must have**
- **Rationale:** The product spans optional backends, local Chrome, cloud providers, and incomplete modules.
- **Acceptance criteria:**
  1. Registry entries include API routes, UI actions, maturity, dependencies, and health checks.
  2. Missing credentials do not surface as generic execution failures.
  3. Capability changes are broadcast to the dashboard.
  4. API clients receive a stable reason code for unavailability.
  5. Contract tests compare registry, routes, UI exposure, and documentation.

## FR-03: Verified-action state model

- **Type:** Functional requirement
- **Description:** Mutating browser actions shall report separate transport, execution, state-change, and goal-verification states.
- **User value:** Users can distinguish true completion from uncertain outcomes.
- **Priority:** **Must have**
- **Rationale:** Optional confirmation and agent verification exist, but the model is not consistently applied across actions.
- **Acceptance criteria:**
  1. Results use a common state model across endpoint families.
  2. High-risk actions require a verification rule or explicitly return “unverified.”
  3. Verification can use URL, text, element state, dialog state, screenshot, or user-defined conditions.
  4. Verification timeout does not overwrite evidence that execution occurred.
  5. UI status text does not label an unverified action as fully successful.

## FR-04: Durable parameterized workflow catalog

- **Type:** Functional requirement
- **Description:** Users shall be able to save, version, parameterize, validate, run, and archive workflows.
- **User value:** Eliminates repeated JSON copying and supports controlled reuse.
- **Priority:** **Should have**
- **Rationale:** The current assistant supports local drafts and templates, while process-local recording/replay is not a durable operator workflow system.
- **Acceptance criteria:**
  1. Workflows have stable IDs, names, versions, owners, tags, and descriptions.
  2. Parameters have types, defaults, required state, validation, and secret classification.
  3. A run stores the workflow version and non-secret parameter values used.
  4. Editing creates a new version instead of mutating historical runs.
  5. Import/export uses a documented, schema-versioned format.
  6. Existing `/script` JSON can be imported without losing supported actions.

## FR-05: Step-level workflow builder

- **Type:** Functional requirement
- **Description:** The dashboard shall provide a visual builder for common steps while retaining synchronized JSON editing.
- **User value:** Reduces syntax errors and speeds routine changes.
- **Priority:** **Should have**
- **Rationale:** Raw JSON remains a high-cognitive-load daily interaction.
- **Acceptance criteria:**
  1. Users can add, reorder, duplicate, disable, and delete steps.
  2. Each step form shows only relevant fields and inline validation.
  3. JSON and visual representations remain round-trip equivalent for supported actions.
  4. Unsupported advanced fields remain editable in advanced JSON mode without silent loss.
  5. Validation errors link to the exact step and field.

## FR-06: Environment management workspace

- **Type:** Functional requirement
- **Description:** The dashboard shall provide unified management for profiles, proxies, fingerprint templates, bundles, and local/headless/cloud sessions.
- **User value:** Makes major capabilities usable without curl or custom clients.
- **Priority:** **Should have**
- **Rationale:** These domains are substantial in the backend and documentation but underrepresented in the GUI.
- **Acceptance criteria:**
  1. Users can list, search, inspect, create, edit, test, import/export, and delete supported objects.
  2. Secret values are never returned to or rendered by the UI after creation.
  3. Dependencies and impact are shown before deletion or context switching.
  4. Health, last-used time, and current associations are visible.
  5. Launching a session from an environment object sets and displays the active context.

## FR-07: Run-centered diagnostics

- **Type:** Functional requirement
- **Description:** Diagnostics shall support filtering and navigation by correlation ID, workflow step, session, tab, and time range.
- **User value:** Reduces manual cross-panel reconstruction.
- **Priority:** **Should have**
- **Rationale:** Current operation, network, cookie, console, and artifact views are separate.
- **Acceptance criteria:**
  1. Opening a run prefilters diagnostics to the relevant time and context.
  2. Events link back to the originating step.
  3. Network, console, screenshot, and operation evidence share a common timestamp basis.
  4. Sensitive data redaction is applied before display and export.
  5. Users can clear one run’s diagnostic data without clearing unrelated records where storage permits.

## FR-08: Context-aware global command palette

- **Type:** Functional requirement
- **Description:** The command palette shall search actions and product objects, not only visible buttons.
- **User value:** Faster navigation for expert users.
- **Priority:** **Could have**
- **Rationale:** Keyboard-driven users are likely to switch repeatedly among tabs, workflows, runs, profiles, and actions.
- **Acceptance criteria:**
  1. Search covers workspaces, enabled actions, tabs, workflows, sessions, profiles, and recent runs.
  2. Results show type, context, and unavailable reason.
  3. Destructive commands still require scoped confirmation.
  4. Keyboard focus returns predictably after completion or cancellation.

## NFR-01: Reliability and release quality gate

- **Type:** Non-functional requirement
- **Description:** Production releases shall have no unresolved failures in the supported capability set and shall not expose test scaffolding or stubs as complete features.
- **User value:** Predictable behavior and increased trust.
- **Priority:** **Must have**
- **Rationale:** The project records a large passing suite but also 221 known failures and multiple explicit stubs.
- **Acceptance criteria:**
  1. The production test profile reports zero unexpected failures.
  2. Expected-failure tests are linked to experimental capability IDs and have owners and expiry dates.
  3. Randomized tests use reproducible seeds and failure diagnostics.
  4. Release notes state supported, experimental, and removed capabilities.
  5. Smoke tests cover first connection, one verified action, one workflow, run history, and diagnostics.

## NFR-02: Performance and responsiveness

- **Type:** Non-functional requirement
- **Description:** Frequent dashboard interactions and run updates shall remain responsive under realistic log, tab, and workflow volumes.
- **User value:** Preserves the product’s speed advantage during daily use.
- **Priority:** **Must have**
- **Rationale:** The product’s core promise is lower-latency browser control.
- **Acceptance criteria:**
  1. Workspace and command searches respond within 100 ms for supported local record limits on reference hardware.
  2. Run status begins updating within 500 ms of a server event under normal local conditions.
  3. Large histories use pagination or virtualization and do not block input.
  4. Export jobs provide progress and do not freeze the interface.
  5. Performance budgets are measured in CI for representative datasets.

## NFR-03: Security and privacy by default

- **Type:** Non-functional requirement
- **Description:** Sensitive browser state, credentials, proxy secrets, and page content shall be minimized, scoped, encrypted where persisted, and redacted in logs and exports.
- **User value:** Makes the tool safer for authenticated and enterprise use.
- **Priority:** **Must have**
- **Rationale:** The product handles cookies, storage, authorization data, provider credentials, and potentially private page content.
- **Acceptance criteria:**
  1. A documented data classification applies to every persisted or exported field.
  2. Secrets are write-only in UI/API and never redisplayed.
  3. Redaction tests cover headers, query parameters, JSON fields, cookie values, and common credential patterns.
  4. Server-side durable workflow/session data supports encryption at rest in production configuration.
  5. Users can inspect and delete stored artifacts by scope and retention policy.
  6. Security-sensitive events are auditable without recording secret values.

## NFR-04: Accessibility quality

- **Type:** Non-functional requirement
- **Description:** All new workspaces and dynamic workflows shall meet WCAG 2.2 AA and remain fully keyboard operable.
- **User value:** Enables inclusive and efficient operation.
- **Priority:** **Must have**
- **Rationale:** The current dashboard has strong foundations that must be preserved as complexity grows.
- **Acceptance criteria:**
  1. Automated accessibility checks pass for all major states.
  2. Keyboard-only end-to-end tests cover connect, navigate, run, diagnose, and recover.
  3. Screen-reader testing validates status, errors, dialogs, tables, and dynamic run updates.
  4. Focus is preserved across workspace switches and restored after dialogs.
  5. Status is never conveyed by color alone.

## UX-01: Operational home and next-best action

- **Type:** UX/UI requirement
- **Description:** Overview shall summarize readiness, active context, recent runs, failures requiring attention, and the most likely next action.
- **User value:** Reduces scanning and uncertainty at session start.
- **Priority:** **Must have**
- **Rationale:** Overview currently focuses primarily on connection and browser management.
- **Acceptance criteria:**
  1. Disconnected state presents a short guided setup sequence.
  2. Connected state shows current target and recent verified outcomes.
  3. Blockers identify the responsible dependency and provide a direct remedy.
  4. Users can resume a recent workflow or open a failed run from Overview.
  5. No sensitive page content appears in summaries by default.

## UX-02: Scoped destructive confirmation

- **Type:** UX/UI requirement
- **Description:** Destructive confirmations shall state target, scope, consequence, and recovery availability.
- **User value:** Prevents accidental loss or wrong-context actions.
- **Priority:** **Must have**
- **Rationale:** Generic confirmation is insufficient in a multi-session product.
- **Acceptance criteria:**
  1. Dialogs name the affected browser/session/object and item count where known.
  2. Irreversible actions use explicit action labels rather than “OK.”
  3. Default focus is on the safe option.
  4. Bulk actions provide a preview or summary.
  5. Confirmation is not repeatedly requested for non-destructive retries.

## UX-03: Progressive disclosure for technical complexity

- **Type:** UX/UI requirement
- **Description:** Common workflows shall show essential controls first and reveal advanced CDP, selector, JSON, and anti-detection options on demand.
- **User value:** Lowers cognitive load without removing expert power.
- **Priority:** **Should have**
- **Rationale:** The product serves experts but includes many controls irrelevant to each immediate task.
- **Acceptance criteria:**
  1. Default forms use task language and safe defaults.
  2. Advanced sections preserve user choices per workspace without storing secrets.
  3. Help text explains consequences, not only parameter types.
  4. Expert users can reach advanced controls by keyboard and command palette.

## DI-01: Versioned data contracts and migration

- **Type:** Data/integration requirement
- **Description:** Workflow, session, profile, fingerprint, run, and export formats shall use explicit schema versions and tested migrations.
- **User value:** Protects users’ reusable assets across releases.
- **Priority:** **Must have**
- **Rationale:** The archive contains version-specific aliases and naming differences.
- **Acceptance criteria:**
  1. Every persisted/exported object includes schema version and creation metadata.
  2. Import validates size, structure, version, and path safety before mutation.
  3. Supported older formats are migrated with a preview and no data loss.
  4. Unsupported versions fail with actionable guidance.
  5. Migration tests cover representative historical fixtures.

## DI-02: Standardized API response and error contracts

- **Type:** Data/integration requirement
- **Description:** All supported API families shall use one versioned success/error envelope and consistent HTTP semantics.
- **User value:** Easier client development and predictable UI behavior.
- **Priority:** **Must have**
- **Rationale:** The project documents a unified envelope but also retains compatibility aliases and varied endpoint generations.
- **Acceptance criteria:**
  1. New endpoints return one canonical data field and stable error object.
  2. Deprecated aliases include a removal version and telemetry.
  3. Errors distinguish validation, unavailable capability, stale context, timeout, dependency failure, policy denial, and internal failure.
  4. OpenAPI examples and contract tests cover every error category.
  5. The dashboard does not parse endpoint-specific ad hoc error strings.

## DI-03: Provider and backend abstraction health contract

- **Type:** Data/integration requirement
- **Description:** Local CDP, headless, Playwright-compatible, and cloud providers shall expose a common health, capability, session, cost, and error contract.
- **User value:** Makes runtime choice understandable and interchangeable.
- **Priority:** **Should have**
- **Rationale:** Multiple execution backends exist but vary in completeness and user visibility.
- **Acceptance criteria:**
  1. Each provider reports supported actions, health, latency, quota, and estimated cost where applicable.
  2. Fallback preserves a trace of attempted providers and reasons.
  3. The UI never silently changes runtime without notifying the user and run record.
  4. Stub providers are excluded from production discovery.

## CW-01: Features explicitly out of scope for the next version

- **Type:** Product scope requirement
- **Description:** The next version shall not prioritize general-purpose scheduling, collaborative workflow editing, or autonomous feature recommendations until reliability, context, runs, and workflow reuse are complete.
- **User value:** Keeps delivery focused on core effectiveness and trust.
- **Priority:** **Won’t have for now**
- **Rationale:** These features would add complexity without resolving the observed daily workflow bottlenecks.
- **Acceptance criteria:**
  1. Roadmap and release scope explicitly mark these items as deferred.
  2. Architecture may preserve extension points, but no incomplete UI is exposed.
  3. Reconsideration requires evidence from usage data or user research.

---

## 5.1 MoSCoW priority summary

### Must have

- BR-01, BR-02
- UR-01, UR-02, UR-03
- FR-01, FR-02, FR-03
- NFR-01, NFR-02, NFR-03, NFR-04
- UX-01, UX-02
- DI-01, DI-02

### Should have

- FR-04, FR-05, FR-06, FR-07
- UX-03
- DI-03

### Could have

- FR-08
- Saved diagnostic views, run comparison, and privacy-safe local usage insights

### Won’t have for now

- CW-01: broad scheduling, real-time collaborative workflow editing, and autonomous recommendations

---

# 6. New opportunities

## 6.1 Verified automation workspace

**Opportunity:** Position Browser Helper around “verified browser operations,” where each important action carries evidence of the resulting state.

**Why users may want it:** Automation users are less interested in whether a CDP command returned than whether the intended page state changed.

**Evidence/reasoning:** The project already includes screenshot confirmation, state comparison, agent expectations, `verify_after`, and evidence-backed extraction. Unifying these is a natural extension, not a random feature.

## 6.2 Reusable environment recipes

**Opportunity:** Allow users to save a launch recipe combining runtime, profile, proxy strategy, fingerprint template, resource limits, and session policy.

**Why users may want it:** These settings are currently separate objects but are repeatedly combined for a run.

**Evidence/reasoning:** The anti-detection compositor already models a bundle, and headless/cloud/profile/proxy APIs already expose the constituent pieces.

## 6.3 Run comparison

**Opportunity:** Compare two runs by step outcomes, timing, screenshots, extracted values, network failures, and context differences.

**Why users may want it:** QA and automation users commonly ask “what changed between the passing and failing run?”

**Evidence/reasoning:** The product already stores artifacts, visual baselines, diffs, timing, and structured action results. Run correlation would make comparison feasible.

## 6.4 Guided recovery playbooks

**Opportunity:** Map common error categories to bounded recovery sequences such as reconnect, refresh observation, re-resolve accessible name, switch tab, restart capture, or validate a workflow field.

**Why users may want it:** Repeated browser failures often have predictable remedies.

**Evidence/reasoning:** Existing code contains stale-reference recovery, accessibility fallback, readiness gating, retry, and connection-aware controls. Playbooks would organize proven recovery logic rather than invent autonomous behavior.

## 6.5 Support bundle generation

**Opportunity:** Export a single redacted diagnostic archive for a selected run.

**Why users may want it:** Operators need to share failures with developers without manually collecting screenshots, logs, network records, and environment metadata.

**Evidence/reasoning:** Every relevant panel already has export or artifact concepts, but they are separate. A correlated bundle is a direct response to current fragmentation.

## 6.6 Capability-driven onboarding

**Opportunity:** Generate onboarding steps dynamically from environment health and user intent.

**Why users may want it:** Setup differs for local Chrome, headless, cloud, profiles, proxies, and agents.

**Evidence/reasoning:** The application already exposes health/readiness endpoints and optional credentials. A capability registry can convert these into precise setup guidance.

## 6.7 Product analytics for workflow friction

**Opportunity:** Add an opt-in, privacy-preserving analytics layer measuring retries, abandonment, validation failures, recovery use, and time to verified outcome.

**Why users may want it:** Product teams need evidence to prioritize actual friction rather than route count.

**Evidence/reasoning:** Local telemetry hooks already exist and deliberately exclude secrets and page content. The next step is aggregate measurement with explicit consent and retention controls.

---

# 7. Final recommendation

## 7.1 What should be built first

### Phase 1: Trust and execution clarity

1. Create the capability/dependency registry.
2. Reconcile stubs, routes, documentation, and release tests.
3. Define the expanded execution-context model.
4. Standardize response, error, and verified-action states.
5. Make Overview a readiness and next-action home.

**Why first:** Users cannot confidently adopt advanced features if they cannot tell what is ready, what context is active, or whether an action truly succeeded.

### Phase 2: Unified runs and diagnosis

1. Introduce cross-product correlation IDs and normalized run events.
2. Build run history and run detail.
3. Link screenshots, network, console, agent evidence, and errors to steps.
4. Add scoped retry/resume and redacted support bundles.

**Why second:** This directly improves the repeated act-inspect-diagnose-retry loop and reduces the largest source of operational friction.

### Phase 3: Reusable automation and environments

1. Build the durable parameterized workflow catalog.
2. Add a visual step builder synchronized with JSON.
3. Add the environment management workspace.
4. Add provider health, capability, and cost visibility.

**Why third:** Once runs and context are reliable, users can safely scale from manual iteration to reusable automation.

## 7.2 UI and workflow improvements to prioritize immediately

- Expand the active-context bar before adding more action buttons.
- Surface recent failures and recommended recovery on Overview.
- Replace panel-specific success messages with links to a unified run detail.
- Use scoped confirmations that display the affected target and consequence.
- Show “executed but unverified” as a first-class status.
- Add step-level validation and navigation within workflow JSON immediately, even before a complete visual builder.
- Make unavailable and experimental capabilities visible and understandable instead of allowing late failure.

## 7.3 Requirements with the greatest expected adoption and efficiency impact

1. **BR-01 / FR-02:** Trustworthy capability readiness.
2. **UR-01:** Persistent, explicit execution context.
3. **UR-02 / FR-01:** Unified run history and correlation.
4. **FR-03:** Verified-action state model.
5. **UR-03:** Safe and understandable recovery.
6. **FR-04:** Durable parameterized workflow catalog.
7. **NFR-01:** Zero unexpected failures for the supported production set.

Together, these requirements shift Browser Helper from a broad collection of powerful browser commands into a coherent, trustworthy operations product. They improve effectiveness, clarity, speed, and satisfaction without inventing unrelated features or discarding the strong dashboard, accessibility, privacy, and agent foundations already present.
