/* ============================================================
   Perseus shared site behaviour
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
      try { if (window.umami) umami.track('copy-install', { cmd: btn.getAttribute('data-copy') }); } catch (e) {}
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

  // ---- demand-capture forms (Cloud early access, Government briefing) ----
  document.querySelectorAll('form[data-capture]').forEach(function (form) {
    var note = form.querySelector('[data-note]');
    var endpoint = form.getAttribute('action');
    function say(msg, color) {
      if (!note) return;
      note.textContent = msg;
      note.style.color = color || 'var(--violet-ink)';
      note.style.display = 'block';
    }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var btn = form.querySelector('[type=submit]');
      var label = btn ? btn.textContent : '';
      if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
      say('Sending…');
      fetch(endpoint, { method: 'POST', headers: { 'Accept': 'application/json' }, body: new FormData(form) })
        .then(function (r) {
          if (r.ok) {
            form.reset();
            say('Thanks. We will be in touch at the email you provided.', 'var(--green)');
            try { var s = form.querySelector('[name=source]'); if (window.umami) umami.track('lead', { source: s ? s.value : 'capture' }); } catch (e) {}
          }
          else { say('Something went wrong. Please email perseus@perseus.observer directly.', 'var(--red)'); }
        })
        .catch(function () { say('Network error. Please email perseus@perseus.observer directly.', 'var(--red)'); })
        .finally(function () { if (btn) { btn.disabled = false; btn.textContent = label; } });
    });
  });
})();
