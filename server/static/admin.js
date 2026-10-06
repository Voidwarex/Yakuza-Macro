// Admin page: confirm destructive actions (no inline handlers, CSP-safe).
document.querySelectorAll("form[data-confirm]").forEach((f) => {
    f.addEventListener("submit", (e) => {
        if (!confirm(f.getAttribute("data-confirm"))) e.preventDefault();
    });
});
