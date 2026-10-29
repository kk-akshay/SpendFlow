/* Person-based loan tracking; never auto-confirm inferred identities or transactions. */
function personNameDialog(defaultName, callback) {
  const m=modal('<h2>Create person</h2><p class="muted small">This is a contact ledger, not another bank account. Rename the suggested name before creating.</p><div id="person-error"></div><div class="field"><label for="person-name">Person name</label><input id="person-name" maxlength="80" value="'+esc(defaultName||'')+'"></div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="person-save">Create</button></div>');
  $('[data-x]',m.el).onclick=()=>m.close();
  $('#person-save',m.el).onclick=async()=>{
    try{const p=await api('/people',{method:'POST',body:{name:$('#person-name',m.el).value}});m.close();if(callback)await callback(p);else go('#/people');}
    catch(e){$('#person-error',m.el).textContent=e.message;}
  };
}
async function personLinkDialog(txnId,refresh) {
  let suggestion, persons;
  try{[suggestion,persons]=await Promise.all([api('/people/transaction/'+txnId+'/suggestions'),api('/people')]);}
  catch(e){fail(e);return;}
  const options=persons.map(p=>'<option value="'+p.id+'">'+esc(p.name)+'</option>').join('');
  const m=modal('<h2>Track with person</h2><p class="muted small">Names are suggestions only. Confirm the correct person and whether this payment is a loan, repayment, or ordinary payment.</p><div id="person-link-error"></div>'+
    '<div class="small muted">UPI: '+esc(suggestion.upi_ids.join(', ')||'Not detected')+'</div>'+
    '<div class="small muted" style="margin:8px 0">Possible matches: '+esc([...suggestion.exact_people,...suggestion.similar_names].map(p=>p.name).join(', ')||'None')+'</div>'+
    '<div class="field"><label>Person</label><select id="link-person">'+options+'</select></div><button class="btn sm" id="new-person">+ Create & rename person</button>'+
    '<div class="field" style="margin-top:12px"><label>Payment purpose</label><select id="person-role"><option value="lent">I lent money</option><option value="repaid">They repaid me</option><option value="borrowed">I borrowed money</option><option value="paid_back">I paid back a loan</option><option value="other">Ordinary payment (do not change totals)</option></select></div>'+
    '<label class="check"><input type="checkbox" id="save-upi"> Remember detected UPI ID(s) for this person</label>'+
    '<div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="confirm-person-link">Link transaction</button></div>');
  $('[data-x]',m.el).onclick=()=>m.close();
  const current=persons.find(p=>suggestion.exact_people.some(x=>x.id===p.id));
  if(current)$('#link-person',m.el).value=current.id;
  $('#new-person',m.el).onclick=()=>personNameDialog(suggestion.merchant||'',p=>{
    persons.push(p);$('#link-person',m.el).insertAdjacentHTML('beforeend','<option value="'+p.id+'">'+esc(p.name)+'</option>');$('#link-person',m.el).value=p.id;
  });
  $('#confirm-person-link',m.el).onclick=async()=>{
    const pid=+$('#link-person',m.el).value;
    if(!pid){$('#person-link-error',m.el).textContent='Create or choose a person first.';return;}
    if(!await confirmBox({title:'Confirm loan tracking?',body:'Only you can confirm this transaction belongs to the person and selected purpose. Loans will not count as personal income or spending.',ok:'Confirm link'}))return;
    try {
      await api('/people/'+pid+'/transactions',{method:'POST',body:{txn_id:txnId,role:$('#person-role',m.el).value}});
      if($('#save-upi',m.el).checked)for(const id of suggestion.upi_ids){try{await api('/people/'+pid+'/upi',{method:'POST',body:{upi_id:id}});}catch(e){toast(e.message,{err:true});}}
      m.close();toast('Person ledger updated');if(refresh)refresh();
    }catch(e){$('#person-link-error',m.el).textContent=e.message;}
  };
}
routes.people=async main=>{
  async function draw(){
    const people=await api('/people');
    main.innerHTML='<div class="head"><div><h1>People & Loans</h1><p class="sub">Track loans and repayments across multiple UPI IDs. Every transaction stays in its original bank history.</p></div><button class="btn primary" id="add-person">+ Add person</button></div>'+
      '<div class="grid g2">'+(people.map(p=>'<div class="card"><div class="row" style="justify-content:space-between"><h2>'+esc(p.name)+'</h2><button class="btn sm" data-rename="'+p.id+'">Rename</button></div>'+
        '<p class="small muted">Lent '+money(p.lent_minor)+' · Repaid '+money(p.repaid_minor)+' · Borrowed '+money(p.borrowed_minor)+' · Paid back '+money(p.paid_back_minor)+'</p>'+
        '<p><b>'+money(p.owed_to_me_minor)+'</b> net owed to you · <b>'+money(p.i_owe_minor)+'</b> net you owe</p>'+
        '<h3>UPI IDs</h3><div class="list">'+p.upi_ids.map(a=>'<div class="row"><span class="grow small">'+esc(a.upi_id)+'</span><button class="btn sm ghost" data-alias-del="'+p.id+':'+a.id+'">Unlink</button></div>').join('')+'</div>'+
        '<div class="row"><button class="btn sm" data-alias-add="'+p.id+'">+ Add UPI ID</button><button class="btn sm" data-person-find="'+p.id+'">Find payments</button><button class="btn sm danger" data-person-del="'+p.id+'">Remove person</button></div>'+
        '<h3 style="margin-top:12px">Linked transactions</h3><div class="list">'+p.transactions.map(t=>'<div class="row" style="justify-content:space-between"><span class="grow small">'+esc(t.date)+' · '+esc(t.merchant||t.description)+' · '+esc(t.role.replaceAll('_',' '))+'</span><b>'+money(t.amount_minor)+'</b><button class="btn sm ghost" data-person-unlink="'+p.id+':'+t.id+'">Unlink</button></div>').join('')+'</div></div>').join('')||'<div class="card"><p class="muted">No people yet. Open a transaction in History and select Track with person, or add a person here.</p></div>')+'</div>';
    $('#add-person').onclick=()=>personNameDialog('',draw);
    $$('[data-rename]',main).forEach(b=>b.onclick=()=>{const p=people.find(x=>x.id===+b.dataset.rename);const m=modal('<h2>Rename person</h2><input id="rename-person" maxlength="80" value="'+esc(p.name)+'"><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="rename-save">Save</button></div>');$('[data-x]',m.el).onclick=()=>m.close();$('#rename-save',m.el).onclick=async()=>{try{await api('/people/'+p.id,{method:'PATCH',body:{name:$('#rename-person',m.el).value}});m.close();draw();}catch(e){fail(e);}};});
    $$('[data-alias-add]',main).forEach(b=>b.onclick=()=>{const m=modal('<h2>Link UPI ID</h2><p class="muted small">You can link several UPI IDs to one person.</p><input id="upi-input" placeholder="name@bank"><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="upi-save">Link UPI ID</button></div>');$('[data-x]',m.el).onclick=()=>m.close();$('#upi-save',m.el).onclick=async()=>{try{await api('/people/'+b.dataset.aliasAdd+'/upi',{method:'POST',body:{upi_id:$('#upi-input',m.el).value}});m.close();draw();}catch(e){fail(e);}};});
    $$('[data-person-find]',main).forEach(b=>b.onclick=async()=>{
      try{
        const candidates=await api('/people/'+b.dataset.personFind+'/candidates');
        const m=modal('<h2>Related payments</h2><p class="muted small">UPI IDs and similar names are suggestions only. Confirm loan purpose for every payment.</p><div id="candidate-error"></div><div class="list" style="max-height:50vh;overflow:auto">'+
        (candidates.map(t=>'<div class="row"><span class="grow small">'+esc(t.date)+' · '+esc(t.merchant||t.description)+' · '+money(t.amount_minor)+' · '+esc(t.reason)+'</span><select data-candidate-role="'+t.id+'" style="width:auto"><option value="">Not related</option><option value="lent" '+(t.direction==='debit'?'':'disabled')+'>I lent money</option><option value="repaid" '+(t.direction==='credit'?'':'disabled')+'>They repaid me</option><option value="borrowed" '+(t.direction==='credit'?'':'disabled')+'>I borrowed</option><option value="paid_back" '+(t.direction==='debit'?'':'disabled')+'>I paid back</option><option value="other">Ordinary payment</option></select></div>').join('')||'<p class="muted">No related payments found. Add a UPI ID or link manually from History.</p>')+
        '</div><div class="foot"><button class="btn" data-x>Cancel</button><button class="btn primary" id="save-candidates">Link selected</button></div>');
        $('[data-x]',m.el).onclick=()=>m.close();
        $('#save-candidates',m.el).onclick=async()=>{
          const selected=$$('[data-candidate-role]',m.el).filter(e=>e.value);
          if(!selected.length){$('#candidate-error',m.el).textContent='Select at least one payment purpose.';return;}
          if(!await confirmBox({title:'Confirm selected payments?',body:'These will be assigned to this person. Loan payments will be excluded from personal totals without changing source transactions.',ok:'Link payments'}))return;
          try {for(const el of selected) await api('/people/'+b.dataset.personFind+'/transactions',{method:'POST',body:{txn_id:+el.dataset.candidateRole,role:el.value}});m.close();draw();}catch(e){$('#candidate-error',m.el).textContent=e.message;}
        };
      }catch(e){fail(e);}
    });
    $$('[data-alias-del]',main).forEach(b=>b.onclick=async()=>{let [pid,id]=b.dataset.aliasDel.split(':');if(await confirmBox({title:'Unlink UPI ID?',body:'Existing transaction links remain. Future suggestions will no longer use this ID.',ok:'Unlink'})){await api('/people/'+pid+'/upi/'+id,{method:'DELETE'});draw();}});
    $$('[data-person-unlink]',main).forEach(b=>b.onclick=async()=>{let [pid,tid]=b.dataset.personUnlink.split(':');if(await confirmBox({title:'Unlink this transaction?',body:'Restore its previous accounting classification?',ok:'Unlink'})){await api('/people/'+pid+'/transactions/'+tid,{method:'DELETE'});draw();}});
    $$('[data-person-del]',main).forEach(b=>b.onclick=async()=>{if(await confirmBox({title:'Remove person?',body:'All links to this person will be removed and original transaction categories restored; bank transactions will stay.',ok:'Remove person',danger:true})){await api('/people/'+b.dataset.personDel,{method:'DELETE'});draw();}});
  }
  await draw();
};
