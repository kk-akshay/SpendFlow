/* Dashboard, History, Plan (budgets/goals/recurring) and Settings. */

/* ---------- monochrome data visualisations ---------- */
function donut(items,total) {
  const R=54,C=2*Math.PI*R;let off=0;
  const arcs=items.map((b,i)=>{
    const len=(Math.max(0,b.amount_minor)/Math.max(total,1))*C;
    const a=`<circle r="${R}" cx="70" cy="70" fill="none" stroke="var(--shade-${i%6})" stroke-width="20" stroke-dasharray="${Math.max(len-1.5,0)} ${C}" stroke-dashoffset="${-off}" transform="rotate(-90 70 70)"><title>${esc(b.name)} ${money(b.amount_minor)}</title></circle>`;
    off+=len;return a;
  }).join('');
  return `<svg viewBox="0 0 140 140" width="150" height="150" role="img" aria-label="Spending by category">${arcs}</svg>`;
}
const smoothLine=(points)=>{
  if(!points.length)return '';
  let s=`M${points[0][0].toFixed(1)},${points[0][1].toFixed(1)}`;
  for(let i=1;i<points.length;i++){const [x0,y0]=points[i-1],[x1,y1]=points[i],xm=(x0+x1)/2;s+=` C${xm.toFixed(1)},${y0.toFixed(1)} ${xm.toFixed(1)},${y1.toFixed(1)} ${x1.toFixed(1)},${y1.toFixed(1)}`;}
  return s;
};
function trendChart(trend){
  const W=520,H=190,p=28,base=H-26,max=Math.max(1,...trend.flatMap(t=>[t.income,t.expense]));
  if(!trend.length)return '<p class="muted small">No cashflow data yet.</p>';
  const pts=key=>trend.map((t,i)=>[p+i*(W-p*2)/Math.max(trend.length-1,1),base-(H-60)*t[key]/max]);
  const inc=pts('income'),spent=pts('expense'),line=smoothLine(inc),low=smoothLine(spent);
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Income (solid) and spending (dashed) over the last six months">
    <defs><linearGradient id="cashflow-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--text)" stop-opacity=".16"/><stop offset="100%" stop-color="var(--text)" stop-opacity="0"/></linearGradient></defs>
    <line class="cashflow-axis" x1="${p}" y1="${base}" x2="${W-p}" y2="${base}"/>
    <path d="${line} L${inc[inc.length-1][0].toFixed(1)},${base} L${inc[0][0].toFixed(1)},${base} Z" fill="url(#cashflow-gradient)"/>
    <path class="cashflow-line" d="${line}"/><path class="cashflow-muted" d="${low}"/>
    ${trend.map((t,i)=>`<text x="${inc[i][0]}" y="${H-6}" text-anchor="middle">${fmonth(t.month,false)}</text>`).join('')}
  </svg><div class="legend"><span>━ Income</span><span>┄ Spending</span></div>`;
}
function paceChart(daily){
  const W=520,H=170,p=26,n=daily.days,max=Math.max(1,...daily.current.filter(v=>v!=null),...daily.previous);
  const X=i=>p+i*(W-2*p)/Math.max(n-1,1),Y=v=>H-22-(H-44)*v/max;
  const pts=a=>a.map((v,i)=>v==null?null:[X(i),Y(v)]);
  const groups=a=>{let g=[],curr=[];for(const point of pts(a)){if(!point){if(curr.length)g.push(curr);curr=[];}else curr.push(point);}if(curr.length)g.push(curr);return g;};
  const current=groups(daily.current),previous=groups(daily.previous);
  const currentPaths=current.map(smoothLine),priorPaths=previous.map(smoothLine);
  const base=H-22;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative spending this month (solid) versus last month (dashed)">
    <defs><linearGradient id="pace-gradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="var(--text)" stop-opacity=".13"/><stop offset="100%" stop-color="var(--text)" stop-opacity="0"/></linearGradient></defs>
    <line class="cashflow-axis" x1="${p}" x2="${W-p}" y1="${base}" y2="${base}"/>
    ${current.map((g,i)=>`<path d="${currentPaths[i]} L${g[g.length-1][0].toFixed(1)},${base} L${g[0][0].toFixed(1)},${base} Z" fill="url(#pace-gradient)"/>`).join('')}
    ${priorPaths.map(d=>`<path class="cashflow-muted" d="${d}"/>`).join('')}
    ${currentPaths.map(d=>`<path class="cashflow-line" d="${d}"/>`).join('')}
    <text x="${p}" y="${H-5}">1</text><text x="${W-p}" y="${H-5}" text-anchor="end">${n}</text>
  </svg><div class="legend"><span>━ This month</span><span>┄ Last month</span></div>`;
}
const delta = (cur, prev, goodWhenUp) => {
  if (!prev) return '';
  const d = cur - prev, pct = Math.round((100 * Math.abs(d)) / Math.abs(prev));
  if (!pct) return '<div class="delta muted">Same as last month</div>';
  return `<div class="delta muted">${d > 0 ? '▲' : '▼'} ${pct}% vs last month</div>`;
};

/* ---------- dashboard ---------- */
routes.dashboard = async (main, [month]) => {
  const d = await api('/dashboard' + (month ? '?month=' + month : ''));
  if (d.empty) {
    main.innerHTML = `<div class="empty card" style="margin-top:40px"><div class="big">🌱</div><h2>Let's see where your money goes</h2>
      <p>Upload a bank or Google Pay statement. SpendFlow reads it, then asks you about each transaction one at a time.</p>
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
      <div class="card stat"><div class="label">Income</div><div class="value amount-in">↑ +${money(d.income_minor)}</div>${delta(d.income_minor, d.prev.income_minor, true)}</div>
      <div class="card stat"><div class="label">Spent</div><div class="value amount-out">↓ −${money(d.expense_minor)}</div>${delta(d.expense_minor, d.prev.expense_minor, false)}</div>
      <div class="card stat"><div class="label">Net savings</div><div class="value ${d.net_minor < 0 ? 'amount-out' : 'amount-in'}">${money(d.net_minor, { sign: true })}</div><div class="delta muted">${d.income_minor > 0 ? Math.round((100 * d.net_minor) / d.income_minor) + '% of income' : '&nbsp;'}${d.saved_minor ? ' · ' + money(d.saved_minor) + ' put into savings' : ''}</div></div></div>
    ${d.insights.length ? `<div class="card" style="margin-bottom:16px"><h2 style="margin-bottom:8px">Insights</h2><div class="list">${d.insights.map((x) => `<div><span class="dot" style="background:var(--shade-3)"></span><div class="grow">${esc(x.text)}</div></div>`).join('')}</div></div>` : ''}
    <div class="grid g-main" style="margin-bottom:16px">
      <div class="card"><h2 style="margin-bottom:14px">Where it went</h2>${d.breakdown.length ? `<div class="donut-wrap">${donut(d.breakdown, d.expense_minor || 1)}<div class="grow list" style="flex:1;min-width:200px">${d.breakdown.slice(0, 8).map((b) => `<a class="row" href="#/transactions/cat-${b.category_id ?? 'uncategorized'}-${d.month}" style="text-decoration:none;color:inherit"><span class="dot" style="background:var(--shade-${d.breakdown.indexOf(b)%6})"></span><span class="grow ell">${esc(b.name)}</span><span class="muted small">${b.pct}%</span><b class="num">${money(b.amount_minor)}</b></a>`).join('')}</div></div>` : '<p class="muted">No spending in this month.</p>'}</div>
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
  const inflow = t.direction === 'credit';
  const category = t.is_split ? 'Split' : (t.category_name || (t.status === 'skipped' ? 'Skipped' : 'Needs a category'));
  const details = (t.type === 'transfer' ? ' · Transfer' : '') + (t.recurring ? ' · ↻' : '');
  const merchant = t.merchant || (t.description || '').slice(0, 60) || 'Unknown';
  return `<div class="txn history-txn" data-txn="${t.id}" tabindex="0" role="button" aria-label="Open ${esc(merchant)} transaction">
    <span class="dot history-txn-dot" aria-hidden="true"></span>
    <div class="history-txn-name"><div class="history-txn-merchant ell"><b>${esc(merchant)}</b>${t.dup_status === 'suspected' ? ' <span class="pill warn">Possible duplicate</span>' : ''}</div>
      <div class="history-txn-mobile-meta small muted">${fdate(t.date, false)} · ${esc(category)}${details}</div></div>
    <span class="history-txn-date small muted">${fdate(t.date)}</span>
    <span class="history-txn-category small muted">${esc(category)}${details}</span>
    <b class="history-txn-amount num ${t.type === 'transfer' ? 'muted' : inflow ? 'amount-in' : 'amount-out'}">${inflow ? '↑ +' : '↓ −'}${money(t.amount_minor)}</b>
    <span class="history-txn-chevron" aria-hidden="true">›</span></div>`;
}
function budgetBars(b, compact) {
  const rows = [...(b.overall ? [{ category_name: 'All spending', category_color: 'var(--accent)', ...b.overall }] : []), ...b.items];
  if (!rows.length) return `<p class="muted small">Set monthly limits to see progress here. ${compact ? '<a href="#/plan">Add a budget</a>' : ''}</p>`;
  return `<div class="list">${rows.slice(0, compact ? 5 : 99).map((r) => `<div style="display:block"><div class="row" style="justify-content:space-between;margin-bottom:6px"><span class="row" style="gap:8px"><span class="dot" style="background:var(--shade-3)"></span><b>${esc(r.category_name)}</b></span><span class="small ${r.pct >= 100 ? 'neg' : 'muted'}">${money(r.spent_minor)} of ${money(r.limit_minor)}</span></div><div class="bar ${r.pct >= 100 ? 'bad' : r.pct >= 80 ? 'warn' : ''}"><i style="width:${Math.min(r.pct, 100)}%"></i></div></div>`).join('')}</div>`;
}

/* ---------- transaction editor (used from dashboard + history) ---------- */
async function openTxn(id, done) {
  let d;
  try { d = await api('/transactions/' + id); } catch (e) { return fail(e); }
  const t = d.txn; let catId = t.category_id, recurring = t.recurring, type = t.type, changed = false;
  let allTags = [], currentTags = [];
  try { [allTags, currentTags] = await Promise.all([api('/tags'),api('/transactions/'+id+'/tags')]); } catch (e) { console.warn('Tags unavailable', e); }
  const m = modal(`<div class="row" style="justify-content:space-between;align-items:flex-start"><div><h2 style="margin:0">${esc(t.merchant || 'Transaction')}</h2><p class="muted small">${fdate(t.date)} · ${esc(t.account_name)}</p></div><b class="num" style="font-size:22px">${t.direction === 'credit' ? '+' : ''}${money(t.amount_minor)}</b></div>
    <div class="desc small muted" style="margin:14px 0;padding:10px 12px;background:var(--surface2);border-radius:12px;word-break:break-word">${esc(t.description || '(no description)')}</div>
    ${t.flags.map((f) => `<div class="flag" style="margin:0 0 8px">⚠ ${esc(f)}</div>`).join('')}
    <div id="terr"></div>
    ${t.is_split ? `<div class="field"><label>Split across</label>${t.splits.map((s) => `<div class="row small">${catDot(s)}<span class="grow">${esc(s.category_name)}</span><b>${money(s.amount_minor)}</b></div>`).join('')}<p class="small muted" style="margin-top:6px">To change a split, send it back to review.</p></div>` : ''}
    <div class="field"><label>Category</label><div class="row" id="tcats" style="gap:8px">${S.cats.map((c) => `<button class="pill" data-c="${c.id}" style="cursor:pointer;border:1.5px solid ${c.id === catId ? esc(c.color) : 'transparent'}">${catDot(c)}${esc(c.name)}</button>`).join('')}</div></div>
    <div class="grid g2"><div class="field"><label>Type</label><select id="tt">${['expense', 'income', 'transfer'].map((k) => `<option value="${k}" ${k === type ? 'selected' : ''}>${typeLabel[k]}</option>`).join('')}</select></div>
      <div class="field"><label>Repeats</label><select id="tr"><option value="">Not recurring</option>${['weekly', 'monthly', 'yearly'].map((f) => `<option value="${f}" ${recurring && t.recurring_freq === f ? 'selected' : ''}>${f[0].toUpperCase() + f.slice(1)}</option>`).join('')}</select></div></div>
    <label class="check small"><input type="checkbox" id="tremember"> Remember classification for future imports</label>
    <div class="field"><label for="tn">Note</label><input id="tn" maxlength="500" value="${esc(t.note || '')}" placeholder="Add a note"></div>
    <div class="field"><label>Tags · trips, people and projects</label><div class="row" id="transaction-tags" style="gap:6px">${allTags.map(g=>`<label class="check small" style="margin:0;padding:5px 10px;border:1px solid var(--line);border-radius:99px"><input type="checkbox" data-assign-tag="${g.id}" ${currentTags.some(x=>x.id===g.id)?'checked':''} style="width:16px;height:16px"> ${esc(g.name)}</label>`).join('')}<button class="btn sm" type="button" id="txn-create-tag">+ Tag</button></div></div>
    <details style="margin-bottom:8px"><summary class="small muted" style="cursor:pointer">Fix merchant, date or amount</summary><div class="grid g2" style="margin-top:12px">
      <div class="field"><label for="tm">Merchant</label><input id="tm" value="${esc(t.merchant)}" maxlength="80"></div><div class="field"><label for="td">Date</label><input id="td" type="date" value="${esc(t.date)}"></div>
      <div class="field"><label for="ta">Amount</label><input id="ta" inputmode="decimal" value="${(t.amount_minor / 100).toFixed(2)}" ${t.is_split ? 'disabled' : ''}></div>
      <div class="field"><label for="tdir">Direction</label><select id="tdir"><option value="debit" ${t.direction === 'debit' ? 'selected' : ''}>Money out</option><option value="credit" ${t.direction === 'credit' ? 'selected' : ''}>Money in</option></select></div></div></details>
    <div class="transaction-editor-toolbar" role="group" aria-label="Transaction actions">
      <div class="txn-editor-buttons"><button class="btn sm danger" id="tdel">Remove</button><button class="btn sm" id="trev">Send to review</button><button class="btn sm" id="tflow">Link flow</button><button class="btn sm" id="tperson">Track with person</button></div>
      <div class="txn-editor-confirm"><button class="btn" data-x>Cancel</button><button class="btn primary" id="tsave">Save changes</button></div>
    </div>
    `);
  $('#txn-create-tag',m.el).onclick=()=>{
    const dialog=modal('<h2>New tag</h2><div class="field"><label>Name</label><input id="tag-new-name" maxlength="80"></div><div class="field"><label>Type</label><select id="tag-new-kind"><option value="trip">Trip</option><option value="person">Person / beneficiary</option><option value="custom">Other</option></select></div><div id="tag-new-err"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="tag-new-save">Create</button></div>');
    $('[data-x]',dialog.el).onclick=()=>dialog.close();
    $('#tag-new-save',dialog.el).onclick=async()=>{
      try{
        const tag=await api('/tags',{method:'POST',body:{name:$('#tag-new-name',dialog.el).value,kind:$('#tag-new-kind',dialog.el).value}});
        if(!$('[data-assign-tag="'+tag.id+'"]',m.el))$('#txn-create-tag',m.el).insertAdjacentHTML('beforebegin','<label class="check small"><input type="checkbox" checked data-assign-tag="'+tag.id+'" style="width:16px;height:16px"> '+esc(tag.name)+'</label>');
        else $('[data-assign-tag="'+tag.id+'"]',m.el).checked=true;
        dialog.close();
      }catch(e){$('#tag-new-err',dialog.el).textContent=e.message;}
    };
  };
  $$('#tcats .pill', m.el).forEach((b) => (b.onclick = () => { catId = +b.dataset.c; changed = true; const c = cat(catId); $$('#tcats .pill', m.el).forEach((x) => (x.style.borderColor = x === b ? c.color : 'transparent')); if (c.kind === 'transfer') $('#tt', m.el).value = 'transfer'; else if (c.kind === 'income') $('#tt', m.el).value = 'income'; else if ($('#tt', m.el).value === 'transfer' || c.kind === 'expense') $('#tt', m.el).value = t.direction === 'credit' && c.kind !== 'expense' ? 'income' : 'expense'; }));
  $('[data-x]', m.el).onclick = () => m.close();
  const patch = async (body, msg, saveTags = false) => { try { const r = await api('/transactions/' + id, { method: 'PATCH', body }); if(saveTags) await api('/transactions/' + id + '/tags',{method:'PUT',body:{tag_ids:$$('[data-assign-tag]:checked',m.el).map(x=>+x.dataset.assignTag)}}); m.close(); refreshBadge(); toast(msg, r.undo?.length ? { action: 'Undo', onAction: async () => { await api('/transactions/restore', { method: 'POST', body: { undo: r.undo } }); done && done(); } } : {}); done && done(); } catch (e) { $('#terr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } };
  $('#trev', m.el).onclick = () => patch({ send_to_review: true }, 'Sent back to review');
  $('#tperson',m.el).onclick=()=>{m.close();personLinkDialog(id,done);};
  $('#tflow', m.el).onclick = async () => {
    try {
      const suggestions = await api('/flows/suggestions/' + id);
      m.close();
      const x = modal(`<h2>Link non-personal transactions</h2><p class="muted small">Select only payments that belong to the same transfer, loan, reimbursement or pass-through. These are suggestions, not confirmed matches.</p>
        <div class="field"><label>Flow type</label><select id="flow-kind"><option value="pass_through">Pass-through payment</option><option value="temporary_transfer">Temporary transfer</option><option value="loan">Loan</option><option value="repayment">Repayment</option><option value="reimbursement">Reimbursement</option></select></div>
        <div class="list">${suggestions.map(s=>`<label class="row" style="flex-wrap:nowrap"><input type="checkbox" data-flow-txn="${s.txn.id}" style="width:20px;flex:none"><span class="grow"><b>${esc(s.txn.merchant||s.txn.description)}</b><span class="small muted"> · ${fdate(s.txn.date)} · ${esc(s.txn.account_name)} ${s.same_amount?' · Same amount':''}</span></span><b>${money(s.txn.amount_minor)}</b></label>`).join('')||'<p class="muted">No suggested incoming/outgoing partners in the surrounding 30 days.</p>'}</div>
        <div class="foot"><button class="btn" id="flow-cancel">Cancel</button><button class="btn primary" id="flow-link">Link selected</button></div>`);
      $('#flow-cancel',x.el).onclick=()=>x.close();
      $('#flow-link',x.el).onclick=async()=>{
        const ids=[id,...$$('[data-flow-txn]:checked',x.el).map(el=>+el.dataset.flowTxn)];
        if(ids.length<2)return toast('Select at least one related transaction',{err:true});
        if(!await confirmBox({title:'Confirm non-personal flow?',body:'The selected transactions will no longer count as personal income or expenses. All original payments remain visible and can be unlinked.',ok:'Link transactions'}))return;
        try { await api('/flows',{method:'POST',body:{kind:$('#flow-kind',x.el).value,transaction_ids:ids}});x.close();toast('Transactions linked');done&&done();} catch(e){fail(e);}
      };
    } catch(e){fail(e);}
  };
  $('#tdel', m.el).onclick = async () => {
    m.close();
    const x = modal('<h2>Remove transaction</h2><p class="muted small">Choose whether to remove only this transaction or also remember an exact rule for future imports.</p><div class="foot" style="flex-direction:column;align-items:stretch"><button class="btn danger" id="remove-once">Remove only this transaction</button><button class="btn" id="exclude-future">Exclude matching future imports</button><button class="btn ghost" id="cancel-remove">Cancel</button></div>');
    $('#cancel-remove', x.el).onclick = () => x.close();
    $('#remove-once', x.el).onclick = async () => { try { await api('/transactions/' + id, { method:'DELETE' }); x.close(); toast('Transaction removed'); refreshBadge(); done && done(); } catch(e) { fail(e); } };
    $('#exclude-future', x.el).onclick = async () => {
      if (!await confirmBox({ title:'Save an exclusion rule?', body:'This will exclude future transactions matching the same account, merchant, amount and direction. Check that repeated genuine payments should also be excluded.', ok:'Save rule', danger:true })) return;
      try { await api('/exclusions',{method:'POST',body:{transaction_id:id}}); x.close(); toast('Exclusion saved'); refreshBadge(); done && done(); } catch(e) { fail(e); }
    };
  };
  const exclude = document.createElement('button'); exclude.className='btn sm danger'; exclude.textContent='Delete and exclude future matches';
  $('#tdel',m.el).after(exclude);
  exclude.onclick=async()=>{if(!await confirmBox({title:'Delete and permanently exclude matching imports?',body:'Matches require the same account, merchant, description, direction and amount. Repeated genuine payments could also match. Remove the rule later in Linked money.',ok:'Confirm exclusion',danger:true}))return;
    try{await api('/transactions/'+id+'/exclude',{method:'POST',body:{confirmed:true}});m.close();toast('Exclusion saved');refreshBadge();done&&done();}catch(e){fail(e);}};
  const findMatches=document.createElement('button'); findMatches.className='btn sm'; findMatches.textContent='Find related payments';
  $('#tdel',m.el).after(findMatches);
  findMatches.onclick=async()=>{
    try{
      const matches=await api('/transactions/'+id+'/matches');
      const prompt=modal('<h2>Possible related payments</h2><p class="muted small">These are suggestions based on amount, date and description. Confirm only genuine loan, repayment or pass-through transactions.</p>'
        +'<div id="match-error"></div><div class="list">'+(matches.map(t=>'<label class="check"><input type="checkbox" data-match="'+t.id+'"><span>'+fdate(t.date)+' · '+esc(t.merchant||t.description)+' · '+money(t.amount_minor)+' · '+esc(t.reason)+'</span></label>').join('')||'<p class="muted">No strong matches found. Use Linked money to link manually.</p>')+'</div>'
        +'<div class="field"><label>Group name</label><input id="match-name" value="'+esc(t.merchant||'Related payments')+'"></div>'
        +'<div class="field"><label>Kind</label><select id="match-kind"><option value="pass_through">Pass-through</option><option value="loan">Loan</option><option value="repayment">Repayment</option><option value="transfer">Transfer</option></select></div>'
        +'<div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="match-confirm">Confirm selected links</button></div>');
      $('[data-x]',prompt.el).onclick=()=>prompt.close();
      $('#match-confirm',prompt.el).onclick=async()=>{
        try{
          const ids=[id,...$$('[data-match]:checked',prompt.el).map(x=>+x.dataset.match)];
          if(ids.length<2)throw Error('Choose at least one matching payment.');
          await api('/groups',{method:'POST',body:{name:$('#match-name',prompt.el).value,kind:$('#match-kind',prompt.el).value,ids}});
          prompt.close();m.close();toast('Payments linked');refreshBadge();done&&done();
        }catch(e){$('#match-error',prompt.el).textContent=e.message;}
      };
    }catch(e){fail(e);}
  };
  $('#tsave', m.el).onclick = () => {
    const freq = $('#tr', m.el).value, body = { remember: $('#tremember', m.el).checked, note: $('#tn', m.el).value, recurring: !!freq, recurring_freq: freq || undefined, type: $('#tt', m.el).value };
    if (catId && (changed || t.status !== 'categorized') && !t.is_split) body.category_id = catId;
    else if (t.status === 'categorized' && catId && !t.is_split) body.category_id = catId;
    if ($('#tm', m.el).value !== t.merchant) body.merchant = $('#tm', m.el).value;
    if ($('#td', m.el).value !== t.date) body.date = $('#td', m.el).value;
    const amt = toMinor($('#ta', m.el).value); if (!t.is_split && amt && amt !== t.amount_minor) body.amount_minor = amt;
    if ($('#tdir', m.el).value !== t.direction) body.direction = $('#tdir', m.el).value;
    patch(body, 'Saved', true);
  };
}

function accountEditor(account=null) {
    const m=modal(`<h2>${account?'Edit account':'Add credit card'}</h2><div id="card-err"></div>
      <div class="field"><label>Name</label><input id="card-name" maxlength="60" value="${esc(account?.name || '')}" placeholder="SuperMoney Credit Card"></div>
      <div class="field"><label>Account type</label><select id="card-type">
        ${[['card','Credit Card'],['bank','Bank'],['upi','UPI'],['cash','Cash']].map(([v,n])=>`<option value="${v}" ${(account?.type || 'card')===v?'selected':''}>${n}</option>`).join('')}</select></div>
      <div class="field"><label>Last 4 digits (optional)</label><input id="card-last4" maxlength="4" inputmode="numeric" value="${esc(account?.last4||'')}"></div>
      <div class="field" id="card-limit-field"><label>Monthly card spending limit (₹)</label>
      <input id="card-limit" inputmode="decimal" value="${account?.card_monthly_limit_minor ? (account.card_monthly_limit_minor/100).toFixed(2) : ''}" placeholder="e.g. 20000">
      <div class="small muted">Optional monthly spending budget (does not reset when you repay).</div></div>
      <div class="field card-credit-field"><label>Card credit limit (₹)</label><input id="credit-limit" inputmode="decimal" value="${account?.card_credit_limit_minor ? (account.card_credit_limit_minor/100).toFixed(2) : ''}" placeholder="e.g. 50000"></div>
      <div class="field card-credit-field"><label>Opening outstanding (₹, optional)</label><input id="opening-outstanding" inputmode="decimal" value="${account?.card_opening_outstanding_minor ? (account.card_opening_outstanding_minor/100).toFixed(2) : ''}" placeholder="0">
      <div class="small muted">Only enter a balance from before your earliest imported card transaction; otherwise leave 0 to avoid counting it twice.</div></div>
      <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="card-save">Save account</button></div>`);
    $('[data-x]',m.el).onclick=()=>m.close();
    const setType=()=>{const isCard=$('#card-type',m.el).value==='card';$('#card-limit-field',m.el).hidden=!isCard;$('.card-credit-field',m.el).forEach(x=>x.hidden=!isCard);};
    $('#card-type',m.el).onchange=setType;setType();
    $('#card-save',m.el).onclick=async()=>{
      try{
        const body={name:$('#card-name',m.el).value.trim(),type:$('#card-type',m.el).value,
          last4:$('#card-last4',m.el).value.trim()||null,
          card_monthly_limit_minor:$('#card-type',m.el).value==='card'?toMinor($('#card-limit',m.el).value||'0'):0,
          card_credit_limit_minor:$('#card-type',m.el).value==='card'?toMinor($('#credit-limit',m.el).value||'0'):0,
          card_opening_outstanding_minor:$('#card-type',m.el).value==='card'?toMinor($('#opening-outstanding',m.el).value||'0'):0};
        if(!body.name)throw new Error('Enter an account name.');
        await api(account?'/accounts/'+account.id:'/accounts',{method:account?'PATCH':'POST',body});
        m.close();await loadRef();route();
      }catch(e){$('#card-err',m.el).textContent=e.message;}
    };
}

/* ---------- history ---------- */
routes.transactions = async (main, [pre]) => {
  const f = { q: '', category: '', account: '', status: '', type: '', from: '', to: '', min: '', max: '', sort: 'date_desc', page: 1, dup: '' };
  if (!pre) { try { Object.assign(f, JSON.parse(sessionStorage.getItem('spendflow-history') || '{}')); } catch {} }
  if (pre === 'duplicates') f.dup = 'suspected';
  else if (pre === 'uncategorized') f.category = 'uncategorized';
  else if (pre && pre.startsWith('cat-')) { const [, c, mo] = pre.split('-').concat([]); f.category = c === 'uncategorized' ? 'uncategorized' : c; if (mo) { const y = pre.split('-')[2], mm = pre.split('-')[3]; f.from = `${y}-${mm}-01`; f.to = `${y}-${mm}-31`; } }
  let selected = new Set(), data = null, timer;
  main.innerHTML = `<div class="head"><div><h1>${f.dup ? 'Possible duplicates' : 'Transactions'}</h1><p class="sub" id="sub"></p></div><div class="row"><a class="btn sm" href="/api/export.csv" download>Export CSV</a><button class="btn primary sm" id="imp">Import</button></div></div>
    <div id="dupbox"></div><div class="row" style="margin-bottom:12px"><button class="btn sm" id="add-manual">+ Add transaction</button><a class="btn sm" href="#/calendar">Calendar</a><button class="btn sm" id="show-removed">Removed transactions</button></div>
    <div class="card flat" style="margin-bottom:16px"><div class="grid g3" style="margin-bottom:10px"><input id="q" type="search" placeholder="Search merchant, note, amount…" aria-label="Search" value="${esc(f.q)}">
      <select id="fcat" aria-label="Category"><option value="">All categories</option><option value="uncategorized">Needs a category</option>${S.cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <select id="facc" aria-label="Account"><option value="">All accounts</option>${S.accounts.map((a) => `<option value="${a.id}">${esc(a.name)}</option>`).join('')}</select></div>
      <details ${f.from ? 'open' : ''}><summary class="small muted" style="cursor:pointer">More filters</summary><div class="grid g3" style="margin-top:10px">
        <select id="ftype" aria-label="Type"><option value="">Any type</option><option value="income">Income</option><option value="expense">Expense</option><option value="transfer">Transfer</option></select>
        <select id="fsort" aria-label="Sort"><option value="date_desc">Newest first</option><option value="date_asc">Oldest first</option><option value="amount_desc">Largest first</option><option value="amount_asc">Smallest first</option></select>
        <label class="check"><input type="checkbox" id="frec"> Recurring only</label>
        <div><label for="ffrom">From</label><input type="date" id="ffrom" value="${esc(f.from.replace(/-31$/, '-01'))}"></div><div><label for="fto">To</label><input type="date" id="fto"></div>
        <div class="row" style="flex-wrap:nowrap"><input id="fmin" inputmode="decimal" placeholder="Min ₹" aria-label="Minimum amount"><input id="fmax" inputmode="decimal" placeholder="Max ₹" aria-label="Maximum amount"></div></div></details></div>
    <div id="selbar" aria-live="polite"></div><div id="list"></div>`;
  $('#fcat').value = f.category; if (f.to) { const [y, mo] = f.to.split('-'); $('#fto').value = new Date(+y, +mo, 0).toISOString().slice(0, 10).replace(/-\d\d$/, '-' + String(new Date(+y, +mo, 0).getDate()).padStart(2, '0')); f.to = $('#fto').value; }
  $('#imp').onclick = () => openImport();
  $('#add-manual').onclick = () => manualTransaction(todayIso(), load);
  $('#show-removed').onclick = () => { f.include_removed = f.include_removed ? '' : 1; $('#show-removed').textContent = f.include_removed ? 'Hide removed' : 'Removed transactions'; load(); };
  const bind = { q: 'q', category: 'fcat', account: 'facc', type: 'ftype', sort: 'fsort', from: 'ffrom', to: 'fto', min: 'fmin', max: 'fmax' };
  Object.entries(bind).forEach(([k, id]) => { $('#' + id).oninput = (e) => { f[k] = e.target.value; f.page = 1; clearTimeout(timer); timer = setTimeout(load, k === 'q' || k === 'min' || k === 'max' ? 300 : 0); }; });
  $('#frec').onchange = (e) => { f.recurring = e.target.checked ? 1 : ''; f.page = 1; load(); };

  async function load() {
    sessionStorage.setItem('spendflow-history', JSON.stringify(f));
    const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v !== '' && v != null)).toString();
    $('#list').innerHTML = '<div class="card"><div class="skel" style="height:260px"></div></div>';
    try { data = await api('/transactions?' + qs); } catch (e) { $('#list').innerHTML = `<div class="err-box">${esc(e.message)}</div>`; return; }
    draw();
  }
  function draw() {
    $('#sub').textContent = `${data.total} transaction${data.total === 1 ? '' : 's'} · in ${money(data.money_in)} · out ${money(data.money_out)}`;
    if (f.dup) loadDups();
    if (!data.items.length) { $('#list').innerHTML = `<div class="empty card"><div class="big">🔍</div><h2>${f.dup ? 'No duplicates to check' : 'Nothing matches'}</h2><p>${f.dup ? 'Nice and tidy.' : 'Try clearing a filter, or import a statement.'}</p></div>`; selbar(); return; }
    $('#list').innerHTML = `<div class="card"><div class="list">${data.items.map((t) => `<div class="history-entry">${t.removed_at ? `<button class="btn sm" data-restore="${t.id}">Restore</button>` : ''}<input type="checkbox" class="history-select" data-sel="${t.id}" aria-label="Select ${esc(t.merchant || 'transaction')}" ${selected.has(t.id) ? 'checked' : ''}><div class="history-entry-body">${txnRow(t)}</div></div>`).join('')}</div>
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
    $('#selbar').innerHTML = selected.size ? `<div class="sel-bar" role="toolbar" aria-label="Selected transaction actions"><b>${selected.size} selected</b>
      <div class="sel-bar-actions"><select id="bcat" aria-label="Set category"><option value="">Set category…</option>${S.cats.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select>
      <button class="btn sm" data-b="pending">Send to review</button><button class="btn sm" data-b="delete">Remove</button><button class="btn sm" data-b="clear">Clear</button></div></div>` : '';
    const bc = $('#bcat'); bc && (bc.onchange = () => bulk('categorize', { category_id: +bc.value }));
    $$('[data-b]').forEach((b) => (b.onclick = async () => { const a = b.dataset.b; if (a === 'clear') { selected.clear(); draw(); } else if (a === 'delete') { if (await confirmBox({ title: `Delete ${selected.size} transactions?`, body: 'Only the selected transactions will be hidden. Their records remain recoverable.', ok: 'Delete', danger: true })) bulk('delete'); } else bulk(a); }));
  }
  async function bulk(action, extra = {}) {
    try { const r = await api('/transactions/bulk', { method: 'POST', body: { ids: [...selected], action, ...extra } }); selected.clear(); refreshBadge(); toast(`${r.changed} updated`, r.undo.length ? { action: 'Undo', onAction: async () => { await api('/transactions/restore', { method: 'POST', body: { undo: r.undo } }); refreshBadge(); load(); } } : {}); load(); } catch (e) { fail(e); }
  }
  main.onclick = (e) => {
    const restore = e.target.closest('[data-restore]');
    if (restore) { api('/transactions/' + restore.dataset.restore + '/restore', { method: 'POST' }).then(load).catch(fail); return; }
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
      ${rec.items.length ? `<div class="list">${rec.items.map((r) => `<div><span class="dot" style="background:var(--shade-3);width:12px;height:12px"></span><div class="grow"><b>${esc(r.merchant)}</b><div class="small muted">${r.frequency} · next around ${fdate(r.next_due)}${r.days_until >= 0 && r.days_until <= 7 ? ' · <span class="neg">due soon</span>' : ''}</div></div><b class="num">${money(r.amount_minor)}</b><button class="btn sm ghost" data-stop="${esc(r.key)}">Stop tracking</button></div>`).join('')}</div>` : '<p class="muted small">Mark a transaction as “Recurring” while reviewing and it appears here.</p>'}
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
  const [sts, accs, cats, exclusions, classificationRules, flows] = await Promise.all([api('/statements'), api('/accounts'), api('/categories'), api('/exclusions'), api('/classification-rules'), api('/flows')]);
  S.accounts = accs; S.cats = cats;
  main.innerHTML = `<div class="head"><div><h1>Settings</h1><p class="sub">${esc(S.user.email)}</p></div><button class="btn" id="out">Sign out</button></div>
    <div class="card" style="margin-bottom:16px"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Statements</h2><button class="btn sm primary" id="imp">Import</button></div>
      ${sts.length ? `<div class="list">${sts.map((s) => `<div><div class="grow"><b class="ell">${esc(s.filename)}</b><div class="small muted">${esc(s.account_name)} · ${s.date_from ? fdate(s.date_from) + ' to ' + fdate(s.date_to) : ''} · ${s.txn_count} transactions${s.status === 'preview' ? ' · <span class="neg">not confirmed</span>' : ''}</div></div>
        ${s.status === 'preview' ? `<a class="btn sm" href="#/import/${s.id}">Review</a>` : `<a class="btn sm ghost" href="/api/statements/${s.id}/file" target="_blank" rel="noopener">View file</a>`}<button class="btn sm ghost danger" data-sdel="${s.id}">Delete</button></div>`).join('')}</div>` : '<p class="muted small">No statements uploaded yet.</p>'}</div>
    <div class="grid g2" style="margin-bottom:16px">
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Accounts</h2><button class="btn sm" id="new-card-account">+ Credit Card</button></div><div class="list">${accs.map((a) => `<div><div class="grow"><b>${esc(a.name)}</b><div class="small muted">${esc(a.type)}${a.last4 ? ' ••' + esc(a.last4) : ''} · ${a.txn_count} transactions${a.type==='card' ? ` · Monthly limit: ${a.card_monthly_limit_minor ? money(a.card_monthly_limit_minor) : 'Not set'}` : ''}</div></div><button class="btn sm ghost" data-aren="${a.id}" data-n="${esc(a.name)}">Edit</button><button class="btn sm ghost danger" data-adel="${a.id}" data-n="${esc(a.name)}">Delete</button></div>`).join('') || '<p class="muted small">Accounts appear when you import a statement.</p>'}</div></div>
      <div class="card"><div class="row" style="justify-content:space-between;margin-bottom:6px"><h2>Categories</h2><button class="btn sm" id="addc">+ New</button></div><div class="list">${cats.map((c) => `<div>${catDot(c)}<span class="grow">${esc(c.name)}</span><span class="small muted">${c.uses}</span>${c.builtin ? '' : `<button class="btn sm ghost danger" data-cdel="${c.id}" data-n="${esc(c.name)}" data-u="${c.uses}">Delete</button>`}</div>`).join('')}</div></div></div>
    <div class="card" style="margin-bottom:16px"><h2>Remembered classifications</h2><p class="muted small">Exact merchant and direction matches only. Existing corrections are never reclassified.</p>
      <div class="list">${classificationRules.map(r=>`<div><span class="grow"><b>${esc(r.merchant_key)}</b><div class="small muted">${esc(r.direction)}</div></span><select data-rule-cat="${r.id}" style="width:auto">${cats.map(x=>`<option value="${x.id}" ${x.id===r.category_id?'selected':''}>${esc(x.name)}</option>`).join('')}</select><button class="btn sm danger" data-rule-del="${r.id}">Remove</button></div>`).join('')||'<p class="muted small">No saved classifications.</p>'}</div></div>
    <div class="card" style="margin-bottom:16px"><h2>Future import exclusions</h2><p class="muted small">Removing a rule stops future exclusions; previously removed transactions can be restored from history.</p>
      <div class="list">${exclusions.map(r=>`<div><span class="grow"><b>${esc(r.merchant_key)}</b><div class="small muted">${esc(r.account_name)} · ${esc(r.direction)} · ${money(r.amount_minor)}</div></span><button class="btn sm danger" data-exclusion-del="${r.id}">Remove</button></div>`).join('')||'<p class="muted small">No exclusion rules.</p>'}</div></div>
    <div class="card" style="margin-bottom:16px"><h2>Linked non-personal flows</h2><p class="muted small">Groups are excluded from personal spending and income without altering the source transactions.</p>
      <div class="list">${flows.map(g=>`<div><span class="grow"><b>${esc(g.kind.replaceAll('_',' '))}</b><div class="small muted">${g.transactions.length} transactions · ${g.transactions.map(t=>money(t.amount_minor)).join(', ')}</div></span><button class="btn sm danger" data-flow-del="${g.id}">Unlink</button></div>`).join('')||'<p class="muted small">No linked flows.</p>'}</div></div>
    <div class="card" style="margin-bottom:16px"><h2>Account security</h2><p class="muted small">Change your password using your current password. You will need to sign in again afterwards.</p><button class="btn sm" id="change-password">Change password</button></div>
    <div class="card" style="margin-bottom:16px"><h2 style="margin-bottom:6px">Appearance</h2><div class="seg" id="theme"><button data-t="light">Light</button><button data-t="dark">Dark</button></div></div>
    <div class="card"><h2 style="margin-bottom:6px">Your data</h2><p class="muted small" style="margin-bottom:14px">Everything lives in this app's own database and upload folder. Nothing is shared.</p>
      <div class="row"><a class="btn" href="/api/export.csv" download>Export all as CSV</a><button class="btn danger" id="wipe">Delete all statements &amp; transactions</button><button class="btn danger" id="delacc">Delete my account</button></div></div>`;
  $('#new-card-account').onclick = () => accountEditor();
  $('#imp').onclick = () => openImport();
  $$('[data-rule-cat]').forEach(el => { el.onchange = async () => { try { const rule = classificationRules.find(r=>r.id===+el.dataset.ruleCat); const newCat=cat(+el.value); await api('/classification-rules/'+rule.id,{method:'PATCH',body:{category_id:newCat.id,type:newCat.kind==='income'?'income':newCat.kind==='transfer'?'transfer':'expense'}}); toast('Rule updated'); } catch(e){fail(e);} }; });
  $('#change-password').onclick = () => {
    const m = modal(`<h2>Change password</h2><div id="password-error" role="alert"></div>
      <div class="field"><label for="current-password">Current password</label><input id="current-password" type="password" autocomplete="current-password"></div>
      <div class="field"><label for="new-password">New password (at least 12 characters)</label><input id="new-password" type="password" minlength="12" autocomplete="new-password"></div>
      <div class="field"><label for="confirm-password">Confirm new password</label><input id="confirm-password" type="password" minlength="12" autocomplete="new-password"></div>
      <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="save-password">Change password</button></div>`);
    $('[data-x]', m.el).onclick = () => m.close();
    $('#save-password',m.el).onclick = async () => {
      const password=$('#new-password',m.el).value;
      if (password !== $('#confirm-password',m.el).value) {
        $('#password-error',m.el).innerHTML='<div class="err-box">Passwords do not match.</div>'; return;
      }
      const btn=$('#save-password',m.el); btn.disabled=true;
      try {
        await api('/auth/change-password',{method:'POST',body:{current_password:$('#current-password',m.el).value,new_password:password}});
        m.close(); S.user=null; renderAuth('login'); toast('Password changed. Please sign in again.');
      } catch(e) { $('#password-error',m.el).innerHTML=`<div class="err-box">${esc(e.message)}</div>`; btn.disabled=false; }
    };
  };
  $('#out').onclick = async () => { await api('/auth/logout', { method: 'POST' }); S.user = null; renderAuth(); };
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
  $$('#theme button').forEach((b) => { b.classList.toggle('on', b.dataset.t === cur); b.onclick = () => { setTheme(b.dataset.t); $$('#theme button').forEach((x) => x.classList.toggle('on', x === b)); }; });
  $('#addc').onclick = () => { const m = modal(`<h2>New category</h2><div id="nerr"></div><div class="field"><label for="cn">Name</label><input id="cn" maxlength="40"></div><div class="field"><label for="ck">Type</label><select id="ck"><option value="expense">Spending</option><option value="income">Income</option><option value="savings">Savings</option></select></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="cgo">Create</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#cgo', m.el).onclick = async () => { try { await api('/categories', { method: 'POST', body: { name: $('#cn', m.el).value, kind: $('#ck', m.el).value, color: '#71717A' } }); m.close(); route(); } catch (e) { $('#nerr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } }; };
  $('#wipe').onclick = async () => { if (await confirmBox({ title: 'Delete all statements and transactions?', body: 'This removes every uploaded file and every transaction. Your account, categories, budgets and goals stay. This can’t be undone.', ok: 'Delete everything', danger: true, typed: 'DELETE' })) { try { await api('/data/wipe', { method: 'POST', body: { confirm: 'DELETE' } }); toast('All statements and transactions deleted'); refreshBadge(); route(); } catch (e) { fail(e); } } };
  $('#delacc').onclick = () => { const m = modal(`<h2>Delete your account?</h2><p class="muted">This permanently deletes your account, all transactions, uploaded files, budgets and goals. Enter your password to confirm.</p><div id="derr"></div><div class="field" style="margin-top:14px"><label for="dpw">Password</label><input id="dpw" type="password" autocomplete="current-password"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="dgo" style="background:var(--bad)">Delete account</button></div>`); $('[data-x]', m.el).onclick = () => m.close(); $('#dgo', m.el).onclick = async () => { try { await api('/auth/delete-account', { method: 'POST', body: { password: $('#dpw', m.el).value } }); m.close(); S.user = null; renderAuth(); } catch (e) { $('#derr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; } }; };
  main.onclick = async (e) => {
    const sd = e.target.closest('[data-sdel]'), ad = e.target.closest('[data-adel]'), ar = e.target.closest('[data-aren]'), cd = e.target.closest('[data-cdel]');
    const ruleDel = e.target.closest('[data-rule-del]'), exclusionDel = e.target.closest('[data-exclusion-del]'), flowDel = e.target.closest('[data-flow-del]');
    try {
      if (ruleDel) { if (await confirmBox({title:'Remove classification rule?',body:'Future imports will no longer use this rule.',ok:'Remove',danger:true})) {await api('/classification-rules/'+ruleDel.dataset.ruleDel,{method:'DELETE'});route();} }
      else if (exclusionDel) { if (await confirmBox({title:'Remove exclusion rule?',body:'Future matching transactions will be imported normally.',ok:'Remove',danger:true})) {await api('/exclusions/'+exclusionDel.dataset.exclusionDel,{method:'DELETE'});route();} }
      else if (flowDel) { if (await confirmBox({title:'Unlink these transactions?',body:'Original classifications and review statuses will be restored.',ok:'Unlink'})) {await api('/flows/'+flowDel.dataset.flowDel,{method:'DELETE'});route();} }
      else if (sd) {
        const m = modal(`<h2>Delete this statement?</h2><p class="muted">The uploaded file will be deleted. What about the transactions imported from it?</p><div class="foot" style="flex-direction:column;align-items:stretch"><button class="btn" id="k">Delete the file, keep the transactions</button><button class="btn danger" id="a">Delete the file and its transactions</button><button class="btn ghost" data-x>Cancel</button></div>`);
        $('[data-x]', m.el).onclick = () => m.close();
        $('#k', m.el).onclick = async () => { await api(`/statements/${sd.dataset.sdel}`, { method: 'DELETE' }); m.close(); toast('File deleted'); route(); };
        $('#a', m.el).onclick = async () => { await api(`/statements/${sd.dataset.sdel}?transactions=true`, { method: 'DELETE' }); m.close(); toast('File and transactions deleted'); refreshBadge(); route(); };
      } else if (ad) { if (await confirmBox({ title: `Delete “${ad.dataset.n}”?`, body: 'This also deletes its statements and transactions. This can’t be undone.', ok: 'Delete account', danger: true })) { await api('/accounts/' + ad.dataset.adel, { method: 'DELETE' }); refreshBadge(); route(); } }
      else if (ar) { accountEditor(accs.find(a=>a.id===+ar.dataset.aren)); }
      else if (cd) { if (await confirmBox({ title: `Delete “${cd.dataset.n}”?`, body: +cd.dataset.u ? `${cd.dataset.u} transaction(s) in this category go back to your review queue.` : 'Nothing is using it.', ok: 'Delete', danger: true })) { await api('/categories/' + cd.dataset.cdel, { method: 'DELETE' }); await loadRef(); refreshBadge(); route(); } }
    } catch (er) { fail(er); }
  };
};

/* Daily calendar, reusing the existing transaction editor. */
routes.calendar = async (main, [initial]) => {
  let day = /^\d{4}-\d{2}-\d{2}$/.test(initial || '') ? initial : todayIso();
  async function draw(){
    const r=await api('/transactions?'+new URLSearchParams({from:day,to:day,sort:'date_desc',limit:'200'}));
    main.innerHTML='<div class="head"><h1>Calendar</h1></div><div class="card flat"><div class="row" id="day-controls"></div></div><div class="card" style="margin-top:16px"><h2>'+fdate(day)+' · '+r.total+' transactions</h2><div class="list">'+(r.items.map(txnRow).join('')||'<p class="muted">No transactions for this date.</p>')+'</div></div>';
    $('#day-controls').innerHTML='<button class="btn sm" id="previous-day">←</button><input type="date" id="chosen-day" aria-label="Chosen day" style="flex:1;min-width:150px" value="'+esc(day)+'"><button class="btn sm" id="next-day">→</button><button class="btn sm" id="go-today">Today</button><button class="btn primary sm" id="create-day">+ Add</button>';
    const move=n=>{const d=new Date(day+'T12:00:00');d.setDate(d.getDate()+n);day=[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');draw();};
    $('#previous-day').onclick=()=>move(-1);$('#next-day').onclick=()=>move(1);$('#go-today').onclick=()=>{day=todayIso();draw();};$('#chosen-day').onchange=e=>{day=e.target.value;draw();};$('#create-day').onclick=()=>manualTransaction(day,draw);
    $$('[data-txn]',main).forEach(el=>{el.onclick=()=>openTxn(+el.dataset.txn,draw);el.onkeydown=e=>{if(e.key==='Enter')openTxn(+el.dataset.txn,draw);};});
  } await draw();
};
function manualTransaction(day,done){
 const m=modal('<h2>Add transaction</h2><div id="manual-error"></div><div class="field"><label>Account</label><select id="ma">'+S.accounts.map(a=>'<option value="'+a.id+'">'+esc(a.name)+'</option>').join('')+'</select></div><div class="field"><label>Date</label><input type="date" id="md" value="'+esc(day)+'"></div><div class="field"><label>Amount</label><input id="mv" inputmode="decimal"></div><div class="field"><label>Money direction</label><select id="mdir"><option value="debit">Money out</option><option value="credit">Money in</option></select></div><div class="field"><label>Description</label><input id="mx" maxlength="500"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="msave">Add</button></div>');
 $('[data-x]',m.el).onclick=()=>m.close();$('#msave',m.el).onclick=async()=>{try{await api('/transactions',{method:'POST',body:{account_id:+$('#ma',m.el).value,date:$('#md',m.el).value,amount_minor:toMinor($('#mv',m.el).value),direction:$('#mdir',m.el).value,description:$('#mx',m.el).value}});m.close();refreshBadge();done();}catch(e){$('#manual-error',m.el).textContent=e.message;}};
}

routes.groups = async (main) => {
  async function draw(){
    const [groups,rules]=await Promise.all([api('/groups'),api('/rules')]);
    main.innerHTML='<div class="head"><div><h1>Linked money</h1><p class="sub">Confirm related loans, reimbursements and pass-through payments. They remain in history but do not count as personal income or spending.</p></div><button class="btn primary" id="link-new">+ Link transactions</button></div>'
      +'<div class="card"><h2>Confirmed groups</h2><div class="list">'+(groups.map(g=>'<div style="display:block;width:100%"><div class="row" style="justify-content:space-between"><b>'+esc(g.name)+'</b><button class="btn sm danger" data-delgroup="'+g.id+'">Unlink group</button></div><p class="muted small">'+esc(g.kind.replace('_',' '))+' · In '+money(g.received_minor)+' · Out '+money(g.paid_minor)+' · Unsettled '+money(g.unsettled_minor)+'</p>'
      +g.items.map(t=>'<div class="row small" style="justify-content:space-between"><span>'+fdate(t.date)+' · '+esc(t.merchant||t.description)+' · '+esc(t.account_name)+'</span><span>'+money(t.amount_minor)+' <button class="btn sm ghost" data-unlink="'+g.id+':'+t.id+'">Unlink</button></span></div>').join('')+'<button class="btn sm" data-addgroup="'+g.id+'">Add related transactions</button></div>').join('')||'<p class="muted">No groups linked yet.</p>')+'</div></div>'
      +'<div class="card" style="margin-top:16px"><h2>Saved import rules</h2><div class="list">'
      +rules.exclusions.map(r=>'<div class="row" style="justify-content:space-between"><span class="small">Exclude · '+esc(r.account_name)+' · '+esc(r.merchant_key)+' · '+money(r.amount_minor)+'</span><button class="btn sm danger" data-rule="exclusion:'+r.id+'">Remove rule</button></div>').join('')
      +rules.classifications.map(r=>'<div class="row" style="justify-content:space-between"><span class="small">'+esc(r.account_name)+' · '+esc(r.merchant_key)+' → '+esc(r.category_name)+'</span><button class="btn sm danger" data-rule="classification:'+r.id+'">Remove rule</button></div>').join('')+'</div></div>';
    $('#link-new').onclick=()=>linkDialog(null,draw);
    $$('[data-addgroup]').forEach(b=>b.onclick=()=>linkDialog(+b.dataset.addgroup,draw));
    $$('[data-delgroup]').forEach(b=>b.onclick=async()=>{if(await confirmBox({title:'Unlink group?',body:'Restore original classifications for every member.',ok:'Unlink',danger:true})){await api('/groups/'+b.dataset.delgroup,{method:'DELETE'});draw();}});
    $$('[data-unlink]').forEach(b=>b.onclick=async()=>{const [g,t]=b.dataset.unlink.split(':');await api('/groups/'+g+'/members/'+t,{method:'DELETE'});draw();});
    $$('[data-rule]').forEach(b=>b.onclick=async()=>{const [kind,id]=b.dataset.rule.split(':');await api('/rules/'+kind+'/'+id,{method:'DELETE'});draw();});
  }
  try{await draw();}catch(e){fail(e);}
};
async function linkDialog(groupId,done){
  const m=modal('<h2>'+(groupId?'Add related transactions':'Link related transactions')+'</h2><p class="muted small">Confirm links manually. Suggestions are not automatically excluded from totals.</p><div id="lerror"></div>'
    +(groupId?'':'<div class="field"><label>Group name</label><input id="lname" placeholder="Tatkal ticket for a friend"></div><div class="field"><label>Kind</label><select id="lkind"><option value="pass_through">Pass-through</option><option value="loan">Loan</option><option value="repayment">Repayment</option><option value="transfer">Transfer</option></select></div>')
    +'<div class="field"><label>Search transactions</label><input id="lsearch" type="search" placeholder="Search merchant or amount"></div><div id="lresults" style="max-height:320px;overflow:auto"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="lsave">Confirm links</button></div>');
  $('[data-x]',m.el).onclick=()=>m.close();
  const chosen=new Set();let timer;
  const load=async()=>{
    const [r,groups]=await Promise.all([api('/transactions?'+new URLSearchParams({q:$('#lsearch',m.el).value,limit:100})),api('/groups')]);
    const existing=new Set(groups.flatMap(g=>g.items.map(t=>t.id)));
    $('#lresults',m.el).innerHTML=r.items.filter(t=>!existing.has(t.id)).map(t=>'<label class="check"><input type="checkbox" data-link="'+t.id+'" '+(chosen.has(t.id)?'checked':'')+'><span class="small">'+fdate(t.date)+' · '+esc(t.merchant||t.description.slice(0,48))+' · '+(t.direction==='credit'?'+':'−')+money(t.amount_minor)+' · '+esc(t.account_name)+'</span></label>').join('')||'<p class="muted small">No available matches.</p>';
    $$('[data-link]',m.el).forEach(b=>b.onchange=()=>b.checked?chosen.add(+b.dataset.link):chosen.delete(+b.dataset.link));
  };
  $('#lsearch',m.el).oninput=()=>{clearTimeout(timer);timer=setTimeout(load,250);};
  $('#lsave',m.el).onclick=async()=>{try{
    if(!chosen.size)throw Error('Select transactions to link.');
    if(groupId)await api('/groups/'+groupId+'/members',{method:'POST',body:{ids:[...chosen]}});
    else await api('/groups',{method:'POST',body:{name:$('#lname',m.el).value,kind:$('#lkind',m.el).value,ids:[...chosen]}});
    m.close();toast('Transactions linked');refreshBadge();done();
  }catch(e){$('#lerror',m.el).textContent=e.message;}};
  try{await load();}catch(e){fail(e);}
}

/* ---------- Trip / Person / Custom tags ---------- */
routes.tags = async (main) => {
  const tags = await api('/tags');
  main.innerHTML = `<div class="head"><div><h1>Tags & Trips</h1><p class="sub">Track spending for a trip, person or project without changing its category.</p></div><button id="tag-create" class="btn primary">+ New tag</button></div>
  <div class="grid g2">${tags.map(t => `<div class="card"><div class="row" style="justify-content:space-between"><div><div class="small muted">${esc(t.kind)}</div><h2>${esc(t.name)}</h2></div><b class="num">${money(t.expense_minor)}</b></div><div class="small muted" style="margin-top:8px">${t.transaction_count} linked transaction(s) · Expense total only</div><button class="btn sm" style="margin-top:12px" data-open-tag="${t.id}">View transactions</button></div>`).join('') || '<div class="card">No tags yet. Create a trip, person or other tag and assign it while reviewing a transaction.</div>'}</div>`;
  $('#tag-create').onclick = () => {
    const m = modal('<h2>Create tag</h2><div id="tag-error"></div><div class="field"><label>Name</label><input id="tag-name" maxlength="80" placeholder="e.g. Goa trip"></div><div class="field"><label>Type</label><select id="tag-kind"><option value="trip">Trip</option><option value="person">Person / beneficiary</option><option value="custom">Other</option></select></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="tag-save">Create</button></div>');
    $('[data-x]',m.el).onclick=()=>m.close();
    $('#tag-save',m.el).onclick=async()=>{try{await api('/tags',{method:'POST',body:{name:$('#tag-name',m.el).value,kind:$('#tag-kind',m.el).value}});m.close();route();}catch(e){$('#tag-error',m.el).textContent=e.message;}};
  };
  $$('[data-open-tag]',main).forEach(b=>b.onclick=async()=>{
    try{
      const data=await api('/tags/'+b.dataset.openTag+'/transactions');
      const m=modal('<h2>'+esc(data.tag.name)+'</h2><p class="muted small">All tagged transactions; expense totals exclude transfers.</p><div class="list">'+data.transactions.map(t=>'<div><span class="grow"><b>'+esc(t.merchant||t.description)+'</b><div class="small muted">'+fdate(t.date)+' · '+esc(t.type)+'</div></span><b class="num">'+money(t.amount_minor)+'</b></div>').join('')+'</div><div class="foot"><button class="btn" data-x>Close</button></div>');
      $('[data-x]',m.el).onclick=()=>m.close();
    }catch(e){fail(e);}
  });
};

/* ---------- credit card usage and repayment suggestions ---------- */
routes.cards = async (main) => {
  const current=new Date().toISOString().slice(0,7);
  const draw=async(month=current)=>{
    const data=await api('/credit-cards?month='+encodeURIComponent(month));
    main.innerHTML=`<div class="head"><div><h1>Credit Cards</h1><p class="sub">Monthly spending and possible repayments</p></div><input type="month" id="card-month" value="${esc(month)}" aria-label="Card spending month"></div>
      <div class="grid g2">${data.cards.map(c=>`<section class="card"><h2>${esc(c.name)} ${c.last4?'••'+esc(c.last4):''}</h2>
      <div class="credit-summary">
        <div><span class="small muted">Available credit</span><div class="value">${c.available_credit_minor===null?'Set credit limit':money(c.available_credit_minor)}</div></div>
        <div class="row" style="justify-content:space-between;margin:10px 0"><span class="small muted">Outstanding</span><b>${money(c.outstanding_minor)}</b></div>
        <div class="row" style="justify-content:space-between"><span class="small muted">Credit utilization</span><b>${c.utilization_percent===null?'—':c.utilization_percent+'%'}</b></div>
        <div class="bar" style="margin:8px 0"><i style="width:${Math.min(100,c.utilization_percent||0)}%"></i></div>
        <p class="small muted">Total credit limit: ${c.credit_limit_minor?money(c.credit_limit_minor):'Not set'} · Includes card debits and credits across all imported dates. Actual bank balance may differ.</p>
      </div>
      <div class="small muted" style="margin:12px 0 5px">Spent this month</div><div class="value">${money(c.spent_minor)}</div>
      <p class="muted small">Monthly budget: ${c.monthly_limit_minor?money(c.monthly_limit_minor):'Not set'}${c.usage_percent!==null?' · '+c.usage_percent+'% used':''}</p>
      <div class="bar" style="margin:10px 0"><i style="width:${Math.min(100,c.usage_percent||0)}%"></i></div>
      <h3 style="margin-top:16px">Possible card bill repayments</h3>
      <p class="small muted">Matches require a bank payment description, equal card credit and dates within 3 days. Confirm before classification.</p>
      <div class="list">${c.repayment_suggestions.map(p=>`<div><div class="grow"><b>${money(p.amount_minor)}</b><div class="small muted">${esc(p.date)} · ${esc(p.description)}</div></div><button class="btn sm" data-repayment="${c.id}:${p.bank_txn_id}">Confirm transfer</button></div>`).join('')||'<p class="muted small">No unambiguous repayment matches found. You can still classify a bill payment as Transfer in History.</p>'}</div></section>`).join('')||'<div class="card"><p>Add a Credit Card to start tracking its monthly usage.</p><button class="btn primary" id="add-card-here">+ Add Credit Card</button></div>'}</div>`;
    $('#card-month').onchange=e=>draw(e.target.value);
    const addCard=$('#add-card-here',main); if(addCard) addCard.onclick=()=>accountEditor();
    $$('[data-repayment]',main).forEach(el=>el.onclick=async()=>{
      const [cid,tid]=el.dataset.repayment.split(':');
      if(!await confirmBox({title:'Confirm credit card repayment?',body:'Both the bank payment and card credit will become Transfers, excluded from spending and income totals.',ok:'Confirm transfer'}))return;
      try {await api('/credit-cards/'+cid+'/repayments/'+tid+'/confirm',{method:'POST'});toast('Repayment linked');draw(month);}catch(e){fail(e);}
    });
  };
  await draw();
};
