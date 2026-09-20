/**
 * AuthorFinder Web Interface
 * Connects to the AuthorFinder API for journalist/author extraction.
 */

// ── Configuration ────────────────────────────────────────────────────────
const API_BASE = 'https://authorfinder-api.shree8920.blitz.cloud';
const REQUEST_TIMEOUT = 90000; // 90s — API may take time for Playwright renders

// ── DOM Elements ─────────────────────────────────────────────────────────
const elements = {
    // API status
    apiStatus: document.getElementById('apiStatus'),

    // Single extraction
    form: document.getElementById('extractForm'),
    urlInput: document.getElementById('articleUrl'),
    extractBtn: document.getElementById('extractBtn'),
    loadingState: document.getElementById('loadingState'),
    errorState: document.getElementById('errorState'),
    errorMessage: document.getElementById('errorMessage'),
    resultsSection: document.getElementById('resultsSection'),
    resultStatus: document.getElementById('resultStatus'),
    resultTime: document.getElementById('resultTime'),
    authorResults: document.getElementById('authorResults'),
    rawJson: document.getElementById('rawJson'),

    // Batch
    csvUpload: document.getElementById('csvUpload'),
    uploadLabel: document.getElementById('uploadLabel'),
    csvPreview: document.getElementById('csvPreview'),
    csvCount: document.getElementById('csvCount'),
    clearCsv: document.getElementById('clearCsv'),
    batchExtractBtn: document.getElementById('batchExtractBtn'),
    batchLoading: document.getElementById('batchLoading'),
    batchProgress: document.getElementById('batchProgress'),
    batchResults: document.getElementById('batchResults'),
    batchTotal: document.getElementById('batchTotal'),
    batchSuccess: document.getElementById('batchSuccess'),
    batchFailed: document.getElementById('batchFailed'),
    batchTime: document.getElementById('batchTime'),
    batchTableBody: document.getElementById('batchTableBody'),
    downloadCsv: document.getElementById('downloadCsv'),
};

// ── State ────────────────────────────────────────────────────────────────
let currentBatchResults = [];
let csvUrls = [];

// ── Initialization ───────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    checkApiHealth();
    setupEventListeners();
});

// ── API Health Check ─────────────────────────────────────────────────────
async function checkApiHealth() {
    const statusEl = elements.apiStatus;
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 10000);
        const response = await fetch(`${API_BASE}/health`, { signal: controller.signal });
        clearTimeout(timeoutId);

        if (response.ok) {
            statusEl.classList.add('online');
            statusEl.classList.remove('offline');
            statusEl.querySelector('.status-text').textContent = 'API Online';
        } else {
            throw new Error('Non-200 response');
        }
    } catch (err) {
        statusEl.classList.add('offline');
        statusEl.classList.remove('online');
        statusEl.querySelector('.status-text').textContent = 'API Offline';
    }
}

// ── Event Listeners ──────────────────────────────────────────────────────
function setupEventListeners() {
    // Form submission
    elements.form.addEventListener('submit', handleExtract);

    // URL input validation
    elements.urlInput.addEventListener('input', validateUrlInput);

    // CSV upload
    elements.csvUpload.addEventListener('change', handleCsvUpload);
    elements.clearCsv.addEventListener('click', clearCsv);
    elements.batchExtractBtn.addEventListener('click', handleBatchExtract);
    elements.downloadCsv.addEventListener('click', downloadResultsCsv);

    // Drag and drop
    elements.uploadLabel.addEventListener('dragover', (e) => {
        e.preventDefault();
        elements.uploadLabel.classList.add('dragover');
    });
    elements.uploadLabel.addEventListener('dragleave', () => {
        elements.uploadLabel.classList.remove('dragover');
    });
    elements.uploadLabel.addEventListener('drop', (e) => {
        e.preventDefault();
        elements.uploadLabel.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file && file.name.endsWith('.csv')) {
            processCsvFile(file);
        }
    });
}

// ── URL Validation ───────────────────────────────────────────────────────
function validateUrlInput() {
    const url = elements.urlInput.value.trim();
    const isValid = url.length > 0 && isValidHttpUrl(url);
    elements.extractBtn.disabled = !isValid;
}

function isValidHttpUrl(string) {
    try {
        const url = new URL(string);
        return url.protocol === 'http:' || url.protocol === 'https:';
    } catch {
        return false;
    }
}

// ── Single Extraction ────────────────────────────────────────────────────
async function handleExtract(e) {
    e.preventDefault();

    const url = elements.urlInput.value.trim();
    if (!isValidHttpUrl(url)) {
        showError('Please enter a valid article URL.');
        return;
    }

    showLoading();
    hideError();
    hideResults();

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);

        const response = await fetch(`${API_BASE}/crawl`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `API returned status ${response.status}`);
        }

        const data = await response.json();
        hideLoading();

        if (data.status === 'success') {
            displayResults(data);
        } else if (data.status === 'no_author_found' || data.status === 'no_author_page') {
            displayNoAuthor(data);
        } else {
            displayApiError(data);
        }
    } catch (err) {
        hideLoading();
        if (err.name === 'AbortError') {
            showError('The request took too long. The article may be difficult to access or the API may be waking from inactivity. Please try again.');
        } else if (err.message.includes('Failed to fetch') || err.message.includes('NetworkError')) {
            showError('Unable to connect to the AuthorFinder API. Please check your connection and try again.');
        } else {
            showError(err.message || 'Unable to extract author information. Please try again.');
        }
    }
}

// ── Display Results ──────────────────────────────────────────────────────
function displayResults(data) {
    elements.resultsSection.hidden = false;
    elements.resultStatus.textContent = data.status;
    elements.resultStatus.className = `result-badge ${data.status}`;
    elements.resultTime.textContent = `${data.elapsed_seconds}s`;

    const author = data.author;
    let html = '<div class="author-card">';

    // Author name
    html += '<div class="author-name-row">';
    if (author.name) {
        html += `<span class="author-name">${escapeHtml(author.name)}</span>`;
    }
    if (author.job_title) {
        html += `<span class="author-title">${escapeHtml(author.job_title)}</span>`;
    }
    html += '</div>';

    // Fields grid
    html += '<div class="author-fields">';

    // Email
    if (author.email) {
        html += createFieldWithCopy('Email', author.email, 'mono');
    }

    // Profile URL
    if (author.profile_url) {
        html += createFieldLink('Profile', author.profile_url);
    }

    // LinkedIn
    if (author.linkedin) {
        html += createFieldLink('LinkedIn', author.linkedin);
    }

    // Twitter
    if (author.twitter) {
        html += createFieldLink('Twitter / X', author.twitter);
    }

    // Organization
    if (author.organization) {
        html += createFieldWithCopy('Organization', author.organization);
    }

    // Location
    if (author.location) {
        html += createFieldWithCopy('Location', author.location);
    }

    // Social links
    if (author.social_links && author.social_links.length > 0) {
        html += '<div class="field-item" style="grid-column: 1 / -1;">';
        html += '<span class="field-label">Social Links</span>';
        html += '<div class="social-links">';
        for (const link of author.social_links) {
            html += `<a href="${escapeAttr(link.url)}" target="_blank" rel="noopener noreferrer" class="social-badge">${escapeHtml(link.platform)}</a>`;
        }
        html += '</div></div>';
    }

    // Bio
    if (author.bio) {
        html += `<div class="field-item bio-section">`;
        html += `<span class="field-label">Bio</span>`;
        html += `<p class="bio-text">${escapeHtml(author.bio)}</p>`;
        html += '</div>';
    }

    html += '</div></div>';

    // Multiple authors
    if (data.authors && data.authors.length > 0) {
        html += '<div style="margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--color-gray-100);">';
        html += `<h4 style="font-size: 0.875rem; font-weight: 600; color: var(--color-gray-700); margin-bottom: 12px;">Additional Authors (${data.authors.length})</h4>`;
        for (const extra of data.authors) {
            html += `<div style="padding: 10px; background: var(--color-gray-50); border-radius: var(--radius-md); margin-bottom: 8px; border: 1px solid var(--color-gray-100);">`;
            if (extra.name) html += `<strong>${escapeHtml(extra.name)}</strong>`;
            if (extra.email) html += ` <span style="color: var(--color-gray-500); font-size: 0.8125rem;">&mdash; ${escapeHtml(extra.email)}</span>`;
            html += '</div>';
        }
        html += '</div>';
    }

    elements.authorResults.innerHTML = html;

    // Raw JSON
    elements.rawJson.textContent = JSON.stringify(data, null, 2);
}

function displayNoAuthor(data) {
    elements.resultsSection.hidden = false;
    elements.resultStatus.textContent = data.status.replace(/_/g, ' ');
    elements.resultStatus.className = `result-badge ${data.status}`;
    elements.resultTime.textContent = data.elapsed_seconds ? `${data.elapsed_seconds}s` : '';

    let message = '';
    if (data.status === 'no_author_found') {
        message = 'No author information was identified for this article.';
    } else if (data.status === 'no_author_page') {
        message = `Author "${data.author?.name || 'unknown'}" was found but no profile page exists on the site.`;
    } else if (data.status === 'blocked') {
        message = `The site blocked the request: ${data.error || 'Access denied'}`;
    } else if (data.status === 'paywall') {
        message = 'This article is behind a paywall and cannot be accessed.';
    } else {
        message = data.error || 'Unable to extract author information.';
    }

    elements.authorResults.innerHTML = `
        <div style="padding: 16px; background: var(--color-warning-light); border-radius: var(--radius-md); color: var(--color-warning); font-size: 0.875rem;">
            ${escapeHtml(message)}
        </div>
    `;
    elements.rawJson.textContent = JSON.stringify(data, null, 2);
}

function displayApiError(data) {
    const message = data.error || `Extraction failed with status: ${data.status}`;
    showError(message);
    // Also show raw JSON if available
    if (data.article_url) {
        elements.resultsSection.hidden = false;
        elements.resultStatus.textContent = data.status;
        elements.resultStatus.className = `result-badge ${data.status}`;
        elements.resultTime.textContent = data.elapsed_seconds ? `${data.elapsed_seconds}s` : '';
        elements.authorResults.innerHTML = `
            <div style="padding: 16px; background: var(--color-error-light); border-radius: var(--radius-md); color: var(--color-error); font-size: 0.875rem;">
                ${escapeHtml(message)}
            </div>
        `;
        elements.rawJson.textContent = JSON.stringify(data, null, 2);
    }
}

// ── Helper: Create Field with Copy ───────────────────────────────────────
function createFieldWithCopy(label, value, className = '') {
    const id = `field-${label.toLowerCase().replace(/\s+/g, '-')}`;
    return `
        <div class="field-item">
            <span class="field-label">${escapeHtml(label)}</span>
            <div class="field-wrapper">
                <span class="field-value ${className}" id="${id}">${escapeHtml(value)}</span>
                <button type="button" class="copy-btn" onclick="copyToClipboard('${escapeAttr(value)}', this)" title="Copy ${escapeHtml(label)}" aria-label="Copy ${escapeHtml(label)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

function createFieldLink(label, url) {
    return `
        <div class="field-item">
            <span class="field-label">${escapeHtml(label)}</span>
            <div class="field-wrapper">
                <span class="field-value">
                    <a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>
                </span>
                <button type="button" class="copy-btn" onclick="copyToClipboard('${escapeAttr(url)}', this)" title="Copy ${escapeHtml(label)}" aria-label="Copy ${escapeHtml(label)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                        <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                </button>
            </div>
        </div>
    `;
}

// ── Copy to Clipboard ────────────────────────────────────────────────────
async function copyToClipboard(text, buttonEl) {
    try {
        await navigator.clipboard.writeText(text);
        buttonEl.classList.add('copied');
        const originalHtml = buttonEl.innerHTML;
        buttonEl.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>';
        setTimeout(() => {
            buttonEl.classList.remove('copied');
            buttonEl.innerHTML = originalHtml;
        }, 1500);
    } catch {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
        buttonEl.classList.add('copied');
        setTimeout(() => buttonEl.classList.remove('copied'), 1500);
    }
}

// ── CSV Handling ─────────────────────────────────────────────────────────
function handleCsvUpload(e) {
    const file = e.target.files[0];
    if (file) processCsvFile(file);
}

function processCsvFile(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        const lines = text.split('\n').map(l => l.trim()).filter(l => l.length > 0);

        // Skip header if it looks like one
        let startIdx = 0;
        if (lines.length > 0 && (lines[0].toLowerCase() === 'url' || lines[0].toLowerCase() === 'urls')) {
            startIdx = 1;
        }

        csvUrls = [];
        for (let i = startIdx; i < lines.length; i++) {
            const url = lines[i].replace(/^,|,$/g, '').trim();
            if (isValidHttpUrl(url)) {
                csvUrls.push(url);
            }
        }

        if (csvUrls.length === 0) {
            showError('No valid URLs found in the CSV file.');
            return;
        }

        if (csvUrls.length > 50) {
            csvUrls = csvUrls.slice(0, 50);
        }

        elements.csvPreview.hidden = false;
        elements.csvCount.textContent = `${csvUrls.length} URL${csvUrls.length !== 1 ? 's' : ''} found`;
    };
    reader.readAsText(file);
}

function clearCsv() {
    csvUrls = [];
    elements.csvUpload.value = '';
    elements.csvPreview.hidden = true;
    elements.batchResults.hidden = true;
}

// ── Batch Extraction ─────────────────────────────────────────────────────
async function handleBatchExtract() {
    if (csvUrls.length === 0) return;

    elements.batchExtractBtn.disabled = true;
    elements.batchLoading.hidden = false;
    elements.batchResults.hidden = true;
    elements.batchProgress.textContent = `Processing ${csvUrls.length} URLs...`;

    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 min for batch

        const response = await fetch(`${API_BASE}/crawl/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ urls: csvUrls }),
            signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `API returned status ${response.status}`);
        }

        const data = await response.json();
        displayBatchResults(data);
    } catch (err) {
        if (err.name === 'AbortError') {
            showError('Batch request timed out. Try processing fewer URLs at once.');
        } else {
            showError(err.message || 'Batch processing failed.');
        }
    } finally {
        elements.batchExtractBtn.disabled = false;
        elements.batchLoading.hidden = true;
    }
}

function displayBatchResults(data) {
    currentBatchResults = data.results;
    elements.batchResults.hidden = false;

    elements.batchTotal.textContent = data.total;
    elements.batchSuccess.textContent = data.success_count;
    elements.batchFailed.textContent = data.failed_count;
    elements.batchTime.textContent = `${data.elapsed_seconds}s`;

    let rows = '';
    for (const result of data.results) {
        const author = result.author;
        const statusClass = result.status === 'success' ? 'success' : 'error';
        rows += `
            <tr>
                <td class="status-cell ${statusClass}">${result.status}</td>
                <td>${author.name ? escapeHtml(author.name) : '<span style="color:var(--color-gray-400)">—</span>'}</td>
                <td>${author.email ? escapeHtml(author.email) : '<span style="color:var(--color-gray-400)">—</span>'}</td>
                <td>${author.linkedin ? `<a href="${escapeAttr(author.linkedin)}" target="_blank" rel="noopener">Profile</a>` : '<span style="color:var(--color-gray-400)">—</span>'}</td>
                <td class="url-cell"><a href="${escapeAttr(result.article_url)}" target="_blank" rel="noopener">${escapeHtml(result.article_url)}</a></td>
            </tr>
        `;
    }
    elements.batchTableBody.innerHTML = rows;
}

// ── Download CSV ─────────────────────────────────────────────────────────
function downloadResultsCsv() {
    if (currentBatchResults.length === 0) return;

    const headers = ['status', 'name', 'email', 'linkedin', 'twitter', 'job_title', 'organization', 'location', 'profile_url', 'article_url'];
    const rows = [headers.join(',')];

    for (const result of currentBatchResults) {
        const a = result.author;
        const row = [
            result.status,
            csvEscape(a.name),
            csvEscape(a.email),
            csvEscape(a.linkedin),
            csvEscape(a.twitter),
            csvEscape(a.job_title),
            csvEscape(a.organization),
            csvEscape(a.location),
            csvEscape(a.profile_url),
            csvEscape(result.article_url),
        ];
        rows.push(row.join(','));
    }

    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `authorfinder_results_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(link.href);
}

function csvEscape(value) {
    if (!value) return '';
    const str = String(value);
    if (str.includes(',') || str.includes('"') || str.includes('\n')) {
        return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
}

// ── UI State Helpers ─────────────────────────────────────────────────────
function showLoading() {
    elements.loadingState.hidden = false;
    elements.extractBtn.disabled = true;
    elements.extractBtn.classList.add('btn-loading');
}

function hideLoading() {
    elements.loadingState.hidden = true;
    elements.extractBtn.classList.remove('btn-loading');
    validateUrlInput(); // Re-enable button if URL is valid
}

function showError(message) {
    elements.errorState.hidden = false;
    elements.errorMessage.textContent = message;
}

function hideError() {
    elements.errorState.hidden = true;
}

function hideResults() {
    elements.resultsSection.hidden = true;
}

// ── Utilities ────────────────────────────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return String(text)
        .replace(/&/g, '&amp;')
        .replace(/'/g, '&#39;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// Expose copyToClipboard globally for onclick handlers
window.copyToClipboard = copyToClipboard;
