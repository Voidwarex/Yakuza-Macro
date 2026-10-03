// Dashboard logic: devices, commands, enrollment, plan limits + upgrades.
// No inline handlers, so a strict CSP (script-src 'self') can be enforced.

let newKey = "";
let newName = "";

const CSRF = document
    .querySelector('meta[name="csrf-token"]')
    .getAttribute("content");

function api(url, options = {}) {
    const opts = { ...options };
    opts.headers = { ...(opts.headers || {}), "X-CSRF-Token": CSRF };
    return fetch(url, opts);
}

function timeAgo(ts) {
    if (!ts) return "never";
    const s = Math.floor(Date.now() / 1000 - ts);
    if (s < 60) return s + "s ago";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
}

function esc(s) {
    return (s || "").replace(/[&<>"]/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])
    );
}

// Icon per device type (desktop / laptop / server).
function iconFor(kind) {
    if (kind === "server") {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/>
            <line x1="7" y1="6.5" x2="7" y2="6.5"/><line x1="7" y1="17.5" x2="7" y2="17.5"/></svg>`;
    }
    if (kind === "laptop") {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="4" y="5" width="16" height="11" rx="2"/><line x1="2" y1="20" x2="22" y2="20"/></svg>`;
    }
    // desktop / default
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>`;
}

function kindLabel(kind) {
    return { server: "Server", laptop: "Laptop", desktop: "Desktop" }[kind] || "Desktop";
}

function updateMeter() {
    const meter = document.getElementById("usageMeter");
    if (!meter) return;
    const pct = planState.limit ? Math.min(100, (planState.used / planState.limit) * 100) : 0;
    const span = meter.querySelector("span");
    if (span) span.style.width = pct + "%";
    meter.classList.toggle("full", !!planState.at_limit);
}

let planState = { used: 0, limit: 3, at_limit: false };
const expanded = new Set(); // device ids whose card is open (survives refresh)
let previewsRequested = false; // request screen previews once per panel entry

function requestPreview(id) {
    // Ask a device to capture its screen (no-op server-side if it's off there).
    api(`/panel/devices/${id}/screenshot`, { method: "POST" }).catch(() => {});
}

async function loadDevices() {
    let res;
    try {
        res = await fetch("/panel/devices");
    } catch (e) {
        return;
    }
    if (res.redirected || res.status === 401) {
        window.location = "/login";
        return;
    }
    const data = await res.json();
    const devices = data.devices || [];
    planState = data.plan || planState;

    // On first load (entering the panel), request a fresh screen preview from
    // each online device. They upload one on their next poll if enabled.
    if (!previewsRequested) {
        previewsRequested = true;
        devices.filter((d) => d.online).forEach((d) => requestPreview(d.id));
    }

    const usage = document.getElementById("usageText");
    if (usage) usage.textContent = `${planState.used} / ${planState.limit} devices`;
    updateMeter();

    const grid = document.getElementById("grid");
    const empty = document.getElementById("empty");

    if (!devices.length) {
        grid.innerHTML = "";
        empty.style.display = "block";
        return;
    }
    empty.style.display = "none";

    grid.innerHTML = devices
        .map((d) => {
            const pending = d.pending
                ? `<span class="badge">${d.pending} pending</span>`
                : "";
            const cancelBtn = d.pending
                ? `<button class="btn-ghost btn-sm" data-act="cancel" data-id="${d.id}">Cancel</button>`
                : "";
            const kind = d.kind || "desktop";
            const open = expanded.has(String(d.id)) ? "open" : "";
            return `
            <div class="card ${d.online ? "is-online" : ""} ${open}" data-card="${d.id}">
                <div class="card-head" data-toggle="${d.id}" role="button" tabindex="0"
                     aria-expanded="${open ? "true" : "false"}">
                    <div class="device-ident">
                        <span class="dev-icon ${d.online ? "on" : ""}">${iconFor(kind)}</span>
                        <div class="ident-text">
                            <div class="device-name">${esc(d.name)}</div>
                            <span class="status-pill ${d.online ? "online" : ""}">
                                ${d.online ? "Online" : "Offline"} · ${kindLabel(kind)}
                            </span>
                        </div>
                    </div>
                    <div class="head-right">
                        ${pending}
                        <svg class="chevron" width="18" height="18" viewBox="0 0 24 24" fill="none"
                             stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
                             stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
                    </div>
                </div>
                <div class="card-body">
                    <div class="preview">
                        ${d.has_preview
                            ? `<img class="preview-img" alt="Screen preview of ${esc(d.name)}"
                                 src="/panel/devices/${d.id}/screenshot?ts=${d.shot_at || 0}">
                               <div class="preview-cap">Screen · ${timeAgo(d.shot_at)}</div>`
                            : `<div class="preview-none">${d.online
                                ? "No screen preview. Enable it in the listener (allow_screenshots = true)."
                                : "Device offline — no preview."}</div>`}
                    </div>
                    <div class="meta">
                        <div>Last seen: <b>${timeAgo(d.last_seen)}</b></div>
                        <div>IP: <b>${esc(d.last_ip) || "—"}</b></div>
                        <div>System: <b>${esc(d.os_info) || "—"}</b></div>
                    </div>
                    <div class="actions">
                        <button class="btn-red btn-sm" data-act="shutdown" data-id="${d.id}">Shut down</button>
                        <button class="btn-amber btn-sm" data-act="restart" data-id="${d.id}">Restart</button>
                        <button class="btn-sm" data-act="lock" data-id="${d.id}">Lock</button>
                        ${cancelBtn}
                        <button class="btn-ghost btn-sm" data-act="schedule" data-id="${d.id}" data-name="${esc(d.name)}">Schedule</button>
                        <button class="btn-ghost btn-sm" data-act="remove" data-id="${d.id}" data-name="${esc(d.name)}">Remove</button>
                    </div>
                </div>
            </div>`;
        })
        .join("");
}

function toggleCard(id) {
    id = String(id);
    const card = document.querySelector(`.card[data-card="${id}"]`);
    if (!card) return;
    const isOpen = expanded.has(id);
    if (isOpen) { expanded.delete(id); } else { expanded.add(id); }
    card.classList.toggle("open", !isOpen);
    const head = card.querySelector("[data-toggle]");
    if (head) head.setAttribute("aria-expanded", String(!isOpen));
    // Opening an online card refreshes its screen preview.
    if (!isOpen && card.classList.contains("is-online")) requestPreview(id);
}

async function cmd(id, action) {
    const labels = {
        shutdown: "shut down",
        restart: "restart",
        lock: "lock",
        cancel: "cancel the pending command for",
    };
    if (action !== "lock" && action !== "cancel") {
        if (!confirm(`Are you sure you want to ${labels[action]} this device?`)) return;
    }
    const res = await api(`/panel/devices/${id}/command`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
    });
    if (res.ok) loadDevices();
    else alert("Failed to send command.");
}

async function removeDevice(id, name) {
    if (!confirm(`Remove "${name}"? Its API key will stop working.`)) return;
    await api(`/panel/devices/${id}`, { method: "DELETE" });
    loadDevices();
}

// ---- add-device modal ----

function openAddModal() {
    if (planState.at_limit) {
        openUpgradeModal();
        return;
    }
    document.getElementById("addStep1").style.display = "block";
    document.getElementById("addStep2").style.display = "none";
    document.getElementById("deviceName").value = "";
    document.getElementById("addModal").classList.add("show");
    document.getElementById("deviceName").focus();
}

function closeAddModal() {
    document.getElementById("addModal").classList.remove("show");
}

async function createDevice() {
    const name = document.getElementById("deviceName").value.trim();
    if (!name) {
        alert("Please enter a device name.");
        return;
    }
    const res = await api("/panel/devices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
    });
    if (res.status === 402) {
        const data = await res.json();
        closeAddModal();
        alert(data.message || "Device limit reached.");
        openUpgradeModal();
        return;
    }
    if (!res.ok) {
        alert("Failed to create device.");
        return;
    }
    const data = await res.json();
    newKey = data.api_key;
    newName = data.name || name;
    document.getElementById("apiKeyBox").textContent = newKey;
    document.getElementById("addStep1").style.display = "none";
    document.getElementById("addStep2").style.display = "block";
}

function downloadConfig() {
    // Build a ready-to-use config.ini pointed at this server, key pre-filled.
    const body =
        "[listener]\n" +
        "server_url = " + window.location.origin + "\n" +
        "api_key = " + newKey + "\n" +
        "device = " + newName + "\n" +
        "kind = auto\n" +
        "poll_interval = 5\n" +
        "dry_run = false\n" +
        "allow_screenshots = false\n";
    const blob = new Blob([body], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "config.ini";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function copyKey() {
    navigator.clipboard.writeText(newKey).then(
        () => alert("API key copied to clipboard."),
        () => alert("Copy failed — select the key and copy it manually.")
    );
}

function finishAdd() {
    closeAddModal();
    loadDevices();
}

// ---- upgrade / billing ----

function openUpgradeModal() {
    document.getElementById("upgradeModal").classList.add("show");
}
function closeUpgradeModal() {
    document.getElementById("upgradeModal").classList.remove("show");
}

async function pickPlan(plan) {
    const res = await api("/panel/billing/checkout", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plan }),
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.url) {
        window.location = data.url; // Stripe Checkout
    } else {
        alert(data.error || "Could not start checkout.");
    }
}

async function manageBilling() {
    const res = await api("/panel/billing/portal", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.url) window.location = data.url;
    else alert(data.error || "Could not open billing portal.");
}

// ---- schedules ----

const CAN_SCHEDULE = document.body.getAttribute("data-can-schedule") === "true";
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
let schDeviceId = null;

function actionLabel(a) {
    return { shutdown: "Shut down", restart: "Restart", lock: "Lock" }[a] || a;
}

function fmtMinute(m) {
    const h = String(Math.floor(m / 60)).padStart(2, "0");
    const mm = String(m % 60).padStart(2, "0");
    return `${h}:${mm}`;
}

function describeSchedule(s) {
    const act = actionLabel(s.action);
    if (s.kind === "once") {
        const when = s.next_run_at ? new Date(s.next_run_at * 1000).toLocaleString() : "—";
        return `${act} once · ${when}`;
    }
    if (s.kind === "daily") return `${act} daily at ${fmtMinute(s.at_minute)}`;
    if (s.kind === "weekly") return `${act} every ${DAYS[s.weekday]} at ${fmtMinute(s.at_minute)}`;
    return act;
}

async function openScheduleModal(id, name) {
    schDeviceId = id;
    document.getElementById("schDeviceName").textContent = name;
    document.getElementById("schLocked").style.display = CAN_SCHEDULE ? "none" : "block";
    document.getElementById("schBody").style.display = CAN_SCHEDULE ? "block" : "none";
    document.getElementById("scheduleModal").classList.add("show");
    if (CAN_SCHEDULE) loadSchedules();
}

function closeScheduleModal() {
    document.getElementById("scheduleModal").classList.remove("show");
    schDeviceId = null;
}

async function loadSchedules() {
    const res = await fetch(`/panel/devices/${schDeviceId}/schedules`);
    if (!res.ok) return;
    const data = await res.json();
    const list = document.getElementById("schList");
    const items = data.schedules || [];
    if (!items.length) {
        list.innerHTML = `<div class="sch-empty">No schedules yet. Add one below.</div>`;
        return;
    }
    list.innerHTML = items
        .map(
            (s) => `
        <div class="sch-row">
            <span>${esc(describeSchedule(s))}</span>
            <button class="btn-ghost btn-sm" data-sch="${s.id}">Delete</button>
        </div>`
        )
        .join("");
}

function onKindChange() {
    const kind = document.getElementById("schKind").value;
    document.getElementById("schDateTime").style.display = kind === "once" ? "" : "none";
    document.getElementById("schTime").style.display = kind === "once" ? "none" : "";
    document.getElementById("schWeekday").style.display = kind === "weekly" ? "" : "none";
}

async function addSchedule() {
    const kind = document.getElementById("schKind").value;
    const action = document.getElementById("schAction").value;
    const tz_offset = -new Date().getTimezoneOffset(); // minutes local is ahead of UTC
    const payload = { action, kind, tz_offset };

    if (kind === "once") {
        const v = document.getElementById("schDateTime").value;
        if (!v) return alert("Pick a date and time.");
        payload.run_at = Math.floor(new Date(v).getTime() / 1000);
    } else {
        const t = document.getElementById("schTime").value;
        if (!t) return alert("Pick a time.");
        const [h, m] = t.split(":").map(Number);
        payload.at_minute = h * 60 + m;
        if (kind === "weekly") payload.weekday = Number(document.getElementById("schWeekday").value);
    }

    const res = await api(`/panel/devices/${schDeviceId}/schedules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (res.status === 402) {
        closeScheduleModal();
        openUpgradeModal();
        return;
    }
    if (!res.ok) return alert(data.error || data.message || "Could not add schedule.");
    loadSchedules();
}

async function deleteSchedule(id) {
    await api(`/panel/schedules/${id}`, { method: "DELETE" });
    loadSchedules();
}

// ---- wiring ----

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("addBtn").addEventListener("click", openAddModal);
    document.getElementById("createBtn").addEventListener("click", createDevice);
    document.getElementById("cancelAddBtn").addEventListener("click", closeAddModal);
    document.getElementById("downloadCfgBtn").addEventListener("click", downloadConfig);
    document.getElementById("copyKeyBtn").addEventListener("click", copyKey);
    document.getElementById("doneBtn").addEventListener("click", finishAdd);

    const upBtn = document.getElementById("upgradeBtn");
    if (upBtn) upBtn.addEventListener("click", openUpgradeModal);
    const mBtn = document.getElementById("manageBtn");
    if (mBtn) mBtn.addEventListener("click", manageBilling);
    document.getElementById("closeUpgradeBtn").addEventListener("click", closeUpgradeModal);

    document.querySelectorAll(".tier-pick").forEach((b) =>
        b.addEventListener("click", () => pickPlan(b.getAttribute("data-plan")))
    );

    document.getElementById("deviceName").addEventListener("keydown", (e) => {
        if (e.key === "Enter") createDevice();
    });

    const grid = document.getElementById("grid");
    grid.addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-act]");
        if (btn) {
            const id = btn.getAttribute("data-id");
            const act = btn.getAttribute("data-act");
            if (act === "remove") removeDevice(id, btn.getAttribute("data-name"));
            else if (act === "schedule") openScheduleModal(id, btn.getAttribute("data-name"));
            else cmd(id, act);
            return;
        }
        const head = e.target.closest("[data-toggle]");
        if (head) toggleCard(head.getAttribute("data-toggle"));
    });
    grid.addEventListener("keydown", (e) => {
        if (e.key !== "Enter" && e.key !== " ") return;
        const head = e.target.closest("[data-toggle]");
        if (head) { e.preventDefault(); toggleCard(head.getAttribute("data-toggle")); }
    });

    // schedule modal
    document.getElementById("schClose").addEventListener("click", closeScheduleModal);
    document.getElementById("schCloseLocked").addEventListener("click", closeScheduleModal);
    document.getElementById("schUpgradeBtn").addEventListener("click", () => {
        closeScheduleModal();
        openUpgradeModal();
    });
    document.getElementById("schKind").addEventListener("change", onKindChange);
    document.getElementById("schAddBtn").addEventListener("click", addSchedule);
    document.getElementById("schList").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-sch]");
        if (btn) deleteSchedule(btn.getAttribute("data-sch"));
    });
    onKindChange();

    loadDevices();
    setInterval(loadDevices, 5000);
});
