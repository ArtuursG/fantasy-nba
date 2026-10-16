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
// Percentages the box-score way: .452, 1.000.
const pct = (v) => (v === null || v === undefined ? "-" : Number(v).toFixed(3).replace(/^0\./, "."));
const signed = (v, d = 1) => (v === null || v === undefined ? "-" : (v >= 0 ? "+" : "") + Number(v).toFixed(d));
const percent = (p) => Math.round(p * 100) + "%";
const STATS = [["3PM", "tpm"], ["REB", "reb"], ["AST", "ast"], ["STL", "stl"], ["BLK", "blk"], ["TO", "to"], ["PTS", "pts"]];
const CALL_CLASS = { "Likely win": "good", "Likely loss": "bad" };

let reportText = "";
// Set by static/data.js when the dashboard is hosted as static files
// (`fantasy export`): no server, so no refresh, settings or trade evaluator.
const STATIC = window.FANTASY_STATIC || null;

function setStatus(text, kind) {
  const el = $("status");
  el.textContent = text || "";
  el.className = "status" + (kind ? " " + kind : "");
}

// size: false = half width, true = full width, "third".
function card(title, size, ...body) {
  const cls = size === true ? "panel wide" : size === "third" ? "panel third" : "panel";
  return h("section", { class: cls }, h("h2", {}, title), body);
}

function stat(label, value, cls) {
  return h("div", { class: "stat" }, h("span", { class: "stat-label" }, label), h("span", { class: "stat-value" + (cls ? " " + cls : "") }, value));
}

function stats(...items) {
  return h("div", { class: "stats" }, items);
}

function tag(text, cls) {
  return h("span", { class: "chip" + (cls ? " " + cls : "") }, text);
}

function probBar(p, cls) {
  return h("span", { class: "prob" + (cls ? " " + cls : "") }, h("span", { style: `width:${Math.round(p * 100)}%` }));
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
  const tbody = h("tbody", {}, body);
  makeSortable(head, tbody);
  return h("div", { class: opts.tall ? "scroll tall" : "scroll" }, h("table", {}, h("thead", {}, head), tbody));
}

// Click a column header to sort: numbers largest first, text A-Z; click
// again to reverse. Empty cells ("-") always go last.
function sortKey(text) {
  const t = text.trim().replace(/\u2212/g, "-");
  if (t === "" || t === "-") return null;
  const m = t.match(/^[+-]?(\d+\.?\d*|\.\d+)/);
  return m ? parseFloat(m[0]) : t.toLowerCase();
}

function makeSortable(head, tbody) {
  const ths = [...head.children];
  ths.forEach((th, col) => {
    th.classList.add("sortable");
    th.title = "Sort";
    th.addEventListener("click", () => {
      const rows = [...tbody.children];
      const keys = new Map(rows.map((r) => [r, sortKey(r.children[col] ? r.children[col].textContent : "")]));
      const numeric = rows.some((r) => typeof keys.get(r) === "number");
      const was = th.getAttribute("aria-sort");
      const dir = was ? (was === "descending" ? "ascending" : "descending") : numeric ? "descending" : "ascending";
      ths.forEach((x) => x.removeAttribute("aria-sort"));
      th.setAttribute("aria-sort", dir);
      const sign = dir === "ascending" ? 1 : -1;
      rows.sort((a, b) => {
        const x = keys.get(a), y = keys.get(b);
        if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
        if (typeof x !== typeof y) return typeof x === "number" ? -1 : 1;
        return (typeof x === "number" ? x - y : x.localeCompare(y)) * sign;
      });
      tbody.append(...rows);
    });
  });
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
  // Healthy players get a blank cell so the injured ones stand out.
  if (!bad && !warn && row.health === "Healthy") return "";
  return { node: tag(row.health, bad ? "bad" : warn ? "warn" : ""), title: row.injury_note || null };
}

function trendCell(trend) {
  if (trend === "UP") return { node: "▲ up", cls: "good" };
  if (trend === "DOWN") return { node: "▼ down", cls: "bad" };
  return { node: trend === "-" || !trend ? "-" : trend.toLowerCase(), cls: "muted" };
}

function minutes(list) {
  return list && list.length ? list.map((m) => m.toFixed(0)).join(" ") : "-";
}

function renderScoreboard(v) {
  const mu = v.matchup;
  if (!mu) return card("Matchup", true, h("p", { class: "muted" }, "No current matchup (off week, or your team was not found)."));
  const score = mu.score_now;
  const fmt = (cat, x) => (x === null || x === undefined ? "-" : cat.endsWith("%") ? pct(x) : num(x, 0));
  const current = Object.fromEntries(mu.current.map((c) => [c.cat, c]));
  const daysLeft = v.schedule.days.length;
  const g = mu.games;
  const cells = mu.projected.map((p) => {
    const c = current[p.cat] || {};
    const call = p.call === "Likely win" ? "win" : p.call === "Likely loss" ? "loss" : "swing";
    return h("div", { class: "sb-cat " + call, title: `${p.call}. Projected ${fmt(p.cat, p.me)} vs ${fmt(p.cat, p.opp)}` },
      h("div", { class: "sb-cat-name" }, p.cat),
      h("div", { class: "sb-cat-now" },
        h("span", { class: c.leader === "me" ? "lead" : null }, fmt(p.cat, c.me)),
        h("span", { class: c.leader === "opp" ? "lead" : null }, fmt(p.cat, c.opp))),
      h("div", { class: "sb-cat-p" }, h("span", { class: "bar-track" }, h("span", { class: "bar-fill", style: `width:${Math.round(p.p_win * 100)}%` })), percent(p.p_win))
    );
  });
  return h("section", { class: "scoreboard", "aria-label": "Current matchup" },
    h("div", { class: "sb-head" },
      h("span", {}, `Matchup ${mu.period} · ${mu.dates[0]} – ${mu.dates[1]}`),
      h("span", { class: "live" }, daysLeft ? `${daysLeft} day${daysLeft === 1 ? "" : "s"} left` : "Final day")),
    h("div", { class: "sb-main" },
      h("div", { class: "sb-team" }, mu.me.name, h("small", {}, "You")),
      h("div", { class: "sb-score", "aria-label": `${score.wins} wins, ${score.losses} losses, ${score.ties} ties` },
        String(score.wins), h("span", { class: "sep" }, "–"), String(score.losses), h("span", { class: "sep" }, "–"), h("span", { class: "tie" }, String(score.ties))),
      h("div", { class: "sb-team opp" }, mu.opp.name, h("small", {}, "Opponent"))),
    h("div", { class: "sb-facts" },
      h("span", {}, "Projected ", h("b", {}, mu.projected_record)),
      h("span", {}, "Win chance ", h("b", {}, percent(mu.outlook.p_win_matchup))),
      h("span", {}, "Expected ", h("b", {}, `${mu.outlook.expected_wins.toFixed(1)} of ${mu.outlook.categories}`), " cats"),
      h("span", {}, "Games ", h("b", {}, `${num(g.me.expected_total)} vs ${num(g.opp.expected_total)}`), ` expected (${g.me.played} and ${g.opp.played} played)`)),
    h("div", { class: "sb-cats" }, cells),
    h("div", { class: "sb-legend" }, "Each column: you, then the opponent, so far this week. The bar is your chance to win the category by the end of the week.")
  );
}

function renderMatchup(v) {
  const mu = v.matchup;
  if (!mu) return null;
  const fmt = (cat, x) => (cat.endsWith("%") ? pct(x) : num(x, 0));
  const current = Object.fromEntries(mu.current.map((c) => [c.cat, c]));
  const rows = mu.projected.map((p) => {
    const c = current[p.cat] || {};
    const callCls = CALL_CLASS[p.call] || "warn";
    return {
      cells: [
        { node: p.cat, cls: "strong" },
        { node: fmt(p.cat, c.me), cls: c.leader === "me" ? "good" : "" },
        { node: fmt(p.cat, c.opp), cls: c.leader === "opp" ? "bad" : "" },
        fmt(p.cat, p.me),
        fmt(p.cat, p.opp),
        { node: [percent(p.p_win), probBar(p.p_win, callCls)] },
        { node: p.call, cls: callCls },
      ],
    };
  });
  return card(
    `This week vs ${mu.opp.name}`,
    false,
    h("div", { class: "chips" },
      mu.likely_wins.map((c) => tag("Win " + c, "good")),
      mu.swing.map((c) => tag("Swing " + c, "warn")),
      mu.likely_losses.map((c) => tag("Loss " + c, "bad"))
    ),
    table(["Cat", "Me now", "Opp now", "Me proj", "Opp proj", "Win %", "Call"], rows),
    mu.attempts_estimated ? h("p", { class: "note" }, "FGA/FTA so far are estimated from lineups (ESPN's matchup data has only the percentages).") : null
  );
}

function renderTargets(v) {
  const mu = v.matchup;
  if (!mu || !mu.targets || !mu.targets.length) return null;
  const rows = mu.targets.map((t) => {
    const isPct = t.cat.endsWith("%");
    const f = (x) => (isPct ? pct(x) : Number(x).toFixed(1));
    const fewer = t.cat === "TO" ? " fewer" : "";
    return {
      cells: [
        t.cat,
        Math.round(t.p_win * 100) + "%",
        signed(t.edge, isPct ? 3 : 1),
        t.to_even ? f(t.to_even) + fewer : "0",
        f(t.to_likely) + fewer + (isPct && t.makes_to_likely !== null ? ` (~${Math.round(t.makes_to_likely)} makes)` : ""),
        Number(t.per_game).toFixed(2) + (isPct ? " makes" : ""),
      ],
    };
  });
  return card(
    "What it takes",
    false,
    h("p", { class: "note" }, "How much more you need in each category you're not yet likely to win, over the rest of the week."),
    table(["Cat", "Win %", "Edge", "To draw even", "To 70%", "Per game left"], rows)
  );
}

function renderWhatIf(v) {
  const w = v.what_if;
  if (!w || !w.adds.length || !w.drops.length) return null;
  const adds = [...w.adds].sort((a, b) => b.value - a.value);
  const label = (p) => `${p.name} (${p.team}${p.health !== "ACTIVE" && p.health !== "NORMAL" ? ", " + (p.health === "DAY_TO_DAY" ? "DTD" : p.health) : ""}) ${signed(p.value, 2)}${p.waiver_until ? " · waivers to " + p.waiver_until : ""}`;
  const search = h("input", { type: "search", placeholder: "Search free agents" });
  const addSel = h("select", { "aria-label": "Add" });
  const dropSel = h("select", { "aria-label": "Drop" }, w.drops.map((p) => h("option", { value: p.id }, label(p))));
  const fillAdds = () => {
    const q = search.value.trim().toLowerCase();
    const keep = addSel.value;
    addSel.replaceChildren(...adds.filter((p) => !q || p.name.toLowerCase().includes(q)).map((p) => h("option", { value: p.id, selected: String(p.id) === keep ? true : null }, label(p))));
  };
  const out = h("div", {});
  const change = (x, d = 0, pctUnit = false) => {
    const val = pctUnit ? Math.round(x * 100) : x;
    return { node: (val > 0 ? "+" : "") + (pctUnit ? val + " pts" : Number(val).toFixed(d)), cls: val > 0 ? "good" : val < 0 ? "bad" : "" };
  };
  const draw = () => {
    const r = w.results[`${addSel.value}:${dropSel.value}`];
    if (!r) { out.replaceChildren(h("p", { class: "note" }, "No free agent matches.")); return; }
    const [pMatch, expWins, usable, expGames] = r;
    const pCats = r.slice(w.columns.length);
    const b = w.base;
    const diff = Math.round(pMatch * 100) - Math.round(b.p_win_matchup * 100);
    out.replaceChildren(
      stats(
        stat("Matchup win chance", `${percent(b.p_win_matchup)} → ${percent(pMatch)}`, diff > 0 ? "good" : diff < 0 ? "bad" : ""),
        stat("Expected categories", `${b.expected_wins.toFixed(1)} → ${expWins.toFixed(1)}`),
        stat("Usable games", `${b.usable} → ${b.usable + usable}`),
        stat("Expected games", `${num(b.expected_games)} → ${num(b.expected_games + expGames)}`)
      ),
      table(["Cat", "Now", "After", "Change", "Call after"], w.categories.map((cat, i) => {
        const after = pCats[i];
        const callAfter = after >= 0.7 ? "Likely win" : after <= 0.3 ? "Likely loss" : "Swing";
        return { cells: [{ node: cat, cls: "strong" }, percent(b.p_win[i]), { node: [percent(after), probBar(after, CALL_CLASS[callAfter] || "warn")] }, change(after - b.p_win[i], 0, true), { node: callAfter, cls: CALL_CLASS[callAfter] || "warn" }] };
      }))
    );
  };
  search.addEventListener("input", () => { fillAdds(); draw(); });
  addSel.addEventListener("change", draw);
  dropSel.addEventListener("change", draw);
  fillAdds();
  draw();
  return card(
    "What if: try a pickup",
    true,
    h("p", { class: "note" }, "Pick a free agent to add and a player to drop. The rest of this matchup is projected again with him in your lineup from the day he can play; games already played stay as they are."),
    h("div", { class: "form" },
      h("label", { class: "field" }, h("span", {}, "Add"), search, addSel),
      h("label", { class: "field" }, h("span", {}, "Drop"), dropSel)
    ),
    out
  );
}

function renderGameCounts(v) {
  const rows = v.game_counts;
  if (!rows || !rows.length) return null;
  const injuries = rows.slice(0, 2).filter((r) => r.injuries.length).map((r) =>
    h("p", { class: "note" }, h("strong", {}, r.team + ": "),
      r.injuries.map((i) => `${i.name} ${i.status === "DAY_TO_DAY" ? "DTD" : i.status} (${i.games} g, −${num(i.lost)})`).join(" · ")));
  return card(
    "Games this week",
    true,
    h("p", { class: "note" }, "Played so far plus the games left that fit a starting slot, each weighted by the chance the player plays: DTD 70% today and tomorrow and 85% after, questionable 50%, doubtful 20%, OUT 0 until his expected return."),
    table(
      ["Team", "Opponent", "Played", "Left", "Expected", "Total", "Edge", "Lost to OUT", "Uncertain", "No slot"],
      rows.map((r, i) => ({
        cls: r.is_me ? "mine" : i % 2 === 1 ? "pair-end" : null,
        cells: [
          { node: r.team, cls: "strong" }, r.opponent || "-", r.played, r.usable_remaining, num(r.expected_remaining),
          { node: num(r.expected_total), cls: "strong" },
          { node: signed(r.edge), cls: r.edge >= 1 ? "good" : r.edge <= -1 ? "bad" : "" },
          { node: r.out_games, cls: r.out_games ? "bad" : "" },
          { node: r.uncertain_games, cls: r.uncertain_games ? "warn" : "" },
          r.no_slot_games,
        ],
      })),
      { textCols: [0, 1] }
    ),
    injuries
  );
}

function renderSimulator(v) {
  const sim = v.moves;
  if (!sim || !sim.moves.length) return null;
  const rows = sim.moves.map((m) => ({
    cells: [
      m.add, m.add_team, m.drop, m.waiver_until || "now",
      { node: (m.usable_change > 0 ? "+" : "") + m.usable_change, cls: m.usable_change > 0 ? "good" : m.usable_change < 0 ? "bad" : "" },
      { node: signed(m.expected_wins_change, 2), cls: m.expected_wins_change > 0.05 ? "good" : m.expected_wins_change < -0.05 ? "bad" : "" },
      `${Math.round(m.p_win_after * 100)}% (${m.p_win_change >= 0 ? "+" : ""}${Math.round(m.p_win_change * 100)})`,
      m.category_changes.slice(0, 3).map((c) => `${c.cat} ${c.change >= 0 ? "+" : ""}${Math.round(c.change * 100)}%`).join(", ") || "-",
      valueCell(m.value_change),
    ],
  }));
  return card(
    "Add/drop simulator",
    true,
    h("p", { class: "note" }, `Now: ${sim.base.expected_wins.toFixed(1)} expected categories, ${Math.round(sim.base.p_win_matchup * 100)}% matchup win chance. Each free agent replaces the weakest player he helps most to drop (${sim.drop_candidates.join(", ")}). Acquisitions left: ${sim.acquisitions_left ?? "?"}.`),
    sim.acquisitions_left === 0 ? h("p", { class: "bad" }, "No acquisitions left this matchup.") : null,
    table(["Add", "Team", "Drop", "Playable", "Usable games", "Exp. cats", "Matchup win %", "Biggest changes", "Season value"], rows, { textCols: [0, 1, 2, 3, 7] })
  );
}

function renderStreamPlan(v) {
  const plan = v.stream_plan;
  if (!plan) return null;
  const pctText = (x) => Math.round(x * 100) + "%";
  if (!plan.steps.length) {
    return card("Streaming plan", false, h("p", { class: "muted" }, plan.acquisitions_left ? "No pickup adds enough to be worth an acquisition right now." : "No acquisitions left this matchup."));
  }
  return card(
    "Streaming plan",
    true,
    stats(
      stat("Expected categories", `${plan.base.expected_wins.toFixed(1)} → ${plan.final.expected_wins.toFixed(1)}`),
      stat("Matchup win chance", `${pctText(plan.base.p_win_matchup)} → ${pctText(plan.final.p_win_matchup)}`, "good"),
      stat("Usable games", `${plan.usable_before} → ${plan.usable_after}`),
      stat("Acquisitions", `${plan.steps.length} / ${plan.acquisitions_left}`)
    ),
    h("ol", { class: "steps" }, plan.steps.map((s) => h("li", {},
      h("strong", {}, s.day), ` · ${s.waiver ? "claim" : "add"} ${s.add} (${s.add_team}), drop ${s.drop}${s.drop_is_streamer ? " (streamer)" : ""}`,
      h("div", { class: "muted" }, `${signed(s.gain, 2)} expected cats · usable games ${s.usable_games_added >= 0 ? "+" : ""}${s.usable_games_added}`)))),
    table(["Cat", "Now", "With plan"], plan.categories.map((c) => ({ cells: [c.cat, pctText(c.before), { node: pctText(c.after), cls: c.after > c.before + 0.02 ? "good" : c.after < c.before - 0.02 ? "bad" : "" }] }))),
    h("p", { class: "note" }, `Only the weakest players are dropped (${plan.droppable.join(", ")}) or streamers the plan added. Re-check daily.`)
  );
}

function renderStrategy(v) {
  const st = v.strategy;
  if (!st) return null;
  const cls = { Chase: "good", Protect: "warn", Locked: "", Concede: "bad", Hold: "warn", Punted: "" };
  return card(
    "Category strategy",
    false,
    h("div", { class: "chips" }, st.categories.map((r) => tag(`${r.plan} ${r.cat}`, cls[r.plan]))),
    table(["Cat", "Win %", "Plan", "Per streamer game"], st.categories.map((r) => ({ cells: [r.cat, Math.round(r.p_win * 100) + "%", r.plan, (r.leverage >= 0 ? "+" : "") + (r.leverage * 100).toFixed(1) + " pts"] }))),
    st.best_fits.length ? h("p", { class: "note" }, "Best fits for the chase categories: " + st.best_fits.map((f) => f.name + (f.helps.length ? ` (${f.helps.join(", ")})` : "")).join(", ")) : null
  );
}

function renderNextMatchup(v) {
  const nm = v.next_matchup;
  if (!nm) return null;
  const fmt = (cat, x) => (cat.endsWith("%") ? pct(x) : num(x, 0));
  return card(
    `Next week: vs ${nm.opponent}, ${nm.dates[0]} – ${nm.dates[1]}`,
    true,
    stats(
      stat("Win chance", percent(nm.outlook.p_win_matchup)),
      stat("Expected categories", `${nm.outlook.expected_wins.toFixed(1)} / ${nm.outlook.categories}`),
      stat("Usable games", `${nm.games.me.usable} vs ${nm.games.opp.usable}`),
      stat("Scheduled", `${nm.games.me.scheduled} vs ${nm.games.opp.scheduled}`)
    ),
    table(["Cat", "My proj", "Opp proj", "Win %", "Call", "My rank", "Opp rank"], nm.projected.map((p) => {
      const callCls = CALL_CLASS[p.call] || "warn";
      const rank = (r) => ({ node: r ?? "-", cls: r ? "rank-" + r : "" });
      return { cells: [{ node: p.cat, cls: "strong" }, fmt(p.cat, p.me), fmt(p.cat, p.opp), { node: [percent(p.p_win), probBar(p.p_win, callCls)] }, { node: p.call, cls: callCls }, rank(nm.ranks[p.cat]?.me), rank(nm.ranks[p.cat]?.opp)] };
    })),
    h("h3", {}, "Days"),
    table(["Day", "NBA games", "Volume", "My players", "My open slots", "Opp playing"], nm.days.map((d) => ({ cells: [d.label, d.nba_games, d.volume, d.my_playing.length, { node: d.my_open_slots, cls: d.my_open_slots > 0 ? "good" : "" }, d.opp_playing] })))
  );
}

function renderTrade(v) {
  const me = v.my_team;
  if (!me) return null;
  const others = v.teams.filter((t) => !t.is_me);
  const result = h("div", {});
  const giveBoxes = me.roster.map((r) => {
    const box = h("input", { type: "checkbox", value: r.id });
    return [box, h("label", { class: "toggle" }, box, `${r.name} (${signed(r.value, 2)})`)];
  });
  const partner = h("select", {}, others.map((t) => h("option", { value: t.id }, t.name)));
  const getList = h("div", { class: "picklist" });
  let getBoxes = [];
  const drawPartner = () => {
    const team = others.find((t) => String(t.id) === partner.value) || others[0];
    getBoxes = team.roster.map((r) => {
      const box = h("input", { type: "checkbox", value: r.id });
      return [box, h("label", { class: "toggle" }, box, `${r.name} (${signed(r.value, 2)})`)];
    });
    getList.replaceChildren(...getBoxes.map(([, label]) => label));
  };
  partner.addEventListener("change", drawPartner);
  drawPartner();
  const go = h("button", { type: "button", class: "primary" }, "Evaluate trade");
  go.addEventListener("click", async () => {
    const give = giveBoxes.filter(([b]) => b.checked).map(([b]) => Number(b.value));
    const get = getBoxes.filter(([b]) => b.checked).map(([b]) => Number(b.value));
    const res = await fetch("/api/trade", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ give, get }) });
    const data = await res.json();
    if (!res.ok) { result.replaceChildren(h("p", { class: "bad" }, data.error || "Evaluation failed.")); return; }
    const rankCell = (b, a) => ({ node: `${b ?? "-"} → ${a ?? "-"}`, cls: a < b ? "good" : a > b ? "bad" : "" });
    const fmt = (cat, x) => (cat.endsWith("%") ? pct(x) : num(x));
    const mu = data.matchup;
    result.replaceChildren(
      h("h3", {}, "Verdict"),
      stats(
        stat("Value to me", signed(data.value_change, 2), data.value_change >= 0 ? "good" : "bad"),
        stat("Average category rank", `${data.avg_rank_before} → ${data.avg_rank_after}`),
        stat(`Value to ${data.partner}`, signed(data.partner_value_change, 2)),
        mu ? stat("This matchup", `${mu.expected_before.toFixed(1)} → ${mu.expected_after.toFixed(1)} cats, ${percent(mu.p_win_before)} → ${percent(mu.p_win_after)}`, "small") : null
      ),
      data.warnings.map((w) => h("p", { class: "warn" }, w)),
      table(
        ["Cat", "Mine per game", "My rank", `${data.partner} per game`, "Their rank"],
        data.mine.map((m, i) => {
          const t = data.theirs[i];
          return { cells: [m.cat, `${fmt(m.cat, m.before)} → ${fmt(m.cat, m.after)}`, rankCell(m.rank_before, m.rank_after), `${fmt(t.cat, t.before)} → ${fmt(t.cat, t.after)}`, rankCell(t.rank_before, t.rank_after)] };
        })
      )
    );
  });
  const tt = v.trade_targets;
  const line = (r) => h("li", {}, h("strong", {}, r.name), ` ${r.pro_team} · ${r.owner} · value ${signed(r.value, 2)}, league ${signed(r.league_value, 2)}`);
  return card(
    "Trade analyzer",
    true,
    tt && tt.buy.length ? [h("h3", {}, "Buy (worth more to you with your punt)"), h("ul", {}, tt.buy.map(line))] : null,
    tt && tt.sell.length ? [h("h3", {}, "Sell (worth more to the league)"), h("ul", {}, tt.sell.map(line))] : null,
    tt && tt.needs.length ? [h("h3", {}, `Help in your weakest categories (${tt.needs.join(", ")})`), h("ul", {}, tt.need_targets.slice(0, 6).map(line))] : null,
    h("h3", {}, "Try a trade"),
    STATIC ? h("p", { class: "note" }, "The trade evaluator needs the app running on a computer (uv run fantasy serve).") : [
      h("div", { class: "form" },
        h("div", { class: "field" }, h("span", {}, "You give"), h("div", { class: "picklist" }, giveBoxes.map(([, label]) => label))),
        h("div", { class: "field" }, h("span", {}, "You get from"), partner, getList)
      ),
      go,
      result,
    ]
  );
}

function renderAccuracy(v) {
  const a = v.accuracy;
  if (!a) return card("Forecast accuracy", false, h("p", { class: "muted" }, "Fills in after the first finished week of daily refreshes."));
  const b = (x) => (x === null || x === undefined ? "-" : x.toFixed(3));
  return card(
    "Forecast accuracy",
    false,
    h("p", {}, `${a.forecasts} category forecasts over ${a.matchups} finished matchup(s). Brier ${b(a.brier)} (0 perfect, 0.25 coin flip); first forecast of each week ${b(a.brier_first)}.`),
    a.likely_correct !== null ? h("p", {}, `Likely calls that came true: ${Math.round(a.likely_correct * 100)}% of ${a.likely_calls}.`) : null,
    a.calibration.length ? table(["Confidence", "Forecasts", "Expected", "Came true"], a.calibration.map((c) => ({ cells: [c.range, c.forecasts, Math.round(c.expected * 100) + "%", Math.round(c.actual * 100) + "%"] }))) : null
  );
}

function renderAdvanced(v) {
  const t = v.my_team;
  if (!t) return null;
  const rows = t.roster.filter((r) => r.advanced).map((r) => {
    const a = r.advanced;
    const c = a.consistency || {};
    return {
      cells: [
        r.name, pct(a.ts_pct), pct(a.efg_pct), pct(a.tp_pct), num(a.tpa), num(a.ast_to, 2), num(a.oreb), num(a.dreb),
        num(a.stocks), a.dd_rate === null ? "-" : Math.round(a.dd_rate * 100) + "%",
        a.per36 ? num(a.per36.pts) : "-", num(r.usage_proxy),
        valueCell(c.mean), c.sd === undefined ? "-" : num(c.sd, 2), valueCell(c.floor), valueCell(c.ceiling),
        a.team_games ? `${a.games_played}/${a.team_games}` : "-",
      ],
    };
  });
  return card(
    "Advanced stats",
    true,
    table(["Player", "TS%", "eFG%", "3P%", "3PA", "AST/TO", "OREB", "DREB", "Stocks", "DD%", "PTS/36", "USG~", "Game value", "Spread", "Floor", "Ceiling", "Played"], rows, { textCols: [0] }),
    h("p", { class: "note" }, "Game value: each of the last 15 games scored like the rankings. Spread is how much it swings; floor and ceiling are the 20th and 80th percentile. Played: games played of the team's games.")
  );
}

function renderSeason(v) {
  const rows = v.season_standings;
  if (!rows) return null;
  const cats = Object.keys(rows[0].values);
  return card(
    "Season totals",
    true,
    h("p", { class: "note" }, "Actual category totals so far. Rank 1 is best; hover a rank for the total."),
    table(
      ["Team", "Record", ...cats, "Avg"],
      rows.map((r) => ({
        cls: r.is_me ? "mine" : null,
        cells: [
          r.team + (r.is_me ? " (me)" : r.is_opp ? " (opp)" : ""), r.record,
          ...cats.map((c) => ({ node: r.ranks[c] ?? "-", cls: r.ranks[c] ? "rank-" + r.ranks[c] : "", title: c.endsWith("%") ? pct(r.values[c]) : num(r.values[c], 0) })),
          num(r.avg_rank),
        ],
      })),
      { textCols: [0, 1] }
    )
  );
}

function renderLineup(v) {
  const c = v.lineup;
  if (!c) return null;
  const items = [];
  const item = (label, cls, text) => items.push(h("li", {}, tag(label, cls), text));
  c.swaps.forEach((s) => item("Start", "bad", s.for ? `${s.start}${s.tipoff ? " (" + s.tipoff + ")" : ""} in ${s.slot} for ${s.for} (${s.reason})` : `${s.start}: rearrange slots to fit him`));
  c.bench.forEach((b) => item("Bench", "bad", `${b.name} (${b.reason})`));
  c.watch.forEach((w) => item("Check", "warn", `${w}, before lock`));
  c.ir.forEach((f) => item("IR", "bad", f));
  c.consider.forEach((f) => item("Maybe", "", f));
  const ok = c.lost_games === 0;
  return card(
    `Lineup: ${c.is_today ? "tonight" : c.day}`,
    false,
    stats(
      stat("Starts set", `${c.current_starts} / ${c.best_starts}`, ok ? "good" : "bad"),
      stat("First tip-off", c.lock ? c.lock.slice(11) : "-"),
      stat("Open slots", String(c.open_slots))
    ),
    items.length ? h("ul", { class: "plain" }, items) : h("p", { class: "good" }, "Lineup is set. Nothing to change.")
  );
}

function renderChanges(v) {
  const c = v.changes;
  let body;
  if (!c.since) body = h("p", { class: "muted" }, "First snapshot: changes appear from the next day.");
  else if (!c.bullets.length) body = h("p", { class: "muted" }, "Nothing important since " + v.meta.compared_with + ".");
  else body = h("ul", { class: "plain" }, c.bullets.slice(0, 20).map((b) => h("li", {}, b)));
  return card("Since yesterday", false, body);
}

function renderAcquisitions(v) {
  const a = v.acquisitions;
  const ir = v.my_ir;
  return card(
    "Acquisitions, waivers, IR",
    false,
    a ? [stats(stat("Used this matchup", `${a.used} / ${a.limit}`), stat("Left", String(a.remaining), a.remaining ? "" : "bad")),
         h("div", { class: "segments", "aria-hidden": "true" }, Array.from({ length: a.limit }, (_, i) => h("span", { class: i < a.used ? "used" : null })))] : null,
    h("h3", {}, "Waiver order"),
    h("ol", { class: "order" }, v.waiver_order.map((w) => h("li", { class: w.is_me ? "good" : null }, w.team + (w.is_me ? " (you)" : "")))),
    ir ? [h("h3", {}, "IR"),
      ir.players.length ? h("ul", { class: "plain" }, ir.players.map((p) => h("li", {}, `${p.name}: ${p.health}${p.expected_return ? ", back ~" + p.expected_return : ""}`))) : h("p", { class: "muted" }, "IR slot empty"),
      ir.flags.map((f) => h("p", { class: "bad" }, f))] : null,
    h("p", { class: "note" }, `C-eligible on roster: ${v.my_c_count} / ${v.meta.rules.c_limit}`)
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
        tag(a.trend, cls[a.trend]), h("strong", {}, a.name), ` ${a.pro_team} · `, h("span", { class: "muted" }, a.owner),
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
    "My roster",
    true,
    table([...ROSTER_HEAD, "Usable"], rosterRows(t.roster, true), { textCols: [0, 1, 2, 3, 4] }),
    h("p", { class: "note" }, "Season per-game averages; * = ESPN projection (no games yet). Hover a health cell for the injury note.")
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
    "Days left this week",
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
    "Free agents",
    true,
    h("p", { class: "note" }, "Sorted by how interesting they are right now (minutes, role, schedule, adds), not by ESPN rank. * = ESPN projection."),
    table(["#", "Player", "Team", "Pos", "St", "Health", "Ros%", "+/-", "Proj MIN", "Last 5 MIN", "Starts", "Trend", "FG%", "FT%", ...STATS.map(([l]) => l), "Usable", "Why"], rows, { textCols: [1, 2, 3, 4, 5, 22], wrapCols: [22] })
  );
}

function renderPopular(v) {
  return card(
    "Most rostered FAs",
    false,
    table(["Player", "Team", "Pos", "Health", "Ros%", "+/-"], v.popular_free_agents.map((r) => ({ cells: [r.name, r.pro_team, r.positions, r.health, num(r.roster_pct), signed(r.roster_pct_change)] })), { textCols: [0, 1, 2, 3] })
  );
}

function renderTransactions(v) {
  const rows = v.transactions;
  if (!rows.length) return card("Transactions, 7 days", false, h("p", { class: "muted" }, "None."));
  return card(
    "Transactions, 7 days",
    false,
    h("ul", { class: "plain" }, rows.map((t) => {
      const actions = [...t.adds.map((n) => "ADD " + n), ...t.drops.map((n) => "DROP " + n), ...t.trades.map((n) => "TRADE " + n)];
      return h("li", {},
        t.new ? tag("New", "solid") : null,
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
  return card(
    "Category strength",
    true,
    h("p", { class: "note" }, "Projected per game from each roster. Rank 1 is best; hover a rank for the value."),
    table(["Team", ...cats, "Avg"], rows, { textCols: [0] })
  );
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
        h("summary", {}, t.name, t.is_opp ? tag("Opponent", "solid") : null, h("span", { class: "muted" }, `${t.record} · waiver #${t.waiver_rank ?? "-"} · acq ${t.acquisitions.used}/${t.acquisitions.limit} · games left ${t.games_remaining}`)),
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
  const puntRow = h("div", { class: "controls" }, h("span", { class: "stat-label" }, "Punt"), puntBoxes);

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
    h("p", { class: "note" }, "Values are per-game z-scores against the rostered players (about +1 first round, 0 the edge of rosterable). Value leaves out punted categories; LeagV counts all. USG~ is a usage proxy: (FGA + 0.44 FTA + TO) per 36 minutes. Owner: ME, OPP, team abbreviation, FA or WA.")
  );
}

let settingsData = null;

function renderSettings() {
  const s = settingsData || {};
  const field = (label, input, hint) => h("label", { class: "field" }, h("span", {}, label), input, hint ? h("small", { class: "muted" }, hint) : null);
  const url = h("input", { type: "url", placeholder: "https://fantasy.espn.com/basketball/team?leagueId=...&teamId=...", autocomplete: "off" });
  const s2 = h("input", { type: "password", placeholder: s.has_espn_s2 ? "saved (leave empty to keep)" : "espn_s2 cookie", autocomplete: "off" });
  const swid = h("input", { type: "password", placeholder: s.has_swid ? "saved (leave empty to keep)" : "SWID cookie, {...}", autocomplete: "off" });
  const team = h("input", { type: "text", value: s.team || "" });
  const punt = h("input", { type: "text", value: (s.punt || []).join(", "), placeholder: "e.g. TO" });
  const tgToken = h("input", { type: "password", placeholder: s.has_telegram ? "saved (leave empty to keep)" : "from @BotFather", autocomplete: "off" });
  const tgChat = h("input", { type: "text", placeholder: s.has_telegram ? "saved (leave empty to keep)" : "your chat id", autocomplete: "off" });
  const test = h("button", { type: "button" }, "Send test alert");
  test.addEventListener("click", async () => {
    const res = await fetch("/api/telegram/test", { method: "POST" });
    const data = await res.json();
    setStatus(res.ok ? "Test alert sent to Telegram." : data.error || "Sending failed.", res.ok ? "ok" : "error");
  });
  const status = h("p", { class: "muted" },
    s.league_id ? `League ${s.league_id}, season ${s.season}, team "${s.team}", cookies ${s.has_espn_s2 && s.has_swid ? "saved" : "missing"}.` : "No league set yet.");
  const save = h("button", { type: "button", class: "primary" }, "Save settings");
  save.addEventListener("click", async () => {
    const form = { team: team.value, punt: punt.value };
    if (url.value.trim()) form.league_url = url.value.trim();
    if (s2.value.trim()) form.espn_s2 = s2.value.trim();
    if (swid.value.trim()) form.swid = swid.value.trim();
    if (tgToken.value.trim()) form.telegram_token = tgToken.value.trim();
    if (tgChat.value.trim()) form.telegram_chat_id = tgChat.value.trim();
    const res = await fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form) });
    const data = await res.json();
    if (!res.ok) { setStatus(data.error || "Saving failed.", "error"); return; }
    settingsData = data.settings;
    setStatus("Settings saved to .dev.vars.", "ok");
    rankState.punt = null;
    render(data.view, settingsData.demo);
  });
  return card(
    "League settings",
    true,
    h("p", { class: "note" }, "Open your team page on fantasy.espn.com and copy its address: it carries the league, team and season ids. The two cookies come from the browser while logged in: press F12, then Application (Chrome/Edge) or Storage (Firefox), Cookies, espn.com, and copy espn_s2 and SWID. ESPN has no API key; these cookies are what give read access to a private league. They are saved only in .dev.vars on this computer."),
    h("div", { class: "form" },
      field("League or team page URL", url),
      field("espn_s2", s2),
      field("SWID", swid),
      field("Your team", team, "Name, abbreviation or team id; the URL's teamId is used when empty."),
      field("Punt categories", punt, "Comma-separated, e.g. TO or TO, FT%. Values and rankings leave them out."),
      field("Telegram bot token", tgToken, "Optional: lineup alerts on your phone. Create a bot with @BotFather."),
      field("Telegram chat id", tgChat, "Send your bot a message, then open api.telegram.org/bot<token>/getUpdates to see it.")
    ),
    h("div", { class: "actions" }, save, s.has_telegram ? test : null),
    status
  );
}

function renderReport() {
  const area = h("textarea", { id: "report-text", class: "report-text", readonly: true, spellcheck: "false", "aria-label": "Daily report text" });
  area.value = reportText;
  return card(
    "Daily report",
    true,
    h("p", { class: "note", id: "report-size" }, reportSize()),
    area
  );
}

function reportSize() {
  if (!reportText) return "Loading the report...";
  const compact = $("compact").checked ? "compact" : "full";
  return `${reportText.length.toLocaleString()} characters, ${compact} version. This is exactly what COPY DAILY FANTASY REPORT puts on the clipboard.`;
}

const TABS = [
  ["today", "Today"],
  ["matchup", "Matchup"],
  ["roster", "Roster"],
  ["wire", "Wire"],
  ["league", "League"],
  ["rankings", "Rankings"],
  ["report", "Report"],
  ["setup", "Setup"],
];
if (STATIC) TABS.splice(TABS.findIndex(([key]) => key === "setup"), 1);

function currentTab() {
  const key = location.hash.slice(1);
  return TABS.some(([k]) => k === key) ? key : "today";
}

function showTab(key) {
  document.querySelectorAll(".section").forEach((el) => { el.hidden = el.dataset.tab !== key; });
  document.querySelectorAll(".tab").forEach((el) => el.setAttribute("aria-selected", String(el.dataset.tab === key)));
}

function renderTabs(counts) {
  const nav = $("tabs");
  nav.replaceChildren(...TABS.map(([key, label]) => {
    const button = h("button", { type: "button", class: "tab", role: "tab", "data-tab": key },
      label, counts[key] ? h("span", { class: "count", title: "Things to fix" }, String(counts[key])) : null);
    button.addEventListener("click", () => {
      if (location.hash.slice(1) !== key) history.replaceState(null, "", "#" + key);
      showTab(key);
    });
    return button;
  }));
}

function renderMasthead(view) {
  const m = view.meta;
  const date = new Date(m.date + "T12:00:00");
  $("league-name").textContent = m.league;
  $("dateline").textContent = [
    date.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" }),
    `Snapshot ${m.fetched_at.slice(11)}`,
    m.compared_with ? `vs ${m.compared_with}` : "first snapshot",
  ].join(" · ");
  const me = view.my_team;
  $("subtitle").textContent = me ? `${me.name} · season ${m.season_label} · ${me.record}` : "Your team was not found: set it under Setup.";
}

function render(view, demo) {
  const app = $("app");
  app.replaceChildren();
  $("demo-banner").hidden = !demo;
  if (!view) {
    $("tabs").replaceChildren();
    app.append(h("div", { class: "section" },
      h("section", { class: "empty-state" }, h("p", {}, "Fill in League settings below, press Refresh to read your league from ESPN and save today's snapshot, then copy the report into ChatGPT.")),
      renderSettings()));
    $("copy").disabled = true;
    $("download").disabled = true;
    return;
  }
  renderMasthead(view);
  const c = view.lineup;
  const fixes = c ? c.swaps.length + c.bench.length + c.ir.length : 0;
  // Some panels are absent (no matchup, no season totals yet): skip them.
  const sections = {
    today: [renderScoreboard(view), renderLineup(view), renderChanges(view), renderAlerts(view), renderAcquisitions(view)],
    matchup: [renderMatchup(view), renderTargets(view), renderWhatIf(view), renderGameCounts(view), renderStrategy(view), renderAccuracy(view), renderSchedule(view), renderStreamPlan(view), renderSimulator(view), renderNextMatchup(view)],
    roster: [renderMyRoster(view), renderAdvanced(view)],
    wire: [renderFreeAgents(view), renderTransactions(view), renderPopular(view)],
    league: [renderStrength(view), renderSeason(view), renderTrade(view), renderTeams(view)],
    rankings: [renderRankings(view)],
    report: [renderReport()],
    setup: STATIC ? [] : [renderSettings()],
  };
  renderTabs({ today: fixes });
  app.append(...TABS.map(([key]) => h("div", { class: "section", "data-tab": key, role: "tabpanel" }, sections[key].filter(Boolean))));
  showTab(currentTab());
  const warnings = view.meta.warnings || [];
  if (warnings.length) setStatus("Warnings: " + warnings.join(" | "));
  loadReport();
}

async function loadReport() {
  if (STATIC) {
    reportText = STATIC.report[$("compact").checked ? "compact" : "full"] || "";
  } else {
    const res = await fetch("/api/report?compact=" + ($("compact").checked ? "1" : "0"));
    if (!res.ok) return;
    reportText = await res.text();
  }
  const area = $("report-text");
  if (area) area.value = reportText;
  const size = $("report-size");
  if (size) size.textContent = reportSize();
  $("copy").disabled = false;
  $("download").disabled = false;
}

async function loadState() {
  if (STATIC) {
    $("refresh").hidden = true;
    render(STATIC.view, STATIC.demo);
    return;
  }
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
    // Older browsers or a denied permission: copy through a hidden textarea.
    const area = h("textarea", { style: "position:fixed;left:-9999px;top:0", readonly: true });
    area.value = reportText;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  setStatus(`Report copied (${reportText.length.toLocaleString()} characters). Paste it into ChatGPT.`, "ok");
}

window.addEventListener("hashchange", () => showTab(currentTab()));
$("refresh").addEventListener("click", refresh);
$("copy").addEventListener("click", copyReport);
$("download").addEventListener("click", () => {
  if (!reportText) return;
  const date = (reportText.match(/^Date: (\S+)/m) || [])[1] || "report";
  const link = h("a", { href: URL.createObjectURL(new Blob([reportText], { type: "text/markdown" })), download: `fantasy-report-${date}.md` });
  document.body.append(link);
  link.click();
  link.remove();
});
$("compact").addEventListener("change", loadReport);
loadState().catch((err) => setStatus("Could not load the dashboard: " + err, "error"));
