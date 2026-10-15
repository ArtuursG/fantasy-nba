"use strict";

// Builds an element; children may be strings, nodes, arrays or null.
// Text always goes through textContent, so ESPN data can't inject markup.
function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style") el.setAttribute("style", value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  const add = (child) => {
    if (child === null || child === undefined || child === false) return;
    if (Array.isArray(child)) child.forEach(add);
    else el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  };
  children.forEach(add);
  return el;
}

const $ = (id) => document.getElementById(id);
const num = (v, d = 1) => (v === null || v === undefined ? "-" : Number(v).toFixed(d));
const pct = (v) => (v === null || v === undefined ? "-" : Number(v).toFixed(3));
const signed = (v, d = 1) => (v === null || v === undefined ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(d));
const STATS = [["3PM", "tpm"], ["REB", "reb"], ["AST", "ast"], ["STL", "stl"], ["BLK", "blk"], ["TO", "to"], ["PTS", "pts"]];

let reportText = "";

function setStatus(text, kind) {
  const el = $("status");
  el.textContent = text || "";
  el.className = "status" + (kind ? " " + kind : "");
}

function card(title, wide, ...body) {
  return h("section", { class: "card" + (wide ? " wide" : "") }, h("h2", {}, title), body);
}

function table(headers, rows, opts = {}) {
  const head = h("tr", {}, headers.map((x, i) => h("th", { class: (opts.textCols || []).includes(i) ? "text" : null }, x)));
  const body = rows.map((r) => {
    const cells = r.cells.map((c, i) => {
      const cls = [(opts.textCols || []).includes(i) ? "text" : "", (opts.wrapCols || []).includes(i) ? "wrap" : "", c && c.cls ? c.cls : ""].join(" ").trim();
      return h("td", { class: cls || null, title: c && c.title ? c.title : null }, c && c.node !== undefined ? c.node : c);
    });
    return h("tr", { class: r.cls || null }, cells);
  });
  return h("div", { class: opts.tall ? "scroll tall" : "scroll" }, h("table", {}, h("thead", {}, head), h("tbody", {}, body)));
}

function statLine(row) {
  if (row.season && row.season.gp > 0) return [row.season, ""];
  if (row.projected) return [row.projected, "*"];
  return [row.proj_line, "*"];
}

function statCells(line) {
  if (!line) return Array(2 + STATS.length).fill("-");
  return [pct(line.fg_pct), pct(line.ft_pct), ...STATS.map(([, k]) => num(line[k]))];
}

function healthCell(row) {
  const bad = ["OUT", "INJURY_RESERVE", "SUSPENSION"].includes(row.injury_status);
  const warn = ["DAY_TO_DAY", "QUESTIONABLE", "DOUBTFUL"].includes(row.injury_status);
  return { node: row.health, cls: bad ? "bad" : warn ? "warn" : "", title: row.injury_note || null };
}

function trendCell(trend) {
  return { node: trend, cls: trend === "UP" ? "good" : trend === "DOWN" ? "bad" : "" };
}

function minutes(list) {
  return list && list.length ? list.map((m) => m.toFixed(0)).join(" ") : "-";
}

function renderMatchup(v) {
  const mu = v.matchup;
  if (!mu) return card("Matchup", true, h("p", { class: "muted" }, "No current matchup (off week, or your team was not found)."));
  const score = mu.score_now;
  const fmt = (cat, x) => (cat.endsWith("%") ? pct(x) : num(x, 0));
  const current = Object.fromEntries(mu.current.map((c) => [c.cat, c]));
  const rows = mu.projected.map((p) => {
    const c = current[p.cat] || {};
    const callCls = p.call === "Likely win" ? "good" : p.call === "Likely loss" ? "bad" : "warn";
    return {
      cells: [
        p.cat,
        { node: fmt(p.cat, c.me), cls: c.leader === "me" ? "good" : "" },
        { node: fmt(p.cat, c.opp), cls: c.leader === "opp" ? "bad" : "" },
        fmt(p.cat, p.me),
        fmt(p.cat, p.opp),
        { node: [Math.round(p.p_win * 100) + "%", h("span", { class: "prob" }, h("span", { style: `width:${Math.round(p.p_win * 100)}%` }))] },
        { node: p.call, cls: callCls },
      ],
    };
  });
  const g = mu.games;
  return card(
    `Matchup ${mu.period}: ${mu.dates[0]} - ${mu.dates[1]}`,
    true,
    h("div", { class: "row" },
      h("div", {}, h("div", { class: "muted" }, mu.me.name + " vs " + mu.opp.name), h("div", { class: "big" }, `${score.wins}-${score.losses}-${score.ties}`)),
      h("div", {}, h("div", { class: "muted" }, "Projected"), h("div", { class: "big" }, mu.projected_record)),
      h("div", {}, h("div", { class: "muted" }, "Games left (usable)"), h("div", {}, `Me ${g.me.scheduled_remaining} (${g.me.usable_remaining}) · Opp ${g.opp.scheduled_remaining} (${g.opp.usable_remaining})`))
    ),
    h("div", { class: "chips" },
      mu.likely_wins.map((c) => h("span", { class: "chip good" }, "Win: " + c)),
      mu.swing.map((c) => h("span", { class: "chip warn" }, "Swing: " + c)),
      mu.likely_losses.map((c) => h("span", { class: "chip bad" }, "Loss: " + c))
    ),
    table(["Cat", "Me now", "Opp now", "Me proj", "Opp proj", "Win %", "Call"], rows),
    mu.attempts_estimated ? h("p", { class: "muted" }, "FGA/FTA so far are estimated from lineups (ESPN's matchup data has only the percentages).") : null
  );
}

function renderChanges(v) {
  const c = v.changes;
  let body;
  if (!c.since) body = h("p", { class: "muted" }, "First snapshot: changes appear from the next day.");
  else if (!c.bullets.length) body = h("p", { class: "muted" }, "Nothing important since " + v.meta.compared_with + ".");
  else body = h("ul", { class: "plain" }, c.bullets.slice(0, 20).map((b) => h("li", {}, b)));
  return card("Important changes since yesterday", false, body);
}

function renderAcquisitions(v) {
  const a = v.acquisitions;
  const ir = v.my_ir;
  return card(
    "Acquisitions, waivers, IR",
    false,
    a ? [h("div", { class: "row" }, h("span", { class: "big" }, `${a.used} / ${a.limit}`), h("span", { class: "muted" }, `used this matchup, ${a.remaining} left`)),
         h("div", { class: "meter" }, h("span", { style: `width:${Math.min(100, (a.used / a.limit) * 100)}%` }))] : null,
    h("h3", {}, "Waiver order"),
    h("ol", {}, v.waiver_order.map((w) => h("li", { class: w.is_me ? "good" : null }, w.team + (w.is_me ? " (you)" : "")))),
    ir ? [h("h3", {}, "IR"),
      ir.players.length ? h("ul", { class: "plain" }, ir.players.map((p) => h("li", {}, `${p.name}: ${p.health}${p.expected_return ? ", back ~" + p.expected_return : ""}`))) : h("p", { class: "muted" }, "IR slot empty"),
      ir.flags.map((f) => h("p", { class: "bad" }, f))] : null,
    h("p", { class: "muted" }, `C-eligible on roster: ${v.my_c_count} / ${v.meta.rules.c_limit}`)
  );
}

function renderAlerts(v) {
  if (!v.alerts.length) return card("Injury & role changes", false, h("p", { class: "muted" }, "Nothing detected."));
  const cls = { UP: "good", DOWN: "bad", INJURY: "bad", WATCH: "warn" };
  return card(
    "Injury & role changes",
    false,
    h("ul", { class: "plain" }, v.alerts.slice(0, 40).map((a) =>
      h("li", {},
        h("strong", {}, a.name), ` (${a.pro_team}) `,
        h("span", { class: "chip" }, a.owner), " ",
        h("span", { class: "chip " + (cls[a.trend] || "") }, a.trend),
        h("ul", { class: "alert-lines" }, a.lines.map((l) => h("li", {}, l)))
      )))
  );
}

function rosterRows(roster, withUsable) {
  return roster.map((r) => {
    const [line, mark] = statLine(r);
    return {
      cells: [
        r.name + mark, r.pro_team, r.positions, r.slot || "-", healthCell(r), r.gp,
        num(line && line.min), minutes(r.last5_min), trendCell(r.trend), ...statCells(line),
        num(r.roster_pct), r.games_remaining, withUsable ? (r.usable_remaining ?? "-") : null,
      ].filter((x) => x !== null),
    };
  });
}

const ROSTER_HEAD = ["Player", "Team", "Pos", "Slot", "Health", "GP", "MIN", "Last 5 MIN", "Trend", "FG%", "FT%", ...STATS.map(([l]) => l), "Ros%", "Games left"];

function renderMyRoster(v) {
  const t = v.my_team;
  if (!t) return card("My roster", true, h("p", { class: "bad" }, "Your team was not found. Set FANTASY_TEAM to its name."));
  return card(
    `My roster: ${t.name} (${t.record})`,
    true,
    table([...ROSTER_HEAD, "Usable"], rosterRows(t.roster, true), { textCols: [0, 1, 2, 3, 4] }),
    h("p", { class: "muted" }, "Season per-game averages; * = ESPN projection (no games yet). Hover a health cell for the injury note.")
  );
}

function renderSchedule(v) {
  const days = v.schedule.days;
  if (!days.length) return card("Schedule", true, h("p", { class: "muted" }, "No games left in this matchup."));
  const rows = days.map((d) => ({
    cells: [
      d.label,
      d.nba_games,
      { node: d.volume, cls: d.volume === "low" ? "warn" : d.volume === "high" ? "good" : "" },
      { node: `${d.my_playing.length}: ${d.my_playing.join(", ") || "-"}`, cls: "" },
      { node: `${d.my_open_slots}${d.my_open_slot_names.length ? " (" + d.my_open_slot_names.join(", ") + ")" : ""}`, cls: d.my_open_slots > 0 ? "good" : "" },
      d.my_benched.join(", ") || "-",
      d.my_out.join(", ") || "-",
      d.opp_playing,
      d.opp_open_slots ?? "-",
    ],
  }));
  return card(
    "Schedule: remaining days",
    true,
    table(["Day", "NBA games", "Volume", "My players playing", "My open slots", "Benched (no slot)", "Out", "Opp playing", "Opp open"], rows, { textCols: [0, 3, 5, 6], wrapCols: [3] })
  );
}

function renderFreeAgents(v) {
  const rows = v.free_agents.map((r, i) => {
    const [line, mark] = statLine(r);
    const status = r.pool_status === "WAIVERS" ? "WA" : "FA";
    return {
      cells: [
        i + 1, r.name + mark, r.pro_team, r.positions, status, healthCell(r), num(r.roster_pct), signed(r.roster_pct_change),
        num(r.projected_min), minutes(r.last5_min), `${r.last5_starts}/${r.last5_min.length}`, trendCell(r.trend),
        ...statCells(line), `${r.usable_remaining}/${r.games_remaining}`, r.reasons.join("; "),
      ],
    };
  });
  return card(
    "Top free agents (by interest, not ESPN rank)",
    true,
    table(["#", "Player", "Team", "Pos", "St", "Health", "Ros%", "+/-", "Proj MIN", "Last 5 MIN", "Starts", "Trend", "FG%", "FT%", ...STATS.map(([l]) => l), "Usable", "Why"], rows, { textCols: [1, 2, 3, 4, 5], wrapCols: [21] })
  );
}

function renderPopular(v) {
  return card(
    "Most rostered free agents",
    false,
    table(["Player", "Team", "Pos", "Health", "Ros%", "+/-"], v.popular_free_agents.map((r) => ({ cells: [r.name, r.pro_team, r.positions, r.health, num(r.roster_pct), signed(r.roster_pct_change)] })), { textCols: [0, 1, 2, 3] })
  );
}

function renderTransactions(v) {
  const rows = v.transactions;
  if (!rows.length) return card("Transactions (7 days)", false, h("p", { class: "muted" }, "None."));
  return card(
    "Transactions (7 days)",
    false,
    h("ul", { class: "plain" }, rows.map((t) => {
      const actions = [...t.adds.map((n) => "ADD " + n), ...t.drops.map((n) => "DROP " + n), ...t.trades.map((n) => "TRADE " + n)];
      return h("li", {},
        t.new ? h("span", { class: "chip warn" }, "NEW") : null, " ",
        h("strong", {}, t.team), ": ", actions.join(", ") || "-",
        h("div", { class: "muted" }, `${new Date(t.ts).toLocaleString()} · ${t.source}${t.result ? " · " + t.result : ""}`)
      );
    }))
  );
}

function renderStrength(v) {
  const cats = v.meta.categories;
  const teams = [...v.teams].sort((a, b) => avgRank(a) - avgRank(b));
  const rows = teams.map((t) => ({
    cls: t.is_me ? "mine" : null,
    cells: [
      t.name + (t.is_me ? " (me)" : t.is_opp ? " (opp)" : ""),
      ...cats.map((c) => {
        const rank = t.strength.ranks[c];
        const value = t.strength.values[c];
        return { node: rank ?? "-", cls: rank ? "rank-" + rank : "", title: c.endsWith("%") ? pct(value) : num(value) };
      }),
      num(avgRank(t)),
    ],
  }));
  return card("Category strength (rank 1 = best, projected per game)", true, table(["Team", ...cats, "Avg"], rows, { textCols: [0] }));
}

function avgRank(t) {
  const ranks = Object.values(t.strength.ranks);
  return ranks.length ? ranks.reduce((a, b) => a + b, 0) / ranks.length : 99;
}

function renderTeams(v) {
  return card(
    "League rosters",
    true,
    v.teams.filter((t) => !t.is_me).map((t) =>
      h("details", { class: "team", open: t.is_opp ? true : null },
        h("summary", {}, `${t.name}${t.is_opp ? " (opponent)" : ""} · ${t.record} · waiver #${t.waiver_rank ?? "-"} · acq ${t.acquisitions.used}/${t.acquisitions.limit} · games left ${t.games_remaining}`),
        table(ROSTER_HEAD, rosterRows(t.roster, false), { textCols: [0, 1, 2, 3, 4] })
      ))
  );
}


const VALUE_LABELS = { PTS: "pV", "3PM": "3V", REB: "rV", AST: "aV", STL: "sV", BLK: "bV", "FG%": "fg%V", "FT%": "ft%V", TO: "toV" };
const rankState = { range: null, owner: "all", pos: "all", search: "", punt: null };

function valueCell(v) {
  if (v === null || v === undefined) return "-";
  const cls = v >= 1 ? "v-pos2" : v >= 0.25 ? "v-pos" : v <= -1 ? "v-neg2" : v <= -0.25 ? "v-neg" : "";
  return { node: signed(v, 2), cls };
}

function rankedRows(view) {
  const r = view.rankings;
  const cats = r.categories;
  const punt = rankState.punt;
  const counted = cats.filter((c) => !punt.has(c));
  const use = counted.length ? counted : cats;
  const rows = (r.rows[rankState.range] || []).map((row) => ({
    ...row,
    punt_value: use.reduce((sum, c) => sum + (row.values[c] ?? 0), 0) / use.length,
  }));
  rows.sort((a, b) => b.punt_value - a.punt_value || a.name.localeCompare(b.name));
  const teams = view.meta.teams || 10;
  rows.forEach((row, i) => { row.live_rank = i + 1; row.live_round = Math.floor(i / teams) + 1; });
  const q = rankState.search.trim().toLowerCase();
  return rows.filter((row) => {
    if (rankState.owner === "fa" && !["FA", "WA"].includes(row.owner_short)) return false;
    if (rankState.owner === "me" && row.owner_short !== "ME") return false;
    if (rankState.owner === "rostered" && ["FA", "WA"].includes(row.owner_short)) return false;
    if (rankState.pos !== "all" && !row.positions.split("/").includes(rankState.pos)) return false;
    if (q && !row.name.toLowerCase().includes(q)) return false;
    return true;
  });
}

function renderRankings(view) {
  const r = view.rankings;
  if (!rankState.range || !r.rows[rankState.range]) rankState.range = r.default;
  if (!rankState.punt) rankState.punt = new Set(view.meta.punt || []);
  const cats = r.categories;
  const body = h("div", {});
  const select = (options, value, onChange) => {
    const el = h("select", {}, options.map(([v, label]) => h("option", { value: v, selected: v === value ? true : null }, label)));
    el.addEventListener("change", () => { onChange(el.value); draw(); });
    return el;
  };
  const search = h("input", { type: "search", placeholder: "Search players", value: rankState.search });
  search.addEventListener("input", () => { rankState.search = search.value; draw(); });
  const puntBoxes = cats.map((c) => {
    const box = h("input", { type: "checkbox", checked: rankState.punt.has(c) ? true : null });
    box.addEventListener("change", () => { box.checked ? rankState.punt.add(c) : rankState.punt.delete(c); draw(); });
    return h("label", { class: "toggle" }, box, c);
  });
  const controls = h("div", { class: "controls" },
    select(r.ranges.filter((x) => x.players > 0).map((x) => [x.key, x.label]), rankState.range, (v) => { rankState.range = v; }),
    select([["all", "All players"], ["fa", "Free agents"], ["me", "My team"], ["rostered", "Rostered"]], rankState.owner, (v) => { rankState.owner = v; }),
    select([["all", "All positions"], ...["PG", "SG", "SF", "PF", "C"].map((p) => [p, p])], rankState.pos, (v) => { rankState.pos = v; }),
    search
  );
  const puntRow = h("div", { class: "controls" }, h("span", { class: "muted" }, "Punt:"), puntBoxes);

  function draw() {
    const rows = rankedRows(view).slice(0, 200).map((row) => ({
      cls: row.owner_short === "ME" ? "mine" : null,
      cells: [
        row.live_round, row.live_rank, valueCell(row.punt_value), valueCell(row.league_value),
        row.name, row.pro_team, row.positions, row.owner_short, row.injury || "-", row.gp,
        num(row.min), num(row.pts), num(row.tpm), num(row.reb), num(row.ast), num(row.stl), num(row.blk),
        pct(row.fg_pct), num(row.fga), pct(row.ft_pct), num(row.fta), num(row.to), num(row.usage_proxy),
        ...cats.map((c) => valueCell(row.values[c])),
      ],
    }));
    body.replaceChildren(table(
      ["Rnd", "Rank", "Value", "LeagV", "Name", "Team", "Pos", "Owner", "Inj", "G", "MIN", "PTS", "3PM", "REB", "AST", "STL", "BLK", "FG%", "FGA", "FT%", "FTA", "TO", "USG~", ...cats.map((c) => VALUE_LABELS[c] || c)],
      rows,
      { textCols: [4, 5, 6, 7, 8], tall: true }
    ));
  }
  draw();
  return card(
    "Player rankings",
    true,
    controls,
    puntRow,
    body,
    h("p", { class: "muted" }, "Values are per-game z-scores against the rostered players (about +1 first round, 0 the edge of rosterable). Value leaves out punted categories; LeagV counts all. USG~ is a usage proxy: (FGA + 0.44 FTA + TO) per 36 minutes. Owner: ME, OPP, team abbreviation, FA or WA.")
  );
}

let settingsData = null;

function renderSettings(open) {
  const s = settingsData || {};
  const field = (label, input, hint) => h("label", { class: "field" }, h("span", {}, label), input, hint ? h("small", { class: "muted" }, hint) : null);
  const url = h("input", { type: "url", placeholder: "https://fantasy.espn.com/basketball/team?leagueId=...&teamId=...", autocomplete: "off" });
  const s2 = h("input", { type: "password", placeholder: s.has_espn_s2 ? "saved (leave empty to keep)" : "espn_s2 cookie", autocomplete: "off" });
  const swid = h("input", { type: "password", placeholder: s.has_swid ? "saved (leave empty to keep)" : "SWID cookie, {...}", autocomplete: "off" });
  const team = h("input", { type: "text", value: s.team || "" });
  const punt = h("input", { type: "text", value: (s.punt || []).join(", "), placeholder: "e.g. TO" });
  const status = h("p", { class: "muted" },
    s.league_id ? `League ${s.league_id}, season ${s.season}, team "${s.team}", cookies ${s.has_espn_s2 && s.has_swid ? "saved" : "missing"}.` : "No league set yet.");
  const save = h("button", { type: "button", class: "primary" }, "Save settings");
  save.addEventListener("click", async () => {
    const form = { team: team.value, punt: punt.value };
    if (url.value.trim()) form.league_url = url.value.trim();
    if (s2.value.trim()) form.espn_s2 = s2.value.trim();
    if (swid.value.trim()) form.swid = swid.value.trim();
    const res = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    const data = await res.json();
    if (!res.ok) { setStatus(data.error || "Saving failed.", "error"); return; }
    settingsData = data.settings;
    setStatus("Settings saved to .dev.vars.", "ok");
    rankState.punt = null;
    render(data.view, settingsData.demo);
  });
  return h("details", { class: "card wide settings", open: open ? true : null },
    h("summary", {}, "League settings"),
    h("p", { class: "muted" }, "Open your team page on fantasy.espn.com and copy its address: it carries the league, team and season ids. The two cookies come from the browser while logged in: press F12, then Application (Chrome/Edge) or Storage (Firefox), Cookies, espn.com, and copy espn_s2 and SWID. ESPN has no API key; these cookies are what give read access to a private league. They are saved only in .dev.vars on this computer."),
    h("div", { class: "form" },
      field("League or team page URL", url),
      field("espn_s2", s2),
      field("SWID", swid),
      field("Your team", team, "Name, abbreviation or team id; the URL's teamId is used when empty."),
      field("Punt categories", punt, "Comma-separated, e.g. TO or TO, FT%. Values and rankings leave them out.")
    ),
    save,
    status
  );
}

function render(view, demo) {
  const app = $("app");
  app.replaceChildren();
  $("demo-banner").hidden = !demo;
  if (!view) {
    app.append(
      card("Start here", true, h("p", {}, "Fill in League settings below, press Refresh to read your league from ESPN and save today's snapshot, then copy the report into ChatGPT.")),
      renderSettings(!(settingsData && settingsData.league_id))
    );
    $("copy").disabled = true;
    $("preview-card").hidden = true;
    return;
  }
  const m = view.meta;
  $("subtitle").textContent = `${m.league} · ${m.my_team || "team not found"} · snapshot ${m.fetched_at}` + (m.compared_with ? ` · vs ${m.compared_with}` : "");
  app.append(
    renderMatchup(view),
    renderChanges(view),
    renderAcquisitions(view),
    renderAlerts(view),
    renderMyRoster(view),
    renderSchedule(view),
    renderFreeAgents(view),
    renderTransactions(view),
    renderPopular(view),
    renderStrength(view),
    renderRankings(view),
    renderTeams(view),
    renderSettings(false)
  );
  if (m.warnings && m.warnings.length) setStatus("Warnings: " + m.warnings.join(" | "));
  loadReport();
}

async function loadReport() {
  const compact = $("compact").checked ? "1" : "0";
  const res = await fetch("/api/report?compact=" + compact);
  if (!res.ok) return;
  reportText = await res.text();
  $("report-text").value = reportText;
  $("preview-card").hidden = false;
  $("copy").disabled = false;
}

async function loadState() {
  settingsData = await (await fetch("/api/settings")).json();
  const res = await fetch("/api/state");
  const data = await res.json();
  render(data.view, data.demo);
}

async function refresh() {
  const button = $("refresh");
  button.disabled = true;
  setStatus("Reading the league from ESPN... this takes a few seconds.");
  try {
    const res = await fetch("/api/refresh", { method: "POST" });
    const data = await res.json();
    if (!res.ok) {
      setStatus(data.error || "Refresh failed.", "error");
      return;
    }
    setStatus("Snapshot saved.", "ok");
    render(data.view, data.demo);
  } catch (err) {
    setStatus("Refresh failed: " + err, "error");
  } finally {
    button.disabled = false;
  }
}

async function copyReport() {
  if (!reportText) return;
  try {
    await navigator.clipboard.writeText(reportText);
  } catch {
    // Older browsers or a denied permission: copy from the selected textarea.
    const area = $("report-text");
    $("preview-card").open = true;
    area.select();
    document.execCommand("copy");
  }
  setStatus(`Report copied (${reportText.length.toLocaleString()} characters). Paste it into ChatGPT.`, "ok");
}

$("refresh").addEventListener("click", refresh);
$("copy").addEventListener("click", copyReport);
$("compact").addEventListener("change", loadReport);
loadState().catch((err) => setStatus("Could not load the dashboard: " + err, "error"));
