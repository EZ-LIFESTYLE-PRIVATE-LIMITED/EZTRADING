// Theme: "system" (follow the OS), "light" or "dark". Loaded as a classic script in <head>
// so the right colours apply before first paint. The choice is a per-device preference.
(function () {
  var KEY = "ezt-theme";
  var media = window.matchMedia("(prefers-color-scheme: dark)");

  function read() {
    try { return localStorage.getItem(KEY) || "system"; } catch (e) { return "system"; }
  }

  function apply(choice) {
    var dark = choice === "dark" || (choice === "system" && media.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    // Keep the browser / Android status bar in step with the top bar (--card).
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#1a1d23" : "#ffffff");
  }

  window.eztTheme = {
    get: read,
    set: function (choice) {
      try { localStorage.setItem(KEY, choice); } catch (e) { /* private mode: applies to this page only */ }
      apply(choice);
    },
  };

  media.addEventListener("change", function () { apply(read()); });
  apply(read());
})();
