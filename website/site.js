// Amos Solutions marketing site — motion layer.
// Scroll-progress bar, hero intro trigger, and scroll-reveal with stagger.
// Everything degrades gracefully: the .js class (set inline in <head>) gates
// the CSS hidden-states, so without JS nothing is hidden.
(function () {
    "use strict";
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    // ---- scroll progress bar ----
    var bar = document.createElement("div");
    bar.className = "scroll-progress";
    document.body.appendChild(bar);

    var ticking = false;
    function onScroll() {
        if (ticking) return;
        ticking = true;
        requestAnimationFrame(function () {
            var el = document.documentElement;
            var max = el.scrollHeight - el.clientHeight;
            var p = max > 0 ? el.scrollTop / max : 0;
            bar.style.transform = "scaleX(" + p.toFixed(4) + ")";
            ticking = false;
        });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();

    // ---- trigger hero entrance ----
    requestAnimationFrame(function () {
        requestAnimationFrame(function () { document.body.classList.add("ready"); });
    });

    if (reduce) return; // reveals stay visible (CSS hides them only when motion is allowed)

    // ---- scroll reveals ----
    var sel = ".section-head, .grid3 > *, .uc-grid > *, .price-grid > *, " +
              ".steps > *, .promise-grid > *, .cols > *, .faq > details, .cta-band, .hero .preview";
    var items = document.querySelectorAll(sel);

    if (!("IntersectionObserver" in window)) {
        items.forEach(function (el) { el.classList.add("is-revealed"); });
        return;
    }

    var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
            if (e.isIntersecting) {
                e.target.classList.add("is-revealed");
                io.unobserve(e.target);
            }
        });
    }, { threshold: 0.12, rootMargin: "0px 0px -8% 0px" });

    items.forEach(function (el) { io.observe(el); });
})();
