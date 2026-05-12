/**
 * Visual Project Intelligence Search
 * Newforma Hackathon 2026 - Project 2
 */

const API_BASE = 'http://localhost:8000';

// ── State ──────────────────────────────────────────────────
let allPhotos = [];
let currentPhoto = null;

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
const loadingState    = null; // removed from UI
const emptyState      = document.getElementById('empty-state'); // may be null
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
  showLoading(true);
  try {
    const res = await fetch(`${API_BASE}/api/photos`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    allPhotos = data.photos;
    renderPhotos(allPhotos);
    loadStats();
  } catch (err) {
    showToast('Could not connect to backend. Make sure the server is running.', 'error');
    showEmpty(true);
  } finally {
    showLoading(false);
  }
}

async function loadFilters() {
  try {
    const [projRes, photogRes] = await Promise.all([
      fetch(`${API_BASE}/api/projects`),
      fetch(`${API_BASE}/api/photographers`),
    ]);
    const projData  = await projRes.json();
    const photogData = await photogRes.json();

    projData.projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.name;
      filterProject.appendChild(opt);
    });

    photogData.photographers.forEach(name => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      filterPhotog.appendChild(opt);
    });
  } catch (_) { /* filters are optional */ }
}

async function loadStats() {
  try {
    const res = await fetch(`${API_BASE}/api/stats`);
    const data = await res.json();
    statsBadge.textContent =
      `${data.analyzed_photos}/${data.total_photos} analyzed · ${data.total_projects} projects`;
  } catch (_) {
    statsBadge.textContent = `${allPhotos.length} photos`;
  }
}

// ── Search ─────────────────────────────────────────────────
async function handleSearch() {
  const query = searchInput.value.trim();
  if (!query) {
    renderPhotos(allPhotos);
    resultsInfo.innerHTML = '';
    return;
  }

  // Don't show full-page spinner for search — just disable the button briefly
  searchBtn.disabled = true;
  searchBtn.textContent = '...';
  try {
    const body = {
      query,
      project_id: filterProject.value || null,
      taken_by: filterPhotog.value || null,
    };
    const res = await fetch(`${API_BASE}/api/search`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    renderPhotos(data.results, query);
    resultsInfo.innerHTML =
      `<strong>${data.total}</strong> result${data.total !== 1 ? 's' : ''} for "<strong>${escHtml(query)}</strong>"
       <button class="results-clear-link" id="results-clear">Clear search</button>`;
    document.getElementById('results-clear')?.addEventListener('click', handleClear);
  } catch (err) {
    showToast('Search failed. Please try again.', 'error');
  } finally {
    searchBtn.disabled = false;
    searchBtn.textContent = 'Search';
  }
}

function handleClear() {
  searchInput.value = '';
  filterProject.value = '';
  filterPhotog.value = '';
  resultsInfo.innerHTML = '';
  renderPhotos(allPhotos);
}

// ── Analyze ────────────────────────────────────────────────
async function handleAnalyzeAll() {
  analyzeAllBtn.disabled = true;
  analyzeAllBtn.textContent = 'Analyzing...';
  analyzeProgress.hidden = false;
  progressFill.style.width = '0%';
  progressLabel.textContent = 'Starting AWS Rekognition analysis...';

  try {
    // Animate progress while waiting
    let fakeProgress = 0;
    const interval = setInterval(() => {
      fakeProgress = Math.min(fakeProgress + 3, 85);
      progressFill.style.width = fakeProgress + '%';
    }, 400);

    const res = await fetch(`${API_BASE}/api/analyze-all`, { method: 'POST' });
    const data = await res.json();

    clearInterval(interval);
    progressFill.style.width = '100%';

    const success = data.results.filter(r => r.status === 'success').length;
    const errors  = data.results.filter(r => r.status === 'error').length;
    progressLabel.textContent = `Done! ${success} photos analyzed${errors ? `, ${errors} errors` : ''}.`;

    showToast(`${success} photos analyzed successfully`, 'success');
    await loadAllPhotos();
    loadStats();
  } catch (err) {
    showToast('Analysis failed. Check backend connection.', 'error');
    progressLabel.textContent = 'Analysis failed.';
  } finally {
    analyzeAllBtn.disabled = false;
    analyzeAllBtn.innerHTML = `
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 2a10 10 0 1 0 10 10"/><path d="M12 6v6l4 2"/>
      </svg>
      Analyze All with AI`;
    // Always hide progress bar after 3 seconds
    setTimeout(() => { analyzeProgress.hidden = true; }, 3000);
  }
}

async function handleReset() {
  if (!confirm('Reset all AI analysis? This will clear all labels, tags, and descriptions.')) return;
  resetBtn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/reset`, { method: 'DELETE' });
    const data = await res.json();
    showToast('Analysis reset — photos are back to unanalyzed state', 'success');
    await loadAllPhotos();
    loadStats();
  } catch (err) {
    showToast('Reset failed.', 'error');
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
    const res = await fetch(`${API_BASE}/api/upload-folder`, { method: 'POST', body: formData });
    const data = await res.json();
    showToast(`${data.added.length} new photo${data.added.length !== 1 ? 's' : ''} added (${data.total} total)`, 'success');
    await loadAllPhotos();
    loadStats();
  } catch (err) {
    showToast('Upload failed. Please try again.', 'error');
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
    const res = await fetch(`${API_BASE}/api/analyze/${currentPhoto.filename}`, { method: 'POST' });
    const data = await res.json();
    currentPhoto = data.photo;
    // Update modal with new data
    renderModalInfo(currentPhoto);
    showToast('Photo analyzed successfully', 'success');
    // Refresh grid
    await loadAllPhotos();
    loadStats();
  } catch (err) {
    showToast('Analysis failed.', 'error');
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
    showEmpty(true);
    return;
  }

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
  card.setAttribute('aria-label', `${photo.filename} - ${photo.project_name}`);

  const isAnalyzed = !!photo.ai_description;
  const topTags = (photo.tags || []).slice(0, 4);
  const dateStr = formatDate(photo.date_taken);

  card.innerHTML = `
    <div class="card-image-wrap">
      ${photo.image_data
        ? `<img class="card-image" src="${photo.image_data}" alt="${escHtml(photo.filename)}" loading="lazy" />`
        : `<div class="card-image-placeholder">
            <svg viewBox="0 0 48 48" fill="none" stroke="currentColor" stroke-width="1.5" width="48" height="48">
              <rect x="4" y="10" width="40" height="30" rx="3"/>
              <circle cx="16" cy="20" r="4"/>
              <path d="M4 34l10-8 8 8 8-6 14 10"/>
            </svg>
           </div>`
      }
      ${isAnalyzed ? '<span class="card-badge">AI Analyzed</span>' : ''}
      ${photo.relevance_score ? `<span class="card-score">&#9733; ${photo.relevance_score} match</span>` : ''}
    </div>
    <div class="card-body">
      <a class="card-project-link" href="#" data-project="${escHtml(photo.project_id)}" title="Filter by ${escHtml(photo.project_name)}">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11"><rect x="1" y="3" width="14" height="11" rx="1.5"/><path d="M5 3V2a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v1"/></svg>
        ${escHtml(photo.project_name)}
      </a>
      <div class="card-filename">${escHtml(photo.filename)}</div>
      <div class="card-meta-row">
        <span class="card-meta-item">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11"><path d="M8 1.5C5.5 1.5 3.5 3.5 3.5 6c0 3.5 4.5 8.5 4.5 8.5s4.5-5 4.5-8.5c0-2.5-2-4.5-4.5-4.5z"/><circle cx="8" cy="6" r="1.5"/></svg>
          ${escHtml(photo.location)}
        </span>
        <span class="card-meta-item">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" width="11" height="11"><rect x="1" y="2" width="14" height="13" rx="1.5"/><path d="M1 6h14M5 1v2M11 1v2"/></svg>
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

  // Project link filter click
  card.querySelector('.card-project-link').addEventListener('click', e => {
    e.preventDefault();
    e.stopPropagation();
    filterProject.value = photo.project_id;
    searchInput.value = '';
    resultsInfo.innerHTML = `Showing photos for <strong>${escHtml(photo.project_name)}</strong>`;
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
  modalImage.src = photo.image_data || '';
  modalImage.alt = photo.filename;
  renderModalInfo(photo);
  modalOverlay.hidden = false;
  document.body.style.overflow = 'hidden';
  modalClose.focus();
}

function renderModalInfo(photo) {
  modalTitle.textContent = photo.filename;

  modalMeta.innerHTML = `
    <div class="meta-row">
      <span class="meta-label">Project</span>
      <span class="meta-value">${escHtml(photo.project_name)} (${escHtml(photo.project_id)})</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Location</span>
      <span class="meta-value">${escHtml(photo.location)}</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Taken By</span>
      <span class="meta-value">${escHtml(photo.taken_by)}</span>
    </div>
    <div class="meta-row">
      <span class="meta-label">Date</span>
      <span class="meta-value">${formatDate(photo.date_taken)}</span>
    </div>
  `;

  modalDesc.textContent = photo.ai_description || '';

  // Tags
  const tags = photo.tags || [];
  modalTags.innerHTML = tags.length
    ? tags.map(t => `<span class="tag tag-cyan">${escHtml(t)}</span>`).join('')
    : '';

  // Labels with confidence bars
  const labels = photo.ai_labels || [];
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
function showLoading(show) {
  if (loadingState) loadingState.hidden = !show;
  if (show) {
    photoGrid.innerHTML = '';
    if (emptyState) emptyState.hidden = true;
  }
}

function showEmpty(show) {
  if (emptyState) emptyState.hidden = !show;
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
