const $ = id => document.getElementById(id);
const int = value => Number(value || 0).toLocaleString();
const escapeHtml = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]);

async function loadSnapshot() {
  try {
    const live = await fetch("data.json", {cache:"no-store"});
    if (live.ok) return await live.json();
  } catch (_) { /* The local export is optional. */ }
  const sample = await fetch("sample.json");
  if (!sample.ok) throw new Error("No dashboard snapshot available");
  return await sample.json();
}

function renderDaily(rows, currency) {
  const perDay = new Map();
  rows.filter(row => !currency || row.payment_currency === currency).forEach(row => {
    perDay.set(row.event_date, (perDay.get(row.event_date) || 0) + Number(row.transaction_count));
  });
  const ordered = [...perDay].sort((a,b) => a[0].localeCompare(b[0])).slice(-20);
  const max = Math.max(1, ...ordered.map(row => row[1]));
  $("daily-chart").innerHTML = ordered.length ? ordered.map(([day,count]) =>
    `<div class="bar-row"><span>${escapeHtml(day.slice(5))}</span><div class="bar-track"><div class="bar-fill" style="width:${count/max*100}%"></div></div><strong>${int(count)}</strong></div>`
  ).join("") : `<p class="empty">No transactions for this currency.</p>`;
}

function render(data) {
  const fixture = data.kind !== "pipeline_export";
  $("fixture-warning").hidden = !fixture;
  $("snapshot-status").textContent = fixture ? "Sample preview" : `Published run #${data.publication_id}`;
  const daily = data.daily || [];
  const alerts = data.alerts || [];
  const q = data.quality || {};
  $("transaction-count").textContent = int(data.totals?.transactions ?? daily.reduce((n,row) => n + Number(row.transaction_count), 0));
  $("alert-count").textContent = int(data.totals?.risk_alerts ?? daily.reduce((n,row) => n + Number(row.risk_alert_count), 0));
  $("rejected-count").textContent = int(q.rejected_rows);
  const imbalanced = Number(q.imbalanced_files || 0) + Number(q.imbalanced_currency_groups || 0);
  $("recon-status").textContent = imbalanced ? "Review" : "Balanced";
  $("source-count").textContent = int(q.source_rows);
  $("accepted-count").textContent = int(q.accepted_rows);
  $("duplicate-count").textContent = int(q.duplicate_candidates);
  $("imbalanced-count").textContent = int(imbalanced);
  $("quality-note").textContent = fixture ? "Values on this page are fabricated and demonstrate the report layout." : `Published ${data.published_at}. Daily rows are limited to ${data.limits.daily_rows}; alert sample to ${data.limits.risk_alerts}.`;
  const currencies = [...new Set(daily.map(row => row.payment_currency))].sort();
  $("currency-filter").insertAdjacentHTML("beforeend", currencies.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join(""));
  $("currency-filter").addEventListener("change", event => renderDaily(daily, event.target.value));
  renderDaily(daily, "");
  $("alert-rows").innerHTML = alerts.length ? alerts.map(a => {
    const signals = [a.high_amount_for_currency_day && "High amount", a.high_hourly_velocity && "Hourly velocity", a.repeated_counterparty && "Repeated counterparty"].filter(Boolean).join(" · ");
    return `<tr><td>${escapeHtml(String(a.event_time).replace("T"," ").slice(0,16))}</td><td>${escapeHtml(a.from_bank_code)} / ${escapeHtml(a.from_account_code)} → ${escapeHtml(a.to_bank_code)} / ${escapeHtml(a.to_account_code)}</td><td>${escapeHtml(a.amount_paid)} ${escapeHtml(a.payment_currency)}</td><td class="score">${escapeHtml(a.risk_score)}</td><td class="signals">${escapeHtml(signals)}</td></tr>`;
  }).join("") : `<tr><td colspan="5" class="empty">No alert rows in this snapshot.</td></tr>`;
}

loadSnapshot().then(render).catch(error => { $("snapshot-status").textContent = error.message; });
