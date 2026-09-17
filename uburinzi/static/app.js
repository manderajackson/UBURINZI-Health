/* Uburinzi Health — small progressive-enhancement layer (no framework). */
(function () {
  "use strict";

  // Confirm before destructive actions (any form with data-confirm).
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.matches("form[data-confirm]")) return;
    if (!window.confirm(form.getAttribute("data-confirm"))) {
      event.preventDefault();
    }
  });

  // Live dashboard: reload every 60 s so the demo numbers move on their own.
  var path = window.location.pathname;
  if (path === "/" || path === "/alerts" || path === "/messages") {
    setTimeout(function () {
      window.location.reload();
    }, 60000);
  }

  // Keep filters sticky in the URL when typing in the patient search box.
  var search = document.querySelector('input[name="q"]');
  if (search) {
    search.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && search.form) search.form.submit();
    });
  }

  // Show character/SMS count for template editing.
  document.querySelectorAll('textarea[name="body"]').forEach(function (el) {
    var hint = document.createElement("div");
    hint.style.cssText = "font-size:11.5px;color:#64748b;margin-top:4px";
    var update = function () {
      var len = el.value.length;
      hint.textContent = len + " characters · " + Math.max(1, Math.ceil(len / 153)) + " SMS segment(s)";
    };
    el.addEventListener("input", update);
    el.parentNode.appendChild(hint);
    update();
  });
})();
