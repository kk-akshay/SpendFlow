/* SpendFlow core: API, helpers, router, auth, app shell, import flow. Other screens live in review.js and pages.js. */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const S = { user: null, cats: [], accounts: [], cfg: { currency: 'INR', locale: 'en-IN' }, badge: 0, cleanup: null };

/* ---------- API ---------- */
async function api(path, { method = 'GET', body, form } = {}) {
  const opt = { method, headers: { 'x-requested-with': 'spendflow' }, credentials: 'same-origin' };
  if (form) opt.body = form;
  else if (body !== undefined) { opt.headers['content-type'] = 'application/json'; opt.body = JSON.stringify(body); }
  let res;
  try { res = await fetch('/api' + path, opt); }
  catch { throw new Error("Can't reach the server. Check your connection and try again."); }
  if (res.status === 401 && !path.startsWith('/auth/')) { S.user = null; renderAuth(); throw new Error('Please sign in again.'); }
  const type = res.headers.get('content-type') || '';
  const data = type.includes('json') ? await res.json() : null;
  if (!res.ok) throw new Error((data && data.detail) || 'Something went wrong. Please try again.');
  return data;
}

/* ---------- formatting ---------- */
function money(minor, { sign = false } = {}) {
  const v = (minor || 0) / 100;
  const whole = Math.abs(v - Math.round(v)) < 0.005 || Math.abs(v) >= 1000;
  let s;
  try {
    s = new Intl.NumberFormat(S.cfg.locale, { style: 'currency', currency: S.cfg.currency, minimumFractionDigits: whole ? 0 : 2, maximumFractionDigits: whole ? 0 : 2 }).format(Math.abs(v));
  } catch { s = Math.abs(v).toFixed(2); }
  return (v < 0 ? '−' : sign && v > 0 ? '+' : '') + s;
}
const toMinor = (str) => { const n = parseFloat(String(str).replace(/[^\d.]/g, '')); return Number.isFinite(n) ? Math.round(n * 100) : 0; };
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const fdate = (iso, withYear = true) => { if (!iso) return ''; const [y, m, d] = iso.split('-'); return `${+d} ${MONTHS[+m - 1]}${withYear ? ' ' + y : ''}`; };
const fmonth = (ym, long = true) => { const [y, m] = ym.split('-'); return new Date(+y, +m - 1, 1).toLocaleString('en', { month: long ? 'long' : 'short', year: long ? 'numeric' : undefined }); };
const todayIso = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; };
const typeLabel = { income: 'Income', expense: 'Expense', transfer: 'Transfer' };
const cat = (id) => S.cats.find((c) => c.id === id);
const catDot = (c) => `<span class="dot" style="background:${esc(c?.color || c?.category_color || '#9CA3AF')}"></span>`;

/* ---------- toast / modal ---------- */
function toast(msg, { err = false, action, onAction, ms = 5000 } = {}) {
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.innerHTML = `<span>${esc(msg)}</span>${action ? `<button>${esc(action)}</button>` : ''}`;
  if (action) $('button', el).onclick = () => { el.remove(); onAction && onAction(); };
  const box = $('#toasts');
  while (box.children.length >= 2) box.firstChild.remove();   // never pile up over the card
  box.append(el);
  setTimeout(() => el.remove(), err ? 7000 : Math.min(ms, 4000));
}
const fail = (e) => toast(e.message || String(e), { err: true });

function modal(html, { onClose } = {}) {
  const prev = document.activeElement;
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  scrim.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { scrim.remove(); document.removeEventListener('keydown', onKey, true); prev && prev.focus && prev.focus(); onClose && onClose(); };
  const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.append(scrim);
  const first = $('input,select,textarea,button.primary', scrim); first && first.focus();
  return { el: $('.modal', scrim), close };
}
function confirmBox({ title, body, ok = 'Confirm', danger = false, typed }) {
  return new Promise((resolve) => {
    const m = modal(`<h2>${esc(title)}</h2><p class="muted">${body}</p>
      ${typed ? `<div class="field" style="margin-top:14px"><label>Type ${esc(typed)} to confirm</label><input id="cf" autocomplete="off"></div>` : ''}
      <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn ${danger ? 'primary danger' : 'primary'}" data-ok ${typed ? 'disabled' : ''}>${esc(ok)}</button></div>`, { onClose: () => resolve(false) });
    if (danger) $('[data-ok]', m.el).style.background = 'var(--bad)';
    if (typed) $('#cf', m.el).oninput = (e) => { $('[data-ok]', m.el).disabled = e.target.value !== typed; };
    $('[data-x]', m.el).onclick = () => m.close();
    $('[data-ok]', m.el).onclick = () => { resolve(true); m.close(); };
  });
}

/* ---------- data refresh ---------- */
async function loadRef() {
  [S.cats, S.accounts] = await Promise.all([api('/categories'), api('/accounts')]);
}
async function refreshBadge() {
  try {
    const d = await api('/review/next');
    S.badge = d.progress.pending + d.progress.skipped;
    const b = $('#nav-badge'); if (b) { b.textContent = S.badge; b.hidden = !S.badge; }
  } catch { /* ignore */ }
}

/* ---------- router ---------- */
const routes = {};
function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }
async function route() {
  if (!S.user) return;
  if (S.cleanup) { S.cleanup(); S.cleanup = null; }
  const [name, ...rest] = (location.hash.replace(/^#\/?/, '') || 'dashboard').split('/');
  const fn = routes[name] || routes.dashboard;
  $$('.nav a.item').forEach((a) => a.classList.toggle('on', a.dataset.r === (routes[name] ? name : 'dashboard')));
  const main = $('main');
  main.innerHTML = '<div class="grid g3"><div class="skel" style="height:96px"></div><div class="skel" style="height:96px"></div><div class="skel" style="height:96px"></div></div>';
  try { await fn(main, rest); } catch (e) { main.innerHTML = `<div class="empty"><div class="big">⚠️</div><h2>Couldn't load this page</h2><p>${esc(e.message)}</p><button class="btn primary" onclick="route()">Try again</button></div>`; }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route);

/* ---------- auth ---------- */
function renderAuth(mode = 'login') {
  $('#app').innerHTML = `<div class="auth"><form class="card" id="af" novalidate>
    <div class="brand" style="padding:0 0 18px"><i></i>SpendFlow</div>
    <h1 style="font-size:22px">${mode === 'login' ? 'Welcome back' : 'Create your account'}</h1>
    <p class="muted" style="margin:6px 0 22px">${mode === 'login' ? 'Pick up where you left off.' : 'Understand where your money goes. Your data stays on this server.'}</p>
    <div id="aerr"></div>
    <div class="field"><label for="em">Email</label><input id="em" type="email" autocomplete="email" required></div>
    <div class="field"><label for="pw">Password</label><input id="pw" type="password" autocomplete="${mode === 'login' ? 'current-password' : 'new-password'}" required minlength="8">${mode === 'register' ? '<p class="small muted" style="margin-top:6px">At least 8 characters.</p>' : ''}</div>
    <button class="btn primary" style="width:100%" id="asub">${mode === 'login' ? 'Sign in' : 'Create account'}</button>
    <p class="small muted" style="text-align:center;margin-top:16px">${mode === 'login' ? 'New here?' : 'Already have an account?'} <a href="#" id="aswitch">${mode === 'login' ? 'Create an account' : 'Sign in'}</a></p>
    ${mode === 'login' ? '<p class="small muted" style="text-align:center;margin-top:8px"><a href="#" id="forgot-password">Forgot password?</a></p>' : ''}
  </form></div>`;
  $('#forgot-password') && ($('#forgot-password').onclick = e => { e.preventDefault(); renderPasswordReset(); });
  $('#aswitch').onclick = (e) => { e.preventDefault(); renderAuth(mode === 'login' ? 'register' : 'login'); };
  $('#af').onsubmit = async (e) => {
    e.preventDefault();
    const btn = $('#asub'); btn.disabled = true; btn.textContent = 'One moment…';
    try {
      S.user = await api(`/auth/${mode}`, { method: 'POST', body: { email: $('#em').value, password: $('#pw').value } });
      await boot();
    } catch (er) { $('#aerr').innerHTML = `<div class="err-box" role="alert">${esc(er.message)}</div>`; btn.disabled = false; btn.textContent = mode === 'login' ? 'Sign in' : 'Create account'; }
  };
}

/* ---------- password recovery ---------- */
function renderPasswordReset() {
  $('#app').innerHTML = `<div class="auth"><form class="card" id="reset-form">
    <div class="brand" style="padding:0 0 18px"><i></i>SpendFlow</div>
    <h1 style="font-size:22px">Reset password</h1>
    <p class="muted small" style="margin:8px 0 18px">On the computer running SpendFlow, run <code>python3 -m backend.reset_password_code</code> to generate a one-time code. It expires after 15 minutes.</p>
    <div id="reset-error" role="alert"></div>
    <div class="field"><label for="reset-code">One-time reset code</label><input id="reset-code" required autocomplete="off"></div>
    <div class="field"><label for="reset-pass">New password</label><input id="reset-pass" type="password" required minlength="12" autocomplete="new-password"></div>
    <div class="field"><label for="reset-confirm">Confirm new password</label><input id="reset-confirm" type="password" required minlength="12" autocomplete="new-password"></div>
    <button class="btn primary" style="width:100%" id="reset-submit">Reset password</button>
    <p class="small muted" style="text-align:center;margin-top:14px"><a href="#" id="reset-back">Back to sign in</a></p>
  </form></div>`;
  $('#reset-back').onclick = e => { e.preventDefault(); renderAuth('login'); };
  $('#reset-form').onsubmit = async e => {
    e.preventDefault();
    const password = $('#reset-pass').value;
    if (password !== $('#reset-confirm').value) {
      $('#reset-error').innerHTML = '<div class="err-box">Passwords do not match.</div>';
      return;
    }
    const b = $('#reset-submit'); b.disabled = true;
    try {
      await api('/auth/reset-password', {method:'POST', body:{token:$('#reset-code').value.trim(),new_password:password}});
      renderAuth('login'); toast('Password updated. Please sign in.');
    } catch (err) { $('#reset-error').innerHTML = `<div class="err-box">${esc(err.message)}</div>`; b.disabled = false; }
  };
}

/* ---------- shell ---------- */
const ICON = {
  dashboard: '<path d="M4 13h6V4H4zM14 20h6V4h-6zM4 20h6v-3H4z"/>',
  review: '<rect x="5" y="4" width="14" height="16" rx="3"/><path d="M9 9h6M9 13h4"/>',
  transactions: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18"/>',
  plan: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/>',
};
const svg = (n) => `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[n]}</svg>`;

function renderShell() {
  const items = [['dashboard', 'Home'], ['review', 'Review'], ['transactions', 'History'], ['calendar', 'Calendar'], ['groups', 'Linked money'], ['plan', 'Plan'], ['settings', 'Settings']];
  $('#app').innerHTML = `<nav class="nav" aria-label="Main"><div class="brand"><i></i>SpendFlow</div>
    ${items.map(([r, l]) => `<a class="item" data-r="${r}" href="#/${r}" ${r === 'review' ? '' : ''}>${svg(r)}<span>${l}</span>${r === 'review' ? '<span class="badge" id="nav-badge" hidden></span>' : ''}</a>`).join('')}
    <div class="grow"></div>
    <button class="btn primary desk" id="nav-import">Import statement</button>
    <button class="btn ghost desk" id="nav-theme">Toggle dark mode</button></nav><main id="main"></main>`;
  $('#nav-import').onclick = () => openImport();
  $('#nav-theme').onclick = toggleTheme;
}
function toggleTheme() {
  const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('spendflow-theme', next); } catch { /* ignore */ }
}

async function boot() {
  try { S.cfg = await api('/config'); } catch { /* defaults */ }
  renderShell();
  await loadRef();
  await refreshBadge();
  if (!location.hash) location.hash = '#/dashboard';
  route();
}

/* ---------- import flow ---------- */
function openImport(preset = {}) {
  const m = modal(`<h2>Import statements</h2>
    <p class="muted small" style="margin:-8px 0 16px">Bank statements or Google Pay statements, as PDF or image. You'll check everything before it's saved.</p>
    <div id="ierr"></div>
    <div class="drop" id="drop" tabindex="0" role="button" aria-label="Choose files"><b>Drop files here</b><p class="muted small">or click to choose · PDF, PNG, JPG · up to 15 MB each</p></div>
    <input type="file" id="files" multiple accept="application/pdf,image/png,image/jpeg,image/webp" class="sr">
    <div id="flist" class="small" style="margin:12px 0"></div>
    <div class="field"><label for="iacc">Account</label><select id="iacc"><option value="">Detect automatically</option>
      ${S.accounts.map((a) => `<option value="${a.id}">${esc(a.name)}${a.last4 ? ' ••' + esc(a.last4) : ''}</option>`).join('')}<option value="new">+ New account…</option></select></div>
    <div class="field" id="newacc" hidden><label for="inew">New account name</label><input id="inew" placeholder="e.g. HDFC Savings" maxlength="60"></div>
    <div class="field" id="pwf" hidden><label for="ipw">PDF password</label><input id="ipw" type="password" autocomplete="off"></div>
    ${S.cfg.llm_available ? '<label class="check"><input type="checkbox" id="iai"> Use AI to read it (sends the statement text to Anthropic)</label>' : ''}
    <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="igo" disabled>Read statements</button></div>`);
  let picked = [];
  const render = () => { $('#flist', m.el).innerHTML = picked.map((f) => `<div class="row" style="justify-content:space-between"><span class="ell">${esc(f.name)}</span><span class="muted">${(f.size / 1048576).toFixed(1)} MB</span></div>`).join(''); $('#igo', m.el).disabled = !picked.length; };
  const add = (list) => { picked = [...picked, ...list].slice(0, 10); render(); };
  const drop = $('#drop', m.el), inp = $('#files', m.el);
  drop.onclick = () => inp.click();
  drop.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); inp.click(); } };
  inp.onchange = () => { add([...inp.files]); inp.value = ''; };
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add('over'); };
  drop.ondragleave = () => drop.classList.remove('over');
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove('over'); add([...e.dataTransfer.files]); };
  $('#iacc', m.el).onchange = (e) => { $('#newacc', m.el).hidden = e.target.value !== 'new'; };
  $('[data-x]', m.el).onclick = () => m.close();
  if (preset.files) add(preset.files);
  $('#igo', m.el).onclick = async () => {
    const btn = $('#igo', m.el); btn.disabled = true; btn.textContent = 'Reading… this can take a minute for scans';
    const fd = new FormData();
    picked.forEach((f) => fd.append('files', f));
    const acc = $('#iacc', m.el).value;
    if (acc === 'new') { if (!$('#inew', m.el).value.trim()) { $('#ierr', m.el).innerHTML = '<div class="err-box">Give the new account a name.</div>'; btn.disabled = false; btn.textContent = 'Read statements'; return; } fd.append('new_account_name', $('#inew', m.el).value.trim()); }
    else if (acc) fd.append('account_id', acc);
    if (!$('#pwf', m.el).hidden && $('#ipw', m.el).value) fd.append('pdf_password', $('#ipw', m.el).value);
    if ($('#iai', m.el)?.checked) fd.append('use_ai', 'true');
    try {
      const { results } = await api('/imports', { method: 'POST', form: fd });
      const ok = results.filter((r) => r.ok), bad = results.filter((r) => !r.ok);
      if (bad.some((r) => r.needs_password)) $('#pwf', m.el).hidden = false;
      if (bad.length) $('#ierr', m.el).innerHTML = bad.map((r) => `<div class="err-box" role="alert"><b>${esc(r.filename)}</b><br>${esc(r.error)}</div>`).join('');
      if (ok.length) { picked = picked.filter((f) => bad.some((r) => r.filename === f.name)); m.close(); await loadRef(); go('#/import/' + ok.map((r) => r.statement_id).join(',')); return; }
      picked = picked.filter((f) => !bad.every((r) => r.filename !== f.name)); render();
    } catch (e) { $('#ierr', m.el).innerHTML = `<div class="err-box" role="alert">${esc(e.message)}</div>`; }
    btn.disabled = !picked.length; btn.textContent = 'Read statements';
  };
}

routes.import = async (main, [ids]) => {
  const list = (ids || '').split(',').filter(Boolean);
  let idx = 0;
  const show = async () => {
    const id = list[idx];
    const d = await api('/imports/' + id);
    const { statement: st, summary: sm, rows } = d;
    const keepFlag = sessionStorage.getItem('spendflow-import-review') === '1';
    if (st.status !== 'preview') { go('#/review'); return; }
    const needsLook = rows.filter((r) => r.dup_status || r.flags.some((f) => !f.startsWith('Read with OCR')));
    main.innerHTML = `<div class="head"><div><h1>Check your import</h1><p class="sub">${esc(st.filename)} · ${esc(st.account_name)}${list.length > 1 ? ` · file ${idx + 1} of ${list.length}` : ''}</p></div>
      <div class="row"><button class="btn danger" id="imp-cancel">Discard</button><button class="btn primary" id="imp-ok">Looks right, import ${sm.count - sm.exact_duplicates}</button></div></div>
      <div class="card" style="margin-bottom:16px"><div class="grid g3">
        <div class="stat"><div class="label">Transactions found</div><div class="value">${sm.count}</div></div>
        <div class="stat"><div class="label">Money in</div><div class="value pos">${money(sm.money_in)}</div></div>
        <div class="stat"><div class="label">Money out</div><div class="value">${money(sm.money_out)}</div></div></div>
        <p class="small muted" style="margin-top:12px">${fdate(sm.date_from)} to ${fdate(sm.date_to)} · read with ${esc({ columns: 'column detection', text: 'text matching', gpay: 'Google Pay reader', ai: 'AI' }[st.parser] || st.parser)}</p></div>
      ${st.warnings.map((w) => `<div class="warn-box">${esc(w)}</div>`).join('')}
      <div class="warn-box">Extracted text can be wrong, especially from scans. Compare a few rows with your statement before relying on the numbers. You can fix any row below.</div>
      ${sm.exact_duplicates ? `<div class="warn-box"><b>${sm.exact_duplicates} already imported.</b> These will be skipped automatically.</div>` : ''}
      ${sm.suspected_duplicates ? `<div class="warn-box"><b>${sm.suspected_duplicates} possible duplicates</b> of transactions in another account or statement (for example a bank payment also shown in Google Pay). They're kept out of your totals until you decide.</div>` : ''}
      <div class="card flat"><div class="row" style="justify-content:space-between;margin-bottom:8px"><h2>Transactions</h2>
        <div class="row">${needsLook.length ? `<label class="check small"><input type="checkbox" id="onlyflag"> Only rows needing a look (${needsLook.length})</label>` : ''}<button class="btn sm" id="addrow">+ Add missing row</button></div></div>
        <div class="scroll-x"><table><thead><tr><th>Date</th><th>Description</th><th class="r">Amount</th><th></th></tr></thead><tbody id="rows"></tbody></table></div></div>`;
    const tb = $('#rows');
    const draw = (only) => {
      tb.innerHTML = rows.filter((r) => !only || needsLook.includes(r)).map((r) => {
        const fl = r.flags.filter((f) => !f.startsWith('Read with OCR'));
        const dup = r.dup_status === 'exact' ? `<div class="flag">Already imported${r.dup_info ? ' (' + esc(fdate(r.dup_info.date)) + ', ' + esc(r.dup_info.account_name) + ')' : ''}. Will be skipped.</div>`
          : r.dup_status === 'suspected' ? `<div class="flag">Possible duplicate${r.dup_info ? ' of ' + esc(fdate(r.dup_info.date)) + ' in ' + esc(r.dup_info.account_name) : ''}. <a href="#" data-keep="${r.id}">Import anyway</a></div>` : '';
        return `<tr style="${r.dup_status === 'exact' ? 'opacity:.5' : ''}"><td class="num ell">${fdate(r.date)}</td><td><div class="ell" style="max-width:420px" title="${esc(r.description)}">${esc(r.description || r.merchant)}</div>${fl.map((f) => `<div class="flag">⚠ ${esc(f)}</div>`).join('')}${dup}</td>
          <td class="r num ${r.direction === 'credit' ? 'pos' : ''}">${r.direction === 'credit' ? '+' : '−'}${money(r.amount_minor).replace('−', '')}</td>
          <td class="r" style="white-space:nowrap"><button class="btn sm ghost" data-edit="${r.id}">Edit</button><button class="btn sm ghost danger" data-del="${r.id}" aria-label="Remove row">✕</button></td></tr>`;
      }).join('') || '<tr><td colspan="4" class="muted">No rows.</td></tr>';
    };
    if ($('#onlyflag')) $('#onlyflag').checked = keepFlag;
    draw(keepFlag);
    $('#onlyflag') && ($('#onlyflag').onchange = (e) => { sessionStorage.setItem('spendflow-import-review', e.target.checked ? '1' : '0'); draw(e.target.checked); });
    main.onclick = async (e) => {
      const keep = e.target.closest('[data-keep]'), del = e.target.closest('[data-del]'), ed = e.target.closest('[data-edit]');
      try {
        if (keep) { e.preventDefault(); await api('/imports/rows/' + keep.dataset.keep, { method: 'PATCH', body: { dup_status: 'cleared' } }); show(); }
        else if (del) { if (await confirmBox({ title: 'Remove this row?', body: 'Only this selected preview row is removed.', ok: 'Remove', danger: true })) { await api('/imports/rows/' + del.dataset.del, { method: 'DELETE' }); show(); } }
        else if (ed) editRow(rows.find((r) => r.id == ed.dataset.edit), show);
      } catch (er) { fail(er); }
    };
    $('#addrow').onclick = () => editRow(null, show, id);
    $('#imp-cancel').onclick = async () => { if (await confirmBox({ title: 'Discard this import?', body: 'The uploaded file and its rows will be deleted.', ok: 'Discard', danger: true })) { await api('/statements/' + id, { method: 'DELETE' }); next(true); } };
    $('#imp-ok').onclick = async () => {
      const b = $('#imp-ok'); b.disabled = true; b.textContent = 'Importing…';
      try {
        const r = await api(`/imports/${id}/commit`, { method: 'POST' });
        const bits = [`${r.imported} imported`]; if (r.already_imported) bits.push(`${r.already_imported} already there`); if (r.excluded) bits.push(`${r.excluded} excluded by your rules`); if (r.auto_classified) bits.push(`${r.auto_classified} auto-classified`); if (r.transfers_detected) bits.push(`${r.transfers_detected} looked like transfers between your accounts`);
        toast(bits.join(' · ')); await refreshBadge(); next(false);
      } catch (er) { fail(er); b.disabled = false; b.textContent = 'Try again'; }
    };
  };
  const next = (discarded) => { idx++; if (idx < list.length) show().catch(fail); else go(discarded && idx >= list.length ? '#/dashboard' : '#/review'); };
  await show();
};

function editRow(r, done, statementId) {
  const m = modal(`<h2>${r ? 'Fix this row' : 'Add a missing row'}</h2><div id="eerr"></div>
    <div class="grid g2"><div class="field"><label for="ed">Date</label><input id="ed" type="date" value="${r ? esc(r.date) : todayIso()}"></div>
    <div class="field"><label for="ea">Amount</label><input id="ea" inputmode="decimal" value="${r ? (r.amount_minor / 100).toFixed(2) : ''}"></div></div>
    <div class="field"><label>Direction</label><div class="seg" id="edir"><button type="button" data-v="debit">Money out</button><button type="button" data-v="credit">Money in</button></div></div>
    <div class="field"><label for="ex">Description</label><input id="ex" maxlength="500" value="${r ? esc(r.description) : ''}"></div>
    <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="es">Save</button></div>`);
  let dir = r ? r.direction : 'debit';
  const sync = () => $$('#edir button', m.el).forEach((b) => b.classList.toggle('on', b.dataset.v === dir));
  sync(); $$('#edir button', m.el).forEach((b) => (b.onclick = () => { dir = b.dataset.v; sync(); }));
  $('[data-x]', m.el).onclick = () => m.close();
  $('#es', m.el).onclick = async () => {
    const body = { date: $('#ed', m.el).value, amount_minor: toMinor($('#ea', m.el).value), direction: dir, description: $('#ex', m.el).value };
    if (!body.amount_minor) { $('#eerr', m.el).innerHTML = '<div class="err-box">Enter an amount above zero.</div>'; return; }
    try { await (r ? api('/imports/rows/' + r.id, { method: 'PATCH', body }) : api(`/imports/${statementId}/rows`, { method: 'POST', body })); m.close(); done(); }
    catch (e) { $('#eerr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; }
  };
}

/* ---------- start ---------- */
(async () => {
  try { S.user = await api('/auth/me'); await boot(); } catch { renderAuth(); }
})();
