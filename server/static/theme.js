// Light/dark theme toggle. The initial theme is applied by a tiny inline
// script in <head> (anti-flash); this just wires the toggle button(s).
(function () {
    function current() {
        return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
    }
    function apply(t) {
        document.documentElement.setAttribute("data-theme", t);
        try { localStorage.setItem("amos-theme", t); } catch (e) {}
    }
    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-theme-toggle]").forEach(function (b) {
            b.addEventListener("click", function () {
                apply(current() === "dark" ? "light" : "dark");
            });
        });
    });
})();
