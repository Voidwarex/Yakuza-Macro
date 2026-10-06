// Auth page: flip between Sign in / Create account, and show a loading
// animation on submit. No inline handlers, to satisfy the strict CSP.

(function () {
    const flip = document.getElementById("flip");
    if (!flip) return;

    function show(mode) {
        const toRegister = mode === "register";
        flip.classList.toggle("flipped", toRegister);
        // Keep the URL in step (so refresh / back land on the same view).
        try {
            history.replaceState(null, "", toRegister ? "/register" : "/login");
        } catch (e) {}
        // Focus the first field of the newly shown card after the flip.
        const face = flip.querySelector(toRegister ? ".auth-back" : ".auth-front");
        setTimeout(() => {
            const first = face && face.querySelector("input");
            if (first) first.focus();
        }, 420);
    }

    // Links that toggle the card instead of navigating.
    document.querySelectorAll("a[data-flip]").forEach((a) => {
        a.addEventListener("click", (e) => {
            e.preventDefault();
            show(a.getAttribute("data-flip"));
        });
    });

    // Loading state on submit (spinner in the button) until navigation happens.
    document.querySelectorAll("form").forEach((form) => {
        form.addEventListener("submit", () => {
            const btn = form.querySelector(".btn-load");
            if (btn) {
                btn.classList.add("loading");
                btn.disabled = true;
            }
            flip.classList.add("submitting");
        });
    });
})();
