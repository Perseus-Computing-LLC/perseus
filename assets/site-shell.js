/* Perseus site shell — shared navigation, theme, and low-noise interactions. */
(function () {
  'use strict';

  var root = document.documentElement;
  var nav = document.querySelector('[data-site-nav]');
  var menu = document.querySelector('[data-mobile-menu]');
  var menuButton = document.querySelector('[data-menu-button]');
  var backdrop = document.querySelector('[data-menu-backdrop]');

  function setMenu(open) {
    if (!menu || !menuButton) return;
    menu.hidden = !open;
    menuButton.setAttribute('aria-expanded', open ? 'true' : 'false');
    menuButton.setAttribute('aria-label', open ? 'Close navigation' : 'Open navigation');
    if (backdrop) backdrop.hidden = !open;
    root.classList.toggle('menu-open', open);
  }

  if (menuButton) {
    menuButton.addEventListener('click', function () {
      setMenu(menuButton.getAttribute('aria-expanded') !== 'true');
    });
  }
  if (backdrop) backdrop.addEventListener('click', function () { setMenu(false); });
  if (menu) menu.querySelectorAll('a').forEach(function (link) {
    link.addEventListener('click', function () { setMenu(false); });
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') setMenu(false);
  });

  if (nav) {
    var onScroll = function () { nav.classList.toggle('is-scrolled', window.scrollY > 8); };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
  }

  document.querySelectorAll('[data-theme-toggle]').forEach(function (button) {
    button.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('perseus-theme', next); } catch (e) {}
      document.querySelectorAll('[data-theme-label]').forEach(function (el) {
        el.textContent = next === 'light' ? 'Dark' : 'Light';
      });
    });
  });

  document.querySelectorAll('[data-copy]').forEach(function (button) {
    var original = button.textContent;
    button.setAttribute('aria-live', 'polite');
    button.addEventListener('click', function () {
      var value = button.getAttribute('data-copy');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).catch(function () {});
      }
      button.textContent = 'Copied';
      button.setAttribute('aria-label', 'Command copied to clipboard');
      window.clearTimeout(button._copyTimer);
      button._copyTimer = window.setTimeout(function () {
        button.textContent = original;
        button.removeAttribute('aria-label');
      }, 1400);
    });
  });

  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var reveals = document.querySelectorAll('.reveal');
  if (reduce || !('IntersectionObserver' in window)) {
    reveals.forEach(function (el) { el.classList.add('in'); });
  } else {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('in');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });
    reveals.forEach(function (el) { observer.observe(el); });
  }
})();

/* A tiny inline-style bootstrap is kept in each document head so the theme
   chosen on a prior visit is applied before this script loads. */
(function () {
  var root = document.documentElement;
  var isDark = root.getAttribute('data-theme') !== 'light';
  document.querySelectorAll('[data-theme-label]').forEach(function (el) {
    el.textContent = isDark ? 'Light' : 'Dark';
  });
})();

/* calculator enhancement used by the homepage */
(function () {
  var form = document.querySelector('[data-calculator]');
  if (!form) return;
  var output = form.querySelector('[data-calc-output]');
  var tokens = form.querySelector('[data-calc-tokens]');
  var agents = form.querySelector('[data-calc-agents]');
  var calls = form.querySelector('[data-calc-calls]');
  var price = form.querySelector('[data-calc-price]');
  var baseline = form.querySelector('[data-calc-baseline]');
  var ratio = Number(form.getAttribute('data-calc-ratio')) || 0.244;
  var money = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 });
  var number = new Intl.NumberFormat('en-US');
  function render() {
    var annualCalls = Math.max(Number(agents.value) || 0, 0) * Math.max(Number(calls.value) || 0, 0) * 365;
    var full = Math.max(Number(baseline.value) || 0, 0);
    var saved = annualCalls * Math.max(full - full * ratio, 0) / 1000000 * Math.max(Number(price.value) || 0, 0);
    var savedTokens = annualCalls * Math.max(full - full * ratio, 0);
    if (output) output.textContent = money.format(Math.round(saved));
    if (tokens) tokens.textContent = number.format(Math.round(savedTokens));
    form.querySelectorAll('[data-calc-value]').forEach(function (el) {
      var field = el.getAttribute('data-calc-value');
      var source = field === 'agents' ? agents : field === 'calls' ? calls : field === 'price' ? price : baseline;
      el.textContent = Number(source.value).toLocaleString('en-US');
    });
  }
  [agents, calls, price, baseline].forEach(function (el) { if (el) el.addEventListener('input', render); });
  render();
})();

/* Progressive enhancement for the static benchmark page: keep the first
   read useful, then let readers filter by measurement family. */
(function () {
  var filter = document.querySelector('[data-benchmark-filter]');
  if (!filter) return;
  filter.addEventListener('change', function () {
    var selected = filter.value;
    document.querySelectorAll('[data-benchmark-section]').forEach(function (section) {
      section.hidden = selected !== 'all' && section.getAttribute('data-benchmark-section') !== selected;
    });
  });
})();
