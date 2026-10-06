// Auth page: flip between Sign in / Create account, plus a "securely signing
// in" overlay (blurred backdrop, staged status, progress bar) on login.
// No inline handlers, to satisfy the strict CSP.

(function () {
    const flip = document.getElementById("flip");
    if (!flip) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const sleep = (ms) => new Promise((r) => setTimeout(r, reduce ? Math.min(ms, 120) : ms));

    // ---- flip between the two cards ----
    function show(mode) {
        const toRegister = mode === "register";
        flip.classList.toggle("flipped", toRegister);
        try {
            history.replaceState(null, "", toRegister ? "/register" : "/login");
        } catch (e) {}
        const face = flip.querySelector(toRegister ? ".auth-back" : ".auth-front");
        setTimeout(() => {
            const first = face && face.querySelector("input");
            if (first) first.focus();
        }, 420);
    }
    document.querySelectorAll("a[data-flip]").forEach((a) => {
        a.addEventListener("click", (e) => {
            e.preventDefault();
            show(a.getAttribute("data-flip"));
        });
    });

    // ---- secure sign-in overlay ----
    const overlay = document.getElementById("authOverlay");
    const ovStatus = document.getElementById("ovStatus");
    const ovBar = document.getElementById("ovBar");
    const loginError = document.getElementById("loginError");

    function setProgress(pct) { if (ovBar) ovBar.style.width = pct + "%"; }
    function setStatus(text) { if (ovStatus) ovStatus.textContent = text; }

    async function stage(text, pct, ms) {
        setStatus(text);
        setProgress(pct);
        await sleep(ms);
    }

    const loginForm = document.querySelector(".auth-front");

    async function doLogin(form) {
        const body = new URLSearchParams(new FormData(form));
        const r = await fetch("/login", {
            method: "POST",
            headers: {
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body,
        });
        return r.json();
    }

    if (loginForm) {
        loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            if (loginError) loginError.style.display = "none";

            overlay.classList.add("show");
            overlay.setAttribute("aria-hidden", "false");
            setProgress(8);

            const pending = doLogin(loginForm).catch(() => ({
                ok: false,
                error: "Network error — please try again.",
            }));

            await stage("Verifying your credentials…", 35, 650);
            await stage("Establishing a secure session…", 70, 650);

            const res = await pending;

            if (res && res.ok) {
                await stage("Loading your devices…", 92, 500);
                setStatus("Ready");
                setProgress(100);
                await sleep(400);
                window.location = res.next || "/";
            } else {
                overlay.classList.remove("show");
                overlay.setAttribute("aria-hidden", "true");
                setProgress(0);
                if (loginError) {
                    loginError.textContent = (res && res.error) || "Sign-in failed.";
                    loginError.style.display = "";
                }
            }
        });
    }

    // Register keeps a simple button spinner and normal submit/navigation.
    const registerForm = document.querySelector(".auth-back");
    if (registerForm) {
        registerForm.addEventListener("submit", () => {
            const btn = registerForm.querySelector(".btn-load");
            if (btn) { btn.classList.add("loading"); btn.disabled = true; }
            flip.classList.add("submitting");
        });
    }
})();
