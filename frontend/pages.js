/* Dashboard, History, Plan (budgets/goals/recurring) and Settings. */

/* ---------- small chart helpers (inline SVG) ---------- */
function donut(items, total) {
  const R = 54, C = 2 * Math.PI * R; let off = 0;
  const arcs = items.map((b) => { const len = (b.amount_minor / total) * C; const a = `<circle r="${R}" cx="70" cy="70" fill="none" stroke="${esc(b.color)}" stroke-width="20" stroke-dasharray="${Math.max(len - 1.5, 0)} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"><title>${esc(b.name)} ${money(b.amount_minor)}</title></circle>`; off += len; return a; }).join('');
  return `<svg viewBox="0 0 140 140" width="150" height="150" role="img" aria-label="Spending by category">${arcs}</svg>`;
}
function trendChart(trend) {
  const W = 520, H = 190, pad = 26, max = Math.max(1, ...trend.flatMap((t) => [t.income, t.expense]));
  const bw = (W - pad * 2) / trend.length;
  const bars = trend.map((t, i) => {
    const x = pad + i * bw, h1 = ((H - 44) * t.income) / max, h2 = ((H - 44) * t.expense) / max, w = bw * 0.3;
    return `<g><rect x="${x + bw * 0.16}" y="${H - 24 - h1}" width="${w}" height="${h1}" rx="4" fill="var(--accent)" opacity=".85"><title>${fmonth(t.month)} income ${money(t.income)}</title></rect>
      <rect x="${x + bw * 0.16 + w + 3}" y="${H - 24 - h2}" width="${w}" height="${h2}" rx="4" fill="var(--warn)"><title>${fmonth(t.month)} spending ${money(t.expense)}</title></rect>
      <text x="${x + bw / 2}" y="${H - 6}" text-anchor="middle">${fmonth(t.month, false)}</text></g>`;
  }).join('');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Income and spending, last 6 months"><line x1="${pad}" x2="${W - pad}" y1="${H - 24}" y2="${H - 24}" stroke="var(--line)"/>${bars}</svg>
    <div class="legend"><span><span class="dot" style="background:var(--accent)"></span> Income</span><span><span class="dot" style="background:var(--warn)"></span> Spending</span></div>`;
}
function paceChart(daily) {
  const W = 520, H = 170, p = 26, n = daily.days;
  const max = Math.max(1, ...daily.current.filter((v) => v != null), ...daily.previous);
  const X = (i) => p + (i * (W - p * 2)) / Math.max(n - 1, 1), Y = (v) => H - 22 - ((H - 44) * v) / max;
  const path = (a) => a.map((v, i) => (v == null ? '' : `${i && a[i - 1] != null ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`)).join(' ');
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative spending this month versus last month"><line x1="${p}" x2="${W - p}" y1="${H - 22}" y2="${H - 22}" stroke="var(--line)"/>
    <path d="${path(daily.previous)}" fill="none" stroke="var(--muted)" stroke-width="2" stroke-dasharray="4 4" opacity=".7"/><path d="${path(daily.current)}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linecap="round"/>
    <text x="${p}" y="${H - 5}">1</text><text x="${W - p}" y="${H - 5}" text-anchor="end">${n}</text></svg>
    <div class="legend"><span><span class="dot" style="background:var(--accent)"></span> This month</span><span><span class="dot" style="background:var(--muted)"></span> Last month</span></div>`;
}
const delta = (cur, prev, goodWhenUp) => {
  if (!prev) return '';
  const d = cur - prev, pct = Math.round((100 * Math.abs(d)) / Math.abs(prev));
  if (!pct) return '<div class="delta muted">Same as last month</div>';
  const good = goodWhenUp ? d > 0 : d < 0;
  return `<div class="delta ${good ? 'pos' : 'neg'}">${d > 0 ? '▲' : '▼'} ${pct}% vs last month</div>`;
};

/* ---------- dashboard ---------- */
routes.dashboard = async (main, [month]) => {
  const d = await api('/dashboard' + (month ? '?month=' + month : ''));
  if (d.empty) {
    main.innerHTML = `<div class="empty card" style="margin-top:40px"><div class="big">🌱</div><h2>Let's see where your money goes</h2>
      <p>Upload a bank or Google Pay statement. Tally reads it, then asks you about each transaction one at a time.</p>
      <button class="btn primary" id="e-imp">Import your first statement</button></div>`;
    $('#e-imp').onclick = () => openImport(); return;
  }
  const i = d.months.indexOf(d.month);
  const unc = d.uncategorized;
  main.innerHTML = `<div class="head"><div><h1>${fmonth(d.month)}</h1><p class="sub">Cash flow and spending</p></div>
    <div class="row"><button class="btn sm" id="pm" ${i <= 0 ? 'disabled' : ''} aria-label="Previous month">←</button>
      <select id="msel" style="width:auto" aria-label="Month">${d.months.map((m) => `<option value="${m}" ${m === d.month ? 'selected' : ''}>${fmonth(m)}</option>`).join('')}</select>
      <button class="btn sm" id="nm" ${i >= d.months.length - 1 ? 'disabled' : ''} aria-label="Next month">→</button></div></div>
    ${unc.count ? `<div class="card flat row" style="justify-content:space-between;margin-bottom:16px;background:var(--accent-soft)"><div><b>${unc.count} transaction${unc.count > 1 ? 's' : ''} to review</b><div class="small muted">Totals are estimates until each one has a category.</div></div><a class="btn primary" href="#/review">Continue reviewing</a></div>` : ''}
    ${d.duplicates ? `<div class="warn-box row" style="justify-content:space-between"><span>${d.duplicates} possible duplicate${d.duplicates > 1 ? 's' : ''} left out of totals.</span><a href="#/transactions/duplicates">Check them</a></div>` : ''}
    <div class="grid g3" style="margin-bottom:16px">
      <div class="card stat"><div class="label">Income</div><div class="value pos">${money(d.income_minor)}</div>${delta(d.income_minor, d.prev.income_minor, true)}</div>
      <div class="card stat"><div class="label">Spent</div><div class="value">${money(d.expense_minor)}</div>${delta(d.expense_minor, d.prev.expense_minor, false)}</div>
      <div class="card stat"><div class="label">Net savings</div><div class="value ${d.net_minor < 0 ? 'neg' : 'pos'}">${money(d.net_minor, { sign: true })}</div><div class="delta muted">${d.income_minor > 0 ? Math.round((100 * d.net_minor) / d.income_minor) + '% of income' : '&nbsp;'}${d.saved_minor ? ' · ' + money(d.saved_minor) + ' put into savings' : ''}</div></div></div>
    ${d.insights.length ? `<div class="card" style="margin-bottom:16px"><h2 style="margin-bottom:8px">Insights</h2><div class="list">${d.insights.map((x) => `<div><span class="dot" style="background:${x.tone === 'warn' ? 'var(--warn)' : x.tone === 'good' ? 'var(--good)' : 'var(--muted)'}"></span><div class="grow">${esc(x.text)}</div></div>`).join('')}</div></div>` : ''}
    <div class="grid g-main" style="margin-bottom:16px">
      <div class="card"><h2 style="margin-bottom:14px">Where it went</h2>${d.breakdown.length ? `<div class="donut-wrap">${donut(d.breakdown, d.expense_minor || 1)}<div class="grow list" style="flex:1;min-width:200px">${d.breakdown.slice(0, 8).map((b) => `<a class="row" href="#/transactions/cat-${b.category_id ?? 'uncategorized'}-${d.month}" style="text-decoration:none;color:inherit"><span class="dot" style="background:${esc(b.color)}"></span><span class="grow ell">${esc(b.name)}</span><span class="muted small">${b.pct}%</span><b class="num">${money(b.amount_minor)}</b></a>`).join('')}</div></div>` : '<p class="muted">No spending in this month.</p>'}</div>
      <div class="card"><h2 style="margin-bottom:6px">Pace</h2><p class="small muted" style="margin-bottom:10px">Cumulative spending through the month</p><div class="chart">${paceChart(d.daily)}</div></div></div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><h2 style="margin-bottom:6px">Last 6 months</h2><div class="chart">${trendChart(d.trend)}</div></div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h2>Budgets</h2><a href="#/plan" class="small">Manage</a></div>${budgetBars(d.budgets, true)}</div></div>
    <div class="grid g2">
      <div class="card"><div class="row" style="justify-content:space-between"><h2>Recent</h2><a href="#/transactions" class="small">All transactions</a></div><div class="list" style="margin-top:6px">${d.recent.map(txnRow).join('')}</div></div>
      <div class="card"><h2 style="margin-bottom:6px">Accounts · ${fmonth(d.month, false)}</h2><div class="list">${d.accounts.map((a) => `<div><div class="grow"><b>${esc(a.name)}</b><div class="small muted">In ${money(a.income)} · Out ${money(a.expense)}${a.transfer_in || a.transfer_out ? ` · Transfers ${money(a.transfer_in - a.transfer_out, { sign: true })}` : ''}</div></div></div>`).join('') || '<p class="muted">No accounts.</p>'}</div>
        ${d.recurring.count ? `<div class="row small" style="margin-top:12px;justify-content:space-between"><span class="muted">${d.recurring.count} recurring bills</span><b>${money(d.recurring.monthly_total_minor)}/mo</b></div>` : ''}</div></div>`;
  const nav = (m) => go('#/dashboard/' + m);
  $('#msel').onchange = (e) => nav(e.target.value); $('#pm').onclick = () => nav(d.months[i - 1]); $('#nm').onclick = () => nav(d.months[i + 1]);
  main.onclick = (e) => { const r = e.target.closest('[data-txn]'); if (r) openTxn(+r.dataset.txn, () => route()); };
};

function txnRow(t) {
  const inflow = t.direction === 'credit', c = t.is_split ? 'Split' : t.category_name;
  return `<div class="txn" data-txn="${t.id}" tabindex="0" role="button">
    <span class="dot" style="background:${esc(t.category_color || '#C9C4BA')};width:12px;height:12px"></span>
    <div class="grow"><div class="ell"><b>${esc(t.merchant || t.description.slice(0, 40) || 'Unknown')}</b>${t.dup_status === 'suspected' ? ' <span class="pill warn">Possible duplicate</span>' : ''}</div>
      <div class="small muted ell">${fdate(t.date, false)} · ${esc(c || (t.status === 'skipped' ? 'Skipped' : 'Needs a category'))}${t.type === 'transfer' ? ' · Transfer' : ''}${t.recurring ? ' · ↻' : ''}</div></div>
    <b class="num ${t.type === 'transfer' ? 'muted' : inflow ? 'pos' : ''}">${inflow ? '+' : ''}${money(t.amount_minor)}</b></div>`;
}
function budgetBars(b, compact) {
  const rows = [...(b.overall ? [{ category_name: 'All spending', category_color: 'var(--accent)', ...b.overall }] : []), ...b.items];
  if (!rows.length) return `<p class="muted small">Set monthly limits to see progress here. ${compact ? '<a href="#/plan">Add a budget</a>' : ''}</p>`;
  return `<div class="list">${rows.slice(0, compact ? 5 : 99).map((r) => `<div style="display:block"><div class="row" style="justify-content:space-between;margin-bottom:6px"><span class="row" style="gap:8px"><span class="dot" style="background:${esc(r.category_color)}"></span><b>${esc(r.category_name)}</b></span><span class="small ${r.pct >= 100 ? 'neg' : 'muted'}">${money(r.spent_minor)} of ${money(r.limit_minor)}</span></div><div class="bar ${r.pct >= 100 ? 'bad' : r.pct >= 80 ? 'warn' : ''}"><i style="width:${Math.min(r.pct, 100)}%"></i></div></div>`).join('')}</div>`;
}

/* ---------- transaction editor (used from dashboard + history) ---------- */
async function openTxn(id, done) {
  let d;
  try { d = await api('/transactions/' + id); } catch (e) { return fail(e); }
  const t = d.txn; let catId = t.category_id, recurring = t.recurring, type = t.type, changed = false;
  const m = modal(`<div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2 style="margin:0">${esc(t.merchant || 'Transaction')}</h2><p class="muted small">${fdate(t.date)} · ${esc(t.account_name)}</p></div><b class="num" style="font-size:22px">${t.direction === 'credit' ? '+' : ''}${money(t.amount_minor)}</b></div>
    <div class="desc small muted" style="margin:14px 0;padding:10px 12px;background:var(--surface2);border-radius:12px;word-break:break-word">${esc(t.description || '(no description)')}</div>
    ${t.flags.map((f) => `<div class="flag" style="margin:0 0 8px">⚠ ${esc(f)}</div>`).join('')}
    <div id="terr"></div>
    ${t.is_split ? `<div class="field"><label>Split across</label>${t.splits.map((s) => `<div class="row small">${catDot(s)}<span class="grow">${esc(s.category_name)}</span><b>${money(s.amount_minor)}</b></div>`).join('')}<p class="small muted" style="margin-top:6px">To change a split, send it back to review.</p></div>` : ''}
    <div class="field"><label>Category</label><div class="row" id="tcats" style="gap:8px">${S.cats.map((c) => `<button class="pill" data-c="${c.id}" style="cursor:pointer;border:1.5px solid ${c.id === catId ? esc(c.color) : 'transparent'}">${catDot(c)}${esc(c.name)}</button>`).join('')}</div></div>
    <div class="grid g2"><div class="field"><label>Type</label><select id="tt">${['expense', 'income', 'transfer'].map((k) => `<option value="${k}" ${k === type ? 'selected' : ''}>${typeLabel[k]}</option>`).join('')}</select></div>
      <div class="field"><label>Repeats</label><select id="tr"><option value="">Not recurring</option>${['weekly', 'monthly', 'yearly'].map((f) => `<option value="${f}" ${recurring && t.recurring_freq === f ? 'selected' : ''}>${f[0].toUpperCase() + f.slice(1)}</option>`).join('')}</select></div></div>
    <div class="field"><label for="tn">Note</label><input id="tn" maxlength="500" value="${esc(t.note || '')}" placeholder="Add a note"></div>
    <details style="margin-bottom:8px"><summary class="small muted" style="cursor:pointer">Fix merchant, date or amount</summary><div class="grid g2" style="margin-top:12px">
      <div class="field"><label for="tm">Merchant</label><input id="tm" value="${esc(t.merchant)}" maxlength="80"></div><div class="field"><label for="td">Date</label><input id="td" type="date" value="${esc(t.date)}"></div>
      <div class="field"><label for="ta">Amount</label><input id="ta" inputmode="decimal" value="${(t.amount_minor / 100).toFixed(2)}" ${t.is_split ? 'disabled' : ''}></div>
      <div class="field"><label for="tdir">Direction</label><select id="tdir"><option value="debit" ${t.direction === 'debit' ? 'selected' : ''}>Money out</option><option value="credit" ${t.direction === 'credit' ? 'selected' : ''}>Money in</option></select></div></div></details>
    <div class="foot" style="justify-content:space-between"><div class="row"><button class="btn sm danger" id="tdel">Delete</button><button class="btn sm" id="trev">Send to review</button></div><div class="row"><button class="btn" data-x>Cancel</button><button class="btn primary" id="tsave">Save</button></div></div>`);
  $$('#tcats .pill', m.el).forEach((b) => (b.onclick = () => { catId = +b.dataset.c; changed = true; const c = cat(catId); $$('#tcats .pill', m.el).forEach((x) => (x.style.borderColor = x === b ? c.color : 'transparent')); if (c.kind === 'transfer') $('#tt', m.el).value = 'transfer'; else if (c.kind === 'income') $('#tt', m.el).value = 'income'; else if ($('#tt', m.el).value === 'transfer' || c.kind === 'expense') $('#tt', m.el).value = t.direction === 'credit' && c.kind !== 'expense' ? 'income' : 'expense'; }));
  $('[data-x]', m.el).onclick = () => m.close();
  const patch = async (body, msg) => { try { const r = await api('/transactions/' + id, { method: 'PATCH', body }); m.close(); refreshBadge(); toast(msg, r.undo?.length ? { action: 'Undo', onAction: async () => { await api('/transactions/restore', { method: 'POST', body: { undo: r.undo } }); done && done(); } } : {}); done && done(); } catch (e) { $('#terr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } };
  $('#trev', m.el).onclick = () => patch({ send_to_review: true }, 'Sent back to review');
  $('#tdel', m.el).onclick = async () => { m.close(); if (await confirmBox({ title: 'Delete this transaction?', body: 'It will be removed from your history and totals.', ok: 'Delete', danger: true })) { try { await api('/transactions/' + id, { method: 'DELETE' }); toast('Transaction deleted'); refreshBadge(); done && done(); } catch (e) { fail(e); } } };
  $('#tsave', m.el).onclick = () => {
    const freq = $('#tr', m.el).value, body = { note: $('#tn', m.el).value, recurring: !!freq, recurring_freq: freq || undefined, type: $('#tt', m.el).value };
    if (catId && (changed || t.status !== 'categorized') && !t.is_split) body.category_id = catId;
    else if (t.status === 'categorized' && catId && !t.is_split) body.category_id = catId;
    if ($('#tm', m.el).value !== t.merchant) body.merchant = $('#tm', m.el).value;
    if ($('#td', m.el).value !== t.date) body.date = $('#td', m.el).value;
    const amt = toMinor($('#ta', m.el).value); if (!t.is_split && amt && amt !== t.amount_minor) body.amount_minor = amt;
    if ($('#tdir', m.el).value !== t.direction) body.direction = $('#tdir', m.el).value;
    patch(body, 'Saved');
  };
}

/* ---------- history ---------- */
routes.transactions = async (main, [pre]) => {
  const f = { q: '', category: '', account: '', status: '', type: '', from: '', to: '', min: '', max: '', sort: 'date_desc', page: 1, dup: '' };
  if (pre === 'duplicates') f.dup = 'suspected';
  else if (pre === 'uncategorized') f.category = 'uncategorized';
  else if (pre && pre.startsWith('cat-')) { const [, c, mo] = pre.split('-').concat([]); f.category = c === 'uncategorized' ? 'uncategorized' : c; if (mo) { const y = pre.split('-')[2], mm = pre.split('-')[3]; f.from = `${y}-${mm}-01`; f.to = `${y}-${mm}-31`; } }
  let selected = new Set(), data = null, timer;
  main.innerHTML = `<div class="head"><div><h1>${f.dup ? 'Possible duplicates' : 'Transactions'}</h1><p class="sub" id="sub"></p></div><div class="row"><a class="btn sm" href="/api/export.csv" download>Export CSV</a><button class="btn primary sm" id="imp">Import</button></div></div>
    <div id="dupbox"></div>
    <div class="card flat" style="margin-bottom:16px"><div class="grid g3" style="margin-bottom:10px"><input id="q" type="search" placeholder="Search merchant, note, amount…" aria-label="Search" value="${esc(f.q)}">
      <select id="fcat" aria-label="Category"><option value="">All categories</option><option value="uncategorized">Needs a category</option>${S.cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <select id="facc" aria-label="Account"><option value="">All accounts</option>${S.accounts.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></div>
      <details ${f.from ? 'open' : ''}><summary class="small muted" style="cursor:pointer">More filters</summary><div class="grid g3" style="margin-top:10px">
        <select id="ftype" aria-label="Type"><option value="">Any type</option><option value="income">Income</option><option value="expense">Expense</option><option value="transfer">Transfer</option></select>
        <select id="fsort" aria-label="Sort"><option value="date_desc">Newest first</option><option value="date_asc">Oldest first</option><option value="amount_desc">Largest first</option><option value="amount_asc">Smallest first</option></select>
        <label class="check"><input type="checkbox" id="frec"> Recurring only</label>
        <div><label for="ffrom">From</label><input type="date" id="ffrom" value="${esc(f.from.replace(/-31$/, '-01'))}"></div><div><label for="fto">To</label><input type="date" id="fto"></div>
        <div class="row" style="flex-wrap:nowrap"><input id="fmin" inputmode="decimal" placeholder="Min ₹" aria-label="Minimum amount"><input id="fmax" inputmode="decimal" placeholder="Max ₹" aria-label="Maximum amount"></div></div></details></div>
    <div id="list"></div><div id="selbar"></div>`;
  $('#fcat').value = f.category; if (f.to) { const [y, mo] = f.to.split('-'); $('#fto').value = new Date(+y, +mo, 0).toISOString().slice(0, 10).replace(/-\d\d$/, '-' + String(new Date(+y, +mo, 0).getDate()).padStart(2, '0')); f.to = $('#fto').value; }
  $('#imp').onclick = () => openImport();
  const bind = { q: 'q', category: 'fcat', account: 'facc', type: 'ftype', sort: 'fsort', from: 'ffrom', to: 'fto', min: 'fmin', max: 'fmax' };
  Object.entries(bind).forEach(([k, id]) => { $('#' + id).oninput = (e) => { f[k] = e.target.value; f.page = 1; clearTimeout(timer); timer = setTimeout(load, k === 'q' || k === 'min' || k === 'max' ? 300 : 0); }; });
  $('#frec').onchange = (e) => { f.recurring = e.target.checked ? 1 : ''; f.page = 1; load(); };

  async function load() {
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '' && v != null)).toString();
    $('#list').innerHTML = '<div class="card"><div class="skel" style="height:260px"></div></div>';
    try { data = await api('/transactions?' + qs); } catch (e) { $('#list').innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    draw();
  }
  function draw() {
    $('#sub').textContent = `${data.total} transaction${data.total === 1 ? '' : 's'} · in ${money(data.money_in)} · out ${money(data.money_out)}`;
    if (f.dup) loadDups();
    if (!data.items.length) { $('#list').innerHTML = `<div class="empty card"><div class="big">🔍</div><h2>${f.dup ? 'No duplicates to check' : 'Nothing matches'}</h2><p>${f.dup ? 'Nice and tidy.' : 'Try clearing a filter, or import a statement.'}</p></div>`; return; }
    $('#list').innerHTML = `<div class="card"><div class="list">${data.items.map((t) => `<div class="row" style="flex-wrap:nowrap"><input type="checkbox" data-sel="${t.id}" style="width:18px;min-height:0;flex:none" aria-label="Select" ${selected.has(t.id) ? 'checked' : ''}><div style="flex:1;min-width:0">${txnRow(t)}</div></div>`).join('')}</div>
      ${data.pages > 1 ? `<div class="row" style="justify-content:center;margin-top:14px"><button class="btn sm" id="pp" ${f.page <= 1 ? 'disabled' : ''}>Previous</button><span class="small muted">Page ${data.page} of ${data.pages}</span><button class="btn sm" id="np" ${f.page >= data.pages ? 'disabled' : ''}>Next</button></div>` : ''}</div>`;
    $('#pp') && ($('#pp').onclick = () => { f.page--; load(); }); $('#np') && ($('#np').onclick = () => { f.page++; load(); });
    selbar();
  }
  async function loadDups() {
    const pairs = await api('/duplicates');
    $('#dupbox').innerHTML = pairs.length ? `<div class="card" style="margin-bottom:16px"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h2>Compare and decide</h2><div class="row"><button class="btn sm" id="keepall">Keep all</button><button class="btn sm danger" id="delall">Delete all new copies</button></div></div>
      ${pairs.map((p) => `<div class="list"><div style="display:block"><div class="grid g2"><div><span class="pill warn">New</span><div><b>${esc(p.new.merchant || p.new.description.slice(0, 30))}</b></div><div class="small muted">${fdate(p.new.date)} · ${money(p.new.amount_minor)} · ${esc(p.new.account_name)}</div></div>
      <div><span class="pill">Original</span><div><b>${esc(p.original.merchant || p.original.description.slice(0, 30))}</b></div><div class="small muted">${fdate(p.original.date)} · ${esc(p.original.account_name)}</div></div></div>
      <div class="row" style="margin-top:8px"><button class="btn sm" data-keep="${p.new.id}">Not a duplicate</button><button class="btn sm danger" data-drop="${p.new.id}">Delete the new one</button></div></div></div>`).join('')}</div>` : '';
    $('#keepall') && ($('#keepall').onclick = () => bulkDup('keep')); $('#delall') && ($('#delall').onclick = () => bulkDup('delete'));
  }
  const bulkDup = async (action) => { try { await api('/duplicates/resolve-all', { method: 'POST', body: { action } }); toast('Done'); refreshBadge(); load(); } catch (e) { fail(e); } };
  function selbar() {
    $('#selbar').innerHTML = selected.size ? `<div class="sel-bar"><b>${selected.size} selected</b><select id="bcat" style="width:auto;background:transparent;color:inherit;border-color:rgba(255,255,255,.3)" aria-label="Set category"><option value="">Set category…</option>${S.cats.map((c) => `<option style="color:#000" value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <button class="btn sm" data-b="pending">Send to review</button><button class="btn sm" data-b="delete">Delete</button><button class="btn sm" data-b="clear">Clear</button></div>` : '';
    const bc = $('#bcat'); bc && (bc.onchange = () => bulk('categorize', { category_id: +bc.value }));
    $$('[data-b]').forEach((b) => (b.onclick = async () => { const a = b.dataset.b; if (a === 'clear') { selected.clear(); draw(); } else if (a === 'delete') { if (await confirmBox({ title: `Delete ${selected.size} transactions?`, body: 'This removes them from your history and totals and can’t be undone.', ok: 'Delete', danger: true })) bulk('delete'); } else bulk(a); }));
  }
  async function bulk(action, extra = {}) {
    try { const r = await api('/transactions/bulk', { method: 'POST', body: { ids: [...selected], action, ...extra } }); selected.clear(); refreshBadge(); toast(`${r.changed} updated`, r.undo.length ? { action: 'Undo', onAction: async () => { await api('/transactions/restore', { method: 'POST', body: { undo: r.undo } }); refreshBadge(); load(); } } : {}); load(); } catch (e) { fail(e); }
  }
  main.onclick = (e) => {
    const cb = e.target.closest('[data-sel]');
    if (cb) { +cb.dataset.sel && (cb.checked ? selected.add(+cb.dataset.sel) : selected.delete(+cb.dataset.sel)); selbar(); return; }
    const keep = e.target.closest('[data-keep]'), drop = e.target.closest('[data-drop]');
    if (keep || drop) { api(`/duplicates/${(keep || drop).dataset.keep || (keep || drop).dataset.drop}/resolve`, { method: 'POST', body: { action: keep ? 'keep' : 'delete' } }).then(() => { refreshBadge(); load(); }).catch(fail); return; }
    const r = e.target.closest('[data-txn]'); if (r) openTxn(+r.dataset.txn, load);
  };
  main.onkeydown = (e) => { const r = e.target.closest?.('[data-txn]'); if (r && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openTxn(+r.dataset.txn, load); } };
  await load();
};

/* ---------- plan: budgets, goals, recurring ---------- */
routes.plan = async (main) => {
  const [b, goals, rec] = await Promise.all([api('/budgets'), api('/goals'), api('/recurring')]);
  const spendCats = S.cats.filter((c) => c.kind === 'expense');
  main.innerHTML = `<div class="head"><div><h1>Plan</h1><p class="sub">Limits, goals and bills · ${fmonth(b.month)}</p></div></div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h2>Monthly limits</h2><button class="btn sm" id="addb">+ Set limit</button></div>${budgetBars(b, false)}
        ${[b.overall && { id: null, name: 'All spending', limit: b.overall.limit_minor }, ...b.items.map((i) => ({ id: i.category_id, name: i.category_name, limit: i.limit_minor }))].filter(Boolean).length ? `<div class="small muted" style="margin-top:10px">${[b.overall && { id: null, name: 'All spending', limit: b.overall.limit_minor }, ...b.items.map((i) => ({ id: i.category_id, name: i.category_name, limit: i.limit_minor }))].filter(Boolean).map((x) => `<a href="#" data-editb="${x.id ?? ''}" data-limit="${x.limit}" data-name="${esc(x.name)}">Edit ${esc(x.name)}</a>`).join(' · ')}</div>` : ''}</div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h2>Savings goals</h2><button class="btn sm" id="addg">+ New goal</button></div>
        ${goals.length ? `<div class="list">${goals.map((g) => { const pct = Math.min(100, Math.round((100 * g.saved_minor) / g.target_minor)); return `<div style="display:block"><div class="row" style="justify-content:space-between"><b>${esc(g.name)}</b><span class="small muted">${money(g.saved_minor)} of ${money(g.target_minor)}${g.deadline ? ' · by ' + fdate(g.deadline) : ''}</span></div><div class="bar" style="margin:8px 0"><i style="width:${pct}%"></i></div><div class="row"><button class="btn sm" data-add="${g.id}">Add money</button><button class="btn sm ghost" data-gdel="${g.id}">Delete</button></div></div>`; }).join('')}</div>` : '<p class="muted small">Saving for something? Set a target and track your progress.</p>'}</div></div>
    <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Recurring bills &amp; subscriptions</h2><span class="muted small">${rec.count ? money(rec.monthly_total_minor) + ' a month' : ''}</span></div>
      ${rec.items.length ? `<div class="list">${rec.items.map((r) => `<div><span class="dot" style="background:${esc(r.category_color || '#C9C4BA')};width:12px;height:12px"></span><div class="grow"><b>${esc(r.merchant)}</b><div class="small muted">${r.frequency} · next around ${fdate(r.next_due)}${r.days_until >= 0 && r.days_until <= 7 ? ' · <span class="neg">due soon</span>' : ''}</div></div><b class="num">${money(r.amount_minor)}</b><button class="btn sm ghost" data-stop="${esc(r.key)}">Stop tracking</button></div>`).join('')}</div>` : '<p class="muted small">Mark a transaction as “Recurring” while reviewing and it appears here.</p>'}
      ${rec.detected.length ? `<h3 style="margin:18px 0 6px">Looks recurring. Track these?</h3><div class="list">${rec.detected.map((r) => `<div><div class="grow"><b>${esc(r.merchant)}</b><div class="small muted">${r.frequency} · seen ${r.count} times</div></div><b class="num">${money(r.amount_minor)}</b><button class="btn sm" data-track="${esc(r.key)}" data-freq="${r.frequency}">Track</button></div>`).join('')}</div>` : ''}</div>`;
  const reload = () => route();
  const limitDialog = (id, name, cur) => {
    const m = modal(`<h2>${id === undefined ? 'Set a monthly limit' : 'Limit for ' + esc(name)}</h2><div id="berr"></div>
      ${id === undefined ? `<div class="field"><label for="bc">Applies to</label><select id="bc"><option value="">All spending</option>${spendCats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></div>` : ''}
      <div class="field"><label for="bl">Limit per month</label><input id="bl" inputmode="decimal" value="${cur ? (cur / 100).toFixed(0) : ''}" placeholder="e.g. 10000"></div>
      <div class="foot">${id !== undefined ? '<button class="btn danger" id="brm" style="margin-right:auto">Remove</button>' : ''}<button class="btn" data-x>Cancel</button><button class="btn primary" id="bgo">Save</button></div>`);
    $('[data-x]', m.el).onclick = () => m.close();
    const put = async (cid, lim) => { try { await api('/budgets', { method: 'PUT', body: { category_id: cid, limit_minor: lim } }); m.close(); reload(); } catch (e) { $('#berr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } };
    $('#bgo', m.el).onclick = () => { const lim = toMinor($('#bl', m.el).value); if (!lim) { $('#berr', m.el).innerHTML = '<div class="err-box">Enter a limit above zero.</div>'; return; } put(id === undefined ? ($('#bc', m.el).value ? +$('#bc', m.el).value : null) : id, lim); };
    $('#brm', m.el) && ($('#brm', m.el).onclick = () => put(id, 0));
  };
  $('#addb').onclick = () => limitDialog();
  $$('[data-editb]').forEach((a) => (a.onclick = (e) => { e.preventDefault(); limitDialog(a.dataset.editb === '' ? null : +a.dataset.editb, a.dataset.name, +a.dataset.limit); }));
  const goalDialog = (g) => {
    const m = modal(`<h2>${g ? 'Edit goal' : 'New savings goal'}</h2><div id="gerr"></div><div class="field"><label for="gn">Name</label><input id="gn" maxlength="60" value="${esc(g?.name || '')}" placeholder="e.g. New laptop"></div>
      <div class="grid g2"><div class="field"><label for="gt">Target</label><input id="gt" inputmode="decimal" value="${g ? g.target_minor / 100 : ''}"></div><div class="field"><label for="gs">Saved so far</label><input id="gs" inputmode="decimal" value="${g ? g.saved_minor / 100 : '0'}"></div></div>
      <div class="field"><label for="gd">Target date (optional)</label><input id="gd" type="date" value="${esc(g?.deadline || '')}"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="ggo">Save</button></div>`);
    $('[data-x]', m.el).onclick = () => m.close();
    $('#ggo', m.el).onclick = async () => { const body = { name: $('#gn', m.el).value, target_minor: toMinor($('#gt', m.el).value), saved_minor: toMinor($('#gs', m.el).value), deadline: $('#gd', m.el).value || null }; if (!body.name.trim() || !body.target_minor) { $('#gerr', m.el).innerHTML = '<div class="err-box">Add a name and a target above zero.</div>'; return; } try { await api(g ? '/goals/' + g.id : '/goals', { method: g ? 'PATCH' : 'POST', body }); m.close(); reload(); } catch (e) { $('#gerr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } };
  };
  $('#addg').onclick = () => goalDialog();
  main.onclick = async (e) => {
    const add = e.target.closest('[data-add]'), gdel = e.target.closest('[data-gdel]'), stop = e.target.closest('[data-stop]'), track = e.target.closest('[data-track]');
    try {
      if (add) { const m = modal(`<h2>Add to goal</h2><div class="field"><label for="ga">Amount</label><input id="ga" inputmode="decimal"></div><p class="small muted">Use a negative amount to take money out.</p><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="gok">Add</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#gok', m.el).onclick = async () => { const raw = $('#ga', m.el).value.trim(); const v = toMinor(raw) * (raw.startsWith('-') ? -1 : 1); if (!v) return; await api(`/goals/${add.dataset.add}/contribute`, { method: 'POST', body: { amount_minor: v } }); m.close(); reload(); }; }
      else if (gdel) { if (await confirmBox({ title: 'Delete this goal?', body: 'Your progress on it will be lost.', ok: 'Delete', danger: true })) { await api('/goals/' + gdel.dataset.gdel, { method: 'DELETE' }); reload(); } }
      else if (stop) { await api('/recurring/stop', { method: 'POST', body: { merchant_key: stop.dataset.stop } }); reload(); }
      else if (track) { await api('/recurring/track', { method: 'POST', body: { merchant_key: track.dataset.track, frequency: track.dataset.freq } }); reload(); }
    } catch (er) { fail(er); }
  };
};

/* ---------- settings ---------- */
routes.settings = async (main) => {
  const [sts, accs, cats] = await Promise.all([api('/statements'), api('/accounts'), api('/categories')]);
  S.accounts = accs; S.cats = cats;
  main.innerHTML = `<div class="head"><div><h1>Settings</h1><p class="sub">${esc(S.user.email)}</p></div><button class="btn" id="out">Sign out</button></div>
    <div class="card" style="margin-bottom:16px"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Statements</h2><button class="btn sm primary" id="imp">Import</button></div>
      ${sts.length ? `<div class="list">${sts.map((s) => `<div><div class="grow"><b class="ell">${esc(s.filename)}</b><div class="small muted">${esc(s.account_name)} · ${s.date_from ? fdate(s.date_from) + ' to ' + fdate(s.date_to) : ''} · ${s.txn_count} transactions${s.status === 'preview' ? ' · <span class="neg">not confirmed</span>' : ''}</div></div>
        ${s.status === 'preview' ? `<a class="btn sm" href="#/import/${s.id}">Review</a>` : `<a class="btn sm ghost" href="/api/statements/${s.id}/file" target="_blank" rel="noopener">View file</a>`}<button class="btn sm ghost danger" data-sdel="${s.id}">Delete</button></div>`).join('')}</div>` : '<p class="muted small">No statements uploaded yet.</p>'}</div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Accounts</h2></div><div class="list">${accs.map((a) => `<div><div class="grow"><b>${esc(a.name)}</b><div class="small muted">${esc(a.type)}${a.last4 ? ' ••' + esc(a.last4) : ''} · ${a.txn_count} transactions</div></div><button class="btn sm ghost" data-aren="${a.id}" data-n="${esc(a.name)}">Rename</button><button class="btn sm ghost danger" data-adel="${a.id}" data-n="${esc(a.name)}">Delete</button></div>`).join('') || '<p class="muted small">Accounts appear when you import a statement.</p>'}</div></div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Categories</h2><button class="btn sm" id="addc">+ New</button></div><div class="list">${cats.map((c) => `<div>${catDot(c)}<span class="grow">${esc(c.name)}</span><span class="small muted">${c.uses}</span>${c.builtin ? '' : `<button class="btn sm ghost danger" data-cdel="${c.id}" data-n="${esc(c.name)}" data-u="${c.uses}">Delete</button>`}</div>`).join('')}</div></div></div>
    <div class="card" style="margin-bottom:16px"><h2 style="margin-bottom:6px">Appearance</h2><div class="seg" id="theme"><button data-t="light">Light</button><button data-t="dark">Dark</button></div></div>
    <div class="card"><h2 style="margin-bottom:6px">Your data</h2><p class="muted small" style="margin-bottom:14px">Everything lives in this app's own database and upload folder. Nothing is shared.</p>
      <div class="row"><a class="btn" href="/api/export.csv" download>Export all as CSV</a><button class="btn danger" id="wipe">Delete all statements &amp; transactions</button><button class="btn danger" id="delacc">Delete my account</button></div></div>`;
  $('#imp').onclick = () => openImport();
  $('#out').onclick = async () => { await api('/auth/logout', { method: 'POST' }); S.user = null; renderAuth(); };
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
  $$('#theme button').forEach((b) => { b.classList.toggle('on', b.dataset.t === cur); b.onclick = () => { document.documentElement.dataset.theme = b.dataset.t; try { localStorage.setItem('tally-theme', b.dataset.t); } catch { /* */ } $$('#theme button').forEach((x) => x.classList.toggle('on', x === b)); }; });
  $('#addc').onclick = () => { const m = modal(`<h2>New category</h2><div id="nerr"></div><div class="field"><label for="cn">Name</label><input id="cn" maxlength="40"></div><div class="field"><label for="ck">Type</label><select id="ck"><option value="expense">Spending</option><option value="income">Income</option><option value="savings">Savings</option></select></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="cgo">Create</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#cgo', m.el).onclick = async () => { try { await api('/categories', { method: 'POST', body: { name: $('#cn', m.el).value, kind: $('#ck', m.el).value, color: '#' + Math.floor(Math.random() * 0xffffff).toString(16).padStart(6, '0') } }); m.close(); route(); } catch (e) { $('#nerr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } }; };
  $('#wipe').onclick = async () => { if (await confirmBox({ title: 'Delete all statements and transactions?', body: 'This removes every uploaded file and every transaction. Your account, categories, budgets and goals stay. This can’t be undone.', ok: 'Delete everything', danger: true, typed: 'DELETE' })) { try { await api('/data/wipe', { method: 'POST', body: { confirm: 'DELETE' } }); toast('All statements and transactions deleted'); refreshBadge(); route(); } catch (e) { fail(e); } } };
  $('#delacc').onclick = () => { const m = modal(`<h2>Delete your account?</h2><p class="muted">This permanently deletes your account, all transactions, uploaded files, budgets and goals. Enter your password to confirm.</p><div id="derr"></div><div class="field" style="margin-top:14px"><label for="dpw">Password</label><input id="dpw" type="password" autocomplete="current-password"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="dgo" style="background:var(--bad)">Delete account</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#dgo', m.el).onclick = async () => { try { await api('/auth/delete-account', { method: 'POST', body: { password: $('#dpw', m.el).value } }); m.close(); S.user = null; renderAuth(); } catch (e) { $('#derr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } }; };
  main.onclick = async (e) => {
    const sd = e.target.closest('[data-sdel]'), ad = e.target.closest('[data-adel]'), ar = e.target.closest('[data-aren]'), cd = e.target.closest('[data-cdel]');
    try {
      if (sd) {
        const m = modal(`<h2>Delete this statement?</h2><p class="muted">The uploaded file will be deleted. What about the transactions imported from it?</p><div class="foot" style="flex-direction:column;align-items:stretch"><button class="btn" id="k">Delete the file, keep the transactions</button><button class="btn danger" id="a">Delete the file and its transactions</button><button class="btn ghost" data-x>Cancel</button></div>`);
        $('[data-x]', m.el).onclick = () => m.close();
        $('#k', m.el).onclick = async () => { await api(`/statements/${sd.dataset.sdel}`, { method: 'DELETE' }); m.close(); toast('File deleted'); route(); };
        $('#a', m.el).onclick = async () => { await api(`/statements/${sd.dataset.sdel}?transactions=true`, { method: 'DELETE' }); m.close(); toast('File and transactions deleted'); refreshBadge(); route(); };
      } else if (ad) { if (await confirmBox({ title: `Delete “${ad.dataset.n}”?`, body: 'This also deletes its statements and transactions. This can’t be undone.', ok: 'Delete account', danger: true })) { await api('/accounts/' + ad.dataset.adel, { method: 'DELETE' }); refreshBadge(); route(); } }
      else if (ar) { const m = modal(`<h2>Rename account</h2><div class="field"><input id="rn" value="${esc(ar.dataset.n)}" maxlength="60" aria-label="Name"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="rg">Save</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#rg', m.el).onclick = async () => { const a = accs.find((x) => x.id == ar.dataset.aren); await api('/accounts/' + a.id, { method: 'PATCH', body: { name: $('#rn', m.el).value, type: a.type, last4: a.last4 } }); m.close(); route(); }; }
      else if (cd) { if (await confirmBox({ title: `Delete “${cd.dataset.n}”?`, body: +cd.dataset.u ? `${cd.dataset.u} transaction(s) in this category go back to your review queue.` : 'Nothing is using it.', ok: 'Delete', danger: true })) { await api('/categories/' + cd.dataset.cdel, { method: 'DELETE' }); await loadRef(); refreshBadge(); route(); } }
    } catch (er) { fail(er); }
  };
};
