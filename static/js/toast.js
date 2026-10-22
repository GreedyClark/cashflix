(function () {
  var zone = document.getElementById("toast-zone");
  var timer;

  document.body.addEventListener("showToast", function (event) {
    show(event.detail.message, event.detail.undo);
  });

  function show(message, undoUrl) {
    clearTimeout(timer);
    zone.innerHTML = "";

    var toast = document.createElement("div");
    toast.className = "toast-cf";
    var text = document.createElement("span");
    text.textContent = message;
    toast.appendChild(text);

    if (undoUrl) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "toast-action";
      button.textContent = zone.dataset.undoLabel || "Повернути";
      button.setAttribute("hx-post", undoUrl);
      button.setAttribute("hx-swap", "none");
      toast.appendChild(button);
    }

    zone.appendChild(toast);
    if (window.htmx) window.htmx.process(toast);
    timer = setTimeout(function () {
      zone.innerHTML = "";
    }, undoUrl ? 6000 : 2600);
  }
})();