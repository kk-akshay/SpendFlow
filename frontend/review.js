/* Review screen: one transaction at a time. Every answer is saved by the server immediately,
   so leaving and coming back resumes at the next unreviewed transaction. */
const KEYS = '1234567890qwertyuiopasdfghjklzxcvbnm'.split('');

routes.review = async (main) => {
  let scope = 'pending';
  let order = localStorage.getItem('spendflow-review-order') === 'asc' ? 'asc' : 'desc';
  let state = null;          // {item, progress}
  let opts = { note: '', recurring: false, similar: false, remember: false, showNote: false };
  let lastUndo = null;
  let busy = false;
  let typeOverride = null;
  let availableTags = [];
  let selectedTagIds = [];
  const loadTags = async () => { try { availableTags = await api('/tags'); } catch { availableTags = []; } };

  const load = async () => { state = await api('/review/next?scope=' + scope + '&order=' + order); draw(); refreshBadge(); };

  const shortcut = (i) => KEYS[i] || '';
  const orderedCats = () => S.cats.filter((c) => c.kind !== 'transfer' || true);

  function progressHtml(p) {
    const done = p.reviewed, total = p.total;
    const pct = total ? Math.round((100 * done) / total) : 0;
    return `<div class="progress"><div class="top"><span><b class="num">${done}</b> of <span class="num">${total}</span> transactions reviewed <b class="review-percent">(${pct}%)</b></span>
      <span>${p.skipped ? `<a href="#" id="toggle-scope">${scope === 'skipped' ? 'Back to main queue' : `${p.skipped} skipped`}</a>` : ''}</span></div>
      <div class="bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><i style="width:${pct}%"></i></div></div>`;
  }

  function draw() {
    const { item, progress: p } = state;
    if (!item) return drawDone(p);
    const t = item.txn, sg = item.suggestion;
    const type = typeOverride || (t.is_refund ? 'refund' : t.type);
    const sgCat = sg && cat(sg.category_id);
    const inflow = t.direction === 'credit';
    main.innerHTML = `<div class="review"><div class="row" style="justify-content:flex-end;margin-bottom:12px"><label class="small">Review order <select id="review-order" style="width:auto"><option value="desc" ${order === 'desc' ? 'selected' : ''}>Newest first</option><option value="asc" ${order === 'asc' ? 'selected' : ''}>Oldest first</option></select></label></div>${progressHtml(p)}
      <div class="stage" id="stage"><div class="swipe-hint r" id="hint-r">${sgCat ? 'ACCEPT' : ''}</div><div class="swipe-hint l" id="hint-l">SKIP</div>
        <article class="tcard enter" id="card" aria-label="Transaction to categorise">
          <div class="kind"><span class="pill ${type === 'transfer' ? '' : inflow ? 'good' : ''}">${typeLabel[type]}</span>
            <button type="button" class="btn sm review-type-btn" id="type-btn" title="Change transaction type" aria-haspopup="dialog">Change type ▾</button></div>
          <div class="review-payee-heading"><div class="merchant">${esc(t.merchant || 'Unknown merchant')}</div><button type="button" class="btn sm" id="edit-payee-name" aria-label="Edit merchant or person name">✎ Edit name</button></div>
          <div class="review-amount-row"><span class="review-direction ${type === 'transfer' ? 'is-transfer' : inflow ? 'is-income' : 'is-expense'}" aria-hidden="true">${type === 'transfer' ? '⇄' : inflow ? '↙' : '↗'}</span><div class="amount num ${type === 'transfer' ? '' : inflow ? 'amount-in' : 'amount-out'}">${type === 'transfer' ? '' : inflow ? '+' : '−'}${money(t.amount_minor)}</div></div>
          <div class="muted review-date-line">${fdate(t.date)}${t.time ? ' · ' + esc(t.time) : ''} · ${esc(t.account_name)}</div>
          ${t.flags.some(f => /date/i.test(f)) ? '<button type="button" class="review-date-warning" id="review-fix-date" aria-label="Check and correct transaction date">⚠ Check date · Edit</button>' : ''}
          <div class="desc" title="As read from your statement. May contain errors.">${esc(t.description || '(no description)')}</div>
          ${t.flags.map((f) => `<div class="flag">⚠ ${esc(f)}</div>`).join('')}
          ${item.pair ? `<div class="flag" style="color:var(--accent)">↔ Matches ${money(item.pair.amount_minor)} in ${esc(item.pair.account_name)} on ${fdate(item.pair.date)}</div>` : ''}
        </article></div>
      <section class="review-prepare">
        <div class="review-prepare-title"><h2>Before you categorize</h2>
          <p>Add optional details first. Choosing a category saves and moves to the next transaction.</p></div>
        <div class="review-tools" role="group" aria-label="Transaction details">
          <button type="button" class="review-tool ${opts.showNote || opts.note ? 'is-selected' : ''}" id="b-note" aria-expanded="${opts.showNote}">
            <span class="review-tool-symbol" aria-hidden="true">✎</span><span class="review-tool-name">Note</span>
            <span class="review-tool-hint">${opts.note ? 'Added' : 'Add details'}</span>
          </button>
          <button type="button" class="review-tool" id="b-split" title="Split amount across categories and save">
            <span class="review-tool-symbol" aria-hidden="true">◫</span><span class="review-tool-name">Split</span>
            <span class="review-tool-hint">Split &amp; save</span>
          </button>
          <button type="button" class="review-tool ${opts.recurring ? 'is-selected' : ''}" id="b-rec" aria-pressed="${opts.recurring}">
            <span class="review-tool-symbol" aria-hidden="true">↻</span><span class="review-tool-name">Recurring</span>
            <span class="review-tool-hint">${opts.recurring ? 'Marked' : 'Mark repeat'}</span>
          </button>
        </div>
        ${opts.showNote ? `<div class="field review-note-field"><label for="note">Transaction note</label><input id="note" placeholder="e.g. Dinner on Goa trip" maxlength="500" value="${esc(opts.note)}"></div>` : ''}
      <div class="field review-tags" style="margin-top:18px">
        <label>Tags (optional) · Trip, person or project</label>
        <div class="row" style="gap:7px">
          ${availableTags.map(tag => `<label class="check small" style="margin:0;padding:6px 10px;border:1px solid var(--line);border-radius:999px"><input type="checkbox" data-tag-id="${tag.id}" ${selectedTagIds.includes(tag.id) ? 'checked' : ''} style="width:16px;height:16px"> ${esc(tag.name)}</label>`).join('')}
          <button class="btn sm" id="create-review-tag" type="button">+ Add tag</button>
        </div>
        <div class="small muted" style="margin-top:6px">Tags don't change whether a transaction counts as an expense, income or loan.</div>
      </div>
        <div class="review-rule-options">
          <label class="review-rule">
            <input type="checkbox" id="remember" ${opts.remember ? 'checked' : ''}>
            <span><strong>Remember this classification</strong><small>Automatically categorize future matches for this merchant and account.</small></span>
          </label>
          ${item.similar_count > 0 ? `<label class="review-rule">
            <input type="checkbox" id="sim" ${opts.similar ? 'checked' : ''}>
            <span><strong>Apply category to ${item.similar_count} similar transaction${item.similar_count > 1 ? 's' : ''}</strong><small>Same merchant and account · category only, not notes or tags.</small></span>
          </label>` : ''}
        </div>
        <div class="review-secondary-actions">
          <button class="btn sm" id="b-skip">Skip for now</button>
          <button class="btn sm ghost" id="b-undo" ${lastUndo ? '' : 'disabled'}>Undo last action</button>
        </div>
      </section>
      <div class="ask">Choose a category to save &amp; continue</div>
      ${sgCat ? `<div class="suggest"><span class="dot" style="background:var(--shade-2);width:14px;height:14px"></span>
        <div class="grow"><b>${esc(sgCat.name)}?</b><span class="small muted">${esc(sg.reason)}</span></div>
        <button class="btn primary" id="accept">Use suggestion <kbd style="margin-left:6px;background:transparent;border-color:rgba(255,255,255,.4);color:inherit">Enter</kbd></button></div>` : ''}
      <div class="cats" role="group" aria-label="Categories">
        ${orderedCats().map((c, i) => `<button class="cat" style="--c:var(--shade-3)" data-id="${c.id}" ${sg && sg.category_id === c.id ? 'data-sg' : ''}><kbd>${shortcut(i)}</kbd><span class="dot"></span>${esc(c.name)}</button>`).join('')}
        <button class="cat" id="newcat" style="--c:var(--muted)"><kbd>+</kbd><span style="font-size:20px;line-height:12px">+</span>New</button></div>
      <div class="keys"><kbd>Enter</kbd> accept suggestion · <kbd>→</kbd> accept / <kbd>←</kbd> skip · category keys shown on buttons</div></div>`;
    wire(item);
  }

  function drawDone(p) {
    if (scope === 'skipped' || !p.skipped) {
      main.innerHTML = `<div class="review">${p.total ? progressHtml(p) : ''}<div class="empty card"><div class="big">${p.total ? '🎉' : '📄'}</div>
        <h2>${p.total ? 'All caught up' : 'No transactions yet'}</h2>
        <p>${p.total ? `You've reviewed ${p.reviewed} transaction${p.reviewed === 1 ? '' : 's'}. New imports will show up here.` : 'Import a bank or Google Pay statement and SpendFlow will walk you through each transaction.'}</p>
        <div class="row" style="justify-content:center">${p.total ? '<a class="btn primary" href="#/dashboard">See your dashboard</a>' : '<button class="btn primary" id="imp">Import a statement</button>'}${scope === 'skipped' ? '<a class="btn" href="#/review" id="toggle-scope">Back to main queue</a>' : ''}</div></div></div>`;
      $('#imp') && ($('#imp').onclick = () => openImport());
      $('#toggle-scope') && ($('#toggle-scope').onclick = (e) => { e.preventDefault(); scope = 'pending'; load(); });
      return;
    }
    main.innerHTML = `<div class="review">${progressHtml(p)}<div class="empty card"><div class="big">✅</div><h2>Main queue finished</h2>
      <p>${p.skipped} transaction${p.skipped === 1 ? ' is' : 's are'} still skipped. Want to take another look?</p>
      <div class="row" style="justify-content:center"><button class="btn primary" id="go-skipped">Review skipped</button><a class="btn" href="#/dashboard">Not now</a></div></div></div>`;
    $('#go-skipped').onclick = () => { scope = 'skipped'; load(); };
    $('#toggle-scope').onclick = (e) => { e.preventDefault(); scope = 'skipped'; load(); };
  }

  async function submit(payload) {
    if (busy || !state.item) return;
    busy = true;
    const t = state.item.txn;
    const card = $('#card');
    card && card.classList.add('out-r');
    try {
      const body = { ...payload, note: opts.note || undefined, recurring: opts.recurring || undefined, remember: !!opts.remember, apply_similar: opts.similar && state.item.similar_count > 0 && !!payload.category_id };
      if (typeOverride) body.type = typeOverride;
      if (body.type==='refund' && !body.category_id && !body.splits) throw Error('Choose an expense category for this refund.');
      if (body.type==='refund' && body.category_id && cat(body.category_id)?.kind!=='expense') throw Error('Choose an expense category for this refund.');
      const r = await api(`/review/${t.id}/categorize?scope=${scope}&order=${order}`, { method: 'POST', body });
      if (selectedTagIds.length) {
        try {
          await api('/transactions/' + t.id + '/tags', { method: 'PUT', body: { tag_ids: selectedTagIds } });
        } catch (tagError) {
          toast('Category saved but tags could not be saved: ' + tagError.message, { err: true });
        }
      }
      selectedTagIds = [];
      lastUndo = r.undo; state = { item: r.item, progress: r.progress }; resetOpts();
      if (r.applied_similar) toast(`Applied to ${r.applied_similar} similar transaction${r.applied_similar > 1 ? 's' : ''} too`, { action: 'Undo', onAction: undo });
      if (body.type==='refund') {
        await openRefundLink(t.id);
        draw();
      } else setTimeout(draw, 160);
    } catch (e) { card && card.classList.remove('out-r'); fail(e); }
    busy = false;
  }
  function resetOpts() { opts = { note: '', recurring: false, similar: false, remember: false, showNote: false }; typeOverride = null; }

  async function skip() {
    if (busy || !state.item) return;
    busy = true;
    const card = $('#card'); card && card.classList.add('out-l');
    try {
      const r = await api(`/review/${state.item.txn.id}/skip?scope=${scope}&order=${order}`, { method: 'POST' });
      selectedTagIds = [];
      lastUndo = r.undo; state = { item: r.item, progress: r.progress }; resetOpts(); setTimeout(draw, 160);
    } catch (e) { card && card.classList.remove('out-l'); fail(e); }
    busy = false;
  }

  async function undo() {
    if (!lastUndo || busy) return;
    busy = true;
    try {
      const r = await api(`/review/restore?scope=${scope}&order=${order}`, { method: 'POST', body: { undo: lastUndo } });
      lastUndo = null; state = { item: r.item, progress: r.progress }; draw();
    } catch (e) { fail(e); }
    busy = false;
  }

  function accept() { const sg = state.item?.suggestion; if (sg) submit({ category_id: sg.category_id }); }

  function wire(item) {
    $('#toggle-scope') && ($('#toggle-scope').onclick = (e) => { e.preventDefault(); scope = scope === 'skipped' ? 'pending' : 'skipped'; load(); });
    $$('.cat[data-id]').forEach((b) => (b.onclick = () => submit({ category_id: +b.dataset.id })));
    $('#accept') && ($('#accept').onclick = accept);
    $('#review-order').onchange = (e) => { order = e.target.value; localStorage.setItem('spendflow-review-order', order); load(); };
    $('#remember').onchange = (e) => { opts.remember = e.target.checked; };
    $$('[data-tag-id]', main).forEach(el => { el.onchange = () => {
      selectedTagIds = $$('[data-tag-id]:checked', main).map(x => +x.dataset.tagId);
    }; });
    $('#create-review-tag').onclick = () => {
      const m = modal('<h2>New transaction tag</h2><div id="tag-error"></div><div class="field"><label>Name</label><input id="new-tag-name" maxlength="80" placeholder="e.g. Goa trip"></div><div class="field"><label>Type</label><select id="new-tag-kind"><option value="trip">Trip</option><option value="person">Person / beneficiary</option><option value="custom">Other</option></select></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="save-new-tag">Add tag</button></div>');
      $('[data-x]', m.el).onclick = () => m.close();
      $('#save-new-tag', m.el).onclick = async () => {
        try {
          const tag = await api('/tags', { method: 'POST', body: { name: $('#new-tag-name', m.el).value, kind: $('#new-tag-kind', m.el).value } });
          if (!selectedTagIds.includes(tag.id)) selectedTagIds.push(tag.id);
          await loadTags(); m.close(); draw();
        } catch (e) { $('#tag-error', m.el).textContent = e.message; }
      };
    };
    $('#edit-payee-name').onclick = () => {
      const t = state.item.txn;
      const remembered = state.item.payee_memory_available;
      const label = state.item.payee_identity_label || '';
      const m = modal(`<h2>Edit transaction name</h2><p class="small muted">Correct the name shown in SpendFlow. The original bank narration stays unchanged.</p>
        <div id="payee-name-error"></div>
        <div class="field"><label for="payee-name-input">Merchant or person name</label><input id="payee-name-input" maxlength="80" value="${esc(t.merchant || '')}" required></div>
        ${remembered ? `<label class="check"><input type="checkbox" id="remember-payee-name"> Remember for future imports matching this reference</label><p class="small muted">${esc(label)} · Only this account's saved rules apply; existing transactions won't be renamed.</p>` :
          '<p class="small muted">No reliable payee identifier was found. You can still correct this transaction individually.</p>'}
        <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="payee-name-save">Save name</button></div>`);
      $('[data-x]', m.el).onclick = () => m.close();
      $('#payee-name-save', m.el).onclick = async () => {
        const name = $('#payee-name-input', m.el).value.trim();
        if (!name) { $('#payee-name-error', m.el).textContent = 'Enter a name.'; return; }
        const button = $('#payee-name-save', m.el);
        button.disabled = true;
        try {
          await api('/review/' + t.id + '/payee-name', { method: 'PATCH',
            body: { name, remember: !!$('#remember-payee-name', m.el)?.checked } });
          m.close();
          await load();
          toast('Name updated');
        } catch (err) { $('#payee-name-error', m.el).textContent = err.message; button.disabled = false; }
      };
    };
    const dateButton = $('#review-fix-date');
    if (dateButton) dateButton.onclick = () => {
      const t = state.item.txn;
      const m = modal(`<h2>Correct transaction date</h2><p class="small muted">Check the date against your statement.</p><div id="review-date-error" role="alert"></div><div class="field"><label for="review-date-input">Transaction date</label><input type="date" id="review-date-input" value="${esc(t.date)}" required></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="review-date-save">Save date</button></div>`);
      $('[data-x]', m.el).onclick = () => m.close();
      $('#review-date-save', m.el).onclick = async () => {
        const date = $('#review-date-input', m.el).value;
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) { $('#review-date-error', m.el).textContent = 'Choose a valid date.'; return; }
        const button = $('#review-date-save', m.el); button.disabled = true;
        try { await api('/transactions/' + t.id, {method:'PATCH', body:{date}}); m.close(); await load(); toast('Date updated'); }
        catch (e) { $('#review-date-error', m.el).textContent = e.message; button.disabled = false; }
      };
    };
    $('#b-skip').onclick = skip; $('#b-undo').onclick = undo;
    $('#b-rec').onclick = () => { opts.recurring = !opts.recurring; draw(); };
    $('#b-note').onclick = () => { opts.showNote = !opts.showNote; draw(); if (opts.showNote) $('#note').focus(); };
    $('#note') && ($('#note').oninput = (e) => { opts.note = e.target.value; });
    $('#review-order') && ($('#review-order').onchange = (e) => { order=e.target.value; localStorage.setItem('tally-review-order',order); load(); });
    $('#remember') && ($('#remember').onchange = (e) => { opts.remember = e.target.checked; });
    $('#sim') && ($('#sim').onchange = (e) => { opts.similar = e.target.checked; });
    $('#b-split').onclick = () => splitDialog(item.txn);
    $('#newcat').onclick = newCategoryDialog;
    $('#type-btn').onclick = typeDialog;
    swipe($('#card'), $('#stage'));
  }

  function typeDialog() {
    const t = state.item.txn;
    const m = modal(`<h2>What kind of transaction is this?</h2><p class="muted small" style="margin-bottom:14px">Transfers between your own accounts are left out of income and spending.</p>
      <div class="grid">${(t.direction==='credit' ? ['income','transfer','refund'] : ['expense','transfer']).map((k) => `<button class="btn" data-k="${k}"><b>${typeLabel[k]}</b></button>`).join('')}</div>`);
    $$('[data-k]', m.el).forEach((b) => (b.onclick = () => {
      typeOverride = b.dataset.k; m.close();
      draw();
    }));
  }

  function splitDialog(t) {
    const exp = S.cats.filter((c) => c.kind !== 'transfer');
    let parts = [{ c: exp[0].id, v: '' }, { c: (exp[1] || exp[0]).id, v: '' }];
    const m = modal(`<h2>Split this transaction</h2><p class="muted small" style="margin-bottom:14px">${esc(t.merchant)} · ${money(t.amount_minor)}. The parts must add up to the total.</p>
      <div id="sp"></div><button class="btn sm" id="addpart" type="button">+ Add part</button><p id="rem" class="small" style="margin-top:12px"></p><div id="sperr"></div>
      <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="spgo">Save split</button></div>`);
    const total = t.amount_minor;
    const rem = () => { const left = total - parts.reduce((a, p) => a + toMinor(p.v), 0); const el = $('#rem', m.el); el.textContent = left === 0 ? 'Adds up ✓' : left > 0 ? `${money(left)} left to assign` : `${money(-left)} over`; el.className = 'small ' + (left === 0 ? 'pos' : 'neg'); return left; };
    const drawParts = () => {
      $('#sp', m.el).innerHTML = parts.map((p, i) => `<div class="row" style="margin-bottom:10px;flex-wrap:nowrap"><select data-c="${i}" aria-label="Category">${exp.map((c) => `<option value="${c.id}" ${c.id === p.c ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select>
        <input data-v="${i}" inputmode="decimal" placeholder="Amount" value="${esc(p.v)}" style="max-width:140px" aria-label="Amount">${parts.length > 2 ? `<button class="btn sm ghost" data-r="${i}" aria-label="Remove">✕</button>` : ''}</div>`).join('');
      $$('[data-c]', m.el).forEach((s) => (s.onchange = () => { parts[+s.dataset.c].c = +s.value; }));
      $$('[data-v]', m.el).forEach((s) => (s.oninput = () => { parts[+s.dataset.v].v = s.value; rem(); }));
      $$('[data-r]', m.el).forEach((s) => (s.onclick = () => { parts.splice(+s.dataset.r, 1); drawParts(); }));
      rem();
    };
    drawParts();
    $('#addpart', m.el).onclick = () => { const left = rem(); parts.push({ c: exp[0].id, v: left > 0 ? (left / 100).toFixed(2) : '' }); drawParts(); };
    $('[data-x]', m.el).onclick = () => m.close();
    $('#spgo', m.el).onclick = async () => {
      if (rem() !== 0) { $('#sperr', m.el).innerHTML = '<div class="err-box">The parts need to add up to the full amount.</div>'; return; }
      m.close(); submit({ splits: parts.map((p) => ({ category_id: p.c, amount_minor: toMinor(p.v) })) });
    };
    const firstAmt = $('[data-v="0"]', m.el); firstAmt.focus();
  }

  function newCategoryDialog() {
    const palette = ['#18181B', '#3F3F46', '#52525B', '#71717A', '#A1A1AA', '#D4D4D8'];
    let color = palette[S.cats.length % palette.length];
    const m = modal(`<h2>New category</h2><div id="nerr"></div><div class="field"><label for="cn">Name</label><input id="cn" maxlength="40" placeholder="e.g. Pets"></div>
      <div class="field"><label>Type</label><div class="seg" id="ck"><button type="button" data-v="expense" class="on">Spending</button><button type="button" data-v="income">Income</button><button type="button" data-v="savings">Savings</button></div></div>
      <div class="field"><label>Colour</label><div class="row">${palette.map((c) => `<button type="button" class="dot" data-col="${c}" aria-label="Colour ${c}" style="background:${c};width:28px;height:28px;border:3px solid ${c === color ? 'var(--text)' : 'transparent'};cursor:pointer"></button>`).join('')}</div></div>
      <div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="cgo">Create &amp; use</button></div>`);
    let kind = 'expense';
    $$('#ck button', m.el).forEach((b) => (b.onclick = () => { kind = b.dataset.v; $$('#ck button', m.el).forEach((x) => x.classList.toggle('on', x === b)); }));
    $$('[data-col]', m.el).forEach((b) => (b.onclick = () => { color = b.dataset.col; $$('[data-col]', m.el).forEach((x) => (x.style.borderColor = x === b ? 'var(--text)' : 'transparent')); }));
    $('[data-x]', m.el).onclick = () => m.close();
    $('#cgo', m.el).onclick = async () => {
      try { const c = await api('/categories', { method: 'POST', body: { name: $('#cn', m.el).value, color, kind } }); await loadRef(); m.close(); draw(); submit({ category_id: c.id }); }
      catch (e) { $('#nerr', m.el).innerHTML = `<div class="err-box">${esc(e.message)}</div>`; }
    };
  }

  /* swipe: right = accept suggestion, left = skip */
  function swipe(card, stage) {
    if (!card) return;
    let x0 = null, dx = 0;
    const hr = $('#hint-r'), hl = $('#hint-l');
    card.addEventListener('pointerdown', (e) => { if (e.target.closest('button,input')) return; x0 = e.clientX; dx = 0; card.classList.add('dragging'); card.setPointerCapture(e.pointerId); });
    card.addEventListener('pointermove', (e) => {
      if (x0 === null) return; dx = e.clientX - x0;
      card.style.transform = `translateX(${dx}px) rotate(${dx / 30}deg)`;
      hr.style.opacity = dx > 0 && state.item.suggestion ? Math.min(dx / 100, 1) : 0; hl.style.opacity = dx < 0 ? Math.min(-dx / 100, 1) : 0;
    });
    const end = () => {
      if (x0 === null) return; card.classList.remove('dragging');
      const d = dx; x0 = null; dx = 0; hr.style.opacity = hl.style.opacity = 0;
      if (d > 110 && state.item.suggestion) { card.style.transform = ''; accept(); }
      else if (d < -110) { card.style.transform = ''; skip(); }
      else { card.style.transform = ''; if (Math.abs(d) > 110) toast('Pick a category to answer, or swipe left to skip.'); }
    };
    card.addEventListener('pointerup', end); card.addEventListener('pointercancel', end);
  }

  function onKey(e) {
    if (!state || !state.item || e.metaKey || e.ctrlKey && e.key !== 'z' || e.altKey) return;
    if (document.querySelector('.scrim')) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName);
    if (typing) { if (e.key === 'Escape') document.activeElement.blur(); if (e.key === 'Enter' && document.activeElement.id === 'note') { e.preventDefault(); document.activeElement.blur(); } return; }
    const k = e.key.toLowerCase();
    if (k === 'enter') { e.preventDefault(); accept(); }
    else if (k === 'arrowright') accept();
    else if (k === 'arrowleft' || k === ' ') { e.preventDefault(); skip(); }
    else if (k === 'backspace' || (e.ctrlKey && k === 'z')) { e.preventDefault(); undo(); }
    else if (k === 'n') { e.preventDefault(); opts.showNote = true; draw(); $('#note').focus(); }
    else if (k === '/') { e.preventDefault(); splitDialog(state.item.txn); }
    else if (k === '.') { opts.recurring = !opts.recurring; draw(); }
    else if (k === '+') { e.preventDefault(); newCategoryDialog(); }
    else { const i = KEYS.indexOf(k); const c = orderedCats()[i]; if (i >= 0 && c) { e.preventDefault(); submit({ category_id: c.id }); } }
  }
  document.addEventListener('keydown', onKey);
  S.cleanup = () => document.removeEventListener('keydown', onKey);
  await loadTags();
  await load();
};
