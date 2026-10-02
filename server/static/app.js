// Dashboard logic: render devices, send commands, enroll new devices.

let newKey = "";

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
    const res = await fetch("/panel/devices");
    if (res.status === 401) {
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
                    <button class="btn-red btn-sm" onclick="cmd(${d.id}, 'shutdown')">Shut down</button>
                    <button class="btn-amber btn-sm" onclick="cmd(${d.id}, 'restart')">Restart</button>
                    <button class="btn-sm" onclick="cmd(${d.id}, 'lock')">Lock</button>
                    ${
                        d.pending
                            ? `<button class="btn-ghost btn-sm" onclick="cmd(${d.id}, 'cancel')">Cancel</button>`
                            : ""
                    }
                    <button class="btn-ghost btn-sm" onclick="removeDevice(${d.id}, '${esc(d.name)}')">Remove</button>
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
    const res = await fetch(`/panel/devices/${id}/command`, {
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
    await fetch(`/panel/devices/${id}`, { method: "DELETE" });
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
    const res = await fetch("/panel/devices", {
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

// Poll the device list so status/last-seen stay fresh.
loadDevices();
setInterval(loadDevices, 5000);
