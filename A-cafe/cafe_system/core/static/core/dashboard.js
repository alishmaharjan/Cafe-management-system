const API = "/api";
const draftItems = [];

const logPanel = document.getElementById("logPanel");
const productSelect = document.getElementById("productSelect");
const draftItemsEl = document.getElementById("draftItems");
const ordersListEl = document.getElementById("ordersList");
const inventoryListEl = document.getElementById("inventoryList");
const overviewCardsEl = document.getElementById("overviewCards");
const salesReportViewEl = document.getElementById("salesReportView");
const inventoryReportViewEl = document.getElementById("inventoryReportView");
const shiftViewEl = document.getElementById("shiftView");
const dayCloseViewEl = document.getElementById("dayCloseView");
const activityLogListEl = document.getElementById("activityLogList");

function log(message) {
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  logPanel.textContent = `${line}\n${logPanel.textContent}`;
}

function activateTab(tabId) {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tabId);
  });
  document.querySelectorAll(".tab-content").forEach((tab) => {
    tab.classList.toggle("active", tab.id === tabId);
  });
}

async function api(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || !payload.success) {
    throw new Error(payload.message || "Request failed");
  }
  return payload.data;
}

function defaultDateRange() {
  const now = new Date();
  const end = now.toISOString().slice(0, 10);
  const startDate = new Date(now);
  startDate.setDate(startDate.getDate() - 6);
  const start = startDate.toISOString().slice(0, 10);
  return { start, end };
}

function reportQuery(start, end) {
  return `?start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`;
}

function setInitialDateInputs() {
  const { start, end } = defaultDateRange();
  [
    "dashboardStartDate",
    "salesStartDate",
    "inventoryStartDate",
    "ordersStartDate",
  ].forEach((id) => {
    document.getElementById(id).value = start;
  });
  [
    "dashboardEndDate",
    "salesEndDate",
    "inventoryEndDate",
    "ordersEndDate",
    "dayCloseDate",
  ].forEach((id) => {
    document.getElementById(id).value = end;
  });
}

function renderKeyValues(container, title, data) {
  const rows = Object.entries(data)
    .map(([k, v]) => `<div><strong>${k}</strong>: ${v}</div>`)
    .join("");
  container.innerHTML = `<h4>${title}</h4>${rows}`;
}

function statusClass(status) {
  const key = (status || "").toLowerCase();
  return `status-${key}`;
}

function renderDraftItems() {
  draftItemsEl.innerHTML = "";
  draftItems.forEach((item, index) => {
    const li = document.createElement("li");
    li.textContent = `${item.product_name} x ${item.qty}`;
    const remove = document.createElement("button");
    remove.textContent = "x";
    remove.onclick = () => {
      draftItems.splice(index, 1);
      renderDraftItems();
    };
    remove.style.marginLeft = "8px";
    li.appendChild(remove);
    draftItemsEl.appendChild(li);
  });
}

async function loadProducts() {
  const products = await api("/products");
  productSelect.innerHTML = products
    .map((p) => `<option value="${p.id}" data-name="${p.name}">${p.name} - ${p.price}</option>`)
    .join("");
  log(`Loaded ${products.length} products`);
}

async function loadOrders(activeOnly = false) {
  const params = new URLSearchParams();
  if (activeOnly) {
    params.set("active_only", "true");
  }
  const q = document.getElementById("orderSearch").value.trim();
  const startDate = document.getElementById("ordersStartDate").value;
  const endDate = document.getElementById("ordersEndDate").value;
  if (q) params.set("q", q);
  if (startDate) params.set("start_date", startDate);
  if (endDate) params.set("end_date", endDate);

  const query = params.toString() ? `?${params.toString()}` : "";
  const orders = await api(`/orders${query}`);
  ordersListEl.innerHTML = orders
    .map((o) => {
      const paid = (o.payments || []).reduce((sum, p) => sum + Number(p.amount || 0), 0);
      const due = Math.max(Number(o.grand_total || 0) - paid, 0).toFixed(2);
      return `<div class="order-row">
        <strong>#${o.id}</strong> ${o.order_no || "-"}
        <span class="badge ${statusClass(o.status)}">${o.status}</span>
        <span class="badge ${statusClass(o.payment_status)}">${o.payment_status}</span>
        <div>Total: ${o.grand_total} | Due: ${due}</div>
        <button type="button" class="select-order-btn" data-order-id="${o.id}" data-due="${due}">Use For Payment</button>
      </div>`;
    })
    .join("");
  log(`Loaded ${orders.length} orders`);
}

async function loadInventory() {
  const ingredients = await api("/inventory/ingredients");
  inventoryListEl.innerHTML = ingredients
    .map(
      (i) =>
        `<div>${i.id}. ${i.name} - ${i.current_qty} ${i.unit} ${i.is_low_stock ? " (LOW)" : ""}</div>`
    )
    .join("");
  log(`Loaded ${ingredients.length} inventory items`);
}

async function loadOverview() {
  try {
    const start = document.getElementById("dashboardStartDate").value;
    const end = document.getElementById("dashboardEndDate").value;
    const data = await api(`/dashboard/overview${reportQuery(start, end)}`);
    overviewCardsEl.innerHTML = `
      <div><strong>Range:</strong> ${data.start_date} to ${data.end_date}</div>
      <div><strong>Gross Sales:</strong> ${data.summary.gross_sales}</div>
      <div><strong>Orders:</strong> ${data.summary.order_count}</div>
      <div><strong>Active Orders:</strong> ${data.active_orders}</div>
      <div><strong>Low Stock Items:</strong> ${data.low_stock_count}</div>
      <div><strong>Current Shift:</strong> ${data.current_shift ? `${data.current_shift.staff_name || "N/A"} @ ${data.current_shift.counter_name || "Counter N/A"}` : "No active shift"}</div>
    `;
  } catch (error) {
    log(error.message);
  }
}

async function loadSalesReport() {
  try {
    const start = document.getElementById("salesStartDate").value;
    const end = document.getElementById("salesEndDate").value;
    const data = await api(`/reports/sales${reportQuery(start, end)}`);
    const topProducts = data.top_products
      .map((p) => `<div>${p.product_name}: qty ${p.total_qty}, revenue ${p.revenue}</div>`)
      .join("");
    salesReportViewEl.innerHTML = `
      <div><strong>Range:</strong> ${data.start_date} to ${data.end_date}</div>
      <div><strong>Gross Sales:</strong> ${data.summary.gross_sales}</div>
      <div><strong>Orders:</strong> ${data.summary.order_count}</div>
      <div><strong>Paid Orders:</strong> ${data.summary.paid_order_count}</div>
      <h4>Top Products</h4>
      ${topProducts || "<div>No data</div>"}
    `;
    log("Sales report loaded");
  } catch (error) {
    log(error.message);
  }
}

async function loadInventoryReport() {
  try {
    const start = document.getElementById("inventoryStartDate").value;
    const end = document.getElementById("inventoryEndDate").value;
    const data = await api(`/reports/inventory${reportQuery(start, end)}`);
    const lowStock = data.low_stock
      .map((i) => `<div>${i.name}: ${i.current_qty}/${i.min_qty_alert} ${i.unit}</div>`)
      .join("");
    const movementSummary = data.movement_summary
      .map((m) => `<div>${m.movement_type}: count ${m.count}, qty ${m.total_qty}</div>`)
      .join("");
    inventoryReportViewEl.innerHTML = `
      <div><strong>Range:</strong> ${data.start_date} to ${data.end_date}</div>
      <h4>Low Stock</h4>
      ${lowStock || "<div>No low stock items</div>"}
      <h4>Movement Summary</h4>
      ${movementSummary || "<div>No movement data</div>"}
    `;
    log("Inventory report loaded");
  } catch (error) {
    log(error.message);
  }
}

async function loadCurrentShift() {
  try {
    const data = await api("/shifts/current");
    if (!data) {
      shiftViewEl.innerHTML = "<div>No active shift</div>";
      return;
    }
    renderKeyValues(shiftViewEl, "Current Shift", data);
    document.getElementById("closeShiftId").value = data.id;
    document.getElementById("shiftStaffName").value = data.staff_name || "";
    document.getElementById("shiftCounterName").value = data.counter_name || "";
    log(`Loaded current shift ${data.id}`);
  } catch (error) {
    log(error.message);
  }
}

async function loadDayClose() {
  try {
    const date = document.getElementById("dayCloseDate").value;
    const data = await api(`/reports/day-close?date=${encodeURIComponent(date)}`);
    renderKeyValues(dayCloseViewEl, "Day Close", data);
    log("Day close report loaded");
  } catch (error) {
    log(error.message);
  }
}

function printReceipt(order) {
  const itemsHtml = (order.items || [])
    .map((it) => `<tr><td>${it.product_name}</td><td>${it.qty}</td><td>${it.line_total}</td></tr>`)
    .join("");
  const html = `
    <html><head><title>Receipt ${order.order_no}</title></head><body>
    <h2>Cafe Receipt</h2>
    <div>Order: ${order.order_no || order.id}</div>
    <div>Status: ${order.status}</div>
    <div>Payment: ${order.payment_status}</div>
    <hr/>
    <table border="1" cellspacing="0" cellpadding="4">
      <tr><th>Item</th><th>Qty</th><th>Total</th></tr>
      ${itemsHtml}
    </table>
    <h3>Grand Total: ${order.grand_total}</h3>
    </body></html>
  `;
  const win = window.open("", "_blank");
  win.document.write(html);
  win.document.close();
  win.focus();
  win.print();
}

function printDayClose(data) {
  const html = `
    <html><head><title>Day Close ${data.date}</title></head><body>
    <h2>Day Close Summary</h2>
    <div>Date: ${data.date}</div>
    <div>Total Orders: ${data.total_orders}</div>
    <div>Paid Orders: ${data.paid_orders}</div>
    <div>Cancelled Orders: ${data.cancelled_orders}</div>
    <div>Gross Sales: ${data.gross_sales}</div>
    <div>Cash: ${data.cash_total}</div>
    <div>Card: ${data.card_total}</div>
    <div>QR: ${data.qr_total}</div>
    </body></html>
  `;
  const win = window.open("", "_blank");
  win.document.write(html);
  win.document.close();
  win.focus();
  win.print();
}

async function loadActivityLogs() {
  try {
    const limit = document.getElementById("activityLimit").value || "50";
    const data = await api(`/dashboard/activity-logs?limit=${encodeURIComponent(limit)}`);
    activityLogListEl.innerHTML = data
      .map((row) => `<div>[${row.type}/${row.action}] ${row.timestamp} - ${row.message}</div>`)
      .join("");
  } catch (error) {
    log(error.message);
  }
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => activateTab(btn.dataset.tab));
});

document.getElementById("addItemBtn").onclick = () => {
  const selected = productSelect.options[productSelect.selectedIndex];
  const qty = Number(document.getElementById("productQty").value || 1);
  if (!selected || qty <= 0) {
    log("Please choose valid product and qty");
    return;
  }
  draftItems.push({
    product_id: Number(selected.value),
    product_name: selected.dataset.name,
    qty,
  });
  renderDraftItems();
};

document.getElementById("createOrderBtn").onclick = async () => {
  try {
    const body = {
      order_type: document.getElementById("orderType").value,
      table_no: document.getElementById("tableNo").value || null,
      auto_confirm: document.getElementById("autoConfirm").checked,
      items: draftItems.map((i) => ({ product_id: i.product_id, qty: i.qty })),
    };
    const created = await api("/orders", { method: "POST", body: JSON.stringify(body) });
    log(`Order ${created.order_no} created with status ${created.status}`);
    draftItems.length = 0;
    renderDraftItems();
    await loadOrders(true);
    await loadInventory();
    await loadOverview();
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("refreshOrdersBtn").onclick = () => loadOrders(true);
document.getElementById("searchOrdersBtn").onclick = () => loadOrders(false);
document.getElementById("refreshInventoryBtn").onclick = loadInventory;
document.getElementById("loadOverviewBtn").onclick = loadOverview;
document.getElementById("loadActivityBtn").onclick = loadActivityLogs;

ordersListEl.addEventListener("click", (event) => {
  const btn = event.target.closest(".select-order-btn");
  if (!btn) return;
  document.getElementById("paymentOrderId").value = btn.dataset.orderId;
  document.getElementById("receiptOrderId").value = btn.dataset.orderId;
  document.getElementById("paymentAmount").value = btn.dataset.due;
  log(`Selected order ${btn.dataset.orderId} for payment`);
});

document.getElementById("addPaymentBtn").onclick = async () => {
  try {
    const orderId = document.getElementById("paymentOrderId").value;
    const body = {
      method: document.getElementById("paymentMethod").value,
      amount: document.getElementById("paymentAmount").value,
    };
    const result = await api(`/orders/${orderId}/payment`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    log(`Payment added for order ${result.order_no}. Payment status: ${result.payment_status}`);
    await loadOrders(true);
    await loadOverview();
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("purchaseBtn").onclick = async () => {
  try {
    const body = {
      ingredient_id: Number(document.getElementById("purchaseIngredientId").value),
      qty: document.getElementById("purchaseQty").value,
      note: "Dashboard purchase entry",
    };
    await api("/inventory/purchase", { method: "POST", body: JSON.stringify(body) });
    log("Inventory purchase recorded");
    await loadInventory();
    await loadOverview();
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("loadSalesReportBtn").onclick = loadSalesReport;
document.getElementById("loadInventoryReportBtn").onclick = loadInventoryReport;
document.getElementById("loadDayCloseBtn").onclick = loadDayClose;

document.getElementById("exportSalesCsvBtn").onclick = () => {
  const start = document.getElementById("salesStartDate").value;
  const end = document.getElementById("salesEndDate").value;
  window.open(`${API}/reports/sales/export${reportQuery(start, end)}`, "_blank");
};

document.getElementById("exportInventoryCsvBtn").onclick = () => {
  const start = document.getElementById("inventoryStartDate").value;
  const end = document.getElementById("inventoryEndDate").value;
  window.open(`${API}/reports/inventory/export${reportQuery(start, end)}`, "_blank");
};

document.getElementById("printReceiptBtn").onclick = async () => {
  try {
    const orderId = document.getElementById("receiptOrderId").value;
    const order = await api(`/orders/${orderId}`);
    printReceipt(order);
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("openShiftBtn").onclick = async () => {
  try {
    const body = {
      staff_name: document.getElementById("shiftStaffName").value,
      counter_name: document.getElementById("shiftCounterName").value,
      opening_cash: document.getElementById("openingCash").value || "0",
    };
    await api("/shifts/open", {
      method: "POST",
      body: JSON.stringify(body),
    });
    log("Shift started");
    await loadCurrentShift();
    await loadOverview();
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("closeShiftBtn").onclick = async () => {
  try {
    const shiftId = document.getElementById("closeShiftId").value;
    const body = {
      closing_cash_actual: document.getElementById("closingCashActual").value || "0",
      notes: document.getElementById("shiftCloseNotes").value,
      staff_name: document.getElementById("shiftStaffName").value,
      counter_name: document.getElementById("shiftCounterName").value,
    };
    await api(`/shifts/${shiftId}/close`, {
      method: "POST",
      body: JSON.stringify(body),
    });
    log(`Shift ${shiftId} closed`);
    await loadCurrentShift();
    await loadDayClose();
    await loadOverview();
  } catch (error) {
    log(error.message);
  }
};

document.getElementById("printDayCloseBtn").onclick = async () => {
  try {
    const date = document.getElementById("dayCloseDate").value;
    const data = await api(`/reports/day-close?date=${encodeURIComponent(date)}`);
    printDayClose(data);
  } catch (error) {
    log(error.message);
  }
};

setInitialDateInputs();
Promise.all([
  loadProducts(),
  loadOrders(true),
  loadInventory(),
  loadOverview(),
  loadSalesReport(),
  loadInventoryReport(),
  loadCurrentShift(),
  loadDayClose(),
  loadActivityLogs(),
]).catch((error) => log(error.message));
