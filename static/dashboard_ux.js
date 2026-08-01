(() => {
  'use strict';
  const WORKSPACE_KEY = 'browser-helper.workspace';
  const TELEMETRY_EVENT = 'browser-helper:telemetry';
  const RECENT_URLS_KEY = 'browser-helper.recent-urls';
  const MAX_RECENT_URLS = 5;
  const GUIDED_RUNS_KEY = 'browser-helper.guided-runs';
  const MAX_GUIDED_RUNS = 20;
  const WORKFLOW_DRAFT_KEY = 'browser-helper.workflow-draft';
  const MAX_DRAFT_BYTES = 65536;
  const MAX_SESSION_IMPORT_BYTES = 5 * 1024 * 1024;
  const MAX_EXPORTED_LOG_ENTRIES = 100;
  const MAX_EXPORTED_DETAIL_CHARS = 500;
  const MAX_EXPORTED_NETWORK_ENTRIES = 500;
  const OPERATION_EXPORT_PREFIX = 'operation-log-';
  const NETWORK_EXPORT_PREFIX = 'network-log-';
  const COOKIE_EXPORT_PREFIX = 'cookie-metadata-';
  const MAX_EXPORTED_COOKIE_ENTRIES = 500;
  let networkCaptureActive = false;
  const SENSITIVE_QUERY_KEYS = new Set(['access_token', 'api_key', 'apikey', 'auth', 'authorization', 'code', 'key', 'password', 'secret', 'session', 'sig', 'signature', 'token']);
  const workspaceCopy = {
    overview: 'Connection, readiness, and the browser process at a glance.',
    browser: 'Operate the active tab and review the current page.',
    automation: 'Run repeatable scripts and save or restore browser state.',
    diagnostics: 'Inspect operations, network activity, cookies, and console output.',
    agent: 'Observe and act through the compact LLM agent interface.'
  };

  const emitTelemetry = (name, detail = {}) => {
    // Local event only. Host applications may subscribe; page content and secrets are excluded.
    window.dispatchEvent(new CustomEvent(TELEMETRY_EVENT, {detail: {name, at: Date.now(), ...detail}}));
  };

  const announce = (message) => {
    const el = document.getElementById('a11y-announcer');
    if (!el) return;
    el.textContent = '';
    window.setTimeout(() => { el.textContent = message; }, 20);
  };

  const showWorkspace = (name, options = {}) => {
    const valid = workspaceCopy[name] ? name : 'overview';
    document.querySelectorAll('#workspace-nav [data-workspace]').forEach((button) => {
      const active = button.dataset.workspace === valid;
      button.setAttribute('aria-current', active ? 'page' : 'false');
    });
    document.querySelectorAll('#workspace-main .card[data-workspace]').forEach((card) => {
      card.hidden = card.dataset.workspace !== valid;
    });
    const title = document.getElementById('workspace-title');
    const description = document.getElementById('workspace-description');
    if (title) title.textContent = valid.charAt(0).toUpperCase() + valid.slice(1);
    if (description) description.textContent = workspaceCopy[valid];
    localStorage.setItem(WORKSPACE_KEY, valid);
    if (!options.silent) announce(`${valid} workspace selected`);
    emitTelemetry('workspace_selected', {workspace: valid});
  };

  const setConnectedState = (connected, tabCount) => {
    const connection = document.getElementById('context-connection');
    const tab = document.getElementById('context-tab');
    const warning = document.getElementById('connection-warning');
    if (connection) connection.textContent = connected ? 'Connected' : 'Disconnected';
    if (tab) tab.textContent = connected ? `${Number(tabCount || 0)} tab${Number(tabCount) === 1 ? '' : 's'}` : 'No active tab';
    if (warning) warning.classList.toggle('visible', !connected);
    document.querySelectorAll('[data-requires-connection]').forEach((control) => {
      control.disabled = !connected;
      control.setAttribute('aria-disabled', String(!connected));
      control.title = connected ? '' : 'Connect to Chrome before using this action.';
    });
    window.BrowserHelperNetwork?.applyConnection?.();
  };

  const decorateControls = () => {
    document.querySelectorAll('.card[data-workspace="browser"] button, .card[data-workspace="diagnostics"] button, .card[data-workspace="agent"] button').forEach((button) => {
      if (!button.closest('[data-connection-control]')) button.dataset.requiresConnection = 'true';
    });
    document.querySelectorAll('button.danger').forEach((button) => {
      button.dataset.confirm = button.dataset.confirm || `Are you sure you want to ${button.textContent.trim().toLowerCase()}?`;
    });
  };

  const protectDangerousActions = () => {
    document.addEventListener('click', (event) => {
      const target = event.target.closest('[data-confirm]');
      if (!target) return;
      if (!window.confirm(target.dataset.confirm)) {
        event.preventDefault();
        event.stopImmediatePropagation();
        announce('Action cancelled');
        emitTelemetry('dangerous_action_cancelled', {label: target.textContent.trim()});
      }
    }, true);
  };

  const commands = () => {
    const items = [];
    document.querySelectorAll('#workspace-nav [data-workspace]').forEach((button) => items.push({
      label: `Open ${button.textContent.trim()}`,
      group: 'Workspace',
      run: () => showWorkspace(button.dataset.workspace)
    }));
    document.querySelectorAll('#workspace-main button.btn').forEach((button) => {
      const label = button.textContent.trim();
      if (!label) return;
      items.push({
        label,
        group: button.closest('.card')?.querySelector('h2')?.textContent.trim() || 'Action',
        run: () => {
          const workspace = button.closest('.card')?.dataset.workspace;
          if (workspace) showWorkspace(workspace, {silent: true});
          button.focus();
          if (!button.disabled) button.click();
        }
      });
    });
    return items;
  };

  const setupPalette = () => {
    const dialog = document.getElementById('command-palette');
    const search = document.getElementById('command-search');
    const results = document.getElementById('command-results');
    const open = document.getElementById('open-command-palette');
    if (!dialog || !search || !results || !open) return;
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const matches = commands().filter((item) => `${item.label} ${item.group}`.toLowerCase().includes(query)).slice(0, 30);
      results.replaceChildren();
      if (!matches.length) {
        const empty = document.createElement('p'); empty.className = 'command-empty'; empty.textContent = 'No matching actions.'; results.appendChild(empty); return;
      }
      matches.forEach((item) => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'btn command-item';
        const label = document.createElement('span'); label.textContent = item.label;
        const group = document.createElement('small'); group.textContent = item.group;
        button.append(label, group);
        button.addEventListener('click', () => { dialog.close(); item.run(); emitTelemetry('command_executed', {command: item.label}); });
        results.appendChild(button);
      });
    };
    const openPalette = () => { render(); dialog.showModal(); search.value = ''; search.focus(); emitTelemetry('command_palette_opened'); };
    open.addEventListener('click', openPalette);
    search.addEventListener('input', render);
    dialog.querySelector('[data-close-palette]').addEventListener('click', () => dialog.close());
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openPalette(); }
      if (event.key === 'Escape' && dialog.open) dialog.close();
    });
  };









  let currentCookies = [];

  const filterCookies = () => {
    const query = (document.getElementById('cookie-search')?.value || '').trim().toLowerCase();
    const secureFilter = document.getElementById('cookie-secure-filter')?.value || 'all';
    return currentCookies.filter((cookie) => {
      const secure = Boolean(cookie.secure);
      const matchesSecure = secureFilter === 'all' || (secureFilter === 'secure' ? secure : !secure);
      const haystack = `${cookie.name || ''} ${cookie.domain || ''} ${cookie.path || ''}`.toLowerCase();
      return matchesSecure && (!query || haystack.includes(query));
    });
  };

  const redactCookieMetadata = (cookie) => ({
    name: String(cookie.name || ''),
    domain: String(cookie.domain || ''),
    path: String(cookie.path || '/'),
    secure: Boolean(cookie.secure),
    httpOnly: Boolean(cookie.httpOnly ?? cookie.http_only),
    sameSite: cookie.sameSite ?? cookie.same_site ?? null,
    expires: cookie.expires ?? cookie.expirationDate ?? null,
    session: Boolean(cookie.session)
  });

  const renderFilteredCookies = () => {
    const tbody = document.getElementById('cookie-table-body');
    const summary = document.getElementById('cookie-visible-summary');
    const empty = document.getElementById('cookie-empty-filtered');
    if (!tbody) return;
    const visible = filterCookies();
    if (summary) summary.textContent = `${visible.length} of ${currentCookies.length} cookies shown.`;
    if (empty) empty.hidden = currentCookies.length === 0 || visible.length > 0;
    if (!currentCookies.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#475569;padding:20px">No cookies found.</td></tr>';
      return;
    }
    if (!visible.length) { tbody.innerHTML = ''; return; }
    tbody.innerHTML = visible.map((cookie) => {
      const secure = cookie.secure ? '<i class="fas fa-lock" style="color:#22c55e" title="Secure" aria-label="Secure"></i>' : '—';
      return `<tr><td style="font-weight:600;color:#e2e8f0">${escHtml(String(cookie.name || '—'))}</td><td class="cookie-value-mask" aria-label="Cookie value masked">••••••••</td><td style="color:#64748b">${escHtml(String(cookie.domain || '—'))}</td><td style="color:#64748b">${escHtml(String(cookie.path || '/'))}</td><td>${secure}</td></tr>`;
    }).join('');
  };

  const exportCookieMetadata = () => {
    const cookies = filterCookies().slice(0, MAX_EXPORTED_COOKIE_ENTRIES).map(redactCookieMetadata);
    downloadDiagnostics(JSON.stringify({schema_version: 1, exported_at: new Date().toISOString(), values_included: false, cookies}, null, 2), 'application/json', 'json', COOKIE_EXPORT_PREFIX);
    announce(`${cookies.length} cookie metadata records exported without values`);
    emitTelemetry('cookie_metadata_exported', {count: cookies.length});
  };

  const setupCookieAssistant = () => {
    document.getElementById('cookie-search')?.addEventListener('input', renderFilteredCookies);
    document.getElementById('cookie-secure-filter')?.addEventListener('change', renderFilteredCookies);
    document.getElementById('cookie-export-metadata')?.addEventListener('click', exportCookieMetadata);
    renderFilteredCookies();
  };

  const sanitizeNetworkUrl = (value) => {
    try {
      const url = new URL(String(value || ''));
      for (const key of [...url.searchParams.keys()]) {
        if (SENSITIVE_QUERY_KEYS.has(key.toLowerCase())) url.searchParams.set(key, '[REDACTED]');
      }
      url.hash = '';
      return url.toString();
    } catch (_) {
      return String(value || '').slice(0, 1000);
    }
  };

  const networkStatusGroup = (status) => {
    const code = Number(status || 0);
    if (!code) return 'pending';
    if (code >= 200 && code < 300) return 'success';
    if (code >= 300 && code < 400) return 'redirect';
    if (code >= 400 && code < 500) return 'client-error';
    if (code >= 500) return 'server-error';
    return 'pending';
  };

  const filterNetworkRequests = () => {
    const query = (document.getElementById('network-search')?.value || '').trim().toLowerCase();
    const method = document.getElementById('network-method-filter')?.value || 'all';
    const statusGroup = document.getElementById('network-status-filter')?.value || 'all';
    return networkRequests.filter((request) => {
      const requestMethod = String(request.method || 'GET').toUpperCase();
      const status = request.status ?? request.statusCode ?? 0;
      const url = sanitizeNetworkUrl(request.url || request.documentURL || '');
      const type = request.type || request.resourceType || '';
      const haystack = `${url} ${type} ${requestMethod} ${status}`.toLowerCase();
      return (method === 'all' || requestMethod === method) && (statusGroup === 'all' || networkStatusGroup(status) === statusGroup) && (!query || haystack.includes(query));
    });
  };

  const redactNetworkEntry = (request) => ({
    method: String(request.method || 'GET').toUpperCase(),
    url: sanitizeNetworkUrl(request.url || request.documentURL || ''),
    status: Number(request.status ?? request.statusCode ?? 0),
    type: String(request.type || request.resourceType || 'other'),
    size: Number(request.size ?? request.transferSize ?? 0),
    timestamp: request.timestamp || request.wallTime || null
  });

  const renderFilteredNetworkLog = () => {
    const tbody = document.getElementById('network-table-body');
    const summary = document.getElementById('network-visible-summary');
    const empty = document.getElementById('network-empty-filtered');
    if (!tbody) return;
    const visible = filterNetworkRequests();
    if (summary) summary.textContent = `${visible.length} of ${networkRequests.length} requests shown.`;
    if (empty) empty.hidden = networkRequests.length === 0 || visible.length > 0;
    if (!networkRequests.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#475569;padding:20px">No requests captured.</td></tr>';
      return;
    }
    if (!visible.length) { tbody.innerHTML = ''; return; }
    tbody.innerHTML = visible.map((request) => {
      const method = String(request.method || 'GET').toUpperCase();
      const url = sanitizeNetworkUrl(request.url || request.documentURL || '—');
      const status = Number(request.status ?? request.statusCode ?? 0);
      const type = String(request.type || request.resourceType || 'other');
      const sizeValue = request.size ?? request.transferSize ?? 0;
      const group = networkStatusGroup(status);
      const statusClass = group === 'success' ? 'ok' : group;
      return `<tr><td><span class="method ${escHtml(method)}">${escHtml(method)}</span></td><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis" title="${escHtml(url)}">${escHtml(shortUrl(url))}</td><td><span class="status-code ${escHtml(statusClass)}">${status || '—'}</span></td><td style="color:#94a3b8">${escHtml(type)}</td><td style="color:#94a3b8">${escHtml(formatBytes(Number(sizeValue)))}</td></tr>`;
    }).join('');
  };

  const setNetworkCaptureState = (active, message = active ? 'Capturing' : 'Stopped') => {
    networkCaptureActive = active;
    const status = document.getElementById('network-capture-status');
    if (status) { status.textContent = message; status.classList.toggle('active', active); }
    const start = document.getElementById('network-start');
    const stop = document.getElementById('network-stop');
    const connected = document.getElementById('context-connection')?.textContent === 'Connected';
    if (start) start.disabled = !connected || active;
    if (stop) stop.disabled = !connected || !active;
  };

  const startNetworkCapture = async () => {
    setNetworkCaptureState(false, 'Starting...');
    const data = await apiPost('/network/start');
    if (data && data.status !== 'error') {
      setNetworkCaptureState(true);
      toast('Network capture started', 'success');
      emitTelemetry('network_capture_started');
      await refreshNetworkLog();
    } else setNetworkCaptureState(false, 'Start failed');
  };

  const stopNetworkCapture = async () => {
    const data = await apiPost('/network/stop');
    if (data && data.status !== 'error') {
      setNetworkCaptureState(false);
      toast('Network capture stopped', 'success');
      emitTelemetry('network_capture_stopped');
      await refreshNetworkLog();
    } else setNetworkCaptureState(true, 'Stop failed');
  };

  const exportNetworkLog = (format) => {
    const requests = filterNetworkRequests().slice(0, MAX_EXPORTED_NETWORK_ENTRIES).map(redactNetworkEntry);
    if (format === 'json') {
      downloadDiagnostics(JSON.stringify({schema_version: 1, exported_at: new Date().toISOString(), filtered: true, requests}, null, 2), 'application/json', 'json', NETWORK_EXPORT_PREFIX);
    } else {
      const rows = [['method', 'url', 'status', 'type', 'size', 'timestamp'], ...requests.map((request) => [request.method, request.url, request.status, request.type, request.size, request.timestamp])];
      downloadDiagnostics(rows.map((row) => row.map(csvCell).join(',')).join('\n'), 'text/csv', 'csv', NETWORK_EXPORT_PREFIX);
    }
    announce(`${requests.length} network requests exported as ${format.toUpperCase()}`);
    emitTelemetry('network_log_exported', {format, count: requests.length});
  };

  const setupNetworkAssistant = () => {
    document.getElementById('network-search')?.addEventListener('input', renderFilteredNetworkLog);
    document.getElementById('network-method-filter')?.addEventListener('change', renderFilteredNetworkLog);
    document.getElementById('network-status-filter')?.addEventListener('change', renderFilteredNetworkLog);
    document.getElementById('network-start')?.addEventListener('click', startNetworkCapture);
    document.getElementById('network-stop')?.addEventListener('click', stopNetworkCapture);
    document.getElementById('network-export-json')?.addEventListener('click', () => exportNetworkLog('json'));
    document.getElementById('network-export-csv')?.addEventListener('click', () => exportNetworkLog('csv'));
    setNetworkCaptureState(false);
    renderFilteredNetworkLog();
  };

  let currentTabs = [];

  const normalizeTabUrl = (value) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) throw new Error('Enter a page address.');
    let parsed;
    try { parsed = new URL(trimmed); } catch (_) { throw new Error('Enter a valid URL, including https:// or http://.'); }
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Only HTTP and HTTPS addresses are supported.');
    return parsed.href;
  };

  const filterTabs = () => {
    const query = (document.getElementById('tab-search')?.value || '').trim().toLowerCase();
    return currentTabs.filter((tab) => {
      const haystack = `${tab.title || ''} ${tab.url || ''} ${tab.id || tab.tabId || tab.targetId || ''}`.toLowerCase();
      return !query || haystack.includes(query);
    });
  };

  const updateTabSummary = (visibleCount = filterTabs().length) => {
    const summary = document.getElementById('tab-visible-summary');
    if (summary) summary.textContent = `${visibleCount} of ${currentTabs.length} tabs shown.`;
  };

  const openValidatedTab = async () => {
    const input = document.getElementById('tab-new-url');
    if (!input) return;
    try {
      const url = normalizeTabUrl(input.value);
      const data = await apiPost('/tab/new', {url});
      if (!data || data.status === 'error') throw new Error(data?.error?.message || data?.error || 'Could not open the tab.');
      input.value = '';
      toast('New tab opened', 'success');
      emitTelemetry('tab_opened');
      await refreshTabs();
    } catch (error) {
      toast(`<i class="fas fa-exclamation-triangle"></i> ${error.message}`, 'error');
      input.setAttribute('aria-invalid', 'true');
      input.focus();
    }
  };

  const setupTabAssistant = () => {
    const search = document.getElementById('tab-search');
    const input = document.getElementById('tab-new-url');
    search?.addEventListener('input', () => renderTabs(currentTabs));
    input?.addEventListener('input', () => input.removeAttribute('aria-invalid'));
    input?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); openValidatedTab(); }
    });
    document.getElementById('tab-open')?.addEventListener('click', openValidatedTab);
    updateTabSummary(0);
  };

  const filterOperationLog = () => {
    const query = (document.getElementById('log-search')?.value || '').trim().toLowerCase();
    const status = document.getElementById('log-status-filter')?.value || 'all';
    return operationLog.filter((entry) => {
      const matchesStatus = status === 'all' || String(entry.status || 'pending').toLowerCase() === status;
      const haystack = `${entry.operation || ''} ${entry.details || ''}`.toLowerCase();
      return matchesStatus && (!query || haystack.includes(query));
    });
  };

  const redactOperationEntry = (entry) => {
    const details = String(entry.details || '')
      .replace(/(authorization|cookie|token|password|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi, '$1=[REDACTED]')
      .slice(0, MAX_EXPORTED_DETAIL_CHARS);
    return {
      id: Number(entry._id || 0),
      timestamp: entry.timestamp || null,
      operation: String(entry.operation || ''),
      status: String(entry.status || 'pending'),
      duration_ms: entry.duration_ms == null ? null : Number(entry.duration_ms),
      details
    };
  };

  const renderFilteredOperationLog = () => {
    const tbody = document.getElementById('log-table-body');
    const summary = document.getElementById('log-visible-summary');
    const empty = document.getElementById('log-empty-filtered');
    if (!tbody) return;
    const filtered = filterOperationLog();
    if (summary) summary.textContent = `${filtered.length} of ${operationLog.length} operations shown.`;
    if (empty) empty.hidden = operationLog.length === 0 || filtered.length > 0;
    if (!operationLog.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#475569;padding:20px">No operations yet.</td></tr>';
    } else if (!filtered.length) {
      tbody.innerHTML = '';
    } else {
      tbody.innerHTML = filtered.map((entry) => {
        const time = entry.timestamp ? new Date(entry.timestamp).toLocaleTimeString() : '—';
        const status = entry.status || 'pending';
        const duration = entry.duration_ms != null ? `${Number(entry.duration_ms).toFixed(0)}ms` : '—';
        return `<tr><td style="color:#475569">${entry._id || '—'}</td><td style="color:#64748b">${escHtml(time)}</td><td style="color:#38bdf8;font-weight:600">${escHtml(String(entry.operation || '—'))}</td><td><span class="op-status ${escHtml(status)}">${escHtml(status)}</span></td><td style="color:#94a3b8">${escHtml(duration)}</td><td style="color:#64748b;max-width:200px;overflow:hidden;text-overflow:ellipsis" title="${escHtml(String(entry.details || ''))}">${escHtml(String(entry.details || ''))}</td></tr>`;
      }).join('');
    }
    const count = document.getElementById('op-count');
    if (count) count.textContent = operationLog.length;
  };

  const downloadDiagnostics = (contents, mime, extension, prefix = OPERATION_EXPORT_PREFIX) => {
    const blob = new Blob([contents], {type: mime});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${prefix}${new Date().toISOString().replace(/[:.]/g, '-')}.${extension}`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const exportOperationLogJson = () => {
    const entries = filterOperationLog().slice(0, MAX_EXPORTED_LOG_ENTRIES).map(redactOperationEntry);
    downloadDiagnostics(JSON.stringify({schema_version: 1, exported_at: new Date().toISOString(), filtered: true, entries}, null, 2), 'application/json', 'json');
    announce(`${entries.length} operation log entries exported as JSON`);
    emitTelemetry('operation_log_exported', {format: 'json', count: entries.length});
  };

  const csvCell = (value) => `"${String(value ?? '').replace(/"/g, '""')}"`;
  const exportOperationLogCsv = () => {
    const entries = filterOperationLog().slice(0, MAX_EXPORTED_LOG_ENTRIES).map(redactOperationEntry);
    const rows = [['id', 'timestamp', 'operation', 'status', 'duration_ms', 'details'], ...entries.map((entry) => [entry.id, entry.timestamp, entry.operation, entry.status, entry.duration_ms, entry.details])];
    downloadDiagnostics(rows.map((row) => row.map(csvCell).join(',')).join('\n'), 'text/csv', 'csv');
    announce(`${entries.length} operation log entries exported as CSV`);
    emitTelemetry('operation_log_exported', {format: 'csv', count: entries.length});
  };

  const setupDiagnosticsAssistant = () => {
    document.getElementById('log-search')?.addEventListener('input', renderFilteredOperationLog);
    document.getElementById('log-status-filter')?.addEventListener('change', renderFilteredOperationLog);
    document.getElementById('log-export-json')?.addEventListener('click', exportOperationLogJson);
    document.getElementById('log-export-csv')?.addEventListener('click', exportOperationLogCsv);
    renderFilteredOperationLog();
  };

  const setSessionStatus = (message, state = '') => {
    const status = document.getElementById('session-validation-status');
    if (!status) return;
    status.className = `session-validation ${state}`.trim();
    status.textContent = message;
  };

  const validateSessionState = (source) => {
    const raw = typeof source === 'string' ? source : JSON.stringify(source);
    const bytes = new TextEncoder().encode(raw).length;
    if (!raw.trim()) throw new Error('Session state is empty.');
    if (bytes > MAX_SESSION_IMPORT_BYTES) throw new Error('Session state exceeds the 5 MB dashboard limit.');
    let state;
    try { state = typeof source === 'string' ? JSON.parse(source) : source; }
    catch (error) { throw new Error(`Invalid JSON: ${error.message}`); }
    if (!state || typeof state !== 'object' || Array.isArray(state)) throw new Error('Session state must be a JSON object.');
    const payload = state.session && typeof state.session === 'object' ? state.session : state;
    const cookies = payload.cookies;
    const localStorageValue = payload.localStorage ?? payload.local_storage;
    const sessionStorageValue = payload.sessionStorage ?? payload.session_storage;
    if (cookies !== undefined && !Array.isArray(cookies)) throw new Error('cookies must be an array.');
    if (localStorageValue !== undefined && (!localStorageValue || typeof localStorageValue !== 'object' || Array.isArray(localStorageValue))) {
      throw new Error('localStorage must be an object.');
    }
    if (sessionStorageValue !== undefined && (!sessionStorageValue || typeof sessionStorageValue !== 'object' || Array.isArray(sessionStorageValue))) {
      throw new Error('sessionStorage must be an object.');
    }
    const cookieCount = Array.isArray(cookies) ? cookies.length : 0;
    const localCount = localStorageValue ? Object.keys(localStorageValue).length : 0;
    const sessionCount = sessionStorageValue ? Object.keys(sessionStorageValue).length : 0;
    setSessionStatus(`Valid session state: ${cookieCount} cookies, ${localCount} local storage keys, ${sessionCount} session storage keys (${bytes} bytes).`, 'success');
    return state;
  };

  const setSessionBusy = (busy) => {
    const wrapper = document.querySelector('.session-assistant');
    if (wrapper) wrapper.setAttribute('aria-busy', String(busy));
    document.querySelectorAll('#session-save, #session-restore, #session-validate, #session-download, #session-import, #session-clear-sensitive').forEach((button) => {
      button.disabled = busy;
    });
    if (!busy) setConnectedState(document.getElementById('context-connection')?.textContent === 'Connected', Number(document.getElementById('tabs-count')?.textContent || 0));
  };

  const downloadSessionState = () => {
    const area = document.getElementById('session-data');
    if (!area) return;
    try {
      const state = validateSessionState(area.value);
      const blob = new Blob([JSON.stringify(state, null, 2)], {type: 'application/json'});
      const link = document.createElement('a');
      link.href = URL.createObjectURL(blob);
      link.download = `session-state-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
      link.click();
      URL.revokeObjectURL(link.href);
      setSessionStatus('Session state downloaded. Store the file securely.', 'warning');
      emitTelemetry('session_state_downloaded', {bytes: blob.size});
    } catch (error) { setSessionStatus(error.message, 'error'); }
  };

  const importSessionFile = async (file) => {
    if (!file) return;
    if (file.size > MAX_SESSION_IMPORT_BYTES) { setSessionStatus('Selected file exceeds the 5 MB limit.', 'error'); return; }
    try {
      const text = await file.text();
      const state = validateSessionState(text);
      const area = document.getElementById('session-data');
      if (area) area.value = JSON.stringify(state, null, 2);
      setSessionStatus(`Imported and validated ${file.name}.`, 'success');
      emitTelemetry('session_state_imported', {bytes: file.size});
    } catch (error) { setSessionStatus(`Import failed: ${error.message}`, 'error'); }
  };

  const setupSessionAssistant = () => {
    const area = document.getElementById('session-data');
    const fileInput = document.getElementById('session-import-file');
    if (!area || !fileInput) return;
    document.getElementById('session-validate')?.addEventListener('click', () => {
      try { validateSessionState(area.value); } catch (error) { setSessionStatus(error.message, 'error'); }
    });
    document.getElementById('session-download')?.addEventListener('click', downloadSessionState);
    document.getElementById('session-import')?.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => { importSessionFile(fileInput.files?.[0]); fileInput.value = ''; });
    document.getElementById('session-clear-sensitive')?.addEventListener('click', () => {
      area.value = '';
      setSessionStatus('Sensitive session state cleared from the editor.', 'success');
      emitTelemetry('session_state_editor_cleared');
    });
  };

  const SUPPORTED_WORKFLOW_ACTIONS = new Set([
    'navigate', 'click', 'click_text', 'click_label', 'type', 'form_fill', 'form_select',
    'find_element', 'wait', 'wait_for_element', 'wait_text', 'wait_for_navigation',
    'wait_for_network_idle', 'scroll', 'screenshot', 'full_page_screenshot',
    'element_screenshot', 'get_text', 'pdf', 'upload_files', 'get_iframe_text',
    'switch_to_iframe', 'get_page_outline', 'analyze_page', 'page_diff', 'close'
  ]);

  const WORKFLOW_TEMPLATES = {
    navigate_capture: {
      name: 'Navigate and capture',
      steps: [
        {action: 'navigate', url: 'https://example.com'},
        {action: 'wait_for_network_idle', timeout: 10},
        {action: 'screenshot'}
      ]
    },
    observe_page: {
      name: 'Observe page',
      steps: [
        {action: 'analyze_page'},
        {action: 'get_page_outline'},
        {action: 'get_text'}
      ]
    },
    form_starter: {
      name: 'Form workflow starter',
      steps: [
        {action: 'navigate', url: 'https://example.com/form'},
        {action: 'form_fill', fields: [{label: 'Email', value: 'replace@example.com'}]},
        {action: 'screenshot'}
      ]
    }
  };

  const setWorkflowStatus = (message, state = '') => {
    const status = document.getElementById('workflow-validation-status');
    if (!status) return;
    status.className = `workflow-validation ${state}`.trim();
    status.textContent = message;
  };

  const validateWorkflowSteps = (source) => {
    let steps;
    try { steps = typeof source === 'string' ? JSON.parse(source) : source; }
    catch (error) { throw new Error(`Invalid JSON: ${error.message}`); }
    if (!Array.isArray(steps) || !steps.length) throw new Error('Workflow must be a non-empty JSON array.');
    if (steps.length > 100) throw new Error('Workflow cannot contain more than 100 steps.');
    steps.forEach((step, index) => {
      if (!step || typeof step !== 'object' || Array.isArray(step)) throw new Error(`Step ${index + 1} must be an object.`);
      if (!SUPPORTED_WORKFLOW_ACTIONS.has(step.action)) throw new Error(`Step ${index + 1} has unsupported action: ${step.action || 'missing'}.`);
      if (step.action === 'navigate' && (!step.url || typeof step.url !== 'string')) throw new Error(`Step ${index + 1} navigate requires a URL.`);
      if (['click', 'type', 'wait', 'element_screenshot'].includes(step.action) && (!step.selector || typeof step.selector !== 'string')) {
        throw new Error(`Step ${index + 1} ${step.action} requires a selector.`);
      }
      if (step.action === 'type' && typeof step.text !== 'string') throw new Error(`Step ${index + 1} type requires text.`);
      if (step.action === 'form_fill' && !Array.isArray(step.fields)) throw new Error(`Step ${index + 1} form_fill requires fields.`);
    });
    return steps;
  };

  const formatWorkflow = () => {
    const area = document.getElementById('script-area');
    if (!area) return;
    try {
      const steps = validateWorkflowSteps(area.value);
      area.value = JSON.stringify(steps, null, 2);
      setWorkflowStatus(`${steps.length} valid step${steps.length === 1 ? '' : 's'} formatted.`, 'success');
    } catch (error) { setWorkflowStatus(error.message, 'error'); }
  };

  const saveWorkflowDraft = () => {
    const area = document.getElementById('script-area');
    if (!area) return;
    const bytes = new TextEncoder().encode(area.value).length;
    if (!area.value.trim()) { setWorkflowStatus('Nothing to save.', 'warning'); return; }
    if (bytes > MAX_DRAFT_BYTES) { setWorkflowStatus('Draft exceeds the 64 KB local storage limit.', 'error'); return; }
    try {
      validateWorkflowSteps(area.value);
      localStorage.setItem(WORKFLOW_DRAFT_KEY, area.value);
      setWorkflowStatus(`Valid draft saved locally (${bytes} bytes).`, 'success');
      emitTelemetry('workflow_draft_saved', {bytes});
    } catch (error) { setWorkflowStatus(`Draft not saved: ${error.message}`, 'error'); }
  };

  const clearWorkflowDraft = () => {
    localStorage.removeItem(WORKFLOW_DRAFT_KEY);
    const area = document.getElementById('script-area');
    if (area) area.value = '';
    setWorkflowStatus('Local draft cleared.', 'success');
    emitTelemetry('workflow_draft_cleared');
  };

  const setWorkflowBusy = (busy) => {
    const wrapper = document.querySelector('.workflow-assistant');
    if (wrapper) wrapper.setAttribute('aria-busy', String(busy));
    document.querySelectorAll('#workflow-run, #workflow-apply-template, #workflow-validate, #workflow-format, #workflow-save-draft, #workflow-clear-draft').forEach((button) => {
      button.disabled = busy;
    });
    if (!busy) setConnectedState(document.getElementById('context-connection')?.textContent === 'Connected', Number(document.getElementById('tabs-count')?.textContent || 0));
  };

  const setupWorkflowAssistant = () => {
    const area = document.getElementById('script-area');
    const template = document.getElementById('workflow-template');
    if (!area || !template) return;
    const saved = localStorage.getItem(WORKFLOW_DRAFT_KEY);
    if (saved && new TextEncoder().encode(saved).length <= MAX_DRAFT_BYTES) {
      area.value = saved;
      setWorkflowStatus('A locally saved draft was restored. Validate it before running.', 'warning');
    }
    document.getElementById('workflow-apply-template')?.addEventListener('click', () => {
      const selected = WORKFLOW_TEMPLATES[template.value];
      if (!selected) return;
      if (area.value.trim() && !window.confirm('Replace the current workflow editor content with this template?')) return;
      area.value = JSON.stringify(selected.steps, null, 2);
      setWorkflowStatus(`${selected.name} template applied. Review placeholder values before running.`, 'warning');
      area.focus();
    });
    document.getElementById('workflow-validate')?.addEventListener('click', () => {
      try {
        const steps = validateWorkflowSteps(area.value);
        setWorkflowStatus(`${steps.length} valid step${steps.length === 1 ? '' : 's'}.`, 'success');
      } catch (error) { setWorkflowStatus(error.message, 'error'); }
    });
    document.getElementById('workflow-format')?.addEventListener('click', formatWorkflow);
    document.getElementById('workflow-save-draft')?.addEventListener('click', saveWorkflowDraft);
    document.getElementById('workflow-clear-draft')?.addEventListener('click', clearWorkflowDraft);
  };

  const getGuidedRuns = () => {
    try {
      const parsed = JSON.parse(sessionStorage.getItem(GUIDED_RUNS_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.slice(0, MAX_GUIDED_RUNS) : [];
    } catch (_) {
      return [];
    }
  };

  const redactRun = (run) => ({
    run_id: String(run.run_id || ''),
    action: String(run.action || ''),
    target: run.action === 'Navigation' ? String(run.target || '') : null,
    started_at: String(run.started_at || ''),
    duration_ms: Number(run.duration_ms || 0),
    outcome: String(run.outcome || ''),
    message: String(run.message || '').slice(0, 500)
  });

  const saveGuidedRuns = (runs) => {
    sessionStorage.setItem(GUIDED_RUNS_KEY, JSON.stringify(runs.map(redactRun).slice(0, MAX_GUIDED_RUNS)));
    renderGuidedRuns();
  };

  const createGuidedRun = (action, target = null) => {
    const run = {
      run_id: crypto.randomUUID ? crypto.randomUUID() : `run_${Date.now()}_${Math.random().toString(16).slice(2)}`,
      action,
      target,
      started_at: new Date().toISOString(),
      duration_ms: 0,
      outcome: 'running',
      message: `${action} started`
    };
    saveGuidedRuns([run, ...getGuidedRuns()]);
    return run;
  };

  const completeGuidedRun = (run, outcome, message, started) => {
    const updated = {...run, outcome, message, duration_ms: Math.max(0, Math.round(performance.now() - started))};
    const runs = getGuidedRuns().filter((item) => item.run_id !== run.run_id);
    saveGuidedRuns([updated, ...runs]);
    return updated;
  };

  const retryGuidedRun = (run) => {
    const input = document.getElementById('guided-url');
    if (run.action === 'Navigation' && input && run.target) input.value = run.target;
    const buttonId = run.action === 'Navigation' ? 'guided-navigate' : run.action === 'Screenshot' ? 'guided-screenshot' : 'guided-observe';
    document.getElementById(buttonId)?.click();
  };

  const renderGuidedRuns = () => {
    const list = document.getElementById('guided-run-list');
    if (!list) return;
    list.replaceChildren();
    const runs = getGuidedRuns();
    if (!runs.length) {
      const empty = document.createElement('li');
      empty.className = 'guided-run-empty';
      empty.textContent = 'No guided actions in this browser tab yet.';
      list.appendChild(empty);
      return;
    }
    runs.forEach((run) => {
      const item = document.createElement('li');
      item.className = 'guided-run-item';
      const status = document.createElement('span');
      status.className = `guided-run-status ${run.outcome}`;
      status.textContent = run.outcome;
      const action = document.createElement('strong'); action.textContent = run.action;
      const target = document.createElement('span'); target.className = 'guided-run-target'; target.textContent = run.target || run.message;
      target.title = run.target || run.message;
      const timing = document.createElement('span'); timing.className = 'guided-run-time'; timing.textContent = `${run.duration_ms} ms`;
      const id = document.createElement('span'); id.className = 'guided-run-id'; id.textContent = run.run_id.slice(0, 8);
      const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'btn sm'; retry.textContent = 'Retry';
      retry.disabled = run.outcome === 'running';
      retry.addEventListener('click', () => retryGuidedRun(run));
      item.append(status, action, target, timing, id, retry);
      list.appendChild(item);
    });
  };

  const exportGuidedRuns = () => {
    const payload = {schema_version: 1, exported_at: new Date().toISOString(), runs: getGuidedRuns().map(redactRun)};
    const blob = new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'});
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `guided-runs-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
    announce('Guided run history exported');
  };

  const setupGuidedRunHistory = () => {
    const clear = document.getElementById('guided-clear-runs');
    const exportButton = document.getElementById('guided-export-runs');
    clear?.addEventListener('click', () => {
      sessionStorage.removeItem(GUIDED_RUNS_KEY);
      renderGuidedRuns();
      announce('Guided run history cleared');
    });
    exportButton?.addEventListener('click', exportGuidedRuns);
    renderGuidedRuns();
  };

  const getRecentUrls = () => {
    try {
      const parsed = JSON.parse(localStorage.getItem(RECENT_URLS_KEY) || '[]');
      return Array.isArray(parsed) ? parsed.filter((value) => typeof value === 'string').slice(0, MAX_RECENT_URLS) : [];
    } catch (_) {
      return [];
    }
  };

  const saveRecentUrl = (url) => {
    const urls = [url, ...getRecentUrls().filter((item) => item !== url)].slice(0, MAX_RECENT_URLS);
    localStorage.setItem(RECENT_URLS_KEY, JSON.stringify(urls));
    renderRecentUrls();
  };

  const renderRecentUrls = () => {
    const container = document.getElementById('guided-recent');
    const input = document.getElementById('guided-url');
    if (!container || !input) return;
    container.replaceChildren();
    const urls = getRecentUrls();
    if (!urls.length) return;
    const label = document.createElement('span');
    label.className = 'guided-recent-label';
    label.textContent = 'Recent:';
    container.appendChild(label);
    urls.forEach((url) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'btn sm';
      button.textContent = url;
      button.title = `Use ${url}`;
      button.addEventListener('click', () => { input.value = url; input.focus(); });
      container.appendChild(button);
    });
  };

  const normalizeGuidedUrl = (value) => {
    const trimmed = value.trim();
    if (!trimmed) throw new Error('Enter a page address.');
    let parsed;
    try { parsed = new URL(trimmed); } catch (_) { throw new Error('Enter a valid URL, including https:// or http://.'); }
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Only HTTP and HTTPS addresses are supported.');
    return parsed.href;
  };

  const setGuidedBusy = (busy) => {
    const body = document.querySelector('#guided-action-card .guided-action-body');
    if (body) body.setAttribute('aria-busy', String(busy));
    const connected = document.getElementById('context-connection')?.textContent === 'Connected';
    document.querySelectorAll('#guided-action-card button').forEach((button) => {
      button.disabled = busy || (!connected && button.hasAttribute('data-requires-connection'));
    });
  };

  const showGuidedResult = (message, state = '') => {
    const result = document.getElementById('guided-result');
    if (!result) return;
    result.className = `guided-result ${state}`.trim();
    result.textContent = message;
  };

  const setupGuidedFlow = () => {
    const input = document.getElementById('guided-url');
    const navigate = document.getElementById('guided-navigate');
    const screenshot = document.getElementById('guided-screenshot');
    const observe = document.getElementById('guided-observe');
    const error = document.getElementById('guided-url-error');
    if (!input || !navigate || !screenshot || !observe || !error) return;

    const run = async (kind) => {
      error.textContent = '';
      let target = null;
      try { if (kind === 'Navigation') target = normalizeGuidedUrl(input.value); } catch (_) { target = input.value.trim(); }
      const started = performance.now();
      const guidedRun = createGuidedRun(kind, target);
      setGuidedBusy(true);
      showGuidedResult(`${kind} in progress...`, 'loading');
      emitTelemetry('guided_action_started', {action: kind});
      try {
        let response;
        if (kind === 'Navigation') {
          const url = normalizeGuidedUrl(input.value);
          response = await apiPost('/navigate', {url});
          if (!response || response.status === 'error') throw new Error(response?.error?.message || response?.error || 'Navigation failed.');
          saveRecentUrl(url);
          showGuidedResult(`Navigation completed: ${url}`, 'success');
        } else if (kind === 'Screenshot') {
          response = await apiPost('/screenshot');
          if (!response || response.status === 'error') throw new Error(response?.error?.message || response?.error || 'Screenshot failed.');
          showGuidedResult('Screenshot captured. Review it in Screenshot Preview.', 'success');
        } else {
          response = await apiPost('/agent/observe', {condensed: true, max_chars: 6000, max_elements: 80});
          if (!response || response.status === 'error') throw new Error(response?.error?.message || response?.error || 'Observation failed.');
          const output = document.getElementById('agent-output');
          if (output) output.textContent = JSON.stringify(response, null, 2);
          showGuidedResult('Observation completed. Open Agent Tools to inspect the structured result.', 'success');
        }
        completeGuidedRun(guidedRun, 'success', `${kind} completed`, started);
        emitTelemetry('guided_action_completed', {action: kind, run_id: guidedRun.run_id});
      } catch (exception) {
        const message = exception.message || `${kind} failed.`;
        if (kind === 'Navigation') error.textContent = message;
        showGuidedResult(message, 'error');
        completeGuidedRun(guidedRun, 'error', message, started);
        emitTelemetry('guided_action_failed', {action: kind, run_id: guidedRun.run_id, reason: message});
      } finally {
        setGuidedBusy(false);
      }
    };

    navigate.addEventListener('click', () => run('Navigation'));
    screenshot.addEventListener('click', () => run('Screenshot'));
    observe.addEventListener('click', () => run('Observation'));
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') { event.preventDefault(); run('Navigation'); }
    });
    renderRecentUrls();
  };

  const bridgeExistingState = () => {
    const original = window.updateState;
    window.updateState = function updateStateWithContext(state) {
      if (typeof original === 'function') original(state);
      const data = state?.data || state?.result || state || {};
      setConnectedState(Boolean(data.connected), data.tabs_count ?? data.tabs?.length ?? 0);
    };
  };

  document.addEventListener('DOMContentLoaded', () => {
    decorateControls();
    protectDangerousActions();
    setupPalette();
    setupGuidedFlow();
    setupGuidedRunHistory();
    setupWorkflowAssistant();
    setupSessionAssistant();
    setupDiagnosticsAssistant();
    setupTabAssistant();
    setupNetworkAssistant();
    setupCookieAssistant();
    bridgeExistingState();
    document.querySelectorAll('#workspace-nav [data-workspace]').forEach((button) => button.addEventListener('click', () => showWorkspace(button.dataset.workspace)));
    showWorkspace(localStorage.getItem(WORKSPACE_KEY) || 'overview', {silent: true});
    setConnectedState(false, 0);
  });

  window.BrowserHelperUX = {showWorkspace, setConnectedState, emitTelemetry};
  window.BrowserHelperWorkflow = {validate: validateWorkflowSteps, setBusy: setWorkflowBusy};
  window.BrowserHelperSession = {validate: validateSessionState, setBusy: setSessionBusy, showStatus: setSessionStatus};
  window.BrowserHelperDiagnostics = {render: renderFilteredOperationLog};
  window.BrowserHelperCookies = {setCookies: (cookies) => { currentCookies = Array.isArray(cookies) ? [...cookies] : []; }, render: renderFilteredCookies};
  window.BrowserHelperNetwork = {
    render: renderFilteredNetworkLog,
    sanitizeUrl: sanitizeNetworkUrl,
    applyConnection: () => setNetworkCaptureState(networkCaptureActive)
  };
  window.BrowserHelperTabs = {
    setTabs: (tabs) => { currentTabs = Array.isArray(tabs) ? [...tabs] : []; },
    getVisible: filterTabs,
    updateSummary: updateTabSummary,
    announceSwitch: (tabId) => announce(`Switched to tab ${String(tabId).slice(0, 8)}`)
  };
})();
