/* deos Dashboard — app.js */
'use strict';

// ===== State =====
const state = {
  projects: [],           // [{name, repo_path, ok, error, counts, total}]
  activeProject: null,    // project name string
  board: null,            // {name, ok, error, columns}
  selectedCard: null,     // {projectName, ticketId}
  detail: null,           // full ticket object or null
  autoRefresh: false,
  autoRefreshTimer: null,
  autoRefreshInterval: 10, // seconds
  autoRefreshCountdown: 0,
  loading: false,
  boardLoading: false,
  detailLoading: false,
};

// ===== DOM refs =====
const $ = id => document.getElementById(id);
let elProjectTabs, elBoard, elBoardArea, elDetailPanel, elDetailBody, elDetailTitle;
let elRefreshBtn, elAutoRefreshBtn, elCountdown;

function initRefs() {
  elProjectTabs  = $('project-tabs');
  elBoard        = $('board');
  elBoardArea    = $('board-area');
  elDetailPanel  = $('detail-panel');
  elDetailBody   = $('detail-body');
  elDetailTitle  = $('detail-title');
  elRefreshBtn   = $('refresh-btn');
  elAutoRefreshBtn = $('auto-refresh-btn');
  elCountdown    = $('auto-refresh-countdown');
}

// ===== API helpers =====
async function apiFetch(url) {
  const res = await fetch(url, { method: 'GET', cache: 'no-store' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ===== Project list =====
async function loadProjects() {
  try {
    const data = await apiFetch('/api/projects');
    state.projects = data.projects || [];
    renderTabs();
    if (state.projects.length > 0 && !state.activeProject) {
      await selectProject(state.projects[0].name);
    } else if (state.activeProject) {
      await loadBoard(state.activeProject);
    }
  } catch (err) {
    renderTabsError(err.message);
  }
}

// ===== Board =====
async function loadBoard(projectName) {
  state.boardLoading = true;
  renderBoardLoading();
  try {
    const data = await apiFetch(`/api/projects/${encodeURIComponent(projectName)}/tickets`);
    state.board = data;
    renderBoard();
  } catch (err) {
    renderBoardError(err.message);
  } finally {
    state.boardLoading = false;
  }
}

// ===== Ticket detail =====
async function loadDetail(projectName, ticketId) {
  state.detailLoading = true;
  state.selectedCard = { projectName, ticketId };
  showDetailLoading(ticketId);
  try {
    const data = await apiFetch(`/api/projects/${encodeURIComponent(projectName)}/tickets/${encodeURIComponent(ticketId)}`);
    state.detail = data;
    renderDetail(data);
  } catch (err) {
    renderDetailError(ticketId, err.message);
  } finally {
    state.detailLoading = false;
  }
}

// ===== Tab selection =====
async function selectProject(name) {
  state.activeProject = name;
  state.selectedCard = null;
  state.detail = null;
  hideDetail();
  renderTabs(); // update active state
  await loadBoard(name);
}

// ===== Refresh =====
async function refresh() {
  resetAutoRefreshCountdown();
  await loadProjects();
  if (state.selectedCard) {
    await loadDetail(state.selectedCard.projectName, state.selectedCard.ticketId);
  }
}

// ===== Auto-refresh =====
function startAutoRefresh() {
  stopAutoRefresh();
  state.autoRefresh = true;
  state.autoRefreshCountdown = state.autoRefreshInterval;
  renderAutoRefreshBtn();
  state.autoRefreshTimer = setInterval(autoRefreshTick, 1000);
}

function stopAutoRefresh() {
  state.autoRefresh = false;
  if (state.autoRefreshTimer) {
    clearInterval(state.autoRefreshTimer);
    state.autoRefreshTimer = null;
  }
  state.autoRefreshCountdown = 0;
  renderAutoRefreshBtn();
}

function resetAutoRefreshCountdown() {
  state.autoRefreshCountdown = state.autoRefreshInterval;
  renderAutoRefreshBtn();
}

function autoRefreshTick() {
  state.autoRefreshCountdown -= 1;
  if (state.autoRefreshCountdown <= 0) {
    state.autoRefreshCountdown = state.autoRefreshInterval;
    refresh();
    return;
  }
  renderAutoRefreshBtn();
}

function toggleAutoRefresh() {
  if (state.autoRefresh) {
    stopAutoRefresh();
  } else {
    startAutoRefresh();
  }
}

// ===== Render: project tabs =====
function renderTabs() {
  elProjectTabs.innerHTML = '';
  for (const project of state.projects) {
    const tab = document.createElement('button');
    tab.className = 'project-tab' + (project.name === state.activeProject ? ' active' : '');
    tab.dataset.name = project.name;

    const nameSpan = document.createElement('span');
    nameSpan.className = 'tab-name';
    nameSpan.textContent = project.name;

    const countSpan = document.createElement('span');
    countSpan.className = 'tab-count';
    countSpan.textContent = project.total;

    tab.appendChild(nameSpan);
    tab.appendChild(countSpan);

    if (!project.ok) {
      const dot = document.createElement('span');
      dot.className = 'error-dot';
      dot.title = project.error || 'Error loading project';
      tab.appendChild(dot);
    }

    tab.addEventListener('click', () => selectProject(project.name));
    elProjectTabs.appendChild(tab);
  }
}

function renderTabsError(msg) {
  elProjectTabs.innerHTML = '';
  const span = document.createElement('span');
  span.style.color = 'var(--color-danger)';
  span.style.fontSize = '12px';
  span.textContent = 'Failed to load projects: ' + msg;
  elProjectTabs.appendChild(span);
}

// ===== Render: board =====
function renderBoardLoading() {
  elBoard.innerHTML = '';
  const msg = document.createElement('div');
  msg.className = 'state-message';
  msg.innerHTML = '<div class="loading-spinner"></div><span>Loading board...</span>';
  elBoard.appendChild(msg);
}

function renderBoardError(msg) {
  elBoard.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'error-box';
  box.textContent = 'Failed to load board: ' + msg;
  elBoard.appendChild(box);
}

const CANONICAL_STATUS_LABELS = {
  todo:       'To Do',
  doing:      'In Progress',
  code_ready: 'Code Ready',
  needs_pm:   'Needs PM',
  blocked:    'Blocked',
  parked:     'Parked',
  done:       'Done',
  unknown:    'Unknown',
};

function renderBoard() {
  elBoard.innerHTML = '';

  if (!state.board) return;

  if (!state.board.ok) {
    const box = document.createElement('div');
    box.className = 'error-box';
    box.textContent = state.board.error || 'Unknown error loading project data';
    elBoard.appendChild(box);
    return;
  }

  const columns = state.board.columns || [];
  for (const col of columns) {
    elBoard.appendChild(renderColumn(col));
  }
}

function renderColumn(col) {
  const el = document.createElement('div');
  el.className = 'column';

  const header = document.createElement('div');
  header.className = 'column-header';

  const dot = document.createElement('span');
  dot.className = 'column-status-dot';
  dot.dataset.status = col.status;

  const title = document.createElement('h3');
  title.textContent = CANONICAL_STATUS_LABELS[col.status] || col.status;

  const count = document.createElement('span');
  count.className = 'column-count';
  count.textContent = (col.tickets || []).length;

  header.appendChild(dot);
  header.appendChild(title);
  header.appendChild(count);
  el.appendChild(header);

  const cards = document.createElement('div');
  cards.className = 'column-cards';

  const tickets = col.tickets || [];
  if (tickets.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'empty-column';
    empty.textContent = 'No tickets';
    cards.appendChild(empty);
  } else {
    for (const ticket of tickets) {
      cards.appendChild(renderCard(ticket));
    }
  }
  el.appendChild(cards);

  // done_truncated affordance
  if (col.status === 'done' && col.done_truncated && col.done_truncated > 0) {
    const more = document.createElement('div');
    more.className = 'column-more';
    more.textContent = '+' + col.done_truncated + ' more done';
    el.appendChild(more);
  }

  return el;
}

function renderCard(ticket) {
  const card = document.createElement('div');
  card.className = 'card';
  card.dataset.status = ticket.status || 'unknown';
  card.dataset.id = ticket.id || '';

  // Check if this card is currently selected
  if (
    state.selectedCard &&
    state.selectedCard.ticketId === ticket.id &&
    state.selectedCard.projectName === state.activeProject
  ) {
    card.classList.add('selected');
  }

  const idEl = document.createElement('div');
  idEl.className = 'card-id';
  idEl.textContent = ticket.id || '—';
  card.appendChild(idEl);

  const goalEl = document.createElement('div');
  goalEl.className = 'card-goal';
  goalEl.textContent = ticket.goal_summary || '(no description)';
  card.appendChild(goalEl);

  const footer = document.createElement('div');
  footer.className = 'card-footer';

  const badge = document.createElement('span');
  const owner = ticket.owner || '';
  badge.className = 'owner-badge owner-' + owner.toLowerCase().replace(/[^a-z0-9]/g, '');
  badge.textContent = owner || '?';
  badge.title = owner;
  footer.appendChild(badge);

  if (ticket.priority) {
    const prio = document.createElement('span');
    const p = String(ticket.priority).toLowerCase();
    prio.className = 'priority-indicator priority-' + (p === 'high' || p === 'medium' || p === 'low' ? p : 'unknown');
    prio.title = 'Priority: ' + ticket.priority;
    footer.appendChild(prio);
  }

  card.appendChild(footer);

  card.addEventListener('click', () => {
    // Deselect all cards
    document.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    loadDetail(state.activeProject, ticket.id);
  });

  return card;
}

// ===== Render: detail panel =====
function hideDetail() {
  elDetailPanel.classList.add('hidden');
}

function showDetailLoading(ticketId) {
  elDetailPanel.classList.remove('hidden');
  elDetailTitle.textContent = ticketId || 'Loading...';
  elDetailBody.innerHTML = `
    <div id="detail-loading">
      <div class="loading-spinner"></div>
      <span>Loading ticket...</span>
    </div>
  `;
}

function renderDetailError(ticketId, msg) {
  elDetailPanel.classList.remove('hidden');
  elDetailTitle.textContent = ticketId || 'Error';
  elDetailBody.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'error-box';
  box.textContent = 'Failed to load ticket: ' + msg;
  elDetailBody.appendChild(box);
}

function renderDetail(ticket) {
  elDetailPanel.classList.remove('hidden');
  elDetailTitle.textContent = ticket.id || 'Ticket';
  elDetailBody.innerHTML = '';

  // Meta row
  const meta = document.createElement('div');
  meta.className = 'detail-section';
  const metaRow = document.createElement('div');
  metaRow.className = 'detail-meta';
  metaRow.appendChild(metaItem('status', ticket.status));
  metaRow.appendChild(metaItem('owner', ticket.owner));
  if (ticket.priority) metaRow.appendChild(metaItem('priority', ticket.priority));
  if (ticket.tdd) metaRow.appendChild(metaItem('tdd', ticket.tdd));
  if (ticket.test_owner) metaRow.appendChild(metaItem('test_owner', ticket.test_owner));
  if (ticket.impl_owner) metaRow.appendChild(metaItem('impl_owner', ticket.impl_owner));
  meta.appendChild(metaRow);
  elDetailBody.appendChild(meta);

  // Goal
  if (ticket.goal) {
    elDetailBody.appendChild(textSection('Goal', ticket.goal));
  }

  // Context
  if (ticket.context) {
    elDetailBody.appendChild(textSection('Context', ticket.context));
  }

  // Constraints
  if (ticket.constraints) {
    elDetailBody.appendChild(textSection('Constraints', ticket.constraints));
  }

  // DoD
  if (ticket.dod && Array.isArray(ticket.dod) && ticket.dod.length > 0) {
    elDetailBody.appendChild(listSection('Definition of Done', ticket.dod, false));
  } else if (ticket.dod && typeof ticket.dod === 'string') {
    elDetailBody.appendChild(textSection('Definition of Done', ticket.dod));
  }

  // Files
  if (ticket.files && Array.isArray(ticket.files) && ticket.files.length > 0) {
    elDetailBody.appendChild(listSection('Files', ticket.files, true));
  }

  // Deps
  if (ticket.deps && Array.isArray(ticket.deps) && ticket.deps.length > 0) {
    elDetailBody.appendChild(listSection('Dependencies', ticket.deps, false));
  }

  // Gates
  if (ticket.gates) {
    elDetailBody.appendChild(textSection('Gates', Array.isArray(ticket.gates) ? ticket.gates.join(', ') : ticket.gates));
  }

  // Verify
  if (ticket.verify) {
    elDetailBody.appendChild(textSection('Verify', ticket.verify));
  }

  // Transition history
  const history = ticket._transition_history;
  if (history && Array.isArray(history) && history.length > 0) {
    elDetailBody.appendChild(historySection(history));
  }
}

function metaItem(key, value) {
  const el = document.createElement('div');
  el.className = 'detail-meta-item';
  const k = document.createElement('span');
  k.className = 'detail-meta-key';
  k.textContent = key + ':';
  const v = document.createElement('span');
  v.className = 'detail-meta-val';
  v.textContent = value != null ? String(value) : '—';
  el.appendChild(k);
  el.appendChild(v);
  return el;
}

function textSection(label, text) {
  const sec = document.createElement('div');
  sec.className = 'detail-section';
  const lbl = document.createElement('div');
  lbl.className = 'detail-label';
  lbl.textContent = label;
  const val = document.createElement('div');
  val.className = 'detail-value';
  val.textContent = typeof text === 'string' ? text : String(text);
  sec.appendChild(lbl);
  sec.appendChild(val);
  return sec;
}

function listSection(label, items, isFile) {
  const sec = document.createElement('div');
  sec.className = 'detail-section';
  const lbl = document.createElement('div');
  lbl.className = 'detail-label';
  lbl.textContent = label;
  const list = document.createElement('ul');
  list.className = 'detail-list';
  for (const item of items) {
    const li = document.createElement('li');
    if (isFile) li.className = 'file-item';
    li.textContent = typeof item === 'string' ? item : JSON.stringify(item);
    list.appendChild(li);
  }
  sec.appendChild(lbl);
  sec.appendChild(list);
  return sec;
}

function historySection(history) {
  const sec = document.createElement('div');
  sec.className = 'detail-section';
  const lbl = document.createElement('div');
  lbl.className = 'detail-label';
  lbl.textContent = 'Transition History';
  sec.appendChild(lbl);

  const table = document.createElement('table');
  table.className = 'history-table';

  const thead = document.createElement('thead');
  const hr = document.createElement('tr');
  for (const col of ['When', 'Status', 'By', 'Note']) {
    const th = document.createElement('th');
    th.textContent = col;
    hr.appendChild(th);
  }
  thead.appendChild(hr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const entry of history) {
    const tr = document.createElement('tr');
    const when = entry.ts || '';
    const status = entry.status || '';
    const by = entry.actor || '';
    const note = (entry.reason || '') + (entry.override ? ' [override]' : '');
    for (const val of [when, status, by, note]) {
      const td = document.createElement('td');
      td.textContent = val;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  sec.appendChild(table);
  return sec;
}

// ===== Render: auto-refresh button =====
function renderAutoRefreshBtn() {
  if (state.autoRefresh) {
    elAutoRefreshBtn.classList.add('active');
    const countdown = state.autoRefreshCountdown > 0 ? ` (${state.autoRefreshCountdown}s)` : '';
    elCountdown.textContent = countdown;
  } else {
    elAutoRefreshBtn.classList.remove('active');
    elCountdown.textContent = '';
  }
}

// ===== Event handlers =====
function onRefreshClick() {
  refresh();
}

function onAutoRefreshToggle() {
  toggleAutoRefresh();
}

function onDetailClose() {
  hideDetail();
  state.selectedCard = null;
  state.detail = null;
  document.querySelectorAll('.card.selected').forEach(c => c.classList.remove('selected'));
}

// ===== Boot =====
function init() {
  initRefs();

  elRefreshBtn.addEventListener('click', onRefreshClick);
  elAutoRefreshBtn.addEventListener('click', onAutoRefreshToggle);
  $('detail-close').addEventListener('click', onDetailClose);

  loadProjects();
}

document.addEventListener('DOMContentLoaded', init);
