/**
 * Visual Project Intelligence Search
 * Newforma Hackathon 2026 - Project 2
 *
 * P6: UI → API integration + results
 *   - Connected search bar to POST /api/search
 *   - Results display: project link, tags, date, similarity score
 *   - Loading state during all async operations
 *   - Empty state with clear-search action
 *   - API key forwarded via X-API-Key header
 */

const API_BASE = '';  // same origin — served by FastAPI

// Read API key from meta tag (set by server) or env-injected window var.
// Falls back to empty string so unauthenticated dev mode still works.
const API_KEY = window.__API_KEY__ || '';

// ── State ──────────────────────────────────────────────────
let allPhotos   = [];
let currentPhoto = null;
let searchMode  = 'idle'; // 'idle' | 'searching' | 'results'

// ── DOM refs ───────────────────────────────────────────────
const searchInput     = document.getElementById('search-input');
const searchBtn       = document.getElementById('search-btn');
const filterProject   = document.getElementById('filter-project');
const filterPhotog    = document.getElementById('filter-photographer');
const analyzeAllBtn   = document.getElementById('analyze-all-btn');
const resetBtn        = document.getElementById('reset-btn');
const refreshBtn      = document.getElementById('refresh-btn');
const selectFolderBtn = document.getElementById('select-folder-btn');
const folderInput     = document.getElementById('folder-input');
const photoGrid       = document.getElementById('photo-grid');
const emptyState      = document.getElementById('empty-state');
const emptyTitle      = document.getElementById('empty-title');
const emptyMessage    = document.getElementById('empty-message');
const emptyClearBtn   = document.getElementById('empty-clear-btn');
const loadingState    = document.getElementById('loading-state');
const loadingMessage  = document.getElementById('loading-message');
const resultsInfo     = document.getElementById('results-info');
const statsBadge      = document.getElementById('stats-badge');
const analyzeProgress = document.getElementById('analyze-progress');
const progressFill    = document.getElementById('progress-bar-fill');
const progressLabel   = document.getElementById('progress-label');

// Modal
const modalOverlay    = document.getElementById('modal-overlay');
const modalClose      = document.getElementById('modal-close');
const modalImage      = document.getElementById('modal-image');
const modalTitle      = document.getElementById('modal-title');
const modalMeta       = document.getElementById('modal-meta');
const modalDesc       = document.getElementById('modal-description');
const modalTags       = document.getElementById('modal-tags');
const modalLabels     = document.getElementById('modal-labels');
const modalAnalyzeBtn = document.getElementById('modal-analyze-btn');

// Toast
const toast = document.getElementById('toast');

// ── API helper ─────────────────────────────────────────────
/**
 * Thin fetch wrapper that:
 *  - Prepends API_BASE
 *  - Injects X-API-Key header when API_KEY is set
 *  - Throws on non-2xx responses with a readable message
 */
async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (API_KEY) headers['X-API-Key'] = API_KEY;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

// ── Init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  analyzeProgress.hidden = true;
  loadFilters();
  loadAllPhotos();
  bindEvents();
});

function bindEvents() {
  searchBtn.addEventListener('click', handleSearch);
  searchInput.addEventListener('keydown', e => { if (e.key === 'Enter') handleSearch(); });
  analyzeAllBtn.addEventListener('click', handleAnalyzeAll);
  resetBtn.addEventListener('click', handleReset);
  refreshBtn.addEventListener('click', () => loadAllPhotos());
  selectFolderBtn.addEventListener('click', () => folderInput.click());
  folderInput.addEventListener('change', handleFolderSelect);
  modalClose.addEventListener('click', closeModal);
  modalOverlay.addEventListener('click', e => { if (e.target === modalOverlay) closeModal(); });
  modalAnalyzeBtn.addEventListener('click', handleAnalyzeSingle);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
  emptyClearBtn.addEventListener('click', handleClear);

  // Suggestion chips
  document.querySelectorAll('.suggestion-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      searchInput.value = chip.dataset.query;
      handleSearch();
    });
  });

  // Filter changes trigger search if there's a query, else re-render all
  filterProject.addEventListener('change', () => {
    if (searchInput.value.trim()) handleSearch(); else renderPhotos(allPhotos);
  });
  filterPhotog.addEventListener('change', () => {
    if (searchInput.value.trim()) handleSearch(); else renderPhotos(allPhotos);
  });
}

// ── Data Loading ───────────────────────────────────────────
async function loadAllPhotos() {
  showLoading(true, 'Loading photos...');
  try {
    const photos = await apiFetch('/api/photos');
    // API returns array directly
    allPhotos = Array.isArray(photos) ? photos : (photos.photos || []);
    renderPhotos(allPhotos);
    updateStatsBadge(allPhotos);
  } catch (err) {
    showToast('Could not connect to backend. Make sure the server is running.', 'error');
    showEmpty(true, 'Cannot reach the server', 'Make sure the backend is running on this host.');
  } finally {
    showLoading(false);
  }
}

async function loadFilters() {
  try {
    const projects = await apiFetch('/api/projects');
    const list = Array.isArray(projects) ? projects : [];
    list.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.project_id;
      opt.textContent = `${p.project_id} – ${p.project_name}`;
      filterProject.appendChild(opt);
    });
  } catch (_) { /* filters are optional */ }

  // Populate photographer filter from loaded photos (no dedicated endpoint needed)
  // Done after loadAllPhotos via updatePhotographerFilter()
}

function updatePhotographerFilter(photos) {
  // Clear existing options except the first ("All Photographers")
  while (filterPhotog.options.length > 1) filterPhotog.remove(1);
  const seen = new Set();
  photos.forEach(p => {
    if (p.taken_by && !seen.has(p.taken_by)) {
      seen.add(p.taken_by);
      const opt = document.createElement('option');
      opt.value = p.taken_by;
      opt.textContent = p.taken_by;
      filterPhotog.appendChild(opt);
    }
  });
}

function updateStatsBadge(photos) {
  const analyzed = photos.filter(p => p.ai_description || (p.ai_labels && p.ai_labels.length)).length;
  const projects = new Set(photos.map(p => p.project_id).filter(Boolean)).size;
  statsBadge.textContent = `${analyzed}/${photos.length} analyzed · ${projects} project${projects !== 1 ? 's' : ''}`;
}

// ── Search ─────────────────────────────────────────────────
async function handleSearch() {
  const query = searchInput.value.trim();
  if (!query) {
    handleClear();
    return;
  }

  searchBtn.disabled = true;
  searchBtn.textContent = '...';
  showLoading(true, `Searching for "${query}"...`);
  showEmpty(false);
  photoGrid.innerHTML = '';

  try {
    const body = {
      query,
      project_id: filterProject.value || null,
      taken_by:   filterPhotog.value   || null,
    };

    const data = await apiFetch('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });

    // API returns { results, total, mode, ... }
    const results = data.results || [];
    const total   = data.total   ?? results.length;
    const mode    = data.mode    || 'vector';

    renderPhotos(results, query);

    const modeLabel = mode === 'vector'
      ? '<span class="mode-chip mode-vector">🧠 Vector</span>'
      : '<span class="mode-chip mode-fallback">⚠️ Keyword fallback</span>';

    resultsInfo.innerHTML =
      `${modeLabel} <strong>${total}</strong> result${total !== 1 ? 's' : ''} for "<strong>${escHtml(query)}</strong>"
       <button class="results-clear-link" id="results-clear">Clear</button>`;
    document.getElementById('results-clear')?.addEventListener('click', handleClear);

    if (results.length === 0) {
      showEmpty(true,
        `No results for "${query}"`,
        'Try different keywords, or clear the filters to broaden your search.'
      );
    }
  } catch (err) {
    showToast(`Search failed: ${err.message}`, 'error');
    showEmpty(true, 'Search failed', err.message);
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
    showLoading(false);
  }
}

function handleClear() {
  searchInput.value   = '';
  filterProject.value = '';
  filterPhotog.value  = '';
  resultsInfo.innerHTML = '';
  showEmpty(false);
  renderPhotos(allPhotos);
}

// ── Analyze ────────────────────────────────────────────────
async function handleAnalyzeAll() {
  analyzeAllBtn.disabled = true;
  analyzeAllBtn.textContent = 'Analyzing...';
  analyzeProgress.hidden = false;
  progressFill.style.width = '0%';
  progressLabel.textContent = 'Starting AWS Rekognition + Bedrock analysis...';

  try {
    let fakeProgress = 0;
    const interval = setInterval(() => {
      fakeProgress = Math.min(fakeProgress + 3, 85);
      progressFill.style.width = fakeProgress + '%';
    }, 400);

    const data = await apiFetch('/api/photos/ingest-all', { method: 'POST' });

    clearInterval(interval);
    progressFill.style.width = '100%';

    const indexed = data.indexed ?? 0;
    const processed = data.processed ?? 0;
    progressLabel.textContent = `Done! ${indexed} photo${indexed !== 1 ? 's' : ''} indexed out of ${processed}.`;

    showToast(`${indexed} photos indexed successfully`, 'success');
    await loadAllPhotos();
  } catch (err) {
    showToast(`Analysis failed: ${err.message}`, 'error');
    progressLabel.textContent = 'Analysis failed.';
  } finally {
    analyzeAllBtn.disabled = false;
    analyzeAllBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 6v6l4 2"/>
      </svg>
      Analyze All with AI`;
    setTimeout(() => { analyzeProgress.hidden = true; }, 3000);
  }
}

async function handleReset() {
  if (!confirm('Reset all AI analysis? This will clear all labels, tags, and descriptions.')) return;
  resetBtn.disabled = true;
  try {
    await apiFetch('/api/reset', { method: 'DELETE' });
    showToast('Analysis reset — photos are back to unanalyzed state', 'success');
    await loadAllPhotos();
  } catch (err) {
    showToast(`Reset failed: ${err.message}`, 'error');
  } finally {
    resetBtn.disabled = false;
  }
}

async function handleFolderSelect() {
  const files = Array.from(folderInput.files).filter(f => f.type.startsWith('image/'));
  if (!files.length) { showToast('No image files found in selected folder.', 'error'); return; }

  selectFolderBtn.disabled = true;
  selectFolderBtn.textContent = `Uploading ${files.length} images...`;

  try {
    const formData = new FormData();
    files.forEach(f => formData.append('files', f));
    const headers = {};
    if (API_KEY) headers['X-API-Key'] = API_KEY;
    const res = await fetch(`${API_BASE}/api/upload-folder`, { method: 'POST', body: formData, headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    showToast(`${data.added?.length ?? 0} new photo(s) added`, 'success');
    await loadAllPhotos();
  } catch (err) {
    showToast(`Upload failed: ${err.message}`, 'error');
  } finally {
    selectFolderBtn.disabled = false;
    selectFolderBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
      </svg>
      Select Folder`;
    folderInput.value = '';
  }
}

async function handleAnalyzeSingle() {
  if (!currentPhoto) return;
  modalAnalyzeBtn.textContent = 'Analyzing...';
  modalAnalyzeBtn.disabled = true;

  try {
    await apiFetch(`/api/photos/${encodeURIComponent(currentPhoto.filename)}/ingest`, { method: 'POST' });
    showToast('Photo indexed successfully', 'success');
    await loadAllPhotos();
    // Refresh current photo data from updated list
    const updated = allPhotos.find(p => p.filename === currentPhoto.filename);
    if (updated) { currentPhoto = updated; renderModalInfo(updated); }
  } catch (err) {
    showToast(`Analysis failed: ${err.message}`, 'error');
  } finally {
    modalAnalyzeBtn.textContent = 'Analyze with AI';
    modalAnalyzeBtn.disabled = false;
  }
}

// ── Render ─────────────────────────────────────────────────
function renderPhotos(photos, query = '') {
  photoGrid.innerHTML = '';
  showEmpty(false);

  if (!photos || photos.length === 0) {
    if (query) {
      showEmpty(true,
        `No results for "${query}"`,
        'Try different keywords, or clear the filters to broaden your search.'
      );
    } else {
      showEmpty(true, 'No photos yet', 'Click "Analyze All with AI" to index your photos.');
    }
    return;
  }

  // Update photographer filter whenever we render a fresh set
  updatePhotographerFilter(photos);

  photos.forEach(photo => {
    const card = createPhotoCard(photo, query);
    photoGrid.appendChild(card);
  });
}

function createPhotoCard(photo, query = '') {
  const card = document.createElement('article');
  card.className = 'photo-card';
  card.setAttribute('role', 'listitem');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `${photo.filename} - ${photo.project_name || photo.project_id}`);

  const isAnalyzed = !!(photo.ai_description || (photo.ai_labels && photo.ai_labels.length));
  const topTags    = (photo.ai_labels || photo.tags || []).slice(0, 4);
  const dateStr    = formatDate(photo.date_taken);

  // Similarity score — present on /search/similar results (_score or similarity_score)
  const score = photo.similarity_score ?? photo._score ?? null;
  const scorePct = score != null ? Math.round(score * 100) : null;

  card.innerHTML = `
    <div class="card-image-wrap">
      <img
        class="card-image"
        src="${API_BASE}/api/photos/${encodeURIComponent(photo.filename)}/image"
        alt="${escHtml(photo.filename)}"
        loading="lazy"
        onerror="this.style.display='none'; this.nextElementSibling.hidden=false"
      />
      <div class="card-image-placeholder" hidden>
        <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
          <rect x="4" y="10" width="40" height="30" rx="3"/>
          <circle cx="16" cy="20" r="4"/>
          <path d="M4 34l10-8 8 8 8-6 14 10"/>
        </svg>
      </div>
      ${isAnalyzed ? '<span class="card-badge">AI Analyzed</span>' : ''}
      ${scorePct != null ? `<span class="card-score">&#9733; ${scorePct}% match</span>` : ''}
    </div>
    <div class="card-body">
      <a class="card-project-link" href="#" data-project="${escHtml(photo.project_id)}" title="Filter by ${escHtml(photo.project_name)}">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11">
          <rect x="1" y="3" width="14" height="11" rx="1.5"/>
          <path d="M5 3V2a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/>
        </svg>
        ${escHtml(photo.project_name || photo.project_id || '—')}
      </a>
      <div class="card-filename">${escHtml(photo.filename)}</div>
      <div class="card-meta-row">
        <span class="card-meta-item">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11">
            <path d="M8 1.5C5.5 1.5 3.5 3.5 3.5 6c0 3.5 4.5 8.5 4.5 8.5s4.5-5 4.5-8.5c0-2.5-2-4.5-4.5-4.5z"/>
            <circle cx="8" cy="6" r="1.5"/>
          </svg>
          ${escHtml(photo.location || '—')}
        </span>
        <span class="card-meta-item">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11">
            <rect x="1" y="2" width="14" height="13" rx="1.5"/>
            <path d="M1 6h14M5 1v2M11 1v2"/>
          </svg>
          ${dateStr}
        </span>
      </div>
      ${photo.ai_description
        ? `<div class="card-description">${escHtml(photo.ai_description)}</div>`
        : '<div class="card-no-ai">Not yet analyzed</div>'}
      ${topTags.length
        ? `<div class="card-tags">${topTags.map(t => `<span class="tag">${escHtml(t)}</span>`).join('')}</div>`
        : ''}
    </div>
  `;

  // Project link — filter grid to that project
  card.querySelector('.card-project-link').addEventListener('click', e => {
    e.preventDefault();
    e.stopPropagation();
    filterProject.value = photo.project_id;
    searchInput.value   = '';
    resultsInfo.innerHTML =
      `Showing photos for <strong>${escHtml(photo.project_name || photo.project_id)}</strong>
       <button class="results-clear-link" id="results-clear">Clear</button>`;
    document.getElementById('results-clear')?.addEventListener('click', handleClear);
    renderPhotos(allPhotos.filter(p => p.project_id === photo.project_id));
    window.scrollTo({ top: 0, behavior: 'smooth' });
  });

  card.addEventListener('click', () => openModal(photo));
  card.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openModal(photo); });

  return card;
}

// ── Modal ──────────────────────────────────────────────────
function openModal(photo) {
  currentPhoto = photo;
  modalImage.src = `${API_BASE}/api/photos/${encodeURIComponent(photo.filename)}/image`;
  modalImage.alt = photo.filename;
  renderModalInfo(photo);
  modalOverlay.hidden = false;
  document.body.style.overflow = 'hidden';
  modalClose.focus();
}

function renderModalInfo(photo) {
  modalTitle.textContent = photo.filename;

  const score = photo.similarity_score ?? photo._score ?? null;

  modalMeta.innerHTML = `
    <div class="meta-row">
      <span class="meta-label">Project</span>
      <span class="meta-value">${escHtml(photo.project_name || '—')} (${escHtml(photo.project_id || '—')})</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Location</span>
      <span class="meta-value">${escHtml(photo.location || '—')}</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Taken By</span>
      <span class="meta-value">${escHtml(photo.taken_by || '—')}</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Date</span>
      <span class="meta-value">${formatDate(photo.date_taken)}</span>
    </div>
    ${score != null ? `
    <div class="meta-row">
      <span class="meta-label">Similarity</span>
      <span class="meta-value" style="color:var(--turquoise);font-weight:700">${Math.round(score * 100)}% match</span>
    </div>` : ''}
  `;

  modalDesc.textContent = photo.ai_description || '';

  // Tags (manual + AI labels combined, deduped)
  const tags = [...new Set([...(photo.tags || []), ...(photo.ai_labels || [])])];
  modalTags.innerHTML = tags.length
    ? tags.map(t => `<span class="tag tag-cyan">${escHtml(t)}</span>`).join('')
    : '';

  // AI label confidence bars — only if labels are objects with {name, confidence}
  const labels = (photo.ai_labels || []).filter(l => typeof l === 'object' && l.name);
  modalLabels.innerHTML = labels.length
    ? `<div style="font-size:11px;font-weight:700;color:var(--turquoise);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px;">AI Labels</div>` +
      labels.slice(0, 8).map(l => `
        <div class="label-row">
          <span class="label-name">${escHtml(l.name)}</span>
          <div class="label-bar-track">
            <div class="label-bar-fill" style="width:${l.confidence}%"></div>
          </div>
          <span class="label-confidence">${l.confidence}%</span>
        </div>
      `).join('')
    : '';

  modalAnalyzeBtn.textContent = photo.ai_description ? 'Re-analyze with AI' : 'Analyze with AI';
}

function closeModal() {
  modalOverlay.hidden = true;
  document.body.style.overflow = '';
  currentPhoto = null;
}

// ── UI Helpers ─────────────────────────────────────────────
function showLoading(show, message = 'Loading...') {
  loadingState.hidden = !show;
  if (loadingMessage) loadingMessage.textContent = message;
  if (show) {
    photoGrid.innerHTML = '';
    showEmpty(false);
  }
}

function showEmpty(show, title = 'No photos found', message = 'Try a different search term.') {
  emptyState.hidden = !show;
  if (show) {
    emptyTitle.textContent   = title;
    emptyMessage.textContent = message;
  }
}

let toastTimer;
function showToast(message, type = '') {
  toast.textContent = message;
  toast.className = `toast show ${type}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.className = 'toast'; }, 3500);
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', {
      year: 'numeric', month: 'short', day: 'numeric'
    });
  } catch { return iso; }
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
