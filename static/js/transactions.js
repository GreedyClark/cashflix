(function () {
  var SYMBOLS = { UAH: "₴", USD: "$", EUR: "€" };
  var dialog = document.getElementById("tx-dialog");
  var body = document.getElementById("tx-dialog-body");

  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail.target !== body) return;
    if (!dialog.open) dialog.showModal();
    setup(body.querySelector("[data-tx-form]"));
  });

  document.body.addEventListener("transactionsChanged", function () {
    if (dialog.open) dialog.close();
  });

  dialog.addEventListener("close", function () {
    body.innerHTML = "";
  });

  function isoDaysAgo(days) {
    var date = new Date();
    date.setDate(date.getDate() - days);
    return [date.getFullYear(), pad(date.getMonth() + 1), pad(date.getDate())].join("-");
  }

  function formatDate(value) {
    var parts = value.split("-");
    var date = new Date(parts[0], parts[1] - 1, parts[2]);
    return date.toLocaleDateString(document.documentElement.lang || "uk", { day: "numeric", month: "long" });
  }

  function pad(value) {
    return String(value).padStart(2, "0");
  }

  function setup(form) {
    if (!form) return;
    var dateInput = form.querySelector("[name=date]");

    function sync() {
      var type = form.querySelector("[name=type]:checked");
      form.dataset.type = type ? type.value : "expense";

      var category = form.querySelector("[name=category]:checked");
      if (category && category.closest(".cat-tile").dataset.kind !== form.dataset.type) {
        category.checked = false;
      }

      var account = form.querySelector("[name=account]:checked");
      form.querySelector("[data-currency-symbol]").textContent = SYMBOLS[account ? account.dataset.currency : "UAH"];

      var matched = false;
      form.querySelectorAll("[data-date-shortcut]").forEach(function (button) {
        var on = dateInput.value === isoDaysAgo(Number(button.dataset.dateShortcut));
        button.classList.toggle("is-on", on);
        matched = matched || on;
      });
      var picker = form.querySelector("[data-date-picker]");
      var label = picker.querySelector("[data-date-label]");
      picker.classList.toggle("is-on", !matched);
      label.textContent = matched || !dateInput.value ? label.dataset.placeholder : formatDate(dateInput.value);
    }

    form.addEventListener("change", sync);
    form.addEventListener("click", function (event) {
      if (event.target.closest("[data-date-picker]")) {
        if (dateInput.showPicker) dateInput.showPicker();
        return;
      }
      var button = event.target.closest("[data-date-shortcut]");
      if (!button) return;
      dateInput.value = isoDaysAgo(Number(button.dataset.dateShortcut));
      sync();
    });

    sync();
    var autofocus = form.querySelector("[data-autofocus]");
    if (autofocus) autofocus.focus();
  }
})();