/* ============================================================
   Perseus — shared site behaviour
   Theme toggle (+ persistence), copy-to-clipboard buttons,
   scroll reveal. Page-specific JS (hero typewriter, contact
   form) lives inline on the page that needs it.
   A tiny pre-paint script in each <head> applies the saved
   theme before first paint to avoid a flash.
   ============================================================ */
(function () {
  var root = document.documentElement;

  // ---- theme toggle ----
  function syncLabels() {
    var isDark = root.getAttribute('data-theme') !== 'light';
    document.querySelectorAll('[data-theme-label]').forEach(function (el) {
      el.textContent = isDark ? 'Light' : 'Dark';
    });
  }
  syncLabels();
  document.querySelectorAll('[data-theme-toggle]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      try { localStorage.setItem('perseus-theme', next); } catch (e) {}
      root.setAttribute('data-theme', next);
      syncLabels();
    });
  });

  // ---- copy buttons ----
  document.querySelectorAll('[data-copy]').forEach(function (btn) {
    var original = btn.textContent;
    btn.addEventListener('click', function () {
      try { navigator.clipboard.writeText(btn.getAttribute('data-copy')); } catch (e) {}
      btn.textContent = 'Copied';
      clearTimeout(btn._t);
      btn._t = setTimeout(function () { btn.textContent = original; }, 1600);
    });
  });

  // ---- scroll reveal ----
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var reveals = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) {
    reveals.forEach(function (r) { r.classList.add('in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (r) { io.observe(r); });
  }
})();
