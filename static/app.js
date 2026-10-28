const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const state = {products: [], customers: [], busy: false};
const pageNames = {overview:'Overview', chat:'Chat ledger', inventory:'Inventory', customers:'Customer udhaar', reports:'Daily reports'};
const today = new Date();
$('#todayLabel').textContent = today.toLocaleDateString('en-IN',{weekday:'short',day:'numeric',month:'short',year:'numeric'});
$('#reportDate').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;

async function api(url, options={}) {
  const response = await fetch(url, {headers:{'Content-Type':'application/json', ...(options.headers||{})}, ...options});
  const data = await response.json().catch(()=>({error:'The server returned an invalid response.'}));
  if (!response.ok) throw new Error(data.error || data.message || `Request failed (${response.status})`);
  return data;
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function rupees(paise) {
  return new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',minimumFractionDigits:2}).format((Number(paise)||0)/100);
}
function toast(message, type='') {
  const el=document.createElement('div'); el.className=`toast ${type}`; el.textContent=message; $('#toastRegion').append(el);
  setTimeout(()=>el.remove(),3600);
}
function setPage(name) {
  $$('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${name}`));
  $$('.nav-item').forEach(b=>b.classList.toggle('active',b.dataset.page===name));
  $('#pageTitle').textContent=pageNames[name]||'Overview';
  $('#sidebar').classList.remove('open');
  if(name==='overview') refreshDashboard();
  if(name==='inventory') refreshProducts();
  if(name==='customers') refreshCustomers();
  if(name==='reports') refreshReports();
  if(name==='chat') $('#chatInput').focus();
}
$$('[data-page]').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));
$('#mobileMenu').addEventListener('click',()=>$('#sidebar').classList.toggle('open'));

async function refreshDashboard() {
  try {
    const d=await api('/api/dashboard');
    $('#metricProducts').textContent=d.product_count;
    $('#metricUnits').textContent=Number(d.total_units).toLocaleString('en-IN');
    $('#metricLow').textContent=d.low_stock_count;
    $('#metricCredit').textContent=rupees(d.outstanding_credit_paise);
    $('#lowStockList').innerHTML=d.low_stock_products.length ? d.low_stock_products.slice(0,5).map(p=>`
      <div class="low-item"><div class="item-avatar">${escapeHtml(p.name.slice(0,1).toUpperCase())}</div><div class="low-item-main"><strong>${escapeHtml(p.name)}</strong><small>Minimum ${p.min_stock} ${escapeHtml(p.unit)}</small></div><span class="stock-tag">${p.quantity} left</span></div>`).join('') : '<div class="empty-state">All stocked up. No low-stock items.</div>';
    $('#recentRows').innerHTML=d.recent_transactions.length ? d.recent_transactions.map(t=>`
      <tr><td><div class="product-cell"><span class="product-mini">${escapeHtml(t.product_name.slice(0,1).toUpperCase())}</span><strong>${escapeHtml(t.product_name)}</strong></div></td><td><span class="movement ${escapeHtml(t.action)}">${escapeHtml(t.action.replaceAll('_',' '))}</span></td><td class="${t.quantity_delta>=0?'delta-positive':'delta-negative'}">${t.quantity_delta>0?'+':''}${t.quantity_delta} ${escapeHtml(t.unit)}</td><td>${formatDate(t.created_at)}</td></tr>`).join('') : '<tr><td colspan="4" class="empty-cell">No stock movements yet. Try a chat command to get started.</td></tr>';
  } catch(e){toast(e.message,'error');}
}
function formatDate(v) { const d=new Date(v); return Number.isNaN(d.getTime())?escapeHtml(v):d.toLocaleString('en-IN',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}); }

function addMessage(text, who='assistant', status='') {
  const row=document.createElement('div'); row.className=`message-row ${who==='user'?'user-row':'assistant-row'}`;
  const avatar=who==='user'?'S':'D';
  row.innerHTML=`<div class="message-avatar">${avatar}</div><div class="message-bubble">${status?`<div class="message-status ${status==='error'?'error':''}">${status==='error'?'Not recorded':'✓ Recorded'}</div>`:''}<p>${escapeHtml(text)}</p><span class="message-time">${new Date().toLocaleTimeString('en-IN',{hour:'2-digit',minute:'2-digit'})}</span></div>`;
  $('#conversation').append(row); $('#conversation').scrollTop=$('#conversation').scrollHeight;
}
async function sendChat(message) {
  const text=message.trim(); if(!text||state.busy)return;
  state.busy=true; $('#sendButton').disabled=true; $('#chatInput').value='';
  addMessage(text,'user');
  const pending=document.createElement('div'); pending.className='message-row assistant-row'; pending.innerHTML='<div class="message-avatar">D</div><div class="message-bubble"><p>Checking your ledger…</p></div>'; $('#conversation').append(pending); $('#conversation').scrollTop=$('#conversation').scrollHeight;
  try {
    const result=await api('/api/chat',{method:'POST',body:JSON.stringify({message:text})});
    pending.remove(); addMessage(result.message||'Done.','assistant',result.ok?'success':'error');
    if(result.supplier_message){$('#supplierPanel').hidden=false;$('#supplierText').value=result.supplier_message;}
    await Promise.all([refreshDashboard(),refreshProducts(),refreshCustomers()]);
    if($('#page-reports').classList.contains('active')) await refreshReports();
  } catch(e) {pending.remove();addMessage(e.message,'assistant','error');}
  finally {state.busy=false;$('#sendButton').disabled=false;$('#chatInput').focus();}
}
$('#chatForm').addEventListener('submit',e=>{e.preventDefault();sendChat($('#chatInput').value);});
$('#chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#chatForm').requestSubmit();}});
$$('[data-command]').forEach(b=>b.addEventListener('click',()=>{setPage('chat');sendChat(b.dataset.command);}));
$('#clearChat').addEventListener('click',()=>{$('#conversation').innerHTML='<div class="chat-day">TODAY</div>';addMessage('Visible conversation cleared. Your saved ledger and database history have not been deleted.');});

async function refreshProducts() {
  try {
    const params=new URLSearchParams(); if($('#productSearch').value.trim())params.set('q',$('#productSearch').value.trim()); if($('#lowFilter').checked)params.set('low_stock','1');
    const data=await api('/api/products?'+params.toString()); state.products=data.products;
    $('#productRows').innerHTML=state.products.length?state.products.map(p=>`
      <tr><td><div class="product-cell"><span class="product-mini">${escapeHtml(p.name.slice(0,1).toUpperCase())}</span><div><strong>${escapeHtml(p.name)}</strong><div class="muted-note">${escapeHtml(p.unit)}</div></div></div></td>
      <td><strong>${p.quantity} ${escapeHtml(p.unit)}</strong></td><td>${p.min_stock} ${escapeHtml(p.unit)}</td><td>${p.selling_price?rupees(Math.round(p.selling_price*100)):'—'}</td>
      <td><span class="status-pill ${p.stock_status}">${p.stock_status==='low'?'● Low stock':'● Healthy'}</span></td><td><button class="row-action" data-edit-product="${p.id}">Edit</button></td></tr>`).join(''):'<tr><td colspan="6" class="empty-cell">No products found. Add a product to begin.</td></tr>';
    const options=state.products.map(p=>`<option value="${p.id}">${escapeHtml(p.name)} (${p.quantity} ${escapeHtml(p.unit)})</option>`).join('');
    $('#adjustProduct').innerHTML=options||'<option value="">No products</option>';
  } catch(e){toast(e.message,'error');}
}
$('#productSearch').addEventListener('input',()=>refreshProducts());
$('#lowFilter').addEventListener('change',()=>refreshProducts());
$('#addProductButton').addEventListener('click',()=>$('#productDialog').showModal());
$('#productForm').addEventListener('submit',async e=>{
  e.preventDefault();
  const body={name:$('#newProductName').value,unit:$('#newProductUnit').value,quantity:$('#newProductQty').value,min_stock:$('#newProductMin').value,selling_price:$('#newProductPrice').value,cost_price:$('#newProductCost').value};
  try{await api('/api/products',{method:'POST',body:JSON.stringify(body)});$('#productDialog').close();e.target.reset();$('#newProductUnit').value='units';$('#newProductQty').value='0';$('#newProductMin').value='5';$('#newProductPrice').value='0';$('#newProductCost').value='0';toast('Product added successfully.');await Promise.all([refreshProducts(),refreshDashboard(),refreshReports()]);}
  catch(err){toast(err.message,'error');}
});
$$('[data-close]').forEach(b=>b.addEventListener('click',()=>document.getElementById(b.dataset.close).close()));
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-edit-product]'); if(!b)return;
  const p=state.products.find(x=>x.id===Number(b.dataset.editProduct));if(!p)return;
  const name=prompt('Product name:',p.name);if(name===null)return;
  const unit=prompt('Unit (packets, kg, litres…):',p.unit);if(unit===null)return;
  const min=prompt('Minimum stock threshold:',p.min_stock);if(min===null)return;
  const price=prompt('Selling price in rupees:',p.selling_price);if(price===null)return;
  try{await api(`/api/products/${p.id}`,{method:'PATCH',body:JSON.stringify({name,unit,min_stock:min,selling_price:price})});toast('Product details updated.');await Promise.all([refreshProducts(),refreshDashboard()]);}
  catch(err){toast(err.message,'error');}
});
$('#adjustForm').addEventListener('submit',async e=>{
  e.preventDefault();const id=$('#adjustProduct').value;if(!id){toast('Add a product first.','error');return;}
  try{const r=await api(`/api/products/${id}/adjust`,{method:'POST',body:JSON.stringify({direction:$('#adjustDirection').value,quantity:$('#adjustQuantity').value,reason:$('#adjustReason').value})});toast(`${r.product}: ${r.before} → ${r.after} ${r.unit}`);$('#adjustQuantity').value='';$('#adjustReason').value='';await Promise.all([refreshProducts(),refreshDashboard(),refreshReports()]);}
  catch(err){toast(err.message,'error');}
});

async function refreshCustomers() {
  try {
    const q=$('#customerSearch').value.trim();const d=await api('/api/customers'+(q?'?q='+encodeURIComponent(q):''));state.customers=d.customers;
    $('#customerRows').innerHTML=state.customers.length?state.customers.map(c=>`<tr><td><div class="product-cell"><span class="product-mini">${escapeHtml(c.name.slice(0,1).toUpperCase())}</span><strong>${escapeHtml(c.name)}</strong></div></td><td>${escapeHtml(c.phone||'—')}</td><td>${c.transaction_count}</td><td><strong>${rupees(c.outstanding_balance_paise)}</strong></td><td><button class="row-action" data-customer-history="${c.id}">History</button></td></tr>`).join(''):'<tr><td colspan="5" class="empty-cell">No customers found. Add your first customer.</td></tr>';
    $('#customerTotal').textContent=rupees(state.customers.reduce((sum,c)=>sum+c.outstanding_balance_paise,0));
    const opts=state.customers.map(c=>`<option value="${c.id}">${escapeHtml(c.name)} — ${rupees(c.outstanding_balance_paise)}</option>`).join('');
    $('#creditCustomer').innerHTML=opts||'<option value="">No customers</option>';
  } catch(e){toast(e.message,'error');}
}
$('#customerSearch').addEventListener('input',refreshCustomers);
$('#addCustomerButton').addEventListener('click',()=>$('#customerDialog').showModal());
$('#customerForm').addEventListener('submit',async e=>{
  e.preventDefault();
  try{await api('/api/customers',{method:'POST',body:JSON.stringify({name:$('#newCustomerName').value,phone:$('#newCustomerPhone').value})});$('#customerDialog').close();e.target.reset();toast('Customer added.');await refreshCustomers();}
  catch(err){toast(err.message,'error');}
});
$('#creditForm').addEventListener('submit',async e=>{
  e.preventDefault();
  try{const r=await api('/api/credit',{method:'POST',body:JSON.stringify({customer_id:$('#creditCustomer').value,type:$('#creditType').value,amount:$('#creditAmount').value,description:$('#creditDescription').value})});toast(`Balance updated: ${rupees(r.balance_before_paise)} → ${rupees(r.balance_after_paise)}`);$('#creditAmount').value='';$('#creditDescription').value='';await Promise.all([refreshCustomers(),refreshDashboard(),refreshReports()]);}
  catch(err){toast(err.message,'error');}
});
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-customer-history]');if(!b)return;
  try{const d=await api(`/api/customers/${b.dataset.customerHistory}/transactions`);const c=state.customers.find(x=>x.id===Number(b.dataset.customerHistory));const lines=d.transactions.map(t=>`${formatDate(t.created_at)} — ${t.type.replaceAll('_',' ')} — ${rupees(t.amount_paise)} — balance ${rupees(t.balance_after_paise)}`);alert(`${c?.name||'Customer'} transaction history\n\n${lines.join('\n')||'No credit transactions yet.'}`);}
  catch(err){toast(err.message,'error');}
});

async function refreshReports() {
  try{
    const d=await api('/api/reports/daily?date='+encodeURIComponent($('#reportDate').value));
    const movements=d.inventory_movements||{}, credits=d.credit||{};
    const metric=(label,value,note)=>`<article class="report-stat"><span>${label}</span><strong>${value}</strong><small>${note}</small></article>`;
    $('#reportMetrics').innerHTML=[
      metric('Units sold',movements.sold?.quantity||0,'Recorded on selected date'),
      metric('Units received',movements.received?.quantity||0,'Incoming stock quantity'),
      metric('Damaged / returned',`${movements.damaged?.quantity||0} / ${movements.returned?.quantity||0}`,'Damaged units / returned units'),
      metric('Credit / payments',`${rupees(credits.credit_purchase?.amount_paise||0)} / ${rupees(credits.payment?.amount_paise||0)}`,'Credit added / payments received')
    ].join('');
    $('#reportStockRows').innerHTML=d.stock_overview.map(p=>`<tr><td><strong>${escapeHtml(p.name)}</strong></td><td>${p.quantity} ${escapeHtml(p.unit)}</td><td>${p.min_stock} ${escapeHtml(p.unit)}</td><td><span class="status-pill ${p.quantity<=p.min_stock?'low':'healthy'}">${p.quantity<=p.min_stock?'● Low stock':'● Healthy'}</span></td></tr>`).join('')||'<tr><td colspan="4" class="empty-cell">No inventory available.</td></tr>';
  }catch(e){toast(e.message,'error');}
}
$('#reportDate').addEventListener('change',refreshReports);
$('#supplierMessageButton').addEventListener('click',async()=>{
  try{const d=await api('/api/supplier-message');$('#supplierText').value=d.message;$('#supplierPanel').hidden=false;$('#supplierText').focus();}
  catch(e){toast(e.message,'error');}
});
$('#copySupplier').addEventListener('click',async()=>{
  try{await navigator.clipboard.writeText($('#supplierText').value);$('#copyStatus').textContent='Copied to clipboard.';}
  catch(e){$('#supplierText').select();$('#copyStatus').textContent='Clipboard unavailable; select and copy the text manually.';}
});

Promise.all([refreshDashboard(),refreshProducts(),refreshCustomers(),refreshReports()]);
