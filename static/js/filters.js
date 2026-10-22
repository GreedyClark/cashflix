(function () {
  document.addEventListener("change", function (event) {
    var input = event.target.closest("[data-filter-menu] input");
    if (!input) return;

    var menu = input.closest("[data-filter-menu]");
    var label = menu.querySelector("[data-chip-label]");
    label.textContent = input.dataset.label || label.dataset.placeholder;
    menu.querySelector("summary").classList.toggle("is-set", Boolean(input.value));
    menu.open = false;
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("details.menu-cf[open]").forEach(function (menu) {
      menu.open = false;
    });
  });
})();