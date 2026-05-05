'use strict';

// ── State ──────────────────────────────────────────────────────────────────
const pos = {
  selectedTable: null,    // e.g. "T01" or null
  orderType: 'DINE_IN',   // or 'TAKEAWAY'
  orderId: null,
  orderNo: null,
  cartItems: [],          // [{item_id, product_id, name, price, qty, line_total}]
  subtotal: 0,
  taxAmount: 0,
  discountAmount: 0,
  grandTotal: 0,
  tables: [],
  categories: [],
  products: [],
  currentCategoryId: '',
};

// ── Bootstrap modals ──────────────────────────────────────────────────────
let cashModal, fonepayModal, receiptModal, splitModal, creditModal;
document.addEventListener('DOMContentLoaded', () => {
  cashModal     = new bootstrap.Modal(document.getElementById('cashModal'));
  fonepayModal  = new bootstrap.Modal(document.getElementById('fonepayModal'));
  receiptModal  = new bootstrap.Modal(document.getElementById('receiptModal'));
  splitModal    = new bootstrap.Modal(document.getElementById('splitModal'));
  creditModal   = new bootstrap.Modal(document.getElementById('creditModal'));
  init();
});

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  await Promise.all([loadTables(), loadCategories()]);
  await loadProducts('');
  setInterval(loadTables, 20000); // Refresh table status every 20s
}

// ── API helpers ───────────────────────────────────────────────────────────
async function apiGet(path) {
  const res = await fetch(`/api${path}`);
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Request failed');
  return data.data;
}
async function apiPost(path, body) {
  const res = await fetch(`/api${path}`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Request failed');
  return data.data;
}
async function apiPatch(path, body) {
  const res = await fetch(`/api${path}`, {
    method: 'PATCH',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Request failed');
  return data.data;
}
async function apiDelete(path) {
  const res = await fetch(`/api${path}`, {method: 'DELETE'});
  const data = await res.json();
  if (!data.success) throw new Error(data.message || 'Request failed');
  return data.data;
}
function fmtNPR(val) {
  return 'NPR ' + parseFloat(val || 0).toFixed(2);
}

// ── Tables ────────────────────────────────────────────────────────────────
async function loadTables() {
  try {
    pos.tables = await apiGet('/tables');
    renderTableMap();
  } catch (err) {
    document.getElementById('tableGrid').innerHTML =
      '<div class="text-danger small p-2">Failed to load tables</div>';
  }
}

function renderTableMap() {
  const grid = document.getElementById('tableGrid');
  grid.innerHTML = pos.tables.map(t => {
    const occupied = t.status === 'OCCUPIED';
    const selected = pos.selectedTable === t.name && pos.orderType === 'DINE_IN';
    let classes = `table-btn ${occupied ? 'occupied' : 'free'} ${selected ? 'selected' : ''}`;
    return `<button class="${classes}" data-table="${t.name}" data-order-id="${t.order_id || ''}"
              onclick="selectTable('${t.name}', '${t.order_id || ''}')">
      <div class="tname">${t.name}</div>
      <div class="tinfo">${occupied ? (t.order_no || 'Occupied') : 'Free'}</div>
    </button>`;
  }).join('');
  // Update takeaway button
  const tw = document.getElementById('takeawayBtn');
  if (pos.orderType === 'TAKEAWAY') tw.classList.add('selected');
  else tw.classList.remove('selected');
}

async function selectTable(tableName, existingOrderId) {
  pos.selectedTable = tableName;
  pos.orderType = 'DINE_IN';
  renderTableMap();
  updateCartHeader();
  if (existingOrderId) {
    await loadOrderIntoCart(parseInt(existingOrderId));
  } else {
    clearCartState();
  }
  renderCart();
}

function selectTakeaway() {
  pos.selectedTable = null;
  pos.orderType = 'TAKEAWAY';
  clearCartState();
  renderTableMap();
  updateCartHeader();
  renderCart();
}

// ── Categories & Products ─────────────────────────────────────────────────
async function loadCategories() {
  try {
    pos.categories = await apiGet('/categories');
    const bar = document.getElementById('categoryBar');
    const extra = pos.categories.map(c =>
      `<button class="cat-btn" data-cat-id="${c.id}" onclick="selectCategory(this, '${c.id}')">${c.name}</button>`
    ).join('');
    bar.innerHTML = `<button class="cat-btn active" data-cat-id="" onclick="selectCategory(this, '')">All</button>${extra}`;
  } catch (err) { /* silent */ }
}

async function selectCategory(btn, catId) {
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  pos.currentCategoryId = catId;
  await loadProducts(catId);
}

async function loadProducts(catId) {
  try {
    const qs = catId ? `?category_id=${catId}` : '';
    pos.products = await apiGet(`/products${qs}`);
    renderProducts();
  } catch (err) { /* silent */ }
}

function renderProducts() {
  const grid = document.getElementById('productGrid');
  if (!pos.products.length) {
    grid.innerHTML = '<div class="text-muted small p-4">No products in this category. Add them via the Admin panel.</div>';
    return;
  }
  grid.innerHTML = pos.products.map(p =>
    `<div class="prod-card" onclick="addToCart(${p.id}, '${escHtml(p.name)}', ${p.price})">
      <div class="prod-name">${escHtml(p.name)}</div>
      <div class="prod-price">NPR ${parseFloat(p.price).toFixed(2)}</div>
    </div>`
  ).join('');
}

function escHtml(str) {
  return String(str).replace(/[&<>"']/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])
  );
}

// ── Cart ──────────────────────────────────────────────────────────────────
function updateCartHeader() {
  const title = document.getElementById('cartTitle');
  const sub   = document.getElementById('cartSub');
  if (pos.orderType === 'TAKEAWAY') {
    title.textContent = 'Takeaway Order';
    sub.textContent   = pos.orderId ? `Order: ${pos.orderNo}` : 'Add items to start';
  } else if (pos.selectedTable) {
    title.textContent = pos.selectedTable;
    sub.textContent   = pos.orderId ? `Order: ${pos.orderNo}` : 'Add items to start';
  } else {
    title.textContent = 'No table selected';
    sub.textContent   = 'Select a table or takeaway';
  }
}

function clearCartState() {
  pos.orderId       = null;
  pos.orderNo       = null;
  pos.cartItems     = [];
  pos.subtotal      = 0;
  pos.taxAmount     = 0;
  pos.discountAmount = 0;
  pos.grandTotal    = 0;
  document.getElementById('discountInput').value = '';
  updateTotalsDisplay();
  setPayBtnsEnabled(false);
}

async function loadOrderIntoCart(orderId) {
  try {
    const order = await apiGet(`/orders/${orderId}`);
    pos.orderId        = order.id;
    pos.orderNo        = order.order_no;
    pos.subtotal       = parseFloat(order.subtotal);
    pos.taxAmount      = parseFloat(order.tax_amount);
    pos.discountAmount = parseFloat(order.discount_amount);
    pos.grandTotal     = parseFloat(order.grand_total);
    pos.cartItems = order.items
      .filter(i => i.item_status !== 'CANCELLED')
      .map(i => ({
        item_id:    i.item_id,
        product_id: i.product_id,
        name:       i.product_name,
        price:      parseFloat(i.unit_price),
        qty:        i.qty,
        line_total: parseFloat(i.line_total),
      }));
    updateCartHeader();
    updateTotalsDisplay();
    setPayBtnsEnabled(pos.cartItems.length > 0 && order.status !== 'PAID');
  } catch (err) {
    showAlert(err.message);
  }
}

async function addToCart(productId, productName, price) {
  if (!pos.selectedTable && pos.orderType !== 'TAKEAWAY') {
    showAlert('Select a table or Takeaway first.', 'warning');
    return;
  }
  try {
    // Create order if needed
    if (!pos.orderId) {
      const order = await apiPost('/orders', {
        order_type: pos.orderType,
        table_no:   pos.orderType === 'DINE_IN' ? pos.selectedTable : null,
      });
      pos.orderId  = order.id;
      pos.orderNo  = order.order_no;
      updateCartHeader();
      loadTables(); // refresh table map to show occupied
    }
    // Add item
    const resp = await apiPost(`/orders/${pos.orderId}/items`, {product_id: productId, qty: 1});
    // Update local cart
    const existing = pos.cartItems.find(i => i.item_id === resp.item_id);
    if (existing) {
      existing.qty        = resp.qty;
      existing.line_total = parseFloat(resp.line_total);
    } else {
      pos.cartItems.push({
        item_id:    resp.item_id,
        product_id: productId,
        name:       productName,
        price:      parseFloat(resp.unit_price),
        qty:        resp.qty,
        line_total: parseFloat(resp.line_total),
      });
    }
    pos.subtotal   = parseFloat(resp.order_subtotal);
    pos.taxAmount  = parseFloat(resp.order_tax);
    pos.grandTotal = parseFloat(resp.order_total) - pos.discountAmount;
    updateTotalsDisplay();
    renderCart();
    setPayBtnsEnabled(true);
  } catch (err) {
    showAlert(err.message);
  }
}

function renderCart() {
  const container = document.getElementById('cartItems');
  if (!pos.cartItems.length) {
    container.innerHTML = '<div class="cart-empty"><i class="bi bi-cart" style="font-size:2rem;display:block;margin-bottom:8px;"></i>Cart is empty</div>';
    return;
  }
  container.innerHTML = pos.cartItems.map(item => `
    <div class="cart-item" data-item-id="${item.item_id}">
      <div class="cart-item-name">${escHtml(item.name)}</div>
      <div class="qty-control">
        <button class="qty-btn" onclick="changeQty(${item.item_id}, ${item.qty - 1})">−</button>
        <span class="qty-val">${item.qty}</span>
        <button class="qty-btn" onclick="changeQty(${item.item_id}, ${item.qty + 1})">+</button>
      </div>
      <div class="cart-item-price">NPR ${item.line_total.toFixed(2)}</div>
      <button class="qty-btn remove-item-btn" title="Remove item" onclick="removeItem(${item.item_id}, '${escHtml(item.name)}')">
        <i class="bi bi-trash3"></i>
      </button>
    </div>
  `).join('');
}

async function removeItem(itemId, itemName) {
  if (!confirm(`Remove "${itemName}" from the order?`)) return;
  await changeQty(itemId, 0);
}

async function changeQty(itemId, newQty) {
  if (!pos.orderId) return;
  try {
    if (newQty <= 0) {
      const resp = await apiDelete(`/orders/${pos.orderId}/items/${itemId}`);
      pos.cartItems = pos.cartItems.filter(i => i.item_id !== itemId);
      pos.subtotal   = parseFloat(resp.order_subtotal || 0);
      pos.taxAmount  = parseFloat(resp.order_tax || 0);
      pos.grandTotal = Math.max(pos.subtotal + pos.taxAmount - pos.discountAmount, 0);
    } else {
      const resp = await apiPatch(`/orders/${pos.orderId}/items/${itemId}`, {qty: newQty});
      const item = pos.cartItems.find(i => i.item_id === itemId);
      if (item) { item.qty = resp.qty; item.line_total = parseFloat(resp.line_total); }
      pos.subtotal   = parseFloat(resp.order_subtotal);
      pos.taxAmount  = parseFloat(resp.order_tax);
      pos.grandTotal = Math.max(parseFloat(resp.order_total) - pos.discountAmount, 0);
    }
    updateTotalsDisplay();
    renderCart();
    setPayBtnsEnabled(pos.cartItems.length > 0);
    if (!pos.cartItems.length) loadTables();
  } catch (err) { showAlert(err.message); }
}

function applyDiscount() {
  const disc = parseFloat(document.getElementById('discountInput').value) || 0;
  pos.discountAmount = Math.max(0, disc);
  pos.grandTotal     = Math.max(pos.subtotal + pos.taxAmount - pos.discountAmount, 0);
  document.getElementById('cartTotal').textContent = fmtNPR(pos.grandTotal);
}

function updateTotalsDisplay() {
  document.getElementById('cartSubtotal').textContent = fmtNPR(pos.subtotal);
  document.getElementById('cartTax').textContent      = fmtNPR(pos.taxAmount);
  document.getElementById('cartTotal').textContent    = fmtNPR(pos.grandTotal);
}

function setPayBtnsEnabled(enabled) {
  document.getElementById('cashBtn').disabled        = !enabled;
  document.getElementById('fonepayBtn').disabled     = !enabled;
  document.getElementById('splitBtn').disabled       = !enabled;
  document.getElementById('creditBtn').disabled      = !enabled;
  document.getElementById('cancelOrderBtn').disabled = !enabled;
}

// ── Payment core ──────────────────────────────────────────────────────────
// payments = [{method, amount, txn_ref?}, ...]
async function processPayment(payments) {
  if (!pos.orderId) { showAlert('No active order.'); return; }
  try {
    const order = await apiPost(`/orders/${pos.orderId}/checkout`, {
      payments: payments.map(p => ({
        method:  p.method,
        amount:  parseFloat(p.amount).toFixed(2),
        txn_ref: p.txn_ref || '',
        customer_name: p.customer_name || '',
        phone: p.phone || '',
        notes: p.notes || '',
      })),
      discount: pos.discountAmount.toFixed(2),
    });
    showReceipt(order);
    clearCartState();
    pos.orderId   = null;
    pos.orderNo   = null;
    pos.cartItems = [];
    renderCart();
    updateCartHeader();
    setPayBtnsEnabled(false);
    loadTables();
    const label = payments.map(p => p.method).join(' + ');
    showAlert(`Payment successful! Order ${order.order_no} paid via ${label}.`, 'success');
  } catch (err) {
    showAlert(err.message);
  }
}

// ── Cash ─────────────────────────────────────────────────────────────────
function openCashModal() {
  document.getElementById('cashAmountDisplay').textContent = fmtNPR(pos.grandTotal);
  document.getElementById('cashTendered').value = '';
  document.getElementById('changeDisplay').classList.add('d-none');
  cashModal.show();
}

function calcChange() {
  const tendered = parseFloat(document.getElementById('cashTendered').value) || 0;
  const change   = tendered - pos.grandTotal;
  const el       = document.getElementById('changeDisplay');
  if (tendered > 0) {
    el.classList.remove('d-none');
    el.textContent = change >= 0 ? `Change: NPR ${change.toFixed(2)}` : `Short by: NPR ${Math.abs(change).toFixed(2)}`;
    el.style.color = change >= 0 ? '#27ae60' : '#e74c3c';
  } else {
    el.classList.add('d-none');
  }
}

async function confirmCashPayment() {
  const tendered = parseFloat(document.getElementById('cashTendered').value) || 0;
  if (tendered < pos.grandTotal) {
    if (!confirm(`Amount tendered (NPR ${tendered}) is less than total (NPR ${pos.grandTotal.toFixed(2)}). Proceed?`)) return;
  }
  cashModal.hide();
  await processPayment([{method: 'CASH', amount: pos.grandTotal}]);
}

// ── FonePay ───────────────────────────────────────────────────────────────
function openFonepayModal() {
  document.getElementById('fonepayAmountDisplay').textContent = fmtNPR(pos.grandTotal);
  document.getElementById('fonepayTxnRef').value = '';
  fonepayModal.show();
}

async function confirmFonepayPayment() {
  const txnRef = document.getElementById('fonepayTxnRef').value.trim();
  fonepayModal.hide();
  await processPayment([{method: 'FONEPAY', amount: pos.grandTotal, txn_ref: txnRef}]);
}

// ── Split Payment ─────────────────────────────────────────────────────────
function openSplitModal() {
  document.getElementById('splitTotalDisplay').textContent = fmtNPR(pos.grandTotal);
  document.getElementById('splitCashInput').value = '';
  document.getElementById('splitFonepayInput').value = '';
  document.getElementById('splitCreditInput').value = '';
  document.getElementById('splitRemainingAmount').textContent = fmtNPR(pos.grandTotal);
  document.getElementById('splitTxnRef').value = '';
  document.getElementById('splitCashInput').max = pos.grandTotal.toFixed(2);
  document.getElementById('splitFonepayInput').max = pos.grandTotal.toFixed(2);
  document.getElementById('splitCreditInput').max = pos.grandTotal.toFixed(2);
  document.getElementById('splitCreditCustomerName').value = '';
  document.getElementById('splitCreditCustomerPhone').value = '';
  document.getElementById('splitCreditNotes').value = '';
  document.getElementById('splitCreditDetails').style.display = 'none';
  // Populate credit autocomplete list
  try {
    apiGet('/credit/accounts').then(accounts => {
      const dl = document.getElementById('splitCreditCustomerList');
      dl.innerHTML = accounts.map(a => `<option value="${escHtml(a.name)}">`).join('');
    }).catch(() => {});
  } catch (_) {}
  splitModal.show();
}

function calcSplitRemainder() {
  const cash    = Math.max(parseFloat(document.getElementById('splitCashInput').value) || 0, 0);
  const fonepay = Math.max(parseFloat(document.getElementById('splitFonepayInput').value) || 0, 0);
  const credit  = Math.max(parseFloat(document.getElementById('splitCreditInput').value) || 0, 0);
  const remaining = pos.grandTotal - (cash + fonepay + credit);
  document.getElementById('splitRemainingAmount').textContent = fmtNPR(Math.max(remaining, 0));
  document.getElementById('splitRemainingAmount').style.color = remaining <= 0.01 ? '#27ae60' : '#e74c3c';
  document.getElementById('splitCreditDetails').style.display = credit > 0 ? 'block' : 'none';
}

async function confirmSplitPayment() {
  const cash    = Math.max(parseFloat(document.getElementById('splitCashInput').value) || 0, 0);
  const fonepay = Math.max(parseFloat(document.getElementById('splitFonepayInput').value) || 0, 0);
  const credit  = Math.max(parseFloat(document.getElementById('splitCreditInput').value) || 0, 0);
  const txnRef  = document.getElementById('splitTxnRef').value.trim();

  if (cash <= 0 && fonepay <= 0 && credit <= 0) {
    showAlert('Enter at least one amount (Cash / FonePay / Credit).', 'warning'); return;
  }
  const total = cash + fonepay + credit;
  if (total < pos.grandTotal - 0.01) {
    showAlert('Split amounts do not cover the total.', 'warning'); return;
  }
  if (total > pos.grandTotal + 0.01) {
    showAlert('Split amounts exceed the total.', 'warning'); return;
  }

  let creditName = '';
  let creditPhone = '';
  let creditNotes = '';
  if (credit > 0) {
    creditName = document.getElementById('splitCreditCustomerName').value.trim();
    if (!creditName) { showAlert('Credit customer name is required.', 'warning'); return; }
    creditPhone = document.getElementById('splitCreditCustomerPhone').value.trim();
    creditNotes = document.getElementById('splitCreditNotes').value.trim();
  }

  const payments = [];
  if (cash > 0)    payments.push({method: 'CASH',    amount: cash});
  if (fonepay > 0) payments.push({method: 'FONEPAY', amount: fonepay, txn_ref: txnRef});
  if (credit > 0)  payments.push({method: 'CREDIT',  amount: credit, customer_name: creditName, phone: creditPhone, notes: creditNotes});

  splitModal.hide();
  await processPayment(payments);
}

// ── Credit ────────────────────────────────────────────────────────────────
async function openCreditModal() {
  document.getElementById('creditAmountDisplay').textContent = fmtNPR(pos.grandTotal);
  document.getElementById('creditCustomerName').value = '';
  document.getElementById('creditCustomerPhone').value = '';
  document.getElementById('creditNotes').value = '';
  // Populate autocomplete list with existing customers
  try {
    const accounts = await apiGet('/credit/accounts');
    const dl = document.getElementById('creditCustomerList');
    dl.innerHTML = accounts.map(a => `<option value="${escHtml(a.name)}">`).join('');
  } catch (_) {}
  creditModal.show();
}

async function confirmCreditPayment() {
  const name = document.getElementById('creditCustomerName').value.trim();
  if (!name) { showAlert('Customer name is required.', 'warning'); return; }
  const phone = document.getElementById('creditCustomerPhone').value.trim();
  const notes = document.getElementById('creditNotes').value.trim();
  if (!pos.orderId) { showAlert('No active order.'); return; }
  try {
    const order = await apiPost(`/orders/${pos.orderId}/credit`, {
      customer_name: name,
      phone,
      notes,
      amount: pos.grandTotal.toFixed(2),
      discount: pos.discountAmount.toFixed(2),
    });
    creditModal.hide();
    showReceipt(order);
    clearCartState();
    pos.orderId = null; pos.orderNo = null; pos.cartItems = [];
    renderCart(); updateCartHeader(); setPayBtnsEnabled(false); loadTables();
    showAlert(`Credit of NPR ${pos.grandTotal.toFixed(2)} recorded for ${name}.`, 'success');
  } catch (err) { showAlert(err.message); }
}

// ── Cancel Order ──────────────────────────────────────────────────────────
async function cancelCurrentOrder() {
  if (!pos.orderId) return;
  if (!confirm('Cancel this order? This cannot be undone.')) return;
  try {
    await apiPost(`/orders/${pos.orderId}/cancel`, {});
    clearCartState();
    pos.orderId  = null;
    pos.orderNo  = null;
    pos.cartItems = [];
    renderCart();
    updateCartHeader();
    loadTables();
    showAlert('Order cancelled.', 'warning');
  } catch (err) { showAlert(err.message); }
}

// ── Receipt ───────────────────────────────────────────────────────────────
function showReceipt(order) {
  const now = new Date().toLocaleString('en-NP');
  const itemRows = order.items.map(i =>
    `<div style="display:flex;justify-content:space-between;padding:2px 0;border-bottom:1px dashed #ddd;">
      <span>${i.product_name} x${i.qty}</span><span>NPR ${parseFloat(i.line_total).toFixed(2)}</span>
    </div>`
  ).join('');
  const methods = order.payments.map(p => `${p.method}: NPR ${p.amount}`).join(', ');
  document.getElementById('receiptBody').innerHTML = `
    <div style="text-align:center;margin-bottom:12px;">
      <strong style="font-size:1.1rem;">Chiya Garden</strong><br>
      <small>Order: ${order.order_no}</small><br>
      <small>${order.order_type}${order.table_no ? ' — ' + order.table_no : ''}</small><br>
      <small>${now}</small>
    </div>
    <div>${itemRows}</div>
    <div style="margin-top:8px;padding-top:8px;border-top:2px solid #000;">
      <div style="display:flex;justify-content:space-between;"><span>Subtotal</span><span>NPR ${parseFloat(order.subtotal).toFixed(2)}</span></div>
      ${parseFloat(order.tax_amount)>0?`<div style="display:flex;justify-content:space-between;"><span>Tax</span><span>NPR ${parseFloat(order.tax_amount).toFixed(2)}</span></div>`:''}
      ${parseFloat(order.discount_amount)>0?`<div style="display:flex;justify-content:space-between;"><span>Discount</span><span>−NPR ${parseFloat(order.discount_amount).toFixed(2)}</span></div>`:''}
      <div style="display:flex;justify-content:space-between;font-weight:700;font-size:1.05rem;border-top:1px solid #000;margin-top:4px;padding-top:4px;">
        <span>TOTAL</span><span>NPR ${parseFloat(order.grand_total).toFixed(2)}</span>
      </div>
      <div style="margin-top:4px;font-size:.85rem;color:#555;">Paid: ${methods}</div>
    </div>
    <div style="text-align:center;margin-top:12px;font-size:.8rem;color:#888;">Thank you for visiting Chiya Garden!</div>`;
  receiptModal.show();
}

function printReceipt() {
  const content = document.getElementById('receiptBody').innerHTML;
  const w = window.open('', '_blank', 'width=380,height=600');
  w.document.write(`<html><head><title>Receipt</title><style>body{font-family:monospace;padding:16px;font-size:13px;}</style></head><body>${content}</body></html>`);
  w.document.close();
  w.focus();
  w.print();
}
