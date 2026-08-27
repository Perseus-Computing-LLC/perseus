/* Perseus public-site interactions. Content and navigation remain usable without JS. */
(function () {
  "use strict";

  var root = document.documentElement;
  var header = document.querySelector("[data-site-nav]");
  var menu = document.querySelector("[data-mobile-menu]");
  var menuButton = document.querySelector("[data-menu-button]");
  var lastMenuFocus = null;

  function setMenu(open) {
    if (!menu || !menuButton) return;
    menu.hidden = !open;
    menuButton.setAttribute("aria-expanded", open ? "true" : "false");
    menuButton.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    menuButton.querySelector("span").textContent = open ? "Close" : "Menu";
    document.body.classList.toggle("menu-open", open);
    if (open) {
      lastMenuFocus = document.activeElement;
      var first = menu.querySelector("a");
      if (first) first.focus();
    } else if (lastMenuFocus && document.contains(lastMenuFocus)) {
      lastMenuFocus.focus();
      lastMenuFocus = null;
    }
  }

  if (menuButton) {
    menuButton.addEventListener("click", function () {
      setMenu(menuButton.getAttribute("aria-expanded") !== "true");
    });
  }
  setMenu(false);
  if (menu) {
    menu.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () { setMenu(false); });
    });
  }
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      setMenu(false);
      return;
    }
    if (event.key !== "Tab" || !menu || !menuButton || menuButton.getAttribute("aria-expanded") !== "true") return;
    var focusable = [menuButton].concat(Array.prototype.slice.call(menu.querySelectorAll("a[href], button:not([disabled])")));
    if (!focusable.length) return;
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  window.addEventListener("resize", function () {
    if (window.innerWidth > 980) setMenu(false);
  });

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
      var next = theme === "light" ? "dark" : "light";
      button.setAttribute("aria-label", "Use " + next + " theme");
      button.setAttribute("title", "Use " + next + " theme");
    });
  }
  applyTheme(root.getAttribute("data-theme") || "light");
  document.querySelectorAll("[data-theme-toggle]").forEach(function (button) {
    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      applyTheme(next);
      try { localStorage.setItem("perseus-theme", next); } catch (error) { /* storage is optional */ }
    });
  });

  function fallbackCopy(value) {
    var field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (error) { ok = false; }
    field.remove();
    return Promise.resolve(ok);
  }

  function copyText(value) {
    if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext) {
      return navigator.clipboard.writeText(value).then(function () { return true; }, function () { return fallbackCopy(value); });
    }
    return fallbackCopy(value);
  }

  document.querySelectorAll("[data-copy]").forEach(function (button) {
    var original = button.textContent;
    var status = button.parentElement.querySelector(".copy-status");
    button.addEventListener("click", function () {
      button.disabled = true;
      copyText(button.getAttribute("data-copy") || "").then(function (ok) {
        button.textContent = ok ? "Copied" : "Select text";
        if (status) status.textContent = ok ? "Command copied." : "Clipboard unavailable. Select the command manually.";
        window.setTimeout(function () {
          button.textContent = original;
          button.disabled = false;
          if (status) status.textContent = "";
        }, 1800);
      });
    });
  });

  if (header) {
    function updateHeader() { header.classList.toggle("is-scrolled", window.scrollY > 8); }
    updateHeader();
    window.addEventListener("scroll", updateHeader, { passive: true });
  }

  var demo = document.querySelector("[data-demo]");
  if (demo) {
    var runButton = demo.querySelector("[data-demo-run]");
    var resetButton = demo.querySelector("[data-demo-reset]");
    var output = demo.querySelector("[data-demo-output]");
    var status = demo.querySelector("[data-demo-status]");
    var steps = demo.querySelectorAll("[data-demo-step]");
    var idleText = "Run the replay to load the committed render artifact.";

    function setStep(name) {
      steps.forEach(function (step) {
        step.classList.toggle("active", step.getAttribute("data-demo-step") === name);
      });
    }

    function resetDemo() {
      output.textContent = idleText;
      status.textContent = "Idle. No network request has run.";
      runButton.disabled = false;
      resetButton.disabled = true;
      setStep("source");
    }

    runButton.addEventListener("click", function () {
      runButton.disabled = true;
      resetButton.disabled = true;
      status.textContent = "Loading the committed local-render artifact…";
      setStep("resolve");
      Promise.all([
        fetch("/demo/sample-resolved.txt", { cache: "no-store" }).then(function (response) {
          if (!response.ok) throw new Error("artifact HTTP " + response.status);
          return response.text();
        }),
        fetch("/demo/sample-metadata.json", { cache: "no-store" }).then(function (response) {
          if (!response.ok) throw new Error("metadata HTTP " + response.status);
          return response.json();
        })
      ]).then(function (values) {
        output.textContent = values[0];
        var metadata = values[1];
        status.textContent = "Loaded a real local render from " + metadata.source_revision.slice(0, 8) + "; SHA-256 " + metadata.output_sha256.slice(0, 12) + "….";
        resetButton.disabled = false;
        setStep("review");
      }).catch(function (error) {
        output.textContent = "The committed replay artifact could not be loaded.";
        status.textContent = "Replay error: " + error.message;
        runButton.disabled = false;
        resetButton.disabled = false;
        setStep("source");
      });
    });
    resetButton.addEventListener("click", resetDemo);
  }
}());
