/* LedgerFlow design-system demo behavior.
   Theme note: the no-flash part lives INLINE in each page's <head> (it must
   run before first paint); this file only wires the toggle + persistence
   and the command palette. */
(function () {
  "use strict";

  /* ---------- theme toggle (persisted) ---------- */
  var toggle = document.getElementById("theme-toggle");

  function syncThemeLabel() {
    if (!toggle) return;
    var dark = document.documentElement.dataset.theme === "dark";
    toggle.setAttribute("aria-pressed", String(dark));
    toggle.textContent = dark ? "Light" : "Dark";
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var dark = document.documentElement.dataset.theme === "dark";
      document.documentElement.dataset.theme = dark ? "" : "dark";
      try {
        localStorage.setItem("lf-theme", dark ? "light" : "dark");
      } catch (error) {
        /* private mode: theme still switches, just not persisted */
      }
      syncThemeLabel();
    });
    syncThemeLabel();
  }

  /* ---------- command palette (⌘K / Ctrl+K) ---------- */
  var dialog = document.getElementById("cmdk");
  if (!dialog || typeof dialog.showModal !== "function") return;
  var input = document.getElementById("cmdk-input");
  var list = document.getElementById("cmdk-list");
  var empty = document.getElementById("cmdk-empty");

  function filterCommands() {
    var query = input.value.trim().toLowerCase();
    var visible = 0;
    list.querySelectorAll("li").forEach(function (item) {
      var hit = item.textContent.toLowerCase().indexOf(query) !== -1;
      item.hidden = !hit;
      if (hit) visible += 1;
    });
    empty.hidden = visible !== 0;
  }

  function openPalette() {
    dialog.showModal();
    input.value = "";
    filterCommands();
    input.focus();
  }

  document.querySelectorAll("[data-cmdk-open]").forEach(function (opener) {
    opener.addEventListener("click", openPalette);
  });

  document.addEventListener("keydown", function (event) {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (dialog.open) {
        dialog.close();
      } else {
        openPalette();
      }
    }
  });

  /* click on the backdrop closes; Esc is native to <dialog> */
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) dialog.close();
  });

  input.addEventListener("input", filterCommands);
})();
