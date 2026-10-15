(function () {
  var root = document.documentElement;
  var stored = null;

  try {
    stored = localStorage.getItem("cashflix-theme");
  } catch (e) {}

  var prefersLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
  root.setAttribute("data-bs-theme", stored || (prefersLight ? "light" : "dark"));

  document.addEventListener("click", function (event) {
    if (!event.target.closest("[data-theme-toggle]")) return;

    var next = root.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-bs-theme", next);
    try {
      localStorage.setItem("cashflix-theme", next);
    } catch (e) {}
    document.dispatchEvent(new CustomEvent("cashflix:theme", { detail: next }));
  });
})();