const API_BASE = "https://errand-concierge-production.up.railway.app";

const thread = document.getElementById("thread");
const composer = document.getElementById("composer");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const sidebar = document.getElementById("sidebar");
const sidebarCollapse = document.getElementById("sidebarCollapse");
const sidebarExpand = document.getElementById("sidebarExpand");
const navButtons = document.querySelectorAll(".nav-item");
const homeView = document.getElementById("homeView");
const featureRow = document.getElementById("featureRow");
const gridView = document.getElementById("gridView");
const gridHeading = document.getElementById("gridHeading");
const errandGrid = document.getElementById("errandGrid");
const integrationsView = document.getElementById("integrationsView");
const googleStatusText = document.getElementById("googleStatusText");
const googleActionBtn = document.getElementById("googleActionBtn");
const newErrandBtn = document.getElementById("newErrandBtn");
const countPending = document.getElementById("countPending");

sidebarCollapse.addEventListener("click", () => {
  sidebar.classList.add("collapsed");
  sidebarExpand.classList.add("visible");
});

sidebarExpand.addEventListener("click", () => {
  sidebar.classList.remove("collapsed");
  sidebarExpand.classList.remove("visible");
});

document.getElementById("todayDate").textContent = new Date().toLocaleDateString(undefined, {
  weekday: "long", month: "long", day: "numeric"
});

function showView(view) {
  homeView.style.display = view === "home" ? "flex" : "none";
  featureRow.style.display = view === "home" ? "grid" : "none";
  gridView.style.display = view === "grid" ? "block" : "none";
  integrationsView.style.display = view === "integrations" ? "block" : "none";
}

navButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    navButtons.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const view = btn.dataset.view;
    showView(view);
    if (view === "grid") {
      loadGrid(btn.dataset.status);
    } else if (view === "integrations") {
      loadGoogleStatus();
    }
  });
});

newErrandBtn.addEventListener("click", () => {
  navButtons.forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav-item[data-view="home"]').classList.add("active");
  showView("home");
  messageInput.focus();
});

function addEntry(who, text, extraClass) {
  const entry = document.createElement("div");
  entry.className = `entry ${extraClass}`;
  entry.innerHTML = `<div class="who">${who}</div><div class="text"></div>`;
  entry.querySelector(".text").textContent = text;
  thread.appendChild(entry);
  thread.scrollTop = thread.scrollHeight;
  return entry;
}

async function sendMessage(message) {
  addEntry("You", message, "user");
  messageInput.value = "";
  sendBtn.disabled = true;

  const thinkingEntry = addEntry("Concierge", "thinking…", "assistant");
  thinkingEntry.querySelector(".text").classList.add("thinking");

  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await res.json();
    thinkingEntry.querySelector(".text").classList.remove("thinking");
    thinkingEntry.querySelector(".text").textContent = data.reply || "Something went wrong.";
  } catch (err) {
    thinkingEntry.querySelector(".text").classList.remove("thinking");
    thinkingEntry.querySelector(".text").textContent = "Couldn't reach the concierge. Is the backend running?";
  }

  sendBtn.disabled = false;
  messageInput.focus();
  refreshPendingCount();
}

composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const msg = messageInput.value.trim();
  if (!msg) return;
  sendMessage(msg);
});

function formatDate(iso) {
  if (!iso) return "";
  return iso.slice(0, 16).replace("T", " ");
}

function statusLabel(status) {
  if (status === "done") return "Done";
  if (status === "cancelled") return "Cancelled";
  return "Pending";
}

async function loadGrid(status) {
  gridHeading.textContent = status === "all" ? "All errands" : status === "trash" ? "Trash" : statusLabel(status) + " errands";
  errandGrid.innerHTML = `<div class="index-empty">Loading…</div>`;
  try {
    if (status === "trash") {
      const res = await fetch(`${API_BASE}/api/errands/trash`);
      const data = await res.json();
      renderTrash(data.errands || []);
      return;
    }
    const res = await fetch(`${API_BASE}/api/errands?status=${status}`);
    const data = await res.json();
    renderGrid(data.errands || []);
  } catch (err) {
    errandGrid.innerHTML = `<div class="index-empty">Couldn't load errands.</div>`;
  }
}

function renderTrash(entries) {
  if (entries.length === 0) {
    errandGrid.innerHTML = `<div class="index-empty">Trash is empty.</div>`;
    return;
  }

  errandGrid.innerHTML = "";
  entries.forEach((t) => {
    const card = document.createElement("div");
    card.className = "grid-card trash";

    let metaBits = [];
    if (t.due) metaBits.push(`<span class="due">was due ${t.due}</span>`);
    metaBits.push(`deleted ${formatDate(t.deleted_at)}`);

    card.innerHTML = `
      <span class="status-badge trash">Deleted</span>
      <p class="grid-card-title">${t.title}</p>
      <div class="grid-card-meta">${metaBits.join(" · ")}</div>
    `;

    errandGrid.appendChild(card);
  });
}

function renderGrid(errands) {
  if (errands.length === 0) {
    errandGrid.innerHTML = `<div class="index-empty">Nothing here yet.</div>`;
    return;
  }

  errandGrid.innerHTML = "";
  errands.forEach((t) => {
    const card = document.createElement("div");
    card.className = `grid-card ${t.status}`;

    let metaBits = [];
    if (t.due) metaBits.push(`<span class="due">due ${t.due}</span>`);
    metaBits.push(`added ${formatDate(t.created_at)}`);
    if (t.completed_at) metaBits.push(`done ${formatDate(t.completed_at)}`);
    if (t.cancelled_at) metaBits.push(`cancelled ${formatDate(t.cancelled_at)}`);

    let actionButtons = "";
    if (t.status === "pending") {
      actionButtons = `
        <button class="action-done">mark done</button>
        <button class="action-cancel">cancel</button>
        <button class="action-delete">delete</button>
      `;
    } else {
      actionButtons = `
        <button class="action-reopen">reopen</button>
        <button class="action-delete">delete</button>
      `;
    }

    card.innerHTML = `
      <span class="status-badge ${t.status}">${statusLabel(t.status)}</span>
      <p class="grid-card-title">${t.title}</p>
      <div class="grid-card-meta">${metaBits.join(" · ")}</div>
      <div class="grid-card-actions">${actionButtons}</div>
    `;

    const doneBtn = card.querySelector(".action-done");
    if (doneBtn) doneBtn.addEventListener("click", async () => {
      await fetch(`${API_BASE}/api/errands/${t.id}/complete`, { method: "POST" });
      loadGrid(currentGridStatus());
      refreshPendingCount();
    });

    const cancelBtn = card.querySelector(".action-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", async () => {
      await fetch(`${API_BASE}/api/errands/${t.id}/cancel`, { method: "POST" });
      loadGrid(currentGridStatus());
      refreshPendingCount();
    });

    const reopenBtn = card.querySelector(".action-reopen");
    if (reopenBtn) reopenBtn.addEventListener("click", async () => {
      await fetch(`${API_BASE}/api/errands/${t.id}/reopen`, { method: "POST" });
      loadGrid(currentGridStatus());
      refreshPendingCount();
    });

    card.querySelector(".action-delete").addEventListener("click", async () => {
      await fetch(`${API_BASE}/api/errands/${t.id}`, { method: "DELETE" });
      loadGrid(currentGridStatus());
      refreshPendingCount();
    });

    errandGrid.appendChild(card);
  });
}

function currentGridStatus() {
  const active = document.querySelector('.nav-item[data-view="grid"].active');
  return active ? active.dataset.status : "pending";
}

async function refreshPendingCount() {
  try {
    const res = await fetch(`${API_BASE}/api/errands?status=pending`);
    const data = await res.json();
    const n = (data.errands || []).length;
    countPending.textContent = n > 0 ? n : "";
  } catch (err) {
    // ignore
  }
}

async function loadGoogleStatus() {
  googleStatusText.textContent = "Checking…";
  googleStatusText.className = "integration-status";
  googleActionBtn.innerHTML = "";
  try {
    const res = await fetch(`${API_BASE}/api/integrations/google/status`);
    const data = await res.json();
    if (data.connected) {
      googleStatusText.textContent = data.email ? `Connected as ${data.email}` : "Connected";
      googleStatusText.classList.add("connected");
      googleActionBtn.innerHTML = `<button class="btn-disconnect" id="googleDisconnectBtn">Disconnect</button>`;
      document.getElementById("googleDisconnectBtn").addEventListener("click", async () => {
        googleActionBtn.innerHTML = "";
        googleStatusText.textContent = "Disconnecting…";
        await fetch(`${API_BASE}/api/integrations/google/disconnect`, { method: "POST" });
        loadGoogleStatus();
      });
    } else {
      googleStatusText.textContent = "Not connected";
      googleActionBtn.innerHTML = `<button class="btn-connect" id="googleConnectBtn">Connect</button>`;
      document.getElementById("googleConnectBtn").addEventListener("click", () => {
        window.location.href = `${API_BASE}/api/integrations/google/connect`;
      });
    }
  } catch (err) {
    googleStatusText.textContent = "Couldn't check status.";
  }
}

refreshPendingCount();

// If Google redirected us back here after connecting, land on the Integrations tab
if (window.location.hash.startsWith("#/integrations")) {
  navButtons.forEach((b) => b.classList.remove("active"));
  document.querySelector('.nav-item[data-view="integrations"]').classList.add("active");
  showView("integrations");
  loadGoogleStatus();
}
