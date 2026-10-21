(function () {
  document.addEventListener("click", function (event) {
    var opener = event.target.closest("[data-dialog-open]");
    if (opener) {
      var dialog = document.querySelector(opener.dataset.dialogOpen);
      var menu = opener.closest("details");
      if (menu) menu.open = false;
      if (dialog) dialog.showModal();
      return;
    }

    var closer = event.target.closest("[data-dialog-close]");
    if (closer) {
      closer.closest("dialog").close();
      return;
    }

    if (event.target.tagName === "DIALOG") {
      event.target.close();
    }

    document.querySelectorAll("details.menu-cf[open]").forEach(function (menu) {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
})();