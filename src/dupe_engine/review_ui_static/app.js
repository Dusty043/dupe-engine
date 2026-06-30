const LABELS = [
  ['duplicate', 'Duplicate'],
  ['likely_duplicate', 'Likely duplicate'],
  ['possible_duplicate', 'Possible duplicate'],
  ['partial_overlap', 'Partial overlap'],
  ['not_duplicate', 'Not duplicate'],
  ['needs_review', 'Needs review'],
];

const state = {
  loading: true,
  error: null,
  run: null,
  pageById: new Map(),
  decisions: new Map(),
  selectedId: null,
  filter: 'needs_review',
  typeFilter: 'all',
  search: '',
  diagnosticsOpen: false,
  draftLabel: '',
  draftNote: '',
  reviewerName: '',
  jobs: [],
  activeJob: null,
  jobPollTimer: null,
  uploadError: null,
  uploading: false,
  pollError: null,
  reviewExpanded: false,
};

const app = document.getElementById('app');

// ---------------------------------------------------------------------------
// Auth token — stored in sessionStorage so it clears when the tab closes.
// Set via the login overlay or by appending ?token=... to the URL on first load.
// ---------------------------------------------------------------------------
function _getToken() {
  return sessionStorage.getItem('dupe_auth_token') || '';
}
function _setToken(t) {
  if (t) sessionStorage.setItem('dupe_auth_token', t.trim());
  else sessionStorage.removeItem('dupe_auth_token');
}

// Pre-seed from URL: ?token=xxx  (stripped from history immediately)
(function seedTokenFromUrl() {
  const params = new URLSearchParams(window.location.search);
  const t = params.get('token');
  if (t) {
    _setToken(t);
    params.delete('token');
    const clean = window.location.pathname + (params.toString() ? '?' + params : '');
    window.history.replaceState({}, '', clean);
  }
})();

async function apiFetch(url, opts = {}) {
  const token = _getToken();
  const headers = { ...(opts.headers || {}) };
  if (token) headers['Authorization'] = 'Bearer ' + token;
  const res = await fetch(url, { ...opts, headers });
  if (res.status === 401) {
    _setToken('');
    showTokenOverlay();
    throw new Error('Authentication required');
  }
  return res;
}

// Browsers can't send Authorization headers on <img src="..."> requests.
// Images use data-auth-src; this loader fetches them with the token and
// swaps in an object URL so the page preview always renders.
async function loadAuthImages() {
  const imgs = document.querySelectorAll('img[data-auth-src]');
  await Promise.all(Array.from(imgs).map(async img => {
    const url = img.getAttribute('data-auth-src');
    if (!url) return;
    try {
      const res = await apiFetch(url);
      if (!res.ok) return;
      const blob = await res.blob();
      img.src = URL.createObjectURL(blob);
      img.removeAttribute('data-auth-src');
    } catch { /* leave image blank on error */ }
  }));
}

function showTokenOverlay() {
  if (document.getElementById('_auth_overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = '_auth_overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;z-index:9999';
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:10px;padding:2rem 2.5rem;max-width:380px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,.25)">
      <h2 style="margin:0 0 .5rem;font-size:1.1rem;font-weight:700">Access token required</h2>
      <p style="margin:0 0 1.2rem;font-size:.875rem;color:#555">Enter the bearer token provided for this instance.</p>
      <input id="_auth_input" type="password" placeholder="paste token here"
        style="width:100%;box-sizing:border-box;padding:.6rem .75rem;border:1px solid #ccc;border-radius:6px;font-size:.95rem;margin-bottom:.75rem">
      <button id="_auth_submit"
        style="width:100%;padding:.65rem;background:#1a56db;color:#fff;border:none;border-radius:6px;font-size:.95rem;cursor:pointer;font-weight:600">
        Sign in
      </button>
      <p id="_auth_err" style="color:#c00;font-size:.8rem;margin:.5rem 0 0;min-height:1em"></p>
    </div>`;
  document.body.appendChild(overlay);

  const input = document.getElementById('_auth_input');
  const btn   = document.getElementById('_auth_submit');
  const err   = document.getElementById('_auth_err');

  async function tryLogin() {
    const t = input.value.trim();
    if (!t) { err.textContent = 'Token cannot be empty.'; return; }
    btn.disabled = true;
    try {
      const res = await fetch('/api/health', { headers: { Authorization: 'Bearer ' + t } });
      if (res.status === 401) { err.textContent = 'Invalid token. Try again.'; btn.disabled = false; return; }
      _setToken(t);
      overlay.remove();
      state.loading = true;
      state.error = null;
      render();
      boot();
    } catch (_) { err.textContent = 'Network error. Try again.'; btn.disabled = false; }
  }

  btn.addEventListener('click', tryLogin);
  input.addEventListener('keydown', e => { if (e.key === 'Enter') tryLogin(); });
  setTimeout(() => input.focus(), 50);
}

boot();

async function boot() {
  try {
    const response = await apiFetch('/api/run', { cache: 'no-store' });
    if (!response.ok) throw new Error(await responseText(response));
    const data = await response.json();
    state.jobs = data.jobs || [];
    if (data.has_run === false) {
      state.run = null;
      state.loading = false;
      render();
      return;
    }
    loadRunData(data);
    state.loading = false;
    render();
  } catch (error) {
    state.loading = false;
    state.error = error instanceof Error ? error.message : String(error);
    render();
  }
}

function loadRunData(data) {
  state.run = normalizeRun(data);
  state.pageById = new Map(state.run.pages.map((page) => [page.page_id, page]));
  state.decisions = new Map(state.run.reviewDecisions.map((decision) => [decision.candidate_id, decision]));
  state.selectedId = state.run.candidates[0]?.candidate_id || null;
  state.filter = 'needs_review';
  state.search = '';
  state.typeFilter = 'all';
  state.reviewExpanded = false;
  applyDecisionDraft();
}

function normalizeRun(data) {
  const candidates = data?.candidates?.candidates || [];
  const pages = data?.pages?.pages || [];
  const reviewDecisions = data?.review_decisions?.decisions || [];
  return {
    manifest: data.manifest || {},
    pages,
    candidates,
    capabilities: data.capabilities || {},
    metrics: data.metrics || {},
    truthEval: data.truth_eval || null,
    fallbackAudit: data.fallback_audit || null,
    progress: data.progress || null,
    reviewDecisions,
    runDirName: data.run_dir_name || 'run',
  };
}

function render() {
  if (state.loading) {
    app.innerHTML = `<div class="loading-shell"><div class="spinner"></div><div><h1>Medical Records Sorter Assist</h1><p>Loading review run...</p></div></div>`;
    return;
  }
  if (state.error) {
    app.innerHTML = `<div class="error-shell"><div><h1>Could not load review run</h1><p>${escapeHtml(state.error)}</p></div></div>`;
    return;
  }

  if (!state.run) {
    app.innerHTML = state.activeJob ? renderProcessingShell() : renderUploadShell();
    bindUploadEvents();
    return;
  }

  const selected = selectedCandidate();
  app.innerHTML = `
    <div class="app-shell app-shell--review">
      ${renderTopbar()}
      <main class="main-grid ${state.reviewExpanded ? 'review-expanded' : ''}">
        <aside class="left-rail">
          ${renderQueueToolbar()}
        </aside>
        <section class="content">
          ${selected ? renderReview(selected) : renderEmptyReview()}
        </section>
      </main>
    </div>
  `;
  bindEvents();
  loadAuthImages();
}

function renderUploadShell() {
  return `
    <div class="app-shell">
      <header class="topbar">
        <div class="topbar-inner">
          <div class="brand">
            <div class="brand-mark">MR</div>
            <div>
              <h1>Medical Records Sorter Assist</h1>
              <p>Upload Received and ERE records to create a local review run.</p>
            </div>
          </div>
          <div class="topbar-actions">
            <button class="btn ghost" data-action="refresh-run">Refresh</button>
          </div>
        </div>
      </header>
      <main class="start-shell">
        <section class="hero-card">
          <div class="hero-copy">
            <span class="eyebrow">Local v0.10.9 workflow</span>
            <h2>Compare incoming medical records against ERE.</h2>
            <p>Files stay on this local machine. The browser uploads PDFs to the local engine server, the engine creates a run folder, and this UI opens the review queue when processing is complete.</p>
          </div>
          <div class="hero-steps">
            <div><b>1</b><span>Upload two buckets</span></div>
            <div><b>2</b><span>Run OCR/candidate detection</span></div>
            <div><b>3</b><span>Review side-by-side</span></div>
          </div>
        </section>

        <form class="upload-form" data-action="upload-form">
          <section class="upload-grid">
            ${renderUploadBucket('received', 'Received Medical Records', 'Upload incoming records that need to be checked against ERE.', 'received_files')}
            ${renderUploadBucket('ere', 'ERE Medical Records', 'Upload existing ERE records used as the comparison set.', 'ere_files')}
          </section>

          <details class="options-details">
            <summary class="options-summary">Advanced options</summary>
            <section class="card options-card">
              <div class="card-body option-grid">
                <label class="field-row">
                  <span>DPI</span>
                  <input name="dpi" type="number" min="72" max="300" value="150" />
                </label>
                <label class="field-row">
                  <span>Tesseract profiles</span>
                  <input name="tesseract_profiles" type="text" value="standard" />
                </label>
                <label class="field-row">
                  <span>OpenAI fallback budget</span>
                  <input name="openai_ocr_max_pages" type="number" min="1" max="500" value="50" />
                </label>
                <label class="field-row">
                  <span>Fallback selection</span>
                  <select name="openai_ocr_selection_mode">
                    <option value="weak_pages_or_vision_expected" selected>Weak pages + vision expected</option>
                    <option value="weak_pages">Weak pages only</option>
                    <option value="vision_expected">Vision expected only</option>
                    <option value="candidate_based">Candidate-based only</option>
                  </select>
                </label>
                <div class="option-note required">
                  <span>OCR + OpenAI fallback required</span>
                  <small>Weak/scanned pages use local OCR first, then OpenAI vision OCR fallback is selected by policy and budget. The run fails fast if the OpenAI key/fallback is unavailable.</small>
                </div>
                <label class="check-row">
                  <input name="multipass_visual_all_pages" type="checkbox" />
                  <span>Broader visual pass</span>
                </label>
              </div>
            </section>
          </details>

          ${state.uploadError ? `<div class="inline-error">${escapeHtml(state.uploadError)}</div>` : ''}

          <div class="start-actions">
            <button class="btn primary big" type="submit" data-action="start-job" disabled>Run Duplicate Check</button>
            <p class="start-hint" data-upload-hint>Select at least one PDF in each bucket.</p>
          </div>
        </form>
        ${renderRecentJobs()}
      </main>
    </div>
  `;
}

function renderUploadBucket(kind, title, helper, inputName) {
  return `
    <section class="upload-bucket ${kind}" data-drop-target="${escapeAttr(inputName)}">
      <div class="upload-bucket-inner">
        <div class="bucket-icon">${kind === 'received' ? 'R' : 'E'}</div>
        <div>
          <h2>${escapeHtml(title)}</h2>
          <p>${escapeHtml(helper)}</p>
        </div>
        <label class="drop-zone">
          <input type="file" name="${escapeAttr(inputName)}" accept="application/pdf,.pdf" multiple data-upload-input="${escapeAttr(inputName)}" />
          <span>Choose or drop PDF files</span>
          <small data-file-summary="${escapeAttr(inputName)}">No files selected</small>
        </label>
      </div>
    </section>
  `;
}

function renderRecentJobs() {
  const jobs = (state.jobs || []).filter((j) => j.status === 'succeeded');
  if (!jobs.length) return '';
  return `
    <section class="card recent-jobs">
      <div class="card-header">
        <div>
          <h2>Previous runs</h2>
          <p>Reopen a completed run to continue reviewing.</p>
        </div>
      </div>
      <div class="card-body job-list">
        ${jobs.slice(0, 8).map((job) => {
          const date = job.created_at ? job.created_at.slice(0, 16).replace('T', ' ') : '';
          const candidates = job.candidate_count != null ? `${job.candidate_count} candidates` : `${(job.received_files || []).length} received · ${(job.ere_files || []).length} ERE`;
          return `
          <div class="job-row">
            <div class="job-row-info">
              <b>${escapeHtml(date)}</b>
              <span>${escapeHtml(candidates)}</span>
            </div>
            <button class="btn small primary" data-action="open-job" data-job-id="${escapeAttr(job.job_id)}">Open</button>
          </div>`;
        }).join('')}
      </div>
    </section>
  `;
}

function renderProcessingShell() {
  const job = state.activeJob || {};
  const status = job.status || 'queued';
  const failed = status === 'failed';
  const succeeded = status === 'succeeded';
  const progress = job.progress || {};
  const percent = typeof progress.percent === 'number' ? Math.round(progress.percent * 100) : null;
  const stage = progress.stage || job.stage || status;
  const events = Array.isArray(progress.events_tail) ? progress.events_tail.slice(-8) : [];
  return `
    <div class="app-shell">
      <header class="topbar">
        <div class="topbar-inner">
          <div class="brand">
            <div class="brand-mark">MR</div>
            <div>
              <h1>Medical Records Sorter Assist</h1>
              <p>${escapeHtml(job.job_id || 'local job')} · ${escapeHtml(status)} · ${escapeHtml(stage)}</p>
            </div>
          </div>
          <div class="topbar-actions">
            <button class="btn ghost" data-action="cancel-to-upload">Start another batch</button>
          </div>
        </div>
      </header>
      <main class="processing-shell">
        <section class="processing-card">
          <div class="spinner ${failed || succeeded ? 'hidden' : ''}"></div>
          <div class="processing-copy">
            <span class="eyebrow">${escapeHtml(status)}</span>
            <h2>${failed ? 'Engine job failed' : succeeded ? 'Review run ready' : 'Running duplicate check locally'}</h2>
            <p>${failed ? 'The engine returned an error. See the log below.' : succeeded ? 'Opening the review queue now.' : escapeHtml(progress.message || 'The engine is reading PDFs, routing OCR/fallback, detecting candidates, and writing UI artifacts.')}</p>
          </div>
          <div class="progress-meter">
            <div class="progress-meter-bar"><span style="width: ${percent ?? 8}%"></span></div>
            <div class="progress-meter-text">${percent === null ? 'Working...' : `${percent}%`} ${progress.current != null && progress.total != null ? `· ${progress.current}/${progress.total}` : ''}</div>
          </div>
          <div class="progress-steps">
            ${progressStep('Upload received', true)}
            ${progressStep('Upload ERE', true)}
            ${progressStep('Run engine', ['running', 'succeeded', 'failed'].includes(status), failed)}
            ${progressStep('Prepare review queue', succeeded, failed)}
          </div>
          ${events.length ? `<div class="progress-events">${events.map(renderProgressEvent).join('')}</div>` : ''}
          ${failed ? renderJobError(job) : ''}
          ${state.pollError ? `<div class="inline-error">Polling error: ${escapeHtml(state.pollError)}</div>` : ''}
        </section>
      </main>
    </div>
  `;
}

function renderJobError(job) {
  const errorText = job.error || '';
  const tail = job.stderr_tail || job.stdout_tail || '';
  const jobId = job.job_id ? escapeHtml(job.job_id) : '';
  const log = [errorText, tail].filter(Boolean).join('\n\n');
  return `
    <div class="job-error-info">
      <p>The engine encountered an error and could not complete this run.</p>
      ${jobId ? `<p class="job-ref">Reference: <code>${jobId}</code></p>` : ''}
      ${log ? `<pre class="job-log">${escapeHtml(log)}</pre>` : ''}
    </div>
  `;
}

function renderProgressEvent(event) {
  const label = event.stage || event.status || 'progress';
  const msg = event.message || '';
  const pct = typeof event.percent === 'number' ? `${Math.round(event.percent * 100)}%` : '';
  return `<div class="progress-event"><b>${escapeHtml(label)}</b><span>${escapeHtml(msg)}</span><em>${escapeHtml(pct)}</em></div>`;
}

function progressStep(label, active, danger = false) {
  const cls = active ? (danger ? 'danger' : 'active') : '';
  return `<div class="progress-step ${cls}"><b></b><span>${escapeHtml(label)}</span></div>`;
}

function renderTopbar() {
  const manifest = state.run.manifest;
  const reviewed = state.decisions.size;
  const total = state.run.candidates.length;
  return `
    <header class="topbar">
      <div class="topbar-inner">
        <div class="brand">
          <div class="brand-mark">MR</div>
          <div>
            <h1>Medical Records Sorter Assist</h1>
            <p>${escapeHtml(manifest.command || 'review run')} · ${escapeHtml(state.run.runDirName)} · ${reviewed}/${total} reviewed</p>
          </div>
        </div>
        <div class="topbar-actions">
          <label class="reviewer-field">
            <span>Reviewer</span>
            <input type="text" data-action="reviewer-name" placeholder="Your name" value="${escapeAttr(state.reviewerName)}" />
          </label>
          <button class="btn primary" data-action="new-batch">Start new batch</button>
          <button class="btn" data-action="export-csv">Export CSV</button>
          <button class="btn" data-action="export-json">Export decisions JSON</button>
        </div>
      </div>
    </header>
  `;
}

function renderProgressCard() {
  const counts = sourceCounts();
  const total = state.run.candidates.length;
  const reviewed = state.decisions.size;
  const needsReview = total - reviewed;
  const pct = total > 0 ? Math.round((reviewed / total) * 100) : 0;
  return `
    <section class="card">
      <div class="card-body">
        <div class="progress-header">
          <h2>Review progress</h2>
          <span class="progress-fraction">${reviewed} / ${total}</span>
        </div>
        <div class="progress-bar-wrap">
          <div class="progress-bar-fill" style="width:${pct}%"></div>
        </div>
        <div class="batch-cards">
          <div class="batch-card received">
            <div class="label">Received Records</div>
            <div class="value">${counts.received}</div>
            <div class="helper">Incoming pages</div>
          </div>
          <div class="batch-card ere">
            <div class="label">ERE Records</div>
            <div class="value">${counts.ere}</div>
            <div class="helper">Comparison pages</div>
          </div>
        </div>
        <div class="summary-mini">
          ${needsReview > 0 ? `<span class="badge warn">${needsReview} to review</span>` : '<span class="badge good">All reviewed</span>'}
          <span class="badge outline">${total} candidates</span>
        </div>
      </div>
    </section>
  `;
}

function renderBatchSummary() {
  const counts = sourceCounts();
  return `
    <section class="card">
      <div class="card-header">
        <div>
          <h2>Batch comparison</h2>
          <p>Two-bucket workflow preserved from the original POC.</p>
        </div>
      </div>
      <div class="card-body">
        <div class="batch-cards">
          <div class="batch-card received">
            <div class="label">Received Medical Records</div>
            <div class="value">${counts.received}</div>
            <div class="helper">Incoming pages to check against ERE.</div>
          </div>
          <div class="batch-card ere">
            <div class="label">ERE Medical Records</div>
            <div class="value">${counts.ere}</div>
            <div class="helper">Existing record pages used for comparison.</div>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderRunStats() {
  const summary = state.run.metrics.summary || state.run.manifest.summary || {};
  const totalCandidates = state.run.candidates.length;
  const reviewed = state.decisions.size;
  const needsReview = state.run.candidates.filter((c) => !state.decisions.has(c.candidate_id)).length;
  const partial = state.run.candidates.filter((c) => c.engine_label === 'partial_overlap' || c.review_bucket === 'partial_overlap').length;
  return `
    <section class="card">
      <div class="card-header">
        <div>
          <h2>Run summary</h2>
          <p>Candidate queue generated by the engine.</p>
        </div>
      </div>
      <div class="card-body summary-grid">
        ${stat('Pages', summary.total_pages ?? state.run.pages.length)}
        ${stat('Candidates', totalCandidates)}
        ${stat('Needs review', needsReview)}
        ${stat('Reviewed', reviewed)}
        ${stat('Likely dupes', summary.engine_candidate_label_counts?.likely_duplicate ?? countByLabel('likely_duplicate'))}
        ${stat('Partial overlaps', partial)}
      </div>
    </section>
  `;
}

function stat(key, value) {
  return `<div class="summary-stat"><div class="k">${escapeHtml(key)}</div><div class="v">${escapeHtml(String(value ?? 0))}</div></div>`;
}

function renderCapabilityCard() {
  const c = state.run.capabilities || {};
  return `
    <section class="card">
      <div class="card-header">
        <div>
          <h2>Capability status</h2>
          <p>Shown so OCR/fallback gaps do not silently disappear.</p>
        </div>
      </div>
      <div class="card-body status-list">
        ${capabilityRow('Deterministic checks', c.deterministic_multipass || c.weighted_text_similarity || c.exact_image_hash)}
        ${capabilityRow('OCR routing', c.ocr)}
        ${capabilityRow('Tesseract OCR', c.tesseract_ocr)}
        ${capabilityRow('Vision fallback', c.openai_ocr_fallback)}
        ${capabilityRow('Embeddings', c.embeddings)}
        ${capabilityRow('LLM adjudicator', c.adjudicator_agent || c.llm_candidate_detector)}
      </div>
    </section>
  `;
}

function capabilityRow(label, layer) {
  const status = capabilityStatus(layer);
  return `<div class="status-row"><span>${escapeHtml(label)}</span>${badge(status.label, status.tone)}</div>`;
}

function capabilityStatus(layer) {
  if (!layer) return { label: 'Unknown', tone: 'outline' };
  if (layer.used) return { label: 'Used', tone: 'good' };
  if (layer.enabled && layer.available) return { label: 'Available', tone: 'info' };
  if (layer.enabled && !layer.available) return { label: 'Unavailable', tone: 'danger' };
  return { label: 'Disabled', tone: 'outline' };
}

function renderDiagnosticsCard() {
  const hidden = state.diagnosticsOpen ? '' : ' hidden';
  const evalSummary = state.run.truthEval?.summary || state.run.metrics.eval_summary || null;
  return `
    <section class="card${hidden}">
      <div class="card-header">
        <div>
          <h2>Run diagnostics</h2>
          <p>Internal calibration view. Keep this out of the primary reviewer workflow.</p>
        </div>
      </div>
      <div class="card-body">
        <div class="diagnostics">${escapeHtml(JSON.stringify({
          engine_version: state.run.manifest.engine_version,
          artifact_contract_version: state.run.manifest.artifact_contract_version,
          truth_status: state.run.manifest.truth_status,
          recall_by_expected_min_layer: evalSummary?.recall_by_expected_min_layer || null,
          ocr_summary: state.run.metrics.ocr_summary || null,
          fallback_audit_summary: state.run.fallbackAudit?.summary || null,
          ai_call_summary: state.run.metrics.ai_call_summary || null,
        }, null, 2))}</div>
      </div>
    </section>
  `;
}

function renderQueueToolbar() {
  const visible = filteredCandidates();
  return `
    <section class="card">
      <div class="card-body">
        <div class="tabs">
          ${tab('needs_review', 'Needs Review')}
          ${tab('reviewed', 'Reviewed')}
          ${tab('all', 'All')}
        </div>
        <div class="queue-toolbar">
          <label class="search-box">
            <span class="icon">⌕</span>
            <input type="search" value="${escapeAttr(state.search)}" placeholder="Search file or page..." data-action="search" />
          </label>
        </div>
        <div class="candidate-list">
          ${visible.length ? visible.map(renderCandidateCard).join('') : '<div class="empty-state"><h2>No candidates in this queue</h2><p>Try changing the filter or search term.</p></div>'}
        </div>
      </div>
    </section>
  `;
}

function tab(value, label) {
  const active = state.filter === value ? ' active' : '';
  return `<button class="tab${active}" data-filter="${value}">${escapeHtml(label)} <span>${filterCount(value)}</span></button>`;
}

function option(value, label) {
  return `<option value="${escapeAttr(value)}" ${state.typeFilter === value ? 'selected' : ''}>${escapeHtml(label)}</option>`;
}

function filterCount(filter) {
  return state.run.candidates.filter((c) => matchesFilterOnly(c, filter)).length;
}

function renderCandidateCard(c) {
  const reviewed = state.decisions.get(c.candidate_id);
  const active = state.selectedId === c.candidate_id ? ' active' : '';
  const reviewedClass = reviewed ? ' reviewed' : '';
  return `
    <button class="candidate-card${active}${reviewedClass}" data-candidate-id="${escapeAttr(c.candidate_id)}">
      <div class="candidate-top">
        <div class="candidate-title">${escapeHtml(labelName(c.engine_label || c.review_bucket || 'candidate'))} · ${Math.round((c.confidence || 0) * 100)}%</div>
        ${reviewed ? badge(labelName(reviewed.human_label), 'good') : badge('Needs review', 'outline')}
      </div>
      <div class="candidate-paths">
        <div class="path-row"><b>Received:</b><span>${escapeHtml(c.left?.document || '')} p.${escapeHtml(String(c.left?.page || ''))}</span></div>
        <div class="path-row"><b>ERE:</b><span>${escapeHtml(c.right?.document || '')} p.${escapeHtml(String(c.right?.page || ''))}</span></div>
      </div>
    </button>
  `;
}

function renderReview(c) {
  const decision = state.decisions.get(c.candidate_id);
  return `
    <div class="review-shell">
      <div class="review-header">
        <div class="review-title">
          <h2>${escapeHtml(labelName(c.engine_label || c.review_bucket || 'candidate'))}</h2>
          <p>${Math.round((c.confidence || 0) * 100)}% match confidence</p>
        </div>
        <div class="review-actions">
          ${badge(decision ? `Reviewed: ${labelName(decision.human_label)}` : 'Unreviewed', decision ? 'good' : 'outline')}
          <button class="btn small" data-action="toggle-expanded-review">${state.reviewExpanded ? 'Exit large view' : 'Expand comparison'}</button>
        </div>
      </div>
      <div class="compare-grid">
        ${renderPagePane(c.left, 'received')}
        ${renderPagePane(c.right, 'ere')}
        ${renderDecisionPanel(c)}
      </div>
    </div>
  `;
}

function renderPagePane(side, kind) {
  const page = state.pageById.get(side?.page_id) || {};
  const label = sideLabel(side, kind === 'received' ? 'Received Medical Records' : 'ERE Medical Records');
  const imageUrl = assetUrl(side?.asset_image_path || page.asset_image_path || '');
  return `
    <section class="page-pane ${kind}">
      <div class="pane-head">
        <div>
          <h3>${escapeHtml(label)}</h3>
          <p>${escapeHtml(side?.document || page.document_name || '')}</p>
        </div>
        ${badge(`Page ${side?.page || page.page_number || '?'}`, kind === 'received' ? 'info' : 'ere')}
      </div>
      <div class="image-frame">
        ${imageUrl ? `<img data-auth-src="${escapeAttr(imageUrl)}" alt="${escapeAttr(label)} page preview" />` : '<div class="empty-state"><p>No page preview asset available.</p></div>'}
      </div>
    </section>
  `;
}

function renderDecisionPanel(c) {
  return `
    <aside class="decision-panel">
      <div class="panel-section panel-decision-intro">
        <h3>Is this a duplicate?</h3>
        <p class="panel-confidence">${Math.round((c.confidence || 0) * 100)}% match confidence</p>
      </div>
      <div class="panel-section">
        <div class="decision-buttons">
          ${LABELS.map(([value, label]) => `<button class="decision-button ${state.draftLabel === value ? 'active' : ''}" data-decision-label="${value}">${escapeHtml(label)}</button>`).join('')}
        </div>
      </div>
      <div class="panel-section">
        <h3>Note <span class="note-optional">(optional)</span></h3>
        <textarea class="note-box" data-action="note" placeholder="Add a note...">${escapeHtml(state.draftNote || '')}</textarea>
      </div>
      <div class="panel-section">
        <button class="btn primary block" data-action="save-decision" ${state.draftLabel && state.reviewerName.trim() ? '' : 'disabled'}>${state.draftLabel && !state.reviewerName.trim() ? 'Enter reviewer name to save' : 'Save decision'}</button>
      </div>
    </aside>
  `;
}

function renderSignal(signal) {
  const score = typeof signal.score === 'number' ? formatScore(signal.score) : '';
  return `<div class="signal-item"><span>${escapeHtml(signal.name || 'signal')}</span><b>${escapeHtml(score)}</b></div>`;
}

function renderEmptyReview() {
  return `<div class="empty-state"><h2>No candidate selected</h2><p>Select a candidate from the review queue.</p></div>`;
}

function bindEvents() {
  document.querySelectorAll('[data-candidate-id]').forEach((button) => {
    button.addEventListener('click', () => {
      state.selectedId = button.dataset.candidateId;
      applyDecisionDraft();
      render();
    });
  });
  document.querySelector('[data-action="toggle-expanded-review"]')?.addEventListener('click', () => {
    state.reviewExpanded = !state.reviewExpanded;
    render();
  });
  document.querySelectorAll('[data-filter]').forEach((button) => {
    button.addEventListener('click', () => {
      state.filter = button.dataset.filter || 'all';
      selectFirstVisible();
      render();
    });
  });
  document.querySelector('[data-action="search"]')?.addEventListener('input', (event) => {
    state.search = event.target.value;
    selectFirstVisible(false);
    render();
  });
  document.querySelector('[data-action="type-filter"]')?.addEventListener('change', (event) => {
    state.typeFilter = event.target.value;
    selectFirstVisible();
    render();
  });
  document.querySelectorAll('[data-decision-label]').forEach((button) => {
    button.addEventListener('click', () => {
      state.draftLabel = button.dataset.decisionLabel;
      render();
    });
  });
  document.querySelector('[data-action="note"]')?.addEventListener('input', (event) => {
    state.draftNote = event.target.value;
  });
  document.querySelector('[data-action="reviewer-name"]')?.addEventListener('input', (event) => {
    state.reviewerName = event.target.value;
  });
  document.querySelector('[data-action="save-decision"]')?.addEventListener('click', saveDecision);
  document.querySelector('[data-action="export-csv"]')?.addEventListener('click', exportCsv);
  document.querySelector('[data-action="export-json"]')?.addEventListener('click', exportJson);
  document.querySelector('[data-action="toggle-diagnostics"]')?.addEventListener('click', () => {
    state.diagnosticsOpen = !state.diagnosticsOpen;
    render();
  });
  document.querySelector('[data-action="new-batch"]')?.addEventListener('click', startNewBatch);
}

function bindUploadEvents() {
  document.querySelectorAll('[data-upload-input]').forEach((input) => {
    input.addEventListener('change', updateUploadCta);
  });
  document.querySelectorAll('[data-drop-target]').forEach((zone) => {
    const inputName = zone.dataset.dropTarget;
    zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragenter', (e) => { e.preventDefault(); zone.classList.add('drag-over'); });
    zone.addEventListener('dragleave', (e) => { if (!zone.contains(e.relatedTarget)) zone.classList.remove('drag-over'); });
    zone.addEventListener('drop', (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const input = zone.querySelector(`[data-upload-input="${inputName}"]`);
      if (!input) return;
      const dropped = Array.from(e.dataTransfer.files).filter(
        (f) => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
      );
      if (!dropped.length) return;
      const dt = new DataTransfer();
      for (const f of dropped) dt.items.add(f);
      input.files = dt.files;
      updateUploadCta();
    });
  });
  document.querySelector('[data-action="upload-form"]')?.addEventListener('submit', startUploadJob);
  document.querySelector('[data-action="refresh-run"]')?.addEventListener('click', boot);
  document.querySelectorAll('[data-action="open-job"]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const jobId = btn.dataset.jobId;
      btn.disabled = true;
      btn.textContent = 'Opening…';
      try {
        const res = await apiFetch('/api/run/load', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ job_id: jobId }),
        });
        if (!res.ok) throw new Error(await responseText(res));
        const data = await res.json();
        loadRunData(data);
        state.loading = false;
        render();
      } catch (err) {
        state.uploadError = err.message || 'Failed to open run';
        render();
      }
    });
  });
  document.querySelector('[data-action="cancel-to-upload"]')?.addEventListener('click', () => {
    clearJobPolling();
    state.activeJob = null;
    state.uploadError = null;
    state.pollError = null;
    render();
  });
  updateUploadCta();
}

function updateUploadCta() {
  const received = document.querySelector('[data-upload-input="received_files"]');
  const ere = document.querySelector('[data-upload-input="ere_files"]');
  const receivedCount = received?.files?.length || 0;
  const ereCount = ere?.files?.length || 0;
  updateFileSummary('received_files', receivedCount);
  updateFileSummary('ere_files', ereCount);
  const button = document.querySelector('[data-action="start-job"]');
  const hint = document.querySelector('[data-upload-hint]');
  if (button) button.disabled = state.uploading || !receivedCount || !ereCount;
  if (hint) hint.textContent = receivedCount && ereCount ? `${receivedCount} received PDF(s), ${ereCount} ERE PDF(s) ready.` : 'Select at least one PDF in each bucket.';
}

function updateFileSummary(name, count) {
  const el = document.querySelector(`[data-file-summary="${name}"]`);
  if (el) el.textContent = count ? `${count} PDF file${count === 1 ? '' : 's'} selected` : 'No files selected';
}

async function startUploadJob(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const received = form.querySelector('[data-upload-input="received_files"]');
  const ere = form.querySelector('[data-upload-input="ere_files"]');
  if (!received?.files?.length || !ere?.files?.length) {
    state.uploadError = 'Select at least one PDF in each bucket.';
    render();
    return;
  }
  const formData = new FormData();
  for (const file of received.files) formData.append('received_files', file);
  for (const file of ere.files) formData.append('ere_files', file);
  formData.append('dpi', form.querySelector('input[name="dpi"]')?.value || '150');
  formData.append('tesseract_profiles', form.querySelector('input[name="tesseract_profiles"]')?.value || 'standard');
  formData.append('openai_ocr_max_pages', form.querySelector('input[name="openai_ocr_max_pages"]')?.value || '50');
  formData.append('openai_ocr_selection_mode', form.querySelector('select[name="openai_ocr_selection_mode"]')?.value || 'weak_pages_or_vision_expected');
  formData.append('ocr', 'true');
  formData.append('require_ocr', 'true');
  formData.append('openai_ocr', 'true');
  formData.append('require_openai_ocr', 'true');
  formData.append('openai_ocr_live', 'true');
  formData.append('multipass_visual_all_pages', form.querySelector('input[name="multipass_visual_all_pages"]')?.checked ? 'true' : 'false');

  state.uploading = true;
  state.uploadError = null;
  state.pollError = null;
  updateUploadCta();
  try {
    const response = await apiFetch('/api/jobs', { method: 'POST', body: formData });
    if (!response.ok) throw new Error(await responseText(response));
    state.activeJob = await response.json();
    state.uploading = false;
    render();
    startJobPolling(state.activeJob.job_id);
  } catch (error) {
    state.uploading = false;
    state.uploadError = error instanceof Error ? error.message : String(error);
    render();
  }
}

function startJobPolling(jobId) {
  clearJobPolling();
  refreshJob(jobId);
  state.jobPollTimer = setInterval(() => refreshJob(jobId), 1500);
}

function clearJobPolling() {
  if (state.jobPollTimer) {
    clearInterval(state.jobPollTimer);
    state.jobPollTimer = null;
  }
}

async function refreshJob(jobId) {
  try {
    const response = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' });
    if (!response.ok) throw new Error(await responseText(response));
    const job = await response.json();
    state.activeJob = job;
    state.pollError = null;
    if (job.status === 'succeeded') {
      clearJobPolling();
      const runResponse = await apiFetch('/api/run', { cache: 'no-store' });
      if (!runResponse.ok) throw new Error(await responseText(runResponse));
      const runData = await runResponse.json();
      loadRunData(runData);
      state.activeJob = null;
    } else if (job.status === 'failed') {
      clearJobPolling();
    }
    render();
  } catch (error) {
    clearJobPolling();
    state.pollError = error instanceof Error ? error.message : String(error);
    render();
  }
}

async function startNewBatch() {
  const response = await apiFetch('/api/clear-run', { method: 'POST' });
  if (!response.ok) {
    showToast(await responseText(response));
    return;
  }
  state.run = null;
  state.pageById = new Map();
  state.decisions = new Map();
  state.selectedId = null;
  state.activeJob = null;
  state.uploadError = null;
  clearJobPolling();
  render();
}

async function saveDecision() {
  const candidate = selectedCandidate();
  if (!candidate || !state.draftLabel) return;
  const decision = {
    candidate_id: candidate.candidate_id,
    human_label: state.draftLabel,
    reviewer_note: state.draftNote || '',
    reviewer_name: state.reviewerName || '',
    reviewed_at: new Date().toISOString(),
  };
  const response = await apiFetch('/api/review-decisions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ decision }),
  });
  if (!response.ok) {
    showToast(await responseText(response));
    return;
  }
  const payload = await response.json();
  state.decisions = new Map((payload.decisions || []).map((item) => [item.candidate_id, item]));
  showToast('Decision saved');
  moveToNextUnreviewed();
  applyDecisionDraft();
  render();
}

function moveToNextUnreviewed() {
  const visible = filteredCandidates();
  const currentIndex = visible.findIndex((c) => c.candidate_id === state.selectedId);
  const next = visible.slice(currentIndex + 1).find((c) => !state.decisions.has(c.candidate_id)) || visible.find((c) => !state.decisions.has(c.candidate_id));
  if (next) state.selectedId = next.candidate_id;
}

function applyDecisionDraft() {
  const decision = state.decisions.get(state.selectedId);
  state.draftLabel = decision?.human_label || '';
  state.draftNote = decision?.reviewer_note || '';
}

function selectedCandidate() {
  return state.run?.candidates.find((candidate) => candidate.candidate_id === state.selectedId) || state.run?.candidates[0] || null;
}

function filteredCandidates() {
  const query = state.search.trim().toLowerCase();
  return state.run.candidates.filter((candidate) => {
    if (!matchesFilterOnly(candidate, state.filter)) return false;
    if (!matchesTypeFilter(candidate)) return false;
    if (!query) return true;
    return candidateSearchText(candidate).includes(query);
  });
}

function matchesFilterOnly(candidate, filter) {
  const reviewed = state.decisions.has(candidate.candidate_id);
  if (filter === 'needs_review') return !reviewed;
  if (filter === 'reviewed') return reviewed;
  if (filter === 'secondary') return !reviewed && candidate.queue === 'secondary_review';
  if (filter === 'likely') return ['duplicate', 'likely_duplicate'].includes(candidate.engine_label) || ['duplicate', 'likely_duplicate'].includes(candidate.review_bucket);
  if (filter === 'partial') return candidate.engine_label === 'partial_overlap' || candidate.review_bucket === 'partial_overlap' || candidate.expected_min_layer === 'human_review';
  return true;
}

function matchesTypeFilter(candidate) {
  const family = matchFamily(candidate);
  if (state.typeFilter === 'all') return true;
  if (state.typeFilter === 'context') return family === 'context';
  if (state.typeFilter === 'image') return family === 'image';
  if (state.typeFilter === 'ocr') return sideHasOcr(candidate.left) || sideHasOcr(candidate.right) || candidate.expected_min_layer === 'ocr';
  if (state.typeFilter === 'vision') return sideNeedsVision(candidate.left) || sideNeedsVision(candidate.right) || candidate.expected_min_layer === 'vision_fallback';
  return true;
}

function selectFirstVisible(strict = true) {
  const visible = filteredCandidates();
  if (!visible.length) {
    if (strict) state.selectedId = null;
    return;
  }
  if (!visible.some((c) => c.candidate_id === state.selectedId)) state.selectedId = visible[0].candidate_id;
  applyDecisionDraft();
}

function candidateSearchText(candidate) {
  return [
    candidate.candidate_id,
    candidate.engine_label,
    candidate.review_bucket,
    candidate.match_type,
    candidate.review_rationale,
    candidate.expected_min_layer,
    ...(candidate.required_layers || []),
    ...(candidate.reason_tags || []),
    candidate.left?.document,
    candidate.right?.document,
    String(candidate.left?.page || ''),
    String(candidate.right?.page || ''),
  ].filter(Boolean).join(' ').toLowerCase();
}

function countByLabel(label) {
  return state.run.candidates.filter((c) => c.engine_label === label || c.review_bucket === label).length;
}

function sourceCounts() {
  let received = 0;
  let ere = 0;
  let other = 0;
  for (const page of state.run.pages) {
    const kind = sourceKind(page);
    if (kind === 'received') received += 1;
    else if (kind === 'ere') ere += 1;
    else other += 1;
  }
  if (!received && !ere) {
    const half = Math.ceil(state.run.pages.length / 2);
    return { received: half, ere: state.run.pages.length - half, other };
  }
  return { received, ere, other };
}

function sourceKind(pageOrSide) {
  const page = pageOrSide?.page_id ? (state.pageById.get(pageOrSide.page_id) || pageOrSide) : pageOrSide;
  const group = String(page?.group || '').toUpperCase();
  const path = String(page?.document_name || page?.document || page?.relative_pdf_path || '').toLowerCase();
  if (group === 'A' || path.includes('source_a') || path.includes('received')) return 'received';
  if (group === 'B' || path.includes('source_b') || path.includes('ere')) return 'ere';
  return 'other';
}

function sideLabel(side, fallback) {
  const kind = sourceKind(side);
  if (kind === 'received') return 'Received Medical Records';
  if (kind === 'ere') return 'ERE Medical Records';
  return fallback;
}

function matchFamily(candidate) {
  const type = String(candidate.match_type || '').toLowerCase();
  const signalNames = (candidate.signals || []).map((s) => String(s.name || '').toLowerCase()).join(' ');
  if (type.includes('image') || type.includes('phash') || signalNames.includes('image') || signalNames.includes('perceptual')) return 'image';
  return 'context';
}

function matchFamilyLabel(candidate) {
  return matchFamily(candidate) === 'image' ? 'Image duplicate' : 'Context overlap';
}

function sideHasOcr(side) {
  return Boolean(side?.tesseract_attempted || side?.openai_ocr_attempted || side?.best_text_source === 'tesseract' || side?.best_text_source === 'openai_ocr');
}

function sideNeedsVision(side) {
  return Boolean(side?.openai_ocr_selected || side?.ocr_route === 'openai_candidate' || side?.ocr_route === 'tesseract_weak');
}

function isRerankerDemoted(candidate) {
  return String(candidate.review_rationale || '').includes('embedding_reranker_demoted');
}

function explanation(candidate) {
  if (candidate.review_rationale) return candidate.review_rationale;
  const parts = [];
  if (matchFamily(candidate) === 'image') parts.push('The pair was flagged by visual/image similarity.');
  else parts.push('The pair was flagged by text/context similarity.');
  if (sideHasOcr(candidate.left) || sideHasOcr(candidate.right)) parts.push('OCR was involved on at least one page.');
  if (sideNeedsVision(candidate.left) || sideNeedsVision(candidate.right)) parts.push('One page may need vision fallback or human attention.');
  return parts.join(' ');
}

function badge(text, tone = 'outline') {
  if (!text) return '';
  return `<span class="badge ${escapeAttr(tone)}">${escapeHtml(String(text).replaceAll('_', ' '))}</span>`;
}

function fact(label, value) {
  return `<div class="fact-row"><span>${escapeHtml(label)}</span><b>${escapeHtml(String(value ?? 'n/a'))}</b></div>`;
}

function labelName(value) {
  const pair = LABELS.find(([key]) => key === value);
  if (pair) return pair[1];
  return String(value || '').replaceAll('_', ' ');
}

function formatScore(value) {
  if (value > 1) return value.toFixed(2);
  return `${Math.round(value * 100)}%`;
}

function assetUrl(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  return `/run-artifacts/${path.split('/').map(encodeURIComponent).join('/')}`;
}

function exportCsv() {
  const rows = [
    ['candidate_id', 'review_status', 'human_label', 'reviewer_name', 'reviewer_note', 'engine_label', 'confidence', 'match_type', 'left_file', 'left_page', 'right_file', 'right_page', 'expected_min_layer', 'reranker_demoted', 'explanation'],
    ...state.run.candidates.map((c) => {
      const decision = state.decisions.get(c.candidate_id);
      return [
        c.candidate_id,
        decision ? 'reviewed' : 'unreviewed',
        decision?.human_label || '',
        decision?.reviewer_name || '',
        decision?.reviewer_note || '',
        c.engine_label || '',
        c.confidence ?? '',
        c.match_type || '',
        c.left?.document || '',
        c.left?.page || '',
        c.right?.document || '',
        c.right?.page || '',
        c.expected_min_layer || '',
        isRerankerDemoted(c) ? 'yes' : '',
        explanation(c),
      ];
    }),
  ];
  const csv = rows.map((row) => row.map(csvCell).join(',')).join('\n');
  downloadText('dupe_review_results.csv', csv, 'text/csv');
}

function exportJson() {
  const payload = {
    schema_version: 'dupe_engine_review_decisions_v0_8_6',
    exported_at: new Date().toISOString(),
    decisions: [...state.decisions.values()],
  };
  downloadText('review_decisions.json', JSON.stringify(payload, null, 2), 'application/json');
}

function csvCell(value) {
  const text = String(value ?? '');
  return `"${text.replaceAll('"', '""')}"`;
}

function downloadText(filename, text, type) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function showToast(message) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 2200);
}

async function responseText(response) {
  try {
    const data = await response.json();
    return data.error || JSON.stringify(data);
  } catch (_) {
    return response.statusText || 'Request failed';
  }
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function escapeAttr(value) {
  return escapeHtml(value);
}
