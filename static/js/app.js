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
    if (clicked === menu || !menu.contains(clicked) || clicked.closest(".menu-item")) {
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

document.addEventListener("keydown", function (event) {
  var row = event.target.closest('[role="button"]');
  if (row && event.key === "Enter" && event.target === row) {
    row.click();
  }
});

document.querySelectorAll("[data-code]").forEach(function (box) {
  box.classList.add("is-live");
});

document.addEventListener("input", function (event) {
  var box = event.target.closest("[data-code]");
  if (!box) {
    return;
  }
  var input = event.target;
  var digits = input.value.replace(/\D/g, "").slice(0, 6);
  input.value = digits;
  box.querySelectorAll(".cell").forEach(function (cell, index) {
    var digit = digits[index] || "";
    var shown = cell.textContent;
    if (digit !== shown) {
      cell.innerHTML = digit ? "<span>" + digit + "</span>" : "";
    }
    cell.classList.toggle("filled", Boolean(digit));
    cell.classList.toggle("caret", index === Math.min(digits.length, 5) && digits.length < 6);
  });
  box.classList.toggle("is-full", digits.length === 6);
  if (digits.length === 6 && input.form) {
    input.form.requestSubmit();
  }
});

document.body.addEventListener("twofactorDone", function (event) {
  var page = document.querySelector("[data-tfa]");
  if (page) {
    page.classList.add("is-done");
  }
  setTimeout(function () {
    window.location.href = event.detail.url;
  }, 1100);
});
