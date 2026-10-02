// Dashboard logic: render devices, send commands, enroll new devices.
// No inline event handlers — everything is wired up here so a strict
// Content-Security-Policy (script-src 'self') can be enforced.

let newKey = "";

const CSRF = document
    .querySelector('meta[name="csrf-token"]')
    .getAttribute("content");

// Wrapper that attaches the CSRF token to state-changing requests.
function api(url, options = {}) {
    const opts = { ...options };
    opts.headers = {
        ...(opts.headers || {}),
        "X-CSRF-Token": CSRF,
    };
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

async function loadDevices() {
    let res;
    try {
        res = await fetch("/panel/devices");
    } catch (e) {
        return; // transient network error; next tick retries
    }
    // Session expired -> login_required redirects us to the sign-in page.
    if (res.redirected || res.status === 401) {
        window.location = "/login";
        return;
    }
    const devices = await res.json();
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
            return `
            <div class="card">
                <div class="card-head">
                    <div class="device-name">
                        <span class="dot ${d.online ? "online" : ""}"></span>
                        ${esc(d.name)}
                    </div>
                    ${pending}
                </div>
                <div class="meta">
                    <div>Status: <b>${d.online ? "Online" : "Offline"}</b></div>
                    <div>Last seen: <b>${timeAgo(d.last_seen)}</b></div>
                    <div>IP: <b>${esc(d.last_ip) || "—"}</b></div>
                    <div>System: <b>${esc(d.os_info) || "—"}</b></div>
                </div>
                <div class="actions">
                    <button class="btn-red btn-sm" data-act="shutdown" data-id="${d.id}">Shut down</button>
                    <button class="btn-amber btn-sm" data-act="restart" data-id="${d.id}">Restart</button>
                    <button class="btn-sm" data-act="lock" data-id="${d.id}">Lock</button>
                    ${cancelBtn}
                    <button class="btn-ghost btn-sm" data-act="remove" data-id="${d.id}" data-name="${esc(d.name)}">Remove</button>
                </div>
            </div>`;
        })
        .join("");
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
    if (res.ok) {
        loadDevices();
    } else {
        alert("Failed to send command.");
    }
}

async function removeDevice(id, name) {
    if (!confirm(`Remove "${name}"? Its API key will stop working.`)) return;
    await api(`/panel/devices/${id}`, { method: "DELETE" });
    loadDevices();
}

// ---- add-device modal ----

function openAddModal() {
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
    if (!res.ok) {
        alert("Failed to create device.");
        return;
    }
    const data = await res.json();
    newKey = data.api_key;
    document.getElementById("apiKeyBox").textContent = newKey;
    document.getElementById("addStep1").style.display = "none";
    document.getElementById("addStep2").style.display = "block";
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

// ---- event wiring (no inline handlers) ----

document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("addBtn").addEventListener("click", openAddModal);
    document.getElementById("createBtn").addEventListener("click", createDevice);
    document.getElementById("cancelAddBtn").addEventListener("click", closeAddModal);
    document.getElementById("copyKeyBtn").addEventListener("click", copyKey);
    document.getElementById("doneBtn").addEventListener("click", finishAdd);

    // Enter key in the name field creates the device.
    document.getElementById("deviceName").addEventListener("keydown", (e) => {
        if (e.key === "Enter") createDevice();
    });

    // Delegate the per-device action buttons.
    document.getElementById("grid").addEventListener("click", (e) => {
        const btn = e.target.closest("button[data-act]");
        if (!btn) return;
        const id = btn.getAttribute("data-id");
        const act = btn.getAttribute("data-act");
        if (act === "remove") {
            removeDevice(id, btn.getAttribute("data-name"));
        } else {
            cmd(id, act);
        }
    });

    // Poll the device list so status/last-seen stay fresh.
    loadDevices();
    setInterval(loadDevices, 5000);
});
