// raglab showcase: chart switches, the candidates slider, tooltips, the pipeline
// explainer and the nav's active section. Everything here is progressive: without
// it the default chart view, the data tables and every pipeline stage still read.
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // Chart switches: a figure shows the panel matching all its switch values.
  document.querySelectorAll("figure.chart").forEach(function (fig) {
    var groups = fig.querySelectorAll("[data-switch]");
    if (!groups.length) return;
    function sync() {
      fig.querySelectorAll(".chart-panel").forEach(function (panel) {
        var keys = panel.dataset.panel.split("|");
        var names = Array.prototype.map.call(groups, function (g) { return g.dataset.switch; });
        // Panel keys follow the switch order as written by the generator (corpus, then metric).
        var match = names.every(function (name, i) { return keys[i] === undefined || fig.dataset[name] === keys[i]; });
        panel.hidden = !match;
      });
    }
    groups.forEach(function (group) {
      group.addEventListener("click", function (e) {
        var btn = e.target.closest("button[data-value]");
        if (!btn) return;
        fig.dataset[group.dataset.switch] = btn.dataset.value;
        group.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
        sync();
      });
    });
    sync();
  });

  // Candidates slider: highlights the chosen run on both small charts.
  document.querySelectorAll('figure[data-chart="sweep"]').forEach(function (fig) {
    var input = fig.querySelector('input[type="range"]');
    var output = fig.querySelector("output");
    var labels = input.dataset.labels.split(",");
    function sync() {
      var i = input.value;
      fig.querySelectorAll(".dot[data-i]").forEach(function (d) { d.classList.toggle("is-sel", d.dataset.i === i); });
      fig.querySelectorAll(".sweep-readout").forEach(function (p) { p.hidden = p.dataset.i !== i; });
      output.textContent = labels[i];
      input.setAttribute("aria-valuetext", labels[i] + " candidates");
    }
    input.addEventListener("input", sync);
    sync();
  });

  // One shared tooltip for every data mark (hover and keyboard focus).
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  document.body.appendChild(tip);
  function show(el) {
    tip.textContent = el.dataset.tip;
    tip.hidden = false;
    var r = el.getBoundingClientRect();
    var w = tip.offsetWidth;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    var top = r.top - tip.offsetHeight - 10;
    if (top < 8) top = r.bottom + 10;
    tip.style.left = left + window.scrollX + "px";
    tip.style.top = top + window.scrollY + "px";
  }
  function hide() { tip.hidden = true; }
  document.addEventListener("pointerover", function (e) { var el = e.target.closest("[data-tip]"); if (el) show(el); });
  document.addEventListener("pointerout", function (e) { if (e.target.closest("[data-tip]")) hide(); });
  document.addEventListener("focusin", function (e) { var el = e.target.closest("[data-tip]"); if (el) show(el); else hide(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hide(); });
  window.addEventListener("scroll", hide, { passive: true });

  // Pipeline explainer: one stage open at a time; the first opens by default.
  document.querySelectorAll("[data-pipeline]").forEach(function (root) {
    var buttons = root.querySelectorAll("button.stage");
    function open(id) {
      buttons.forEach(function (b) {
        var on = b.dataset.stage === id;
        b.setAttribute("aria-expanded", String(on));
        document.getElementById("stage-" + b.dataset.stage).classList.toggle("is-open", on);
      });
    }
    buttons.forEach(function (b) { b.addEventListener("click", function () { open(b.dataset.stage); }); });
    open("citation");
  });

  // Nav: highlight the in-page section crossing the middle of the viewport (as on the portfolio).
  var links = Array.prototype.filter.call(document.querySelectorAll(".site-header nav a"), function (a) {
    return a.getAttribute("href").charAt(0) === "#";
  });
  if (links.length && "IntersectionObserver" in window) {
    var targets = links.map(function (a) { return document.querySelector(a.getAttribute("href")); }).filter(Boolean);
    function setActive(id) {
      links.forEach(function (a) {
        if (a.getAttribute("href") === "#" + id) a.setAttribute("aria-current", "page");
        else a.removeAttribute("aria-current");
      });
    }
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) setActive(e.target.id);
      });
    }, { rootMargin: "-45% 0px -50% 0px" });
    targets.forEach(function (t) { obs.observe(t); });
  }
})();
