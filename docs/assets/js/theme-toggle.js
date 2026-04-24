(function () {
  "use strict";

  var storageKey = "eu-gov-scans-theme";
  var root = document.documentElement;
  var mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function getStoredTheme() {
    try {
      var value = localStorage.getItem(storageKey);
      if (value === "light" || value === "dark") {
        return value;
      }
    } catch (error) {
      return null;
    }
    return null;
  }

  function getTheme() {
    var explicit = root.getAttribute("data-theme");
    if (explicit === "light" || explicit === "dark") {
      return explicit;
    }
    return mediaQuery.matches ? "dark" : "light";
  }

  function saveTheme(theme) {
    try {
      localStorage.setItem(storageKey, theme);
    } catch (error) {
      // Ignore storage failures and keep the active session usable.
    }
  }

  function updateButton(theme) {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button) {
      return;
    }

    var icon = button.querySelector("[data-theme-toggle-icon]");
    var text = button.querySelector("[data-theme-toggle-text]");
    var nextTheme = theme === "dark" ? "light" : "dark";
    var label = "Switch to " + nextTheme + " mode";

    if (icon) {
      icon.textContent = theme === "dark" ? "☀" : "☾";
    }

    button.dataset.theme = theme;
    button.setAttribute("aria-label", label);
    button.setAttribute("title", label);

    if (text) {
      text.textContent = label;
    }
  }

  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    saveTheme(theme);
    updateButton(theme);
  }

  function toggleTheme() {
    applyTheme(getTheme() === "dark" ? "light" : "dark");
  }

  function syncWithSystem() {
    if (getStoredTheme()) {
      return;
    }
    root.removeAttribute("data-theme");
    updateButton(getTheme());
  }

  function init() {
    var button = document.querySelector("[data-theme-toggle]");
    if (!button) {
      return;
    }

    updateButton(getTheme());
    button.addEventListener("click", toggleTheme);

    if (typeof mediaQuery.addEventListener === "function") {
      mediaQuery.addEventListener("change", syncWithSystem);
    } else if (typeof mediaQuery.addListener === "function") {
      mediaQuery.addListener(syncWithSystem);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
