/**
 * ESG Evidence View Frontend Application
 */

let currentTicker = 'VNM';
let currentTab = 'environment';
let currentYear = '';
let evidenceData = null;

const INITIAL_CARD_LIMIT = 2;

// DOM Elements
const searchInput = document.getElementById('companySearchInput');
const dropdownList = document.getElementById('searchDropdown');
const companyNameEl = document.getElementById('companyName');
const tickerSpanEl = document.getElementById('tickerSpan');
const yearSelectEl = document.getElementById('yearSelect');

const tabButtons = document.querySelectorAll('.tab-btn');
const colVerifiedCards = document.getElementById('colVerifiedCards');
const colContradictedCards = document.getElementById('colContradictedCards');
const colMissingCards = document.getElementById('colMissingCards');

const countEnvEl = document.getElementById('countEnv');
const countSocEl = document.getElementById('countSoc');
const countGovEl = document.getElementById('countGov');

// Track loaded dropdown ticker
let lastPopulatedTicker = '';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
  initSearch();
  initYearSelect();
  initTabs();
  loadCompanyEvidence(currentTicker);
});

// Initialize Search Autocomplete
function initSearch() {
  let debounceTimer = null;

  searchInput.addEventListener('input', (e) => {
    clearTimeout(debounceTimer);
    const query = e.target.value.trim();

    debounceTimer = setTimeout(() => {
      fetchCompanies(query);
    }, 250);
  });

  searchInput.addEventListener('focus', () => {
    fetchCompanies(searchInput.value.trim());
  });

  // Close dropdown when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('.search-wrapper')) {
      dropdownList.classList.remove('active');
    }
  });
}

// Initialize Year Dropdown Selector
function initYearSelect() {
  yearSelectEl.addEventListener('change', (e) => {
    currentYear = e.target.value;
    loadCompanyEvidence(currentTicker, currentYear);
  });
}

// Fetch companies for dropdown
async function fetchCompanies(query) {
  try {
    const res = await fetch(`/api/companies?q=${encodeURIComponent(query)}&_t=${Date.now()}`);
    if (!res.ok) return;
    const companies = await res.json();
    renderDropdown(companies);
  } catch (err) {
    console.error('Error fetching companies:', err);
  }
}

// Render Autocomplete Dropdown
function renderDropdown(companies) {
  dropdownList.innerHTML = '';
  if (!companies || companies.length === 0) {
    dropdownList.classList.remove('active');
    return;
  }

  companies.forEach((comp) => {
    const item = document.createElement('div');
    item.className = 'dropdown-item';
    item.innerHTML = `
      <span class="item-ticker">${comp.ticker}</span>
      <span class="item-name">${comp.short || comp.name}</span>
    `;
    item.addEventListener('click', () => {
      currentTicker = comp.ticker;
      currentYear = ''; // Reset year filter when switching company
      lastPopulatedTicker = ''; // Force year options refresh
      searchInput.value = '';
      dropdownList.classList.remove('active');
      loadCompanyEvidence(currentTicker);
    });
    dropdownList.appendChild(item);
  });

  dropdownList.classList.add('active');
}

// Initialize Pillar Tabs
function initTabs() {
  tabButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      tabButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      currentTab = btn.getAttribute('data-tab');
      renderPillarColumns();
    });
  });
}

// Load company evidence from backend API
async function loadCompanyEvidence(ticker, year = '') {
  try {
    let url = `/api/evidence/${ticker}?_t=${Date.now()}`;
    if (year) {
      url += `&year=${encodeURIComponent(year)}`;
    }
    const res = await fetch(url);
    if (!res.ok) throw new Error('Network error loading evidence');
    evidenceData = await res.json();
    
    updateHeaderInfo();
    updateTabCounts();
    renderPillarColumns();
  } catch (err) {
    console.error('Error loading evidence:', err);
  }
}

// Update Top Header Info & Year Selector
function updateHeaderInfo() {
  if (!evidenceData || !evidenceData.company) return;
  const comp = evidenceData.company;
  
  if (companyNameEl) {
    companyNameEl.textContent = comp.short || comp.name;
  }
  if (tickerSpanEl) {
    tickerSpanEl.textContent = `(${comp.ticker})`;
  }
  
  // Populate Year options ONLY if switching company or not yet populated
  if (lastPopulatedTicker !== comp.ticker && comp.available_years && comp.available_years.length > 0) {
    let optionsHtml = '';
    comp.available_years.forEach((yr) => {
      optionsHtml += `<option value="${yr}">${yr}</option>`;
    });
    yearSelectEl.innerHTML = optionsHtml;
    lastPopulatedTicker = comp.ticker;
  }

  // Set active value in select box cleanly without destroying innerHTML
  if (evidenceData.selected_year) {
    yearSelectEl.value = evidenceData.selected_year;
  }
}

// Update Counts in Tab Headers
function updateTabCounts() {
  if (!evidenceData || !evidenceData.tabs) return;
  const tabs = evidenceData.tabs;

  if (tabs.environment) {
    countEnvEl.textContent = tabs.environment.counts.total;
  }
  if (tabs.social) {
    countSocEl.textContent = tabs.social.counts.total;
  }
  if (tabs.governance) {
    countGovEl.textContent = tabs.governance.counts.total;
  }
}

// Render 3 Columns for Active Tab
function renderPillarColumns() {
  if (!evidenceData || !evidenceData.tabs || !evidenceData.tabs[currentTab]) return;

  const pillarData = evidenceData.tabs[currentTab];

  renderColumn(colVerifiedCards, pillarData.verified, 'verified');
  renderColumn(colContradictedCards, pillarData.contradicted, 'contradicted');
  renderColumn(colMissingCards, pillarData.missing, 'missing');
}

// Helper to Render Individual Column with "Xem thêm v" Expand functionality
function renderColumn(containerEl, items, type) {
  containerEl.innerHTML = '';

  if (!items || items.length === 0) {
    containerEl.innerHTML = `
      <div class="empty-col-message">
        Không ghi nhận dữ liệu trong mục này (${evidenceData.selected_year || 'tất cả năm'}).
      </div>
    `;
    return;
  }

  const listWrapper = document.createElement('div');
  listWrapper.className = 'cards-list-wrapper';

  items.forEach((item, index) => {
    const card = document.createElement('div');
    const isHidden = index >= INITIAL_CARD_LIMIT;
    card.className = `evidence-card card-${type}${isHidden ? ' hidden-card' : ''}`;

    if (type === 'verified') {
      card.innerHTML = `
        <div class="standard-tag">
          [${item.standard_id}] · ${item.standard_name} 
          ${item.gri_equivalent ? `<span class="gri-ref">· ${item.gri_equivalent}</span>` : ''}
        </div>
        <div class="claim-quote">"${escapeHtml(item.claim_quote)}"</div>
        <div class="claim-source">📄 Nguồn: ${escapeHtml(item.claim_source)}</div>
        <div class="verify-box box-verified">
          <div class="verify-title">
            <span class="verify-icon">✓</span> Được xác nhận bởi: ${escapeHtml(item.verification.verifier)}
          </div>
          <div>${escapeHtml(item.verification.finding)}</div>
        </div>
      `;
    } else if (type === 'contradicted') {
      card.innerHTML = `
        <div class="standard-tag">
          [${item.standard_id}] · ${item.standard_name}
          ${item.gri_equivalent ? `<span class="gri-ref">· ${item.gri_equivalent}</span>` : ''}
        </div>
        <div class="claim-quote">"${escapeHtml(item.claim_quote)}"</div>
        <div class="claim-source">📄 Nguồn: ${escapeHtml(item.claim_source)}</div>
        <div class="verify-box box-contradicted">
          <div class="verify-title">
            <span class="verify-icon">✗</span> Bị bác bỏ bởi: ${escapeHtml(item.verification.verifier)}
          </div>
          <div>${escapeHtml(item.verification.finding)}</div>
        </div>
      `;
    } else if (type === 'missing') {
      card.innerHTML = `
        <div class="standard-tag">
          [${item.standard_id}] · ${item.standard_name}
          ${item.gri_equivalent ? `<span class="gri-ref">· ${item.gri_equivalent}</span>` : ''}
        </div>
        <div class="claim-quote" style="font-style: normal; color: #334155;">
          ${escapeHtml(item.requirement)}
        </div>
        <div class="verify-box box-missing" style="margin-top: 12px;">
          <div class="verify-title">
            <span class="verify-icon">ℹ</span> ${escapeHtml(item.note || 'Lưu ý xác minh')}
          </div>
        </div>
      `;
    }

    listWrapper.appendChild(card);
  });

  containerEl.appendChild(listWrapper);

  // Render "Xem thêm v" button if total items exceed limit
  if (items.length > INITIAL_CARD_LIMIT) {
    const btnContainer = document.createElement('div');
    btnContainer.className = 'load-more-container';

    const loadMoreBtn = document.createElement('button');
    loadMoreBtn.className = 'load-more-btn';
    loadMoreBtn.innerHTML = `Xem thêm <span>˅</span>`;

    let isExpanded = false;

    loadMoreBtn.addEventListener('click', () => {
      isExpanded = !isExpanded;
      const hiddenCards = listWrapper.querySelectorAll('.evidence-card');

      hiddenCards.forEach((c, idx) => {
        if (idx >= INITIAL_CARD_LIMIT) {
          if (isExpanded) {
            c.classList.remove('hidden-card');
          } else {
            c.classList.add('hidden-card');
          }
        }
      });

      if (isExpanded) {
        loadMoreBtn.innerHTML = `Thu gọn <span>˄</span>`;
      } else {
        loadMoreBtn.innerHTML = `Xem thêm <span>˅</span>`;
      }
    });

    btnContainer.appendChild(loadMoreBtn);
    containerEl.appendChild(btnContainer);
  }
}

function escapeHtml(text) {
  if (!text) return '';
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
