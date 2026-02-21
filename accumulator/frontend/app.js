/**
 * Accumulator Predictor – Frontend Application
 * Vanilla JS, no framework dependencies.
 * Fetches from GET /matchday and renders the full UI.
 */

'use strict';

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let _currentData = null;
let _expandedRows = new Set();

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------

document.addEventListener('DOMContentLoaded', () => {
  // Default date picker to today
  const datePicker = document.getElementById('date-input');
  const today = new Date().toISOString().split('T')[0];
  datePicker.value = today;

  // Auto-load demo mode if flag is set (via /demo route)
  if (window.DEMO_MODE) {
    const banner = document.createElement('div');
    banner.style.cssText = 'background:rgba(59,130,246,0.12);border:1px solid rgba(59,130,246,0.3);border-radius:6px;padding:8px 16px;margin:12px 0;font-size:0.82rem;color:#93c5fd;';
    banner.textContent = 'Demo mode — showing sample data. Add your API keys to .env to see live matchday data.';
    document.querySelector('main.container').prepend(banner);
    loadMatchday(true);
  } else {
    loadMatchday();
  }
});

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadMatchday(demo = false) {
  const dateInput = document.getElementById('date-input').value;
  const params = new URLSearchParams();
  if (dateInput) params.set('date', dateInput);
  if (demo || window.DEMO_MODE) params.set('demo', 'true');

  setLoading(true);
  clearError();

  try {
    const resp = await fetch(`/matchday?${params}`);
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(body.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    _currentData = data;
    _expandedRows.clear();
    render(data);
  } catch (err) {
    showError(`Failed to load matchday data: ${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Top-level render
// ---------------------------------------------------------------------------

function render(data) {
  renderHeader(data);
  renderSummaryBar(data);
  renderTiers(data.tiers);
  renderMatchups(data.matchups || []);
  renderExcluded(data.excluded_selections || []);
  document.getElementById('main-content').classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function renderHeader(data) {
  // Date display
  const dateEl = document.getElementById('matchday-date-display');
  if (data.matchday_date) {
    dateEl.textContent = formatDate(data.matchday_date);
  }

  // Leagues covered
  const leaguesEl = document.getElementById('leagues-display');
  const leagues = data.leagues_covered || [];
  leaguesEl.textContent = leagues.length > 0 ? leagues.join(' · ') : 'No fixtures today';

  // Source status dots
  const bar = document.getElementById('source-status-bar');
  bar.innerHTML = '';
  const sources = data.header_sources || [];
  sources.forEach(src => {
    const dot = document.createElement('div');
    dot.className = 'source-dot';
    dot.dataset.status = src.status;
    dot.innerHTML = `
      <span class="dot"></span>
      <span>${src.source}</span>
      ${src.reason ? `<span class="tooltip">${escHtml(src.reason)}</span>` : ''}
    `;
    bar.appendChild(dot);
  });
}

// ---------------------------------------------------------------------------
// Summary bar
// ---------------------------------------------------------------------------

function renderSummaryBar(data) {
  const bar = document.getElementById('summary-bar');
  bar.innerHTML = '';

  const items = [
    ['Fixtures Analysed', data.total_fixtures_analysed ?? '—'],
    ['Selections Evaluated', data.total_selections_evaluated ?? '—'],
    ['Generated', data.generated_at ? formatTime(data.generated_at) : '—'],
  ];

  items.forEach(([label, value]) => {
    const chip = document.createElement('div');
    chip.className = 'summary-chip';
    chip.innerHTML = `${escHtml(label)}: <strong>${escHtml(String(value))}</strong>`;
    bar.appendChild(chip);
  });
}

// ---------------------------------------------------------------------------
// Tiers
// ---------------------------------------------------------------------------

function renderTiers(tiers) {
  const grid = document.getElementById('tiers-grid');
  grid.innerHTML = '';

  const tierKeys = ['low', 'medium', 'high'];
  tierKeys.forEach(key => {
    const tier = tiers[key];
    if (!tier) return;
    grid.appendChild(buildTierCard(tier, key));
  });
}

function buildTierCard(tier, tierKey) {
  const card = document.createElement('div');
  card.className = 'tier-card';
  card.dataset.tier = tierKey;

  // Notes HTML
  const notesHtml = (tier.notes || []).map(n =>
    `<li class="tier-note-item">${escHtml(n)}</li>`
  ).join('');

  card.innerHTML = `
    <div class="tier-header">
      <div class="tier-title-row">
        <span class="tier-name">${escHtml(tier.name)}</span>
        <span class="tier-subtitle">${escHtml(tier.subtitle)}</span>
      </div>
      <div class="tier-odds-block">
        <span class="combined-odds">${escHtml(String(tier.estimated_combined_decimal))}</span>
        <span class="combined-odds-frac">${escHtml(tier.estimated_combined_fractional || '')}</span>
        <span class="tier-target">${escHtml(tier.target_odds_range)}</span>
      </div>
    </div>
    ${notesHtml ? `<ul class="tier-notes">${notesHtml}</ul>` : ''}
    <div class="selection-table-wrap">
      ${buildSelectionTable(tier.picks || [], tierKey)}
    </div>
  `;

  return card;
}

function buildSelectionTable(picks, tierKey) {
  if (!picks.length) {
    return '<div class="empty-state text-muted" style="padding:20px;">No selections for this tier.</div>';
  }

  const rowsHtml = picks.map((pick, idx) => {
    const rowId = `${tierKey}-${idx}`;
    return buildSelectionRow(pick, rowId);
  }).join('');

  return `
    <table class="selection-table">
      <thead>
        <tr>
          <th class="col-fixture">Fixture</th>
          <th class="col-market">Market</th>
          <th class="col-selection">Selection</th>
          <th class="col-conf">Confidence</th>
          <th class="col-odds">Odds</th>
          <th class="col-badges">Flags</th>
          <th class="col-expand"></th>
        </tr>
      </thead>
      <tbody id="tbody-${tierKey}">
        ${rowsHtml}
      </tbody>
    </table>
  `;
}

function buildSelectionRow(pick, rowId) {
  const confClass = pick.confidence >= 8 ? 'conf-high' : pick.confidence >= 6 ? 'conf-mid' : 'conf-low';
  const confWidth = Math.round((pick.confidence / 10) * 100);

  const badgesHtml = [
    pick.h2h_conflict  ? '<span class="badge badge-h2h">H2H Conflict</span>' : '',
    pick.value_flag    ? '<span class="badge badge-value">Thin Value</span>' : '',
    pick.matchup_boost ? '<span class="badge badge-matchup">Matchup Boost</span>' : '',
  ].filter(Boolean).join('');

  const oddsHtml = pick.decimal_odds
    ? `<span class="decimal-odds">${Number(pick.decimal_odds).toFixed(2)}</span>
       <br><span class="fractional-odds">${escHtml(pick.fractional_odds || '')}</span>`
    : '<span class="text-muted">—</span>';

  return `
    <tr id="row-${rowId}" onclick="toggleRow('${rowId}', ${JSON.stringify(pick).replace(/'/g, "\\'")})"
        class="selection-row">
      <td class="col-fixture fixture-cell">
        <div class="fixture-name">${escHtml(pick.home_team)} vs ${escHtml(pick.away_team)}</div>
        <div class="fixture-league text-muted">${escHtml(pick.league_code || '')}</div>
      </td>
      <td class="col-market market-cell">${escHtml(pick.market_label || pick.market_key || '')}</td>
      <td class="col-selection selection-label">${escHtml(pick.selection || '')}</td>
      <td class="col-conf">
        <div class="conf-bar-wrap ${confClass}">
          <div class="conf-bar-track">
            <div class="conf-bar-fill" style="width:${confWidth}%"></div>
          </div>
          <span class="conf-val">${pick.confidence}</span>
        </div>
      </td>
      <td class="col-odds odds-cell">${oddsHtml}</td>
      <td class="col-badges"><div class="badges">${badgesHtml}</div></td>
      <td class="col-expand">
        <button class="expand-btn" id="expand-btn-${rowId}"
                onclick="event.stopPropagation(); toggleRow('${rowId}', ${JSON.stringify(pick).replace(/'/g, "\\'")})">
          &#9654;
        </button>
      </td>
    </tr>
    <tr class="detail-row hidden" id="detail-${rowId}">
      <td colspan="7"></td>
    </tr>
  `;
}

// ---------------------------------------------------------------------------
// Row expansion
// ---------------------------------------------------------------------------

function toggleRow(rowId, pick) {
  const detailRow = document.getElementById(`detail-${rowId}`);
  const expandBtn = document.getElementById(`expand-btn-${rowId}`);
  const mainRow = document.getElementById(`row-${rowId}`);

  if (!detailRow) return;

  const isOpen = !detailRow.classList.contains('hidden');

  if (isOpen) {
    detailRow.classList.add('hidden');
    detailRow.querySelector('td').innerHTML = '';
    if (expandBtn) expandBtn.innerHTML = '&#9654;';
    if (mainRow) mainRow.classList.remove('expanded');
    _expandedRows.delete(rowId);
  } else {
    detailRow.querySelector('td').innerHTML = buildDetailPanel(pick);
    detailRow.classList.remove('hidden');
    if (expandBtn) expandBtn.innerHTML = '&#9660;';
    if (mainRow) mainRow.classList.add('expanded');
    _expandedRows.add(rowId);
  }
}

function buildDetailPanel(pick) {
  const keyStats = pick.key_stats || {};
  const statsHtml = Object.entries(keyStats)
    .filter(([, v]) => v != null)
    .map(([k, v]) =>
      `<div class="stat-item">
        <span class="stat-label">${escHtml(formatStatLabel(k))}:</span>
        <span class="stat-value">${escHtml(formatStatValue(v))}</span>
      </div>`
    ).join('');

  const explainHtml = pick.season_avg_explanation
    ? `<div class="detail-explanation">${escHtml(pick.season_avg_explanation)}</div>`
    : '';

  const h2hHtml = pick.h2h_conflict
    ? `<div class="mt-4"><span class="badge badge-h2h">H2H Conflict</span>
       <span class="text-muted" style="font-size:0.75rem;margin-left:6px;">
         H2H average diverges >20% from season average – confidence reduced.</span></div>`
    : '';

  const valueHtml = pick.value_flag
    ? `<div class="mt-4"><span class="badge badge-value">Thin Value</span>
       <span class="text-muted" style="font-size:0.75rem;margin-left:6px;">
         Bookmaker implied prob (${pick.implied_probability}%) exceeds our estimate by >10pp.</span></div>`
    : '';

  const matchupHtml = pick.matchup_boost
    ? `<div class="mt-4"><span class="badge badge-matchup">Matchup Boost</span>
       <span class="text-muted" style="font-size:0.75rem;margin-left:6px;">
         A player matchup directly supports this market (+1 confidence).</span></div>`
    : '';

  return `
    <div class="detail-panel">
      <div class="detail-title">Key Stats</div>
      <div class="stats-grid">${statsHtml || '<span class="text-muted">No additional stats available.</span>'}</div>
      ${explainHtml}
      ${h2hHtml}${valueHtml}${matchupHtml}
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Matchups panel
// ---------------------------------------------------------------------------

function renderMatchups(matchups) {
  const grid = document.getElementById('matchups-grid');
  grid.innerHTML = '';

  if (!matchups.length) {
    grid.innerHTML = '<div class="empty-state text-muted">No matchups identified for this matchday.</div>';
    return;
  }

  matchups.forEach(m => {
    const card = document.createElement('div');
    card.className = 'matchup-card';
    card.innerHTML = `
      ${m.fixture ? `<div class="matchup-fixture-tag" style="grid-column:1/-1;">${escHtml(m.fixture)}</div>` : ''}
      <div class="matchup-player">
        <span class="matchup-player-name">${escHtml(m.player1 || '—')}</span>
        <span class="matchup-stat">${escHtml(m.stat1_name || '')}: ${escHtml(String(m.stat1_val ?? ''))}</span>
      </div>
      <div class="matchup-vs">vs</div>
      <div class="matchup-player">
        <span class="matchup-player-name">${escHtml(m.player2 || '—')}</span>
        <span class="matchup-stat">${escHtml(m.stat2_name || '')}: ${escHtml(String(m.stat2_val ?? ''))}</span>
      </div>
      <div class="matchup-market-wrap">
        <span class="matchup-market-label">Supports</span>
        <span class="matchup-market-name">${escHtml(m.market_supported || '')}</span>
      </div>
      <div class="matchup-explanation">${escHtml(m.explanation || '')}</div>
    `;
    grid.appendChild(card);
  });
}

// ---------------------------------------------------------------------------
// Excluded selections
// ---------------------------------------------------------------------------

function renderExcluded(excluded) {
  const countEl = document.getElementById('excluded-count');
  countEl.textContent = excluded.length;

  const body = document.getElementById('excluded-body');
  if (!excluded.length) {
    body.innerHTML = '<div class="text-muted" style="padding:8px 0;font-size:0.82rem;">No excluded selections.</div>';
    return;
  }

  const rowsHtml = excluded.map(e => `
    <tr>
      <td>${escHtml(e.fixture || '—')}</td>
      <td>${escHtml(e.market || '—')}</td>
      <td>${escHtml(e.selection || '—')}</td>
      <td>${escHtml(String(e.confidence ?? '—'))}</td>
      <td>${e.bookmaker_odds ? Number(e.bookmaker_odds).toFixed(2) : '—'}</td>
      <td>${escHtml(e.reason || '—')}</td>
    </tr>
  `).join('');

  body.innerHTML = `
    <table class="excluded-table">
      <thead>
        <tr>
          <th>Fixture</th><th>Market</th><th>Selection</th>
          <th>Conf.</th><th>Odds</th><th>Reason</th>
        </tr>
      </thead>
      <tbody>${rowsHtml}</tbody>
    </table>
  `;
}

function toggleExcluded() {
  const header = document.getElementById('excluded-toggle');
  const body = document.getElementById('excluded-body');
  header.classList.toggle('open');
  body.classList.toggle('open');
}

// ---------------------------------------------------------------------------
// UI state helpers
// ---------------------------------------------------------------------------

function setLoading(on) {
  const overlay = document.getElementById('loading-overlay');
  const content = document.getElementById('main-content');
  const btn = document.getElementById('refresh-btn');

  if (on) {
    overlay.style.display = 'flex';
    content.classList.add('hidden');
    btn.disabled = true;
    btn.textContent = 'Loading…';
  } else {
    overlay.style.display = 'none';
    btn.disabled = false;
    btn.textContent = 'Analyse';
  }
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = msg;
  el.classList.remove('hidden');
}

function clearError() {
  const el = document.getElementById('error-banner');
  el.classList.add('hidden');
  el.textContent = '';
}

// ---------------------------------------------------------------------------
// Formatting utilities
// ---------------------------------------------------------------------------

function formatDate(isoDate) {
  try {
    const d = new Date(isoDate + 'T12:00:00Z');
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' });
  } catch { return isoDate; }
}

function formatTime(isoTs) {
  try {
    const d = new Date(isoTs);
    return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }) + ' UTC';
  } catch { return isoTs; }
}

function formatStatLabel(key) {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function formatStatValue(val) {
  if (typeof val === 'number') {
    return val % 1 === 0 ? String(val) : val.toFixed(2);
  }
  return String(val);
}

/**
 * Escape HTML to prevent XSS.
 */
function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
