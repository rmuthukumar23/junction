// @ts-nocheck
// Legacy port of scripts/pixel/stats.js (vanilla JS). Untyped on purpose: replaced by the sprite system (web/src/engine).
/* Greenhouse Bench pixel site: analytics + stats page.
   window.PixelStats.mount(containerEl, { fetchJson })
   fetchJson('/api/stats') -> analytics.compute_stats output, or {"error": "..."}.
   Vanilla JS, inline SVG, no dependencies. Pixel look: crisp edges, stepped bars, no gradients. */

  var PALETTE = ["#a5411c", "#1d5c94", "#23703a", "#6b4a8c", "#b87c06", "#0b7a6b", "#b03a6b", "#7a5230", "#5a6b7a", "#6b7a2e"];
  var TOOL_PALETTE = ["#1d5c94", "#b87c06", "#23703a", "#6b4a8c", "#b03a6b", "#7a5230", "#a5411c", "#0b7a6b", "#5a6b7a"];
  var NS = "http://www.w3.org/2000/svg";

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function isNum(x) { return typeof x === "number" && isFinite(x); }
  function num(x, d) { return isNum(x) ? x.toLocaleString("en-US", { maximumFractionDigits: d == null ? 0 : d, minimumFractionDigits: 0 }) : "n/a"; }
  function eur(x) { return isNum(x) ? (x < 0 ? "-" : "") + "€" + Math.abs(x).toLocaleString("en-US", { maximumFractionDigits: 0 }) : "n/a"; }
  function sgn(x) { return isNum(x) ? (x > 0 ? "+" : "") + eur(x) : "n/a"; }
  function score(x) { return isNum(x) ? x.toFixed(3) : "n/a"; }

  /* A bar made of equal-sized blocks (stepped, never a smooth fill). */
  function blockBar(frac, color, cells, w, h) {
    cells = cells || 20; w = w || 120; h = h || 10;
    var f = isNum(frac) ? Math.max(0, Math.min(1, frac)) : 0, on = Math.round(f * cells), cw = w / cells, out = "";
    for (var i = 0; i < cells; i++) {
      out += '<rect x="' + (i * cw + 0.5).toFixed(1) + '" y="0" width="' + (cw - 1.5).toFixed(1) + '" height="' + h +
        '" fill="' + (i < on ? color : "var(--px-ink, #1e3226)") + '" opacity="' + (i < on ? 1 : 0.14) + '"/>';
    }
    return '<svg class="st-blocks" width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + " " + h +
      '" shape-rendering="crispEdges" role="img" aria-label="' + Math.round(f * 100) + ' percent">' + out + "</svg>";
  }

  function tag(text, cls) { return '<span class="px-tag st-tag ' + (cls || "") + '">' + esc(text) + "</span>"; }
  function panel(title, body, id, note) {
    return '<section class="px-panel st-panel" id="' + id + '"><h2 class="px-title st-h">' + esc(title) + "</h2>" +
      (note ? '<p class="st-note">' + note + "</p>" : "") + body + "</section>";
  }
  function empty(msg) { return '<div class="st-empty"><span class="st-sprite" aria-hidden="true"></span><p>' + esc(msg) + "</p></div>"; }
  function stat(label, value, cls) {
    return '<div class="st-stat ' + (cls || "") + '"><b>' + value + "</b><span>" + esc(label) + "</span></div>";
  }

  /* ---------- sections ---------- */

  function summary(s) {
    var m = s.meta || {}, f = m.failures_by_class || {};
    return '<div class="st-stats">' +
      stat("runs", num(m.runs)) + stat("complete", num(m.complete), "st-good") +
      stat("partial", num(m.partial), "st-warn") + stat("failed", num(m.failed), m.failed ? "st-bad" : "") +
      stat("agent failures", num(f.agent), f.agent ? "st-bad" : "") +
      stat("infrastructure failures", num(f.infrastructure), "st-infra") +
      stat("unclassified", num(f.unknown)) + stat("replays analysed", num(m.replays_analysed)) + "</div>" +
      '<p class="st-note">Infrastructure failures (setup timeouts, sandbox, model API errors) are shown apart and never counted against the agent. ' +
      "Scenarios: " + esc((m.scenarios || []).join(", ") || "none") + ".</p>";
  }

  function leaderboard(s) {
    var lb = s.leaderboard || [];
    if (!lb.length) return empty("No runs recorded yet.");
    var maxScore = 0;
    lb.forEach(function (g) { if (isNum(g.mean_score)) maxScore = Math.max(maxScore, g.mean_score, g.best_score || 0); });
    if (maxScore <= 0) maxScore = 1;
    var rows = lb.map(function (g, i) {
      var f = g.failures || {}, col = g.kind === "policy" ? "var(--px-co2, #0b7a6b)" : "var(--px-accent, #a5411c)";
      return "<tr><td>" + g.rank + "</td><td><b>" + esc(g.name) + "</b> " + tag(g.kind, g.kind === "policy" ? "st-tag-policy" : "") + "</td>" +
        "<td>" + g.n_complete + "/" + g.n_runs + "</td>" +
        '<td class="st-barcell">' + blockBar(isNum(g.mean_score) ? g.mean_score / maxScore : 0, col) + " " + score(g.mean_score) + "</td>" +
        "<td>" + score(g.best_score) + " / " + score(g.worst_score) + "</td>" +
        "<td>" + eur(g.mean_profit_eur) + "</td>" +
        "<td>" + eur(g.best_profit_eur) + " / " + eur(g.worst_profit_eur) + "</td>" +
        '<td class="' + (isNum(g.mean_profit_vs_baseline_eur) ? (g.mean_profit_vs_baseline_eur > 0 ? "st-good" : "st-bad") : "") + '">' +
        sgn(g.mean_profit_vs_baseline_eur) + (g.n_with_baseline ? " <small>(" + g.beats_baseline + "/" + g.n_with_baseline + " beat)</small>" : "") + "</td>" +
        "<td>" + (g.n_paired_with_reference ? sgn(g.gap_to_reference_eur) : "n/a") + "</td>" +
        '<td><span class="st-bad">' + (f.agent || 0) + '</span> / <span class="st-infra">' + (f.infrastructure || 0) +
        "</span>" + (f.unknown ? ' / <span class="st-dim">' + f.unknown + "?</span>" : "") + "</td></tr>";
    }).join("");
    return '<div class="st-scroll"><table class="st-table"><thead><tr><th>#</th><th>Model / policy</th><th>Done</th><th>Mean score</th>' +
      "<th>Best / worst</th><th>Mean profit</th><th>Best / worst profit</th><th>vs do-nothing</th><th>vs reference</th>" +
      '<th title="agent / infrastructure / unclassified">Failures A / I</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
  }

  function colorFor(map, key) {
    if (!(key in map)) map[key] = PALETTE[Object.keys(map).length % PALETTE.length];
    return map[key];
  }

  function profitChart(s, state) {
    var cs = (s.profit_curves || []).filter(function (c) { return (c.points || []).some(function (p) { return isNum(p.profit) || isNum(p.cash); }); });
    if (!cs.length) return empty("No day-by-day profit data. Replays of complete or partial runs are needed.");
    var colors = {};
    cs.forEach(function (c) { colorFor(colors, c.run); });
    var legend = '<div class="st-legend">' + cs.map(function (c) {
      var off = state.hidden[c.run];
      return '<button type="button" class="px-btn st-leg' + (off ? " st-off" : "") + '" data-run="' + esc(c.run) + '" aria-pressed="' + (!off) + '">' +
        '<i style="background:' + colors[c.run] + '"></i>' + esc(c.label || c.run) + "</button>";
    }).join("") + "</div>";
    var W = 760, H = 300, L = 62, R = 14, T = 12, B = 30, vals = [], maxDay = 1;
    cs.forEach(function (c) { if (!state.hidden[c.run]) c.points.forEach(function (p) {
      var v = isNum(p.profit) ? p.profit : p.cash; if (isNum(v)) { vals.push(v); maxDay = Math.max(maxDay, p.day); } }); });
    if (!vals.length) vals = [0, 1];
    var lo = Math.min.apply(null, vals.concat([0])), hi = Math.max.apply(null, vals.concat([0]));
    if (hi === lo) hi = lo + 1;
    var pad = (hi - lo) * 0.06; lo -= pad; hi += pad;
    function X(d) { return L + (d / maxDay) * (W - L - R); }
    function Y(v) { return T + (1 - (v - lo) / (hi - lo)) * (H - T - B); }
    var g = "";
    for (var i = 0; i <= 4; i++) {
      var v = lo + (hi - lo) * i / 4, y = Y(v).toFixed(1);
      g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y + '" y2="' + y + '" stroke="var(--px-ink,#1e3226)" opacity=".15"/>' +
        '<text x="' + (L - 6) + '" y="' + (+y + 4) + '" text-anchor="end">' + esc(eur(v)) + "</text>";
    }
    var step = maxDay > 28 ? 7 : maxDay > 12 ? 4 : 2;
    for (var d = 0; d <= maxDay; d += step) {
      g += '<text x="' + X(d).toFixed(1) + '" y="' + (H - 10) + '" text-anchor="middle">d' + d + "</text>";
    }
    g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + Y(0).toFixed(1) + '" y2="' + Y(0).toFixed(1) + '" stroke="var(--px-ink,#1e3226)" stroke-width="2"/>';
    cs.forEach(function (c) {
      if (state.hidden[c.run]) return;
      var pts = c.points.filter(function (p) { return isNum(p.profit) || isNum(p.cash); });
      /* stepped line: hold the value until the next day, like the game's daily turn */
      var dpath = "";
      pts.forEach(function (p, i) {
        var v = isNum(p.profit) ? p.profit : p.cash, x = X(p.day).toFixed(1), y = Y(v).toFixed(1);
        dpath += (i === 0 ? "M" : "H" + x + "V") + (i === 0 ? x + " " + y : y);
      });
      g += '<path d="' + dpath + '" fill="none" stroke="' + colors[c.run] + '" stroke-width="2.5" shape-rendering="crispEdges"' +
        (c.kind === "policy" ? ' stroke-dasharray="6 3"' : "") + "/>";
      var last = pts[pts.length - 1];
      if (last) g += '<rect x="' + (X(last.day) - 3).toFixed(1) + '" y="' + (Y(isNum(last.profit) ? last.profit : last.cash) - 3).toFixed(1) +
        '" width="6" height="6" fill="' + colors[c.run] + '"/>';
    });
    return legend + '<svg class="st-chart" viewBox="0 0 ' + W + " " + H + '" shape-rendering="crispEdges" role="img" aria-label="Profit by day">' +
      g + "</svg>" + '<p class="st-note">Stepped lines: profit holds until the next daily turn. Dashed = scripted policy. Falls back to cash when profit is absent.</p>';
  }

  function baselineChart(s) {
    var rows = (s.leaderboard || []).filter(function (g) { return isNum(g.mean_profit_eur) && isNum(g.mean_baseline_profit_eur); });
    if (!rows.length) return empty("No profit-vs-do-nothing data yet. Needs complete runs with a profit and a baseline.");
    var max = 1, min = 0;
    rows.forEach(function (g) { max = Math.max(max, g.mean_profit_eur, g.mean_baseline_profit_eur); min = Math.min(min, g.mean_profit_eur, g.mean_baseline_profit_eur); });
    var W = 760, L = 150, R = 90, rh = 38, H = rows.length * rh + 24, span = max - min;
    function X(v) { return L + ((v - min) / span) * (W - L - R); }
    var zero = X(0).toFixed(1), g = "";
    function bar(v, y, color) {
      var x0 = X(0), x1 = X(v), x = Math.min(x0, x1), w = Math.max(2, Math.abs(x1 - x0)), cells = Math.max(1, Math.round(w / 8)), cw = w / cells, out = "";
      for (var i = 0; i < cells; i++) out += '<rect x="' + (x + i * cw + 0.5).toFixed(1) + '" y="' + y + '" width="' + (cw - 1.5).toFixed(1) + '" height="11" fill="' + color + '"/>';
      return out;
    }
    rows.forEach(function (r, i) {
      var y = 14 + i * rh;
      g += '<text x="' + (L - 8) + '" y="' + (y + 16) + '" text-anchor="end">' + esc(r.name.length > 22 ? r.name.slice(0, 21) + "…" : r.name) + "</text>" +
        bar(r.mean_baseline_profit_eur, y, "var(--px-ink,#4a5e4c)") + bar(r.mean_profit_eur, y + 13, r.mean_profit_eur >= r.mean_baseline_profit_eur ? "var(--px-good,#23703a)" : "var(--px-bad,#b3261e)") +
        '<text x="' + (W - R + 6) + '" y="' + (y + 22) + '">' + esc(sgn(r.mean_profit_eur - r.mean_baseline_profit_eur)) + "</text>";
    });
    g += '<line x1="' + zero + '" x2="' + zero + '" y1="4" y2="' + (H - 8) + '" stroke="var(--px-ink,#1e3226)" stroke-width="2"/>';
    return '<svg class="st-chart" viewBox="0 0 ' + W + " " + H + '" shape-rendering="crispEdges" role="img" aria-label="Profit against do-nothing baseline">' + g + "</svg>" +
      '<p class="st-note"><i class="st-key" style="background:var(--px-ink,#4a5e4c)"></i> do-nothing baseline (same seed) &nbsp; <i class="st-key" style="background:var(--px-good,#23703a)"></i> model/policy mean profit. Right: gap.</p>';
  }

  function toolChart(s) {
    var tu = s.tool_usage || {}, per = (tu.per_run || []).filter(function (r) { return r.calls > 0; });
    var tools = Object.keys(tu.by_tool || {});
    if (!per.length || !tools.length) return empty("No tool calls recorded.");
    tools.sort(function (a, b) { return tu.by_tool[b].calls - tu.by_tool[a].calls; });
    var tc = {}; tools.forEach(function (t, i) { tc[t] = TOOL_PALETTE[i % TOOL_PALETTE.length]; });
    var rows = [{ label: "ALL RUNS", by_tool: tu.by_tool, calls: tu.calls, invalid: tu.invalid, apd: tu.mean_actions_per_day }].concat(per.map(function (r) {
      return { label: r.label || r.run, by_tool: r.by_tool, calls: r.calls, invalid: r.invalid, apd: r.actions_per_day };
    }));
    var maxN = 1; per.forEach(function (r) { maxN = Math.max(maxN, r.calls); });
    var W = 760, L = 170, R = 150, rh = 24, H = rows.length * rh + 6, g = "";
    rows.forEach(function (r, i) {
      var y = 4 + i * rh, x = L, scale = (W - L - R) / (i === 0 ? Math.max(1, r.calls) : maxN);
      g += '<text x="' + (L - 8) + '" y="' + (y + 13) + '" text-anchor="end"' + (i === 0 ? ' font-weight="bold"' : "") + ">" + esc(String(r.label).length > 24 ? String(r.label).slice(0, 23) + "…" : r.label) + "</text>";
      tools.forEach(function (t) {
        var n = (r.by_tool[t] || {}).calls || 0; if (!n) return;
        var w = Math.max(2, Math.round(n * scale / 2) * 2);
        g += '<rect x="' + x + '" y="' + y + '" width="' + w + '" height="16" fill="' + tc[t] + '" stroke="var(--px-bg,#f1efe0)" stroke-width="1"><title>' + esc(t) + ": " + n + "</title></rect>";
        x += w;
      });
      g += '<text x="' + (x + 6) + '" y="' + (y + 13) + '">' + r.calls + " calls" + (r.invalid ? ' <tspan fill="var(--px-bad,#b3261e)">' + r.invalid + " invalid</tspan>" : "") +
        (isNum(r.apd) ? " · " + r.apd.toFixed(1) + "/day" : "") + "</text>";
    });
    var leg = '<div class="st-legend">' + tools.map(function (t) {
      var b = tu.by_tool[t]; return '<span class="st-leg-static"><i style="background:' + tc[t] + '"></i>' + esc(t) + " " + b.calls + (b.invalid ? " (" + b.invalid + " invalid)" : "") + "</span>";
    }).join("") + "</div>";
    return leg + '<svg class="st-chart" viewBox="0 0 ' + W + " " + H + '" shape-rendering="crispEdges" role="img" aria-label="Tool usage">' + g + "</svg>" +
      '<p class="st-note">Invalid-call rate overall: ' + (isNum(tu.invalid_rate) ? (tu.invalid_rate * 100).toFixed(1) + "%" : "n/a") +
      "; mean actions per day with actions: " + (isNum(tu.mean_actions_per_day) ? tu.mean_actions_per_day.toFixed(1) : "n/a") + ".</p>";
  }

  function mistakes(s) {
    var m = s.mistakes || {}, t = m.totals || {}, rc = m.reaction || {}, out = "";
    out += '<div class="st-stats">' +
      stat("damage days (est.)", num(t.damage_days), t.damage_days ? "st-warn" : "") +
      stat("missed harvest days (est.)", num(t.missed_harvest_days, 1), t.missed_harvest_days ? "st-warn" : "") +
      stat("crops lost", num(t.crops_lost), t.crops_lost ? "st-bad" : "") +
      stat("bankruptcies", num(t.bankruptcies), t.bankruptcies ? "st-bad" : "") +
      stat("early stops", num(t.early_stops), t.early_stops ? "st-warn" : "") +
      stat("unreacted signals", num(rc.unreacted) + "/" + num(rc.signals), rc.unreacted ? "st-warn" : "") +
      stat("median reaction", isNum(rc.median_latency_h) ? num(rc.median_latency_h, 1) + " h" : "n/a") + "</div>";
    var inv = m.invalid_actions || [];
    out += '<h3 class="st-h3">Invalid actions, grouped by error</h3>';
    out += inv.length ? '<ul class="st-list">' + inv.map(function (e) {
      return "<li><b class=\"st-bad\">" + e.count + "x</b> <code>" + esc(e.err) + "</code> <small>" + esc(Object.keys(e.tools || {}).join(", ")) + " · " + e.runs + " run(s)</small></li>";
    }).join("") + "</ul>" : '<p class="st-note">No invalid actions recorded.</p>';
    var slow = rc.slowest || [];
    out += '<h3 class="st-h3">Slowest reactions to alarms and events</h3>';
    out += slow.length ? '<ul class="st-list">' + slow.map(function (r) {
      return "<li>" + (r.reacted ? "<b>" + num(r.latency_h) + " h</b>" : '<b class="st-bad">not reacted within ' + num(rc.window_h) + " h</b>") +
        " · " + tag(r.source) + " " + esc(r.kind || "") + (r.target ? " @ " + esc(r.target) : "") + " <small>day " + esc(r.day == null ? "?" : r.day) + " · " + esc(r.text) + "</small></li>";
    }).join("") + "</ul>" : '<p class="st-note">No alarms or events in the analysed replays.</p>';
    var pr = (m.per_run || []).filter(function (r) { return r.crops_lost || r.damage_days || r.bankrupt_day != null || r.early_stop; });
    if (pr.length) {
      out += '<h3 class="st-h3">Runs with losses</h3><ul class="st-list">' + pr.map(function (r) {
        var bits = [];
        if (r.crops_lost) bits.push(r.crops_lost + " crop batch(es) lost");
        if (r.damage_days) bits.push(r.damage_days + " day(s) with active damage");
        if (r.bankrupt_day != null) bits.push("cash <= 0 on day " + r.bankrupt_day);
        if (r.early_stop) bits.push("stopped early");
        return "<li><b>" + esc(r.label || r.run) + "</b> <small>" + esc(bits.join("; ")) + "</small></li>";
      }).join("") + "</ul>";
    }
    return out;
  }

  function energy(s) {
    var e = s.energy || {}, t = e.total || {}, per = (e.per_run || []).filter(function (r) { return r.hours > 0; });
    if (!per.length) return empty("No energy data. It comes from hourly frames of greenhouse replays.");
    var share = t.heat_produced_kwh > 0 ? t.heat_lost_kwh / t.heat_produced_kwh : null;
    var out = '<div class="st-stats">' +
      stat("gas cost", eur(t.gas_cost_eur)) + stat("gas used", num(t.gas_m3) + " m3") +
      stat("electricity import", eur(t.import_cost_eur)) + stat("export revenue", eur(t.export_revenue_eur), "st-good") +
      stat("heat lost", num(t.heat_lost_kwh) + " kWh", "st-warn") + stat("lost share of heat", isNum(share) ? (share * 100).toFixed(1) + "%" : "n/a") +
      stat("CHP hours", num(t.chp_hours)) + stat("boiler hours", num(t.boiler_hours)) + stat("CO2 requested (est.)", num(t.co2_requested_kg) + " kg") + "</div>";
    var maxHeat = 1; per.forEach(function (r) { maxHeat = Math.max(maxHeat, r.heat_produced_kwh || 0); });
    out += '<div class="st-scroll"><table class="st-table"><thead><tr><th>Run</th><th>Heat produced / lost</th><th>Gas cost</th><th>Electricity</th><th>CHP h</th><th>Boiler h</th></tr></thead><tbody>' +
      per.map(function (r) {
        var lostFrac = r.heat_produced_kwh > 0 ? r.heat_lost_kwh / r.heat_produced_kwh : 0;
        return "<tr><td>" + esc(r.label || r.run) + '</td><td class="st-barcell">' + blockBar((r.heat_produced_kwh || 0) / maxHeat, "var(--px-heat,#b3261e)", 16, 96) + " " + num(r.heat_produced_kwh) +
          " / " + '<span class="st-warn">' + num(r.heat_lost_kwh) + " (" + (lostFrac * 100).toFixed(0) + "%)</span></td><td>" + eur(r.gas_cost_eur) +
          "</td><td>" + eur(r.import_cost_eur - r.export_revenue_eur) + "</td><td>" + num(r.chp_hours) + "</td><td>" + num(r.boiler_hours) + "</td></tr>";
      }).join("") + "</tbody></table></div>";
    return out;
  }

  function runTable(s) {
    var rs = s.runs || [];
    if (!rs.length) return empty("No runs yet.");
    var cls = { complete: "st-good", partial: "st-warn", failed: "st-bad" };
    return '<div class="st-scroll"><table class="st-table st-runs"><thead><tr><th>Run</th><th>Who</th><th>Scenario</th><th>Seed</th><th>Status</th><th>Score</th><th>Profit</th><th>vs baseline</th><th>Failure</th></tr></thead><tbody>' +
      rs.map(function (r) {
        var fc = r.failure_class, fcls = fc === "infrastructure" ? "st-infra" : fc === "agent" ? "st-bad" : "st-dim";
        return '<tr><td><a class="st-link" href="#/run/' + encodeURIComponent(r.id) + '">' + esc(r.label || r.id) + "</a></td><td>" + esc(r.group) + " " + tag(r.kind || "?", r.kind === "policy" ? "st-tag-policy" : "") + "</td>" +
          "<td>" + esc(r.scenario || "") + "</td><td>" + esc(r.seed == null ? "" : r.seed) + '</td><td class="' + (cls[r.status] || "") + '">' + esc(r.status) + "</td>" +
          "<td>" + score(r.score) + "</td><td>" + eur(r.profit_eur) + "</td><td>" + sgn(r.profit_vs_baseline_eur) + "</td>" +
          '<td class="' + fcls + '">' + (fc && fc !== "none" ? tag(fc, fcls) + ' <small title="' + esc(r.failure || "") + '">' + esc(String(r.failure || "").slice(0, 70)) + "</small>" : "") + "</td></tr>";
      }).join("") + "</tbody></table></div>";
  }

  /* ---------- page ---------- */

  function render(root, s) {
    var state = { hidden: {} };
    function draw() {
      root.innerHTML = '<div class="st-page">' +
        '<header class="st-head"><h1 class="px-title st-title">Greenhouse Bench: stats</h1>' +
        '<nav class="st-nav"><a class="px-btn" href="#/">Runs</a></nav></header>' +
        panel("Overview", summary(s), "st-overview") +
        panel("Leaderboard", leaderboard(s), "st-leaderboard") +
        panel("Profit by day", profitChart(s, state), "st-profit") +
        panel("Score vs do-nothing baseline", baselineChart(s), "st-baseline") +
        panel("Tool usage", toolChart(s), "st-tools") +
        panel("Mistakes and failure modes", mistakes(s), "st-mistakes") +
        panel("Energy", energy(s), "st-energy") +
        panel("All runs", runTable(s), "st-all") +
        panel("How to read this", '<ul class="st-list">' + ((s.meta && s.meta.estimates) || []).map(function (e) { return "<li>" + esc(e) + "</li>"; }).join("") + "</ul>" +
          ((s.meta && s.meta.replays_failed && s.meta.replays_failed.length) ? '<p class="st-note st-bad">' + s.meta.replays_failed.length + " replay(s) could not be analysed.</p>" : ""), "st-notes") +
        "</div>";
      var btns = root.querySelectorAll(".st-leg[data-run]");
      for (var i = 0; i < btns.length; i++) {
        btns[i].addEventListener("click", function (ev) {
          var r = ev.currentTarget.getAttribute("data-run");
          state.hidden[r] = !state.hidden[r];
          var y = window.pageYOffset; draw(); window.scrollTo(0, y);
        });
      }
    }
    draw();
  }

  function message(root, cls, title, text) {
    root.innerHTML = '<div class="st-page"><div class="px-panel st-panel st-msg ' + cls + '"><span class="st-sprite st-sprite-' + cls.replace("st-", "") + '" aria-hidden="true"></span>' +
      '<h2 class="px-title">' + esc(title) + "</h2><p>" + esc(text) + "</p></div></div>";
  }

  function mount(root, opts) {
    var fetchJson = opts && opts.fetchJson;
    if (!root || typeof fetchJson !== "function") throw new Error("PixelStats.mount(el, {fetchJson})");
    root.classList.add("st-root");
    message(root, "st-loading", "Counting seedlings...", "Crunching the recorded runs.");
    var p;
    try { p = Promise.resolve(fetchJson("/api/stats")); } catch (e) { p = Promise.reject(e); }
    p.then(function (s) {
      if (!s || s.error) { message(root, "st-error", "The greenhouse jammed", (s && s.error) || "The stats endpoint returned nothing."); return; }
      if (!(s.runs || []).length) { message(root, "st-empty-state", "Nothing growing yet", "No runs recorded. Play a policy or run an agent, then come back."); return; }
      render(root, s);
    }).catch(function (e) {
      message(root, "st-error", "The greenhouse jammed", "Could not load /api/stats: " + (e && e.message ? e.message : e));
    });
  }

  export const PixelStats = { mount: mount };
