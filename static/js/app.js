document.addEventListener("click", function (event) {
  var opener = event.target.closest("[data-dialog-open]");
  if (opener) {
    document.querySelector(opener.dataset.dialogOpen).showModal();
  }

  var closer = event.target.closest("[data-dialog-close]");
  if (closer) {
    closer.closest("dialog").close();
  }

  // a click on the dimmed area around a dialog lands on the dialog itself
  if (event.target.tagName === "DIALOG") {
    event.target.close();
  }

  var copyButton = event.target.closest("[data-copy]");
  if (copyButton) {
    copyText(copyButton);
  }

  closeMenus(event.target);
});

document.body.addEventListener("htmx:afterSwap", function (event) {
  var dialog = event.detail.target.closest("dialog");
  if (dialog && !dialog.open && event.detail.requestConfig.verb === "get") {
    dialog.showModal();
  }
});

document.body.addEventListener("closeModal", function () {
  document.querySelectorAll("dialog[open]").forEach(function (dialog) {
    dialog.close();
  });
});

function closeMenus(clicked) {
  document.querySelectorAll("details.menu-cf[open]").forEach(function (menu) {
    if (clicked === menu || !menu.contains(clicked)) {
      menu.open = false;
    }
  });
}

function copyText(button) {
  var input = document.querySelector(button.dataset.copy);
  var label = button.querySelector("span");
  var original = label.textContent;

  navigator.clipboard.writeText(input.value);
  label.textContent = button.dataset.copied;
  setTimeout(function () {
    label.textContent = original;
  }, 1800);
}