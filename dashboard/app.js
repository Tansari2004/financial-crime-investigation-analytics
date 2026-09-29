const DATA_URL = '../data/processed/dashboard_cases.json';
const PAGE_SIZE = 15;
const state = { rows: [], filtered: [], page: 0 };
const $ = (id) => document.getElementById(id);

const number = (value) => new Intl.NumberFormat('en-CA').format(value);
const dateOnly = (value) => value.slice(0, 10);
const prettyDate = (value) => new Date(`${dateOnly(value)}T12:00:00`).toLocaleDateString('en-CA', { month: 'short', day: 'numeric' });
const amount = (value) => new Intl.NumberFormat('en-CA', { maximumFractionDigits: 2, minimumFractionDigits: 2 }).format(value);

function textNode(value) { return document.createTextNode(String(value)); }
function element(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value !== undefined) node.append(textNode(value));
  return node;
}

function fillSelect(id, values) {
  const select = $(id);
  for (const value of values) {
    const option = element('option', '', value);
    option.value = value;
    select.append(option);
  }
}

function getFilters() {
  return {
    rank: Number($('rank-filter').value), date: $('date-filter').value,
    currency: $('currency-filter').value, format: $('format-filter').value,
    search: $('search-filter').value.trim().toLowerCase(), spike: $('spike-filter').checked,
  };
}

function applyFilters() {
  const filters = getFilters();
  state.filtered = state.rows.filter((row) =>
    row.review_rank <= filters.rank &&
    (!filters.date || dateOnly(row.transaction_time) === filters.date) &&
    (!filters.currency || row.payment_currency === filters.currency) &&
    (!filters.format || row.payment_format === filters.format) &&
    (!filters.spike || row.amount_spike_rule) &&
    (!filters.search || [row.transaction_id, row.from_bank, row.from_account,
      row.to_bank, row.to_account].some((value) => String(value).toLowerCase().includes(filters.search)))
  );
  state.page = 0;
  render();
}

function renderCards() {
  const rows = state.filtered;
  $('case-count').textContent = number(rows.length);
  $('high-score-count').textContent = number(rows.filter((row) => row.review_score >= 0.90).length);
  $('spike-count').textContent = number(rows.filter((row) => row.amount_spike_rule).length);
  $('currency-count').textContent = number(new Set(rows.map((row) => row.payment_currency)).size);
  $('results-label').textContent = `${number(rows.length)} cases displayed`;
}

function countsBy(field) {
  const counts = new Map();
  for (const row of state.filtered) counts.set(row[field], (counts.get(row[field]) || 0) + 1);
  return [...counts].sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])));
}

function renderBars(id, field) {
  const host = $(id);
  host.replaceChildren();
  const values = countsBy(field).slice(0, 5);
  const maximum = Math.max(1, ...values.map((item) => item[1]));
  for (const [label, count] of values) {
    const row = element('div', 'bar-row');
    const name = element('span', 'bar-label', label);
    name.title = label;
    const track = element('div', 'bar-track');
    const fill = element('div', 'bar-fill');
    fill.style.width = `${(count / maximum) * 100}%`;
    track.append(fill);
    row.append(name, track, element('span', 'bar-number', number(count)));
    host.append(row);
  }
  if (!values.length) host.append(element('p', 'panel-note', 'No cases match these filters.'));
}

function svgNode(tag, attributes = {}) {
  const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
  return node;
}

function renderTimeline() {
  const host = $('timeline');
  host.replaceChildren();
  const allDates = [...new Set(state.rows.map((row) => dateOnly(row.transaction_time)))].sort();
  const byDate = new Map(allDates.map((date) => [date, 0]));
  for (const row of state.filtered) byDate.set(dateOnly(row.transaction_time), byDate.get(dateOnly(row.transaction_time)) + 1);
  const points = [...byDate];
  const maximum = Math.max(1, ...points.map((point) => point[1]));
  const width = 900, height = 245, left = 20, right = 18, top = 27, bottom = 33;
  const x = (index) => left + index * (width - left - right) / Math.max(1, points.length - 1);
  const y = (count) => height - bottom - count * (height - top - bottom) / maximum;
  const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'presentation' });
  const defs = svgNode('defs');
  const gradient = svgNode('linearGradient', { id: 'area-fill', x1: '0', y1: '0', x2: '0', y2: '1' });
  gradient.append(svgNode('stop', { offset: '0%', 'stop-color': '#1d89a5', 'stop-opacity': '.25' }), svgNode('stop', { offset: '100%', 'stop-color': '#1d89a5', 'stop-opacity': '0' }));
  defs.append(gradient); svg.append(defs);
  for (let index = 0; index < 4; index++) {
    const gy = top + index * (height - top - bottom) / 3;
    svg.append(svgNode('line', { x1: left, x2: width - right, y1: gy, y2: gy, class: 'grid-line' }));
  }
  const line = points.map((point, index) => `${index ? 'L' : 'M'} ${x(index)} ${y(point[1])}`).join(' ');
  svg.append(svgNode('path', { d: `${line} L ${x(points.length - 1)} ${height - bottom} L ${left} ${height - bottom} Z`, class: 'area' }));
  svg.append(svgNode('path', { d: line, class: 'line' }));
  points.forEach(([date, count], index) => {
    const dot = svgNode('circle', { cx: x(index), cy: y(count), r: '5', class: 'dot' });
    const title = svgNode('title'); title.textContent = `${prettyDate(date)}: ${number(count)} cases`;
    dot.append(title); svg.append(dot);
    const label = svgNode('text', { x: x(index), y: height - 8, 'text-anchor': 'middle' });
    label.textContent = prettyDate(date); svg.append(label);
    if (count && (index === 0 || index === points.length - 1 || count === maximum)) {
      const value = svgNode('text', { x: x(index), y: y(count) - 11, 'text-anchor': 'middle', class: 'point-label' });
      value.textContent = number(count); svg.append(value);
    }
  });
  host.append(svg);
  $('date-range').textContent = `${prettyDate(allDates[0])} – ${prettyDate(allDates[allDates.length - 1])}`;
}

function renderTable() {
  const body = $('case-rows'); body.replaceChildren();
  const start = state.page * PAGE_SIZE;
  const rows = state.filtered.slice(start, start + PAGE_SIZE);
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.tabIndex = 0;
    tr.setAttribute('aria-label', `View transaction ${row.transaction_id}`);
    tr.addEventListener('click', () => openCase(row));
    tr.addEventListener('keydown', (event) => { if (event.key === 'Enter') openCase(row); });
    tr.append(element('td', '', `#${number(row.review_rank)}`));
    tr.append(element('td', '', row.transaction_id));
    tr.append(element('td', '', `${prettyDate(row.transaction_time)} · ${row.transaction_time.slice(11, 16)}`));
    tr.append(element('td', 'account-cell', `${row.from_bank}/${row.from_account} → ${row.to_bank}/${row.to_account}`));
    const money = element('td', 'amount-cell', amount(row.amount_paid));
    money.append(element('small', '', row.payment_currency)); tr.append(money);
    tr.append(element('td', '', row.payment_format));
    const score = element('td'); score.append(element('span', `score-chip${row.review_score >= .9 ? ' strong' : ''}`, row.review_score.toFixed(3))); tr.append(score);
    tr.append(element('td', 'reason-cell', row.model_reasons[0] || 'No positive model factor'));
    body.append(tr);
  }
  if (!rows.length) {
    const tr = document.createElement('tr');
    const td = element('td', '', 'No cases match these filters.'); td.colSpan = 8; tr.append(td); body.append(tr);
  }
  $('page-label').textContent = rows.length ? `Showing ${number(start + 1)}–${number(start + rows.length)} of ${number(state.filtered.length)}` : 'No results';
  $('previous-page').disabled = state.page === 0;
  $('next-page').disabled = start + PAGE_SIZE >= state.filtered.length;
}

function openCase(row) {
  $('dialog-title').textContent = `Transaction ${number(row.transaction_id)}`;
  const body = $('dialog-body'); body.replaceChildren();
  const score = element('div', 'detail-score');
  score.append(element('strong', '', row.review_score.toFixed(3)), element('span', '', `Model review score · queue rank #${number(row.review_rank)}`));
  body.append(score);
  const grid = element('div', 'detail-grid');
  for (const [label, value] of [
    ['Date and time', row.transaction_time], ['Payment amount', `${amount(row.amount_paid)} ${row.payment_currency}`],
    ['Sender', `${row.from_bank} / ${row.from_account}`], ['Receiver', `${row.to_bank} / ${row.to_account}`],
    ['Payment format', row.payment_format], ['Earlier sender payments', number(row.prior_transaction_count)],
  ]) {
    const item = element('div', 'detail-item'); item.append(element('span', '', label), element('strong', '', value)); grid.append(item);
  }
  body.append(grid);
  const box = element('div', 'reason-box'); box.append(element('h3', '', 'Model factors raising this score'));
  const list = document.createElement('ol');
  for (const reason of row.model_reasons) list.append(element('li', '', reason));
  box.append(list); body.append(box);
  if (row.amount_spike_rule) body.append(element('p', 'rule-box', `Additional rule: ${row.rule_reason}`));
  body.append(element('p', 'detail-note', 'These factors describe this model’s calculation. They do not prove a crime or explain its cause. The score is for ranking reviews, not a probability.'));
  $('case-dialog').showModal();
}

function render() { renderCards(); renderTimeline(); renderBars('format-bars', 'payment_format'); renderBars('currency-bars', 'payment_currency'); renderTable(); }

async function main() {
  try {
    const response = await fetch(DATA_URL);
    if (!response.ok) throw new Error(`Could not load dashboard data (${response.status})`);
    const payload = await response.json();
    state.rows = payload.rows;
    fillSelect('date-filter', [...new Set(state.rows.map((row) => dateOnly(row.transaction_time)))].sort());
    fillSelect('currency-filter', [...new Set(state.rows.map((row) => row.payment_currency))].sort());
    fillSelect('format-filter', [...new Set(state.rows.map((row) => row.payment_format))].sort());
    for (const id of ['rank-filter', 'date-filter', 'currency-filter', 'format-filter', 'spike-filter']) $(id).addEventListener('change', applyFilters);
    $('search-filter').addEventListener('input', applyFilters);
    $('reset-button').addEventListener('click', () => {
      for (const id of ['date-filter', 'currency-filter', 'format-filter', 'search-filter']) $(id).value = '';
      $('rank-filter').value = '10000'; $('spike-filter').checked = false; applyFilters();
    });
    $('previous-page').addEventListener('click', () => { state.page--; renderTable(); });
    $('next-page').addEventListener('click', () => { state.page++; renderTable(); });
    $('close-dialog').addEventListener('click', () => $('case-dialog').close());
    applyFilters();
  } catch (error) {
    $('case-rows').replaceChildren();
    const row = document.createElement('tr'); const cell = element('td', '', `${error.message}. Run the data build command from the repository root and start a local server.`);
    cell.colSpan = 8; row.append(cell); $('case-rows').append(row);
  }
}

main();
