/* JobVeyra dashboard: queue filtering and sorting, and JSON submission of the action forms.
   Every page works without this script; it only makes filtering instant and keeps you on the page. */
(function () {
  "use strict";

  var meta = document.querySelector('meta[name="csrf-token"]');
  var TOKEN = meta ? meta.getAttribute("content") : "";

  /* ---------------------------------------------------------- queue filter and sort */
  function setupQueue() {
    var form = document.getElementById("queue-filters");
    var table = document.querySelector("table.queue");
    if (!form || !table) return;
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    var count = document.getElementById("queue-count");
    var get = function (id) { return document.getElementById(id); };
    var applyBtn = form.querySelector('button[type="submit"]');
    if (applyBtn) applyBtn.parentNode.hidden = true;

    function value(row, key) {
      var v = row.getAttribute("data-" + key) || "";
      if (key === "fit" || key === "rank") return v === "" ? null : parseFloat(v);
      return v;
    }

    function compare(a, b, key, dir) {
      var va = value(a, key), vb = value(b, key);
      var emptyA = va === null || va === "", emptyB = vb === null || vb === "";
      if (emptyA && emptyB) return 0;
      if (emptyA) return 1;            /* rows without a value always go last */
      if (emptyB) return -1;
      var r = va < vb ? -1 : va > vb ? 1 : 0;
      return dir === "asc" ? r : -r;
    }

    function apply() {
      var st = get("f-state").value, tr = get("f-track").value, src = get("f-source").value;
      var text = get("f-q").value.trim().toLowerCase();
      var sort = get("f-sort").value, dir = get("f-dir").value;
      var key = sort === "state" ? "rank" : sort;
      var shown = 0;
      rows.forEach(function (row) {
        var ok = (!st || row.getAttribute("data-state") === st) &&
                 (!tr || row.getAttribute("data-track") === tr) &&
                 (!src || row.getAttribute("data-source") === src) &&
                 (!text || (row.getAttribute("data-text") || "").indexOf(text) !== -1);
        row.hidden = !ok;
        if (ok) shown += 1;
      });
      var ordered = rows.slice().sort(function (a, b) {
        return compare(a, b, key, dir) || compare(a, b, "employer", "asc");
      });
      ordered.forEach(function (row) { tbody.appendChild(row); });
      if (count) count.textContent = "Showing " + shown + " of " + rows.length + " jobs";
      if (window.history && window.history.replaceState) {
        var params = new URLSearchParams();
        if (st) params.set("state", st);
        if (tr) params.set("track", tr);
        if (src) params.set("source", src);
        if (text) params.set("q", text);
        if (sort !== "fit") params.set("sort", sort);
        if (!(sort === "fit" && dir === "desc")) params.set("dir", dir);
        var qs = params.toString();
        window.history.replaceState(null, "", "/queue" + (qs ? "?" + qs : ""));
      }
    }

    get("f-sort").addEventListener("change", function () {
      var s = get("f-sort").value;
      get("f-dir").value = (s === "employer" || s === "state") ? "asc" : "desc";
    });
    form.addEventListener("input", apply);
    form.addEventListener("change", apply);
    form.addEventListener("submit", function (ev) { ev.preventDefault(); apply(); });
    apply();
  }

  /* ---------------------------------------------------------- action forms */
  function collect(form, submitter) {
    var body = {};
    var fields = form.elements;
    for (var i = 0; i < fields.length; i++) {
      var el = fields[i];
      if (!el.name || el.disabled || el.name === "csrf" || el.name === "next") continue;
      if (el.type === "submit" || el.type === "button") continue;
      if (el.type === "checkbox") {
        if (el.name === "exclude") {
          body.exclude = body.exclude || [];
          if (el.checked) body.exclude.push(el.value);
        } else if (el.checked) {
          body[el.name] = el.value;
        }
        continue;
      }
      body[el.name] = el.value;
    }
    if (submitter && submitter.name) body[submitter.name] = submitter.value;
    return body;
  }

  function setupForms() {
    document.addEventListener("submit", function (ev) {
      var form = ev.target;
      if (!form || !form.hasAttribute || !form.hasAttribute("data-api")) return;
      ev.preventDefault();
      var confirmText = form.getAttribute("data-confirm");
      if (confirmText && !window.confirm(confirmText)) return;
      var submitter = ev.submitter || null;
      var status = form.querySelector(".form-status");
      var buttons = form.querySelectorAll("button");
      var next = form.querySelector('input[name="next"]');
      Array.prototype.forEach.call(buttons, function (b) { b.disabled = true; });
      if (status) { status.classList.remove("err"); status.textContent = "Saving…"; }
      fetch(form.getAttribute("action"), {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": TOKEN, "Accept": "application/json" },
        body: JSON.stringify(collect(form, submitter))
      }).then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) {
          return { ok: res.ok, data: data, status: res.status };
        });
      }).then(function (r) {
        if (r.ok) {
          if (status) status.textContent = (r.data && r.data.message) || "Saved.";
          window.location.assign(next && next.value ? next.value : window.location.pathname);
          return;
        }
        if (status) {
          status.classList.add("err");
          status.textContent = (r.data && r.data.error) || ("Request failed (" + r.status + ")");
        }
        Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      }).catch(function () {
        if (status) { status.classList.add("err"); status.textContent = "The dashboard did not answer. Is it still running?"; }
        Array.prototype.forEach.call(buttons, function (b) { b.disabled = false; });
      });
    });
  }

  function ready(fn) {
    if (document.readyState !== "loading") fn();
    else document.addEventListener("DOMContentLoaded", fn);
  }
  ready(function () { setupQueue(); setupForms(); });
})();
