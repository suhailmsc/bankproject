// Small progressive enhancements. No inline scripts anywhere (strict CSP).
document.addEventListener("submit", function (event) {
  var form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  // Stop double-submits on money-moving forms.
  form.querySelectorAll("button[type=submit]:not([data-keep])").forEach(function (button) {
    window.setTimeout(function () { button.disabled = true; }, 0);
  });
});

document.addEventListener("click", function (event) {
  var target = event.target.closest("[data-copy]");
  if (!target || !navigator.clipboard) return;
  navigator.clipboard.writeText(target.getAttribute("data-copy")).then(function () {
    var original = target.textContent;
    target.textContent = "Copied";
    window.setTimeout(function () { target.textContent = original; }, 1500);
  });
});

document.addEventListener("click", function (event) {
  if (event.target.closest("[data-print]")) window.print();
});
