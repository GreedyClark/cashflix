(function () {
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;

    var input = document.querySelector(button.dataset.copy);
    var label = button.querySelector("span");
    var original = label ? label.textContent : "";

    function done() {
      if (!label) return;
      label.textContent = button.dataset.copied || original;
      setTimeout(function () { label.textContent = original; }, 1800);
    }

    input.select();
    if (navigator.clipboard) {
      navigator.clipboard.writeText(input.value).then(done, function () {
        document.execCommand("copy");
        done();
      });
    } else {
      document.execCommand("copy");
      done();
    }
  });
})();