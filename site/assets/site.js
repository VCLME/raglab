// raglab showcase: the results chart (question-set switch, series toggles, stage
// readout), tooltips on the trade-off chart, the pipeline explainer and the nav's
// active section. Everything here is progressive: without it the default chart
// view, the hidden data tables and every pipeline stage still read.
(function () {
  "use strict";
  document.documentElement.classList.add("js");
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)");

  // Arriving from another page on an anchor: start at the top and glide to the section, as an
  // in-page link does. Reloads and back/forward keep the browser's own position.
  var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];

  var anchor = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
  if (anchor && !reduce.matches && nav && nav.type === "navigate" && document.referrer.indexOf(location.origin) === 0) {
    window.scrollTo({ top: 0, behavior: "instant" });
    // Glide once the page is shown: after the view transition when there is one, else after load.
    var glided = false;
    var glide = function () {
      if (glided) return;
      glided = true;
      setTimeout(function () { anchor.scrollIntoView({ behavior: "smooth" }); }, 60);
    };
    window.addEventListener("pagereveal", function (e) {
      if (e.viewTransition) e.viewTransition.finished.then(glide, glide);
      else glide();
    });
    window.addEventListener("load", function () { setTimeout(glide, 400); });
  }

  // ── Results chart ───────────────────────────────────────────────────────────
  // The generator renders the default view; this redraws it from the embedded data
  // and tweens every value when the question set changes, from wherever it stands.
  document.querySelectorAll('figure[data-chart="results"]').forEach(function (fig) {
    var data = JSON.parse(fig.querySelector(".chart-json").textContent);
    var area = fig.querySelector(".plot-area");
    var sub = fig.querySelector(".chart-sub");
    var readout = fig.querySelector(".readout");
    var cross = fig.querySelector(".crosshair");
    var cols = Array.prototype.slice.call(fig.querySelectorAll("button.col"));
    var legend = Array.prototype.slice.call(fig.querySelectorAll(".legend button"));
    var n = data.stages.length;
    var off = {};
    var corpus = data.corpora[0];
    var shown = values(corpus); // what is on screen now, tweened towards the target
    var active = -1;
    var frame = 0;

    function x(i) { return 6 + (i / Math.max(n - 1, 1)) * 88; }
    function y(v) { return 100 - v * 100; }
    function values(c) {
      return data.series.map(function (s) {
        return c.values[s.key].map(function (v) { return v ? v[0] : null; });
      });
    }
    function el(sel, sid, col) {
      return area.querySelector(sel + '[data-series="' + sid + '"]' + (col === undefined ? "" : '[data-col="' + col + '"]'));
    }

    function draw(vals) {
      var ends = [];
      data.series.forEach(function (s, k) {
        var d = "", started = false;
        vals[k].forEach(function (v, i) {
          var mark = el(".mark", s.id, i);
          if (v === null) { mark.style.display = "none"; started = false; return; }
          d += (started ? "L" : "M") + x(i).toFixed(2) + "," + y(v).toFixed(2);
          started = true;
          mark.style.display = "";
          mark.style.left = x(i) + "%";
          mark.style.top = y(v) + "%";
        });
        el("path.line", s.id).setAttribute("d", d);
        var last = vals[k].filter(function (v) { return v !== null; }).pop();
        var end = el(".end-label", s.id);
        end.querySelector("b").textContent = last === undefined ? "" : last.toFixed(2);
        if (last !== undefined && !off[s.id]) ends.push({ id: s.id, top: y(last), el: end });
        end.hidden = last === undefined;
      });
      // End labels never overlap: spread them at least 18 px apart, top to bottom.
      var h = area.clientHeight || 320, prev = -1e9;
      ends.sort(function (a, b) { return a.top - b.top; }).forEach(function (e) {
        var px = Math.max((e.top / 100) * h, prev + 18);
        e.el.style.top = (px / h) * 100 + "%";
        prev = px;
      });
    }

    function whiskers() {
      data.series.forEach(function (s) {
        corpus.values[s.key].forEach(function (v, i) {
          var w = el("line.whisker", s.id, i);
          var has = v && v.length === 3;
          w.setAttribute("y1", has ? y(v[1]).toFixed(2) : 0);
          w.setAttribute("y2", has ? y(v[2]).toFixed(2) : 0);
          w.classList.toggle("is-on", has && i === active && !off[s.id]);
        });
      });
    }

    function tween(target, dur) {
      cancelAnimationFrame(frame);
      if (reduce.matches) { shown = target; draw(shown); return; }
      var from = shown, t0 = performance.now();
      dur = dur || 320;
      function step(now) {
        var t = Math.min(1, (now - t0) / dur);
        // Ease-in-out: the lines morph in place, so they accelerate and settle like one shape.
        var e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
        shown = target.map(function (row, k) {
          return row.map(function (v, i) {
            var a = from[k][i];
            if (v === null || a === null) return v;
            return a + (v - a) * e;
          });
        });
        draw(shown);
        if (t < 1) frame = requestAnimationFrame(step);
      }
      frame = requestAnimationFrame(step);
    }

    function fmt(v) { return v.toFixed(3); }
    function label(i) {
      return data.series.filter(function (s) { return !off[s.id]; }).map(function (s) {
        var v = corpus.values[s.key][i];
        if (!v) return s.name + " not measured";
        return s.name + " " + fmt(v[0]) + (v.length === 3 ? ", 95% interval " + fmt(v[1]) + " to " + fmt(v[2]) : "");
      }).join("; ");
    }
    function labelCols() {
      cols.forEach(function (b, i) { b.setAttribute("aria-label", data.stages[i] + ", " + corpus.name + ": " + label(i)); });
    }

    // One readout for the whole stage: every visible series, value first, interval after.
    function show(i) {
      active = i;
      area.classList.add("is-reading");
      cross.style.left = x(i) + "%";
      area.querySelectorAll(".mark").forEach(function (m) { m.classList.toggle("is-active", m.dataset.col === String(i)); });
      whiskers();
      readout.textContent = "";
      var head = document.createElement("p");
      head.className = "readout-head";
      head.textContent = data.stages[i];
      readout.appendChild(head);
      data.series.forEach(function (s) {
        if (off[s.id]) return;
        var v = corpus.values[s.key][i];
        var row = document.createElement("p");
        row.className = "readout-row s-" + s.id;
        var key = document.createElement("span");
        key.className = "key";
        var val = document.createElement("strong");
        val.textContent = v ? fmt(v[0]) : "—";
        var name = document.createElement("span");
        name.textContent = s.name;
        row.append(key, val, name);
        if (v && v.length === 3) {
          var ci = document.createElement("span");
          ci.className = "ci";
          ci.textContent = fmt(v[1]) + "–" + fmt(v[2]);
          row.appendChild(ci);
        }
        readout.appendChild(row);
      });
      readout.hidden = false;
      // Beside the stage, on whichever side has room, in the half of the plot the lines leave empty.
      var vis = data.series.filter(function (s) { return !off[s.id] && corpus.values[s.key][i]; });
      var mean = vis.reduce(function (a, s) { return a + corpus.values[s.key][i][0]; }, 0) / (vis.length || 1);
      readout.style.top = mean > 0.5 ? "auto" : "0";
      readout.style.bottom = mean > 0.5 ? "0" : "auto";
      var left = i < n / 2;
      readout.style.left = left ? "calc(" + x(i) + "% + 16px)" : "auto";
      readout.style.right = left ? "auto" : "calc(" + (100 - x(i)) + "% + 16px)";
    }
    function hide() {
      active = -1;
      area.classList.remove("is-reading");
      readout.hidden = true;
      area.querySelectorAll(".mark.is-active").forEach(function (m) { m.classList.remove("is-active"); });
      whiskers();
    }

    cols.forEach(function (b, i) {
      b.addEventListener("pointerenter", function () { show(i); });
      b.addEventListener("focus", function () { show(i); });
      b.addEventListener("click", function () { show(i); }); // a tap on touch screens
      b.addEventListener("keydown", function (e) {
        var j = e.key === "ArrowRight" ? i + 1 : e.key === "ArrowLeft" ? i - 1 : -1;
        if (e.key === "Escape") { hide(); return; }
        if (j >= 0 && j < n) { e.preventDefault(); cols[j].focus(); }
      });
    });
    area.addEventListener("pointerleave", function (e) { if (e.pointerType === "mouse") hide(); });
    fig.addEventListener("focusout", function (e) { if (!area.contains(e.relatedTarget)) hide(); });

    fig.querySelector('[data-switch="corpus"]').addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-value]");
      if (!btn || btn.getAttribute("aria-pressed") === "true") return;
      this.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
      corpus = data.corpora.filter(function (c) { return c.key === btn.dataset.value; })[0];
      fig.dataset.corpus = corpus.key;
      sub.textContent = corpus.name + ": " + (corpus.cases || "?") + " frozen questions";
      tween(values(corpus));
      if (active >= 0) show(active); else whiskers();
      labelCols();
    });

    legend.forEach(function (b) {
      b.addEventListener("click", function () {
        var id = b.dataset.series;
        var visible = legend.filter(function (l) { return !off[l.dataset.series]; }).length;
        if (!off[id] && visible === 1) return; // keep at least one line on the chart
        off[id] = !off[id];
        b.setAttribute("aria-pressed", String(!off[id]));
        area.querySelectorAll('[data-series="' + id + '"]').forEach(function (m) { m.classList.toggle("is-off", !!off[id]); });
        draw(shown);
        if (active >= 0) show(active); else whiskers();
        labelCols();
      });
    });

    draw(shown);
    whiskers();
    labelCols();
    window.addEventListener("resize", function () { draw(shown); });

    // First view only: every line starts level at its baseline value and climbs to what
    // each brick measured. Skipped when the chart is already on screen or motion is reduced.
    // Only on a fresh visit: back, forward and reload restore a scroll position after this runs.
    var fresh = !nav || nav.type === "navigate";
    if (fresh && "IntersectionObserver" in window && !reduce.matches && fig.getBoundingClientRect().top > window.innerHeight) {
      var real = values(corpus);
      shown = real.map(function (row) { return row.map(function (v) { return v === null ? null : row[0]; }); });
      draw(shown);
      var reveal = new IntersectionObserver(function (entries) {
        if (!entries[0].isIntersecting) return;
        reveal.disconnect();
        tween(values(corpus), 900);
      }, { threshold: 0.5 });
      reveal.observe(area);
      window.addEventListener("beforeprint", function () { reveal.disconnect(); shown = values(corpus); draw(shown); });
    }
  });

  // ── Cost chart: the path drawn as arrows in pixels (a stretched SVG would bend the heads) ──
  document.querySelectorAll('figure[data-chart="cost"]').forEach(function (fig) {
    function arrows() {
      fig.querySelectorAll(".chart-panel:not([hidden]) .plot-area[data-path]").forEach(function (area) {
        area.querySelectorAll(".arrow").forEach(function (a) { a.remove(); });
        var w = area.clientWidth, h = area.clientHeight;
        var pts = area.dataset.path.split(" ").map(function (p) {
          var xy = p.split(",");
          return [(parseFloat(xy[0]) / 100) * w, (parseFloat(xy[1]) / 100) * h];
        });
        for (var i = 1; i < pts.length; i++) {
          var dx = pts[i][0] - pts[i - 1][0], dy = pts[i][1] - pts[i - 1][1];
          var len = Math.sqrt(dx * dx + dy * dy), gap = 9;
          if (len < gap * 2 + 4) continue; // too short to carry a head: the two dots touch
          var ux = dx / len, uy = dy / len;
          var a = document.createElement("span");
          a.className = "arrow";
          a.style.left = pts[i - 1][0] + ux * gap + "px";
          a.style.top = pts[i - 1][1] + uy * gap + "px";
          a.style.width = len - gap * 2 + "px";
          a.style.transform = "rotate(" + Math.atan2(dy, dx) + "rad)";
          area.insertBefore(a, area.querySelector("svg").nextSibling);
        }
      });
    }
    var sw = fig.querySelector('[data-switch="corpus"]');
    if (sw) sw.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-value]");
      if (!btn) return;
      sw.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", String(b === btn)); });
      fig.querySelectorAll(".chart-panel").forEach(function (p) { p.hidden = p.dataset.panel !== btn.dataset.value; });
      arrows();
    });
    arrows();
    window.addEventListener("resize", arrows);
  });

  // ── Cost chart: one shared tooltip for every data mark (hover and focus) ──
  var tip = document.createElement("div");
  tip.className = "tip";
  tip.setAttribute("role", "status");
  tip.hidden = true;
  document.body.appendChild(tip);
  function showTip(el) {
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
  function hideTip() { tip.hidden = true; }
  document.addEventListener("pointerover", function (e) { var el = e.target.closest("[data-tip]"); if (el) showTip(el); });
  document.addEventListener("pointerout", function (e) { if (e.target.closest("[data-tip]")) hideTip(); });
  document.addEventListener("focusin", function (e) { var el = e.target.closest("[data-tip]"); if (el) showTip(el); else hideTip(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") hideTip(); });
  window.addEventListener("scroll", hideTip, { passive: true });

  // ── Copy button on every code block: an icon, a check once copied ──
  var ICON_COPY = '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5"/></svg>';
  var ICON_DONE = '<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false"><path d="M3 8.5l3.2 3L13 4.5"/></svg>';
  if (navigator.clipboard) document.querySelectorAll("pre").forEach(function (pre) {
    var box = document.createElement("div");
    box.className = "code";
    pre.parentNode.insertBefore(box, pre);
    box.appendChild(pre);
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "copy";
    btn.setAttribute("aria-label", "Copy");
    btn.innerHTML = '<span class="copy-icon">' + ICON_COPY + '</span><span class="copy-icon is-done">' + ICON_DONE + "</span>";
    var said = document.createElement("span");
    said.className = "sr-only";
    said.setAttribute("role", "status");
    box.append(btn, said);
    var timer = 0;
    btn.addEventListener("click", function () {
      navigator.clipboard.writeText(pre.textContent.trim()).then(function () {
        btn.classList.add("is-copied");
        said.textContent = "Copied";
        clearTimeout(timer);
        timer = setTimeout(function () { btn.classList.remove("is-copied"); said.textContent = ""; }, 1600);
      });
    });
  });

  // ── Pipeline explainer: one stage open at a time, none until the reader picks one ──
  document.querySelectorAll("[data-pipeline]").forEach(function (root) {
    var buttons = root.querySelectorAll("button.stage");
    function open(id) {
      buttons.forEach(function (b) {
        var on = b.dataset.stage === id;
        b.setAttribute("aria-expanded", String(on));
        document.getElementById("stage-" + b.dataset.stage).classList.toggle("is-open", on);
      });
    }
    var hint = root.querySelector(".stage-hint");
    buttons.forEach(function (b) {
      b.addEventListener("click", function () { open(b.dataset.stage); hint.hidden = true; });
    });
    hint.hidden = false;
  });

  // ── Nav: highlight the in-page section crossing the middle of the viewport ──
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
