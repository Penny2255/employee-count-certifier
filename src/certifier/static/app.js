/* GTM Data Certifier: page logic. The card renderer (window.GTMCard) is prepended by the server. */
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var STAGES = ["resolve", "filings", "sweep", "corroborate", "score", "certified"];
  var STAGE_LABEL = { resolve: "Resolve entity", filings: "SEC & official filings", sweep: "Web sweep",
                      corroborate: "Corroboration", score: "Scoring", certified: "Certified" };
  var state = { query: "", current: null, rating: null, candidates: null, controller: null };

  // ---------- storage (browser only) ----------
  function get(key, fallback) { try { var v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch (e) { return fallback; } }
  function put(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {} }
  function code() { return get("gtm_code", ""); }

  // ---------- small DOM helpers ----------
  function el(tag, attrs, children) {
    var n = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (attrs[k] == null) continue;
      if (k === "text") n.textContent = attrs[k]; else if (k === "cls") n.className = attrs[k]; else n.setAttribute(k, attrs[k]);
    }
    (children || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return n;
  }
  function svg(markup) { var t = document.createElement("template"); t.innerHTML = markup.trim(); return t.content.firstChild; }
  function num(n) { return n == null ? "–" : Number(n).toLocaleString("en-US"); }
  function host(url) { try { return new URL(url).hostname.replace(/^www\./, ""); } catch (e) { return ""; } }
  function say(id, msg, isError) { var n = $(id); n.textContent = msg || ""; n.classList.toggle("error", !!isError); }

  // ---------- views ----------
  function show(view) {
    ["home", "confirm", "expedition", "result"].forEach(function (v) { $("view-" + v).hidden = v !== view; });
    if (view !== "expedition") stopPhrases();
    window.scrollTo(0, 0);
    var title = document.querySelector("#view-" + view + " h1");
    if (title && view !== "home") { title.setAttribute("tabindex", "-1"); title.focus({ preventScroll: true }); }
    if (view === "home") renderRecent();
  }
  // Each step is a browser history entry, so Back returns to the previous step or result.
  function go(view, extra) {
    show(view);
    try { history.pushState(Object.assign({ view: view }, extra || {}), ""); } catch (e) {}
  }
  try { history.replaceState({ view: "home" }, ""); } catch (e) {}
  window.addEventListener("popstate", function (e) {
    var st = e.state || { view: "home" };
    cancelLookup();
    if (st.view === "confirm" && state.candidates) { renderCandidates(state.candidates); show("confirm"); }
    else if (st.view === "result" && st.qid && state.current && state.current.query_id === st.qid) showResult(state.current, true);
    else if (st.view === "result" && st.qid && st.qid !== "demo") openStored(st.qid, true);
    else show("home");
  });
  function cancelLookup() {
    if (state.controller) { state.controller.abort(); state.controller = null; }
    stopPhrases();
  }
  // Start over: clear every step and return to an empty search box, without reloading the page.
  function reset(keepQuery) {
    cancelLookup();
    state.current = null; state.candidate = null; state.candidates = null; state.rating = null;
    $("q").value = keepQuery ? state.query : "";
    $("candidates").textContent = ""; $("stages").textContent = ""; $("result-card").textContent = "";
    say("home-status", ""); say("result-status", "");
    go("home");
    $("q").focus();
    if (keepQuery) $("q").select();
  }

  // ---------- theme toggle ----------
  function currentTheme() {
    var t = document.documentElement.getAttribute("data-theme");
    if (t) return t;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function syncToggle() {
    var dark = currentTheme() === "dark";
    $("theme-toggle").setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  }
  $("theme-toggle").addEventListener("click", function () {
    var next = currentTheme() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    put("gtm_theme", next);
    syncToggle();
  });
  syncToggle();

  // ---------- API (JSON errors only; never raw parse errors) ----------
  function api(path, opts) {
    opts = opts || {};
    var headers = { "Authorization": "Bearer " + code() };
    if (opts.body) headers["Content-Type"] = "application/json";
    return fetch(path, { method: opts.method || "GET", headers: headers, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) {
        return r.text().then(function (text) {
          var data = null;
          try { data = text ? JSON.parse(text) : {}; } catch (e) { data = null; }
          if (!r.ok || data === null) {
            var err = new Error((data && data.error) || "The service didn't respond as expected. Please try again.");
            err.status = r.status;
            throw err;
          }
          return data;
        });
      }, function () { throw new Error("Can't reach the service. Check your connection and try again."); });
  }
  function needCode(message) {
    $("code-form").hidden = false;
    $("code-help").textContent = message || "GTM Data Certifier is invite-only. Enter your access code to continue; it's remembered in this browser.";
    $("code").focus();
  }
  function handleAuth(err, retry) {
    if (err.status === 401) { put("gtm_code", ""); show("home"); needCode("That access code wasn't accepted. Check it and enter it again."); state.retry = retry; return true; }
    return false;
  }

  // ---------- home ----------
  $("search-form").addEventListener("submit", function (e) { e.preventDefault(); search($("q").value); });
  Array.prototype.forEach.call(document.querySelectorAll("[data-example]"), function (b) {
    b.addEventListener("click", function () { $("q").value = b.getAttribute("data-example"); search(b.getAttribute("data-example")); });
  });
  $("code-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var value = $("code").value.trim();
    if (!value) return;
    put("gtm_code", value);
    $("code").value = "";
    $("code-form").hidden = true;
    var retry = state.retry; state.retry = null;
    if (retry) retry(); else if ($("q").value.trim()) search($("q").value);
  });

  function search(q) {
    q = (q || "").trim();
    if (!q) { say("home-status", "Enter a company name or website.", true); $("q").focus(); return; }
    state.query = q;
    if (!code()) { state.retry = function () { search(q); }; needCode(); return; }
    say("home-status", "Finding matching organizations…");
    api("/api/find", { method: "POST", body: { query: q } }).then(function (d) {
      say("home-status", "");
      if (!d.candidates.length) { say("home-status", "No matching organization found. Try the website instead (e.g. stripe.com).", true); return; }
      state.candidates = d.candidates;
      renderCandidates(d.candidates);
      go("confirm");
    }).catch(function (err) { if (!handleAuth(err, function () { search(q); })) say("home-status", err.message, true); });
  }

  // ---------- confirm ----------
  function logo(c) {
    var box = el("div", { cls: "logo", "aria-hidden": "true", text: (c.name || "?").slice(0, 1).toUpperCase() });
    if (c.logo_url && /^https:\/\//.test(c.logo_url)) {
      var img = el("img", { src: c.logo_url, alt: "", width: "28", height: "28", loading: "lazy", referrerpolicy: "no-referrer" });
      img.addEventListener("load", function () { if (img.naturalWidth > 1) { box.textContent = ""; box.appendChild(img); } });
    }
    return box;
  }
  function renderCandidates(list) {
    var root = $("candidates");
    root.textContent = "";
    list.forEach(function (c) {
      var meta = [c.website ? host(c.website) : null, c.hq].filter(Boolean).join(" · ");
      var parent = c.is_subsidiary && c.legal_parent ? "Part of " + c.legal_parent : null;
      var go = el("button", { type: "button", cls: "primary", text: "Certify" });
      go.addEventListener("click", function () { certify(c, false); });
      root.appendChild(el("article", { cls: "candidate", "aria-label": c.name }, [logo(c),
        el("div", null, [el("h2", { text: c.name }), meta ? el("p", { cls: "small muted", text: meta }) : null,
          c.description ? el("p", { cls: "small", text: c.description }) : null,
          parent ? el("p", { cls: "small muted", text: parent }) : null]), go]));
    });
  }

  // ---------- expedition themes ----------
  var I = function (body) { return '<svg viewBox="0 0 24 24" class="st-icon" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + "</svg>"; };
  var THEMES = [
    { id: "deep-sea", name: "Deep Sea Dive",
      scene: '<svg viewBox="0 0 240 120" aria-hidden="true"><path d="M0 22 Q30 14 60 22 T120 22 T180 22 T240 22" stroke="var(--sky)" stroke-width="3" fill="none"/>' +
             '<g class="bob"><ellipse cx="120" cy="72" rx="34" ry="14" fill="var(--loop-blue)"/><rect x="112" y="50" width="16" height="12" rx="3" fill="var(--loop-blue)"/><circle cx="108" cy="72" r="4" fill="var(--card)"/><circle cx="124" cy="72" r="4" fill="var(--card)"/></g>' +
             '<circle class="rise" cx="160" cy="70" r="3" fill="var(--sky)"/><circle class="rise d1" cx="168" cy="80" r="2" fill="var(--sky)"/><circle class="rise d2" cx="152" cy="84" r="2.5" fill="var(--sky)"/>' +
             '<path d="M20 112 q10 -16 20 0 q10 -16 20 0" stroke="var(--loop-green)" stroke-width="3" fill="none"/></svg>',
      icons: { resolve: I('<circle cx="8" cy="12" r="4"/><circle cx="16" cy="12" r="4"/><path d="M12 12h0"/>'),
               filings: I('<path d="M12 3v15"/><circle cx="12" cy="5" r="2"/><path d="M5 13a7 7 0 0 0 14 0"/>'),
               sweep: I('<path d="M4 18a10 10 0 0 1 16 0"/><path d="M7 18a6 6 0 0 1 10 0"/><circle cx="12" cy="18" r="1"/>'),
               corroborate: I('<ellipse cx="11" cy="12" rx="7" ry="4"/><path d="M18 12l4-3v6z"/><circle cx="8" cy="11" r=".6"/>'),
               score: I('<path d="M4 16a8 8 0 0 1 16 0"/><path d="M12 16l4-5"/>'),
               certified: I('<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/>') },
      phrases: { resolve: ["Checking the dive gear", "Marking the dive site"], filings: ["Descending to the filing reef", "Reading the logbooks on the seabed"],
                 sweep: ["Sonar sweep of the open web", "Following the current"], corroborate: ["Comparing samples from every depth", "Cross-checking the catch"],
                 score: ["Weighing the findings at the surface", "Calibrating the depth gauge"], certified: ["Surfacing with a certified answer"] } },
    { id: "treasure", name: "Treasure Map",
      scene: '<svg viewBox="0 0 240 120" aria-hidden="true"><rect x="30" y="14" width="180" height="92" rx="10" fill="var(--soft)" stroke="var(--line)"/>' +
             '<path class="trace" d="M50 90 C80 40 120 100 150 50 S190 40 196 34" stroke="var(--loop-blue)" stroke-width="3" fill="none"/>' +
             '<path d="M188 26l14 14M202 26l-14 14" stroke="var(--loop-green)" stroke-width="4"/><circle class="bob" cx="50" cy="90" r="6" fill="var(--loop-blue)"/></svg>',
      icons: { resolve: I('<circle cx="12" cy="12" r="8"/><path d="M12 6l2 6-2 6-2-6z"/>'),
               filings: I('<rect x="6" y="4" width="12" height="16" rx="2"/><path d="M9 9h6M9 13h6"/>'),
               sweep: I('<path d="M4 18c4-10 8 2 16-12" stroke-dasharray="2 3"/>'),
               corroborate: I('<path d="M5 5l14 14M19 5L5 19"/>'),
               score: I('<ellipse cx="12" cy="8" rx="6" ry="2.5"/><path d="M6 8v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V8"/><path d="M6 12v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5v-4"/>'),
               certified: I('<rect x="4" y="9" width="16" height="10" rx="2"/><path d="M4 13h16"/><path d="M6 9a6 4 0 0 1 12 0"/>') },
      phrases: { resolve: ["Unrolling the map", "Finding true north"], filings: ["Digging through the official archives", "Reading the old ledgers"],
                 sweep: ["Following the trail across the web", "Checking every landmark"], corroborate: ["Matching clues against the map", "Confirming X marks the spot"],
                 score: ["Counting the treasure", "Weighing the gold"], certified: ["Treasure certified"] } },
    { id: "galaxy", name: "Galaxy Star-Gazing",
      scene: '<svg viewBox="0 0 240 120" aria-hidden="true"><circle cx="120" cy="60" r="18" fill="var(--loop-blue)"/>' +
             '<ellipse cx="120" cy="60" rx="40" ry="10" stroke="var(--sky)" stroke-width="3" fill="none"/>' +
             '<circle class="twinkle" cx="40" cy="24" r="3" fill="var(--sky)"/><circle class="twinkle d1" cx="200" cy="30" r="2.5" fill="var(--loop-green)"/>' +
             '<circle class="twinkle d2" cx="190" cy="96" r="3" fill="var(--sky)"/><circle class="twinkle" cx="56" cy="92" r="2" fill="var(--loop-green)"/>' +
             '<path d="M40 24L56 92M200 30l-10 66" stroke="var(--line)" stroke-dasharray="3 4"/></svg>',
      icons: { resolve: I('<path d="M4 16l10-6 2 3-10 6z"/><path d="M9 17l-2 4M11 16l2 5"/>'),
               filings: I('<circle cx="12" cy="12" r="5"/><ellipse cx="12" cy="12" rx="10" ry="3"/>'),
               sweep: I('<ellipse cx="12" cy="12" rx="9" ry="5" stroke-dasharray="3 2"/><circle cx="20" cy="11" r="1.5"/>'),
               corroborate: I('<circle cx="5" cy="7" r="1.5"/><circle cx="12" cy="5" r="1.5"/><circle cx="18" cy="11" r="1.5"/><circle cx="10" cy="17" r="1.5"/><path d="M5 7l7-2 6 6-8 6z"/>'),
               score: I('<path d="M12 3l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 16.4 6.8 19.2l1-5.9L3.5 9.2l5.9-.8z"/>'),
               certified: I('<path d="M12 3v18M3 12h18M6 6l12 12M18 6L6 18"/>') },
      phrases: { resolve: ["Pointing the telescope", "Locking onto the right star"], filings: ["Reading the star charts", "Checking the official catalog"],
                 sweep: ["Scanning the night sky", "Sweeping every constellation"], corroborate: ["Lining up the constellations", "Comparing observations"],
                 score: ["Measuring the brightness", "Plotting the coordinates"], certified: ["Charted and certified"] } },
    { id: "detective", name: "Detective's Clues",
      scene: '<svg viewBox="0 0 240 120" aria-hidden="true"><rect x="40" y="20" width="160" height="80" rx="8" fill="var(--soft)" stroke="var(--line)"/>' +
             '<path d="M60 44h70M60 58h90M60 72h56" stroke="var(--line)" stroke-width="4" stroke-linecap="round"/>' +
             '<g class="sweep"><circle cx="150" cy="56" r="20" stroke="var(--loop-blue)" stroke-width="5" fill="none"/><path d="M164 70l18 18" stroke="var(--loop-blue)" stroke-width="7" stroke-linecap="round"/></g></svg>',
      icons: { resolve: I('<path d="M4 14h16"/><path d="M7 14l1-7h8l1 7"/>'),
               filings: I('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>'),
               sweep: I('<circle cx="10" cy="10" r="6"/><path d="M15 15l5 5"/>'),
               corroborate: I('<path d="M8 20c0-6 2-9 4-9s4 3 4 9"/><path d="M5 17c0-8 3-12 7-12s7 4 7 12"/>'),
               score: I('<path d="M12 4v16M6 8h12"/><path d="M6 8l-3 6h6zM18 8l-3 6h6z"/>'),
               certified: I('<circle cx="12" cy="12" r="8"/><path d="M8 12l3 3 5-6"/>') },
      phrases: { resolve: ["Opening the case file", "Confirming who we're looking for"], filings: ["Pulling the official records", "Reading the fine print"],
                 sweep: ["Canvassing the neighborhood", "Following every lead"], corroborate: ["Checking alibis against each other", "Ruling out the copycats"],
                 score: ["Weighing the evidence", "Writing up the report"], certified: ["Case closed and certified"] } },
    { id: "frontier", name: "Frontier Voyage",
      scene: '<svg viewBox="0 0 240 120" aria-hidden="true"><path d="M0 92 Q40 82 80 92 T160 92 T240 92" stroke="var(--loop-blue)" stroke-width="3" fill="none"/>' +
             '<g class="bob"><path d="M96 80h48l-8 12h-32z" fill="var(--loop-blue)"/><path d="M120 30v48" stroke="var(--text)" stroke-width="3"/><path d="M122 34l24 36h-24z" fill="var(--loop-green)"/></g>' +
             '<path d="M186 40l14-20 14 20z" fill="var(--sky)"/><path d="M200 40l10-14 10 14z" fill="var(--loop-green)" opacity=".7"/></svg>',
      icons: { resolve: I('<path d="M12 21s-6-6-6-11a6 6 0 0 1 12 0c0 5-6 11-6 11z"/><circle cx="12" cy="10" r="2"/>'),
               filings: I('<path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z"/><path d="M8 4v13"/>'),
               sweep: I('<path d="M4 17h16l-3 3H7z"/><path d="M12 4v13"/><path d="M12 5l6 9h-6z"/>'),
               corroborate: I('<circle cx="12" cy="12" r="8"/><path d="M12 6l2 6-2 6-2-6zM6 12h12"/>'),
               score: I('<path d="M3 19l6-10 4 6 3-4 5 8z"/>'),
               certified: I('<path d="M6 21V4"/><path d="M6 4h11l-3 4 3 4H6"/>') },
      phrases: { resolve: ["Packing for the voyage", "Plotting the course"], filings: ["Reading the harbor records", "Checking the ship's papers"],
                 sweep: ["Setting sail across the web", "Charting new territory"], corroborate: ["Comparing notes with other travelers", "Checking the landmarks"],
                 score: ["Surveying the land", "Taking the final bearings"], certified: ["Landfall: certified"] } }
  ];

  var phraseTimer = null, elapsedTimer = null;
  function stopPhrases() { clearInterval(phraseTimer); clearInterval(elapsedTimer); phraseTimer = elapsedTimer = null; }
  function setupExpedition(theme, name) {
    $("scene").innerHTML = theme.scene;
    $("exp-theme").textContent = theme.name;
    $("exp-title").textContent = "Certifying " + name;
    var list = $("stages");
    list.textContent = "";
    STAGES.forEach(function (s) {
      var li = el("li", { cls: "stage", "data-stage": s }, [el("span", { cls: "st-state", "aria-hidden": "true", text: "○" })]);
      li.appendChild(svg(theme.icons[s]));
      li.appendChild(el("span", { cls: "st-label", text: STAGE_LABEL[s] }));
      list.appendChild(li);
    });
    var started = Date.now();
    $("elapsed").textContent = "";
    elapsedTimer = setInterval(function () { $("elapsed").textContent = Math.round((Date.now() - started) / 1000) + " s · a new lookup usually takes 30 to 90 seconds"; }, 1000);
  }
  function markStage(theme, stage) {
    var idx = STAGES.indexOf(stage);
    Array.prototype.forEach.call($("stages").children, function (li, i) {
      var st = li.querySelector(".st-state");
      li.classList.toggle("done", i < idx || stage === "certified");
      li.classList.toggle("active", i === idx && stage !== "certified");
      if (i === idx && stage !== "certified") { li.setAttribute("aria-current", "step"); st.textContent = ""; st.appendChild(el("span", { cls: "spin" })); }
      else { li.removeAttribute("aria-current"); st.textContent = i < idx || stage === "certified" ? "✓" : "○"; }
    });
    $("exp-live").textContent = STAGE_LABEL[stage] + (stage === "certified" ? "." : " in progress.");
    $("track").style.setProperty("--p", String(Math.max(0, idx) / (STAGES.length - 1)));
    var phrases = theme.phrases[stage] || [STAGE_LABEL[stage]], n = 0;
    function roll() { var p = $("phrase"); p.classList.remove("roll"); void p.offsetWidth; p.textContent = phrases[n++ % phrases.length] + (stage === "certified" ? "" : "…"); p.classList.add("roll"); }
    clearInterval(phraseTimer); roll(); phraseTimer = setInterval(roll, 2600);
  }

  // ---------- certify (server-sent events over fetch) ----------
  function certify(c, refresh) {
    state.candidate = c;
    var theme = THEMES[Math.floor(Math.random() * THEMES.length)];
    state.theme = theme;
    setupExpedition(theme, c.name);
    show("expedition");
    markStage(theme, "resolve");
    var body = { name: c.name, website: c.website, hq: c.hq, cik: c.cik, legal_parent: c.legal_parent, parent_cik: c.parent_cik,
                 relationship_to_parent: c.relationship_to_parent, query: state.query, refresh: !!refresh };
    if (state.controller) state.controller.abort();
    var controller = state.controller = window.AbortController ? new AbortController() : null;
    fetch("/api/lookup", { method: "POST", headers: { "Content-Type": "application/json", "Authorization": "Bearer " + code() }, body: JSON.stringify(body),
                           signal: controller ? controller.signal : undefined })
      .then(function (r) {
        if (!r.ok || !r.body) {
          return r.text().then(function (t) { var d = null; try { d = JSON.parse(t); } catch (e) {} var err = new Error((d && d.error) || "The service didn't respond as expected. Please try again."); err.status = r.status; throw err; });
        }
        var reader = r.body.getReader(), decoder = new TextDecoder(), buffer = "";
        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) return;
            buffer += decoder.decode(chunk.value, { stream: true });
            var parts = buffer.split("\n\n"); buffer = parts.pop();
            parts.forEach(function (block) {
              var ev = "message", data = "";
              block.split("\n").forEach(function (line) {
                if (line.indexOf("event:") === 0) ev = line.slice(6).trim();
                else if (line.indexOf("data:") === 0) data += line.slice(5).trim();
              });
              if (!data) return;
              var payload; try { payload = JSON.parse(data); } catch (e) { return; }
              if (ev === "progress") markStage(theme, payload.stage);
              else if (ev === "result") { markStage(theme, "certified"); state.controller = null; setTimeout(function () { if (!controller || !controller.signal.aborted) showResult(payload); }, 600); }
              else if (ev === "error") throw Object.assign(new Error(payload.message), { status: payload.kind === "limit" ? 429 : 500 });
            });
            return pump();
          });
        }
        return pump();
      })
      .catch(function (err) {
        stopPhrases();
        if (err && err.name === "AbortError") return;  // the person went Back or started over
        if (handleAuth(err, function () { certify(c, refresh); })) return;
        show("home");
        say("home-status", err.message, true);
      });
  }

  // ---------- result ----------
  function showResult(payload, fromHistory) {
    state.current = payload;
    state.rating = null;
    var rec = payload.record;
    GTMCard.render($("result-card"), rec, { actions: false });
    // The expedition's theme signs off on the result it found.
    var done = $("theme-done"), theme = fromHistory ? null : state.theme;
    state.theme = null;
    done.textContent = "";
    done.hidden = !theme;
    if (theme) {
      done.appendChild(svg(theme.icons.certified));
      done.appendChild(el("span", { text: theme.phrases.certified[0] + " · " + theme.name }));
    }
    var on = $("certified-on");
    on.textContent = "Certified on " + (payload.certified_on || "–");
    if (payload.cached) on.appendChild(el("span", { cls: "badge-cache", text: "from the shared cache" }));
    $("refresh").hidden = !payload.cached || payload.query_id === "demo";
    resetRating();
    say("result-status", "");
    if (fromHistory) show("result"); else go("result", { qid: payload.query_id });
    remember(payload);  // every completed result is saved to Recent lookups
    $("saved-note").hidden = payload.query_id === "demo";
  }
  Array.prototype.forEach.call(document.querySelectorAll("[data-action='reset']"), function (b) {
    b.addEventListener("click", function () { reset(false); });
  });
  $("search-again").addEventListener("click", function () { reset(true); });
  $("discard").addEventListener("click", function () {
    var cur = state.current;
    if (cur) put("gtm_recent", get("gtm_recent", []).filter(function (r) { return r.id !== cur.query_id; }));
    reset(false);
    say("home-status", "Removed from Recent lookups.");
  });
  $("refresh").addEventListener("click", function () {
    if (state.candidate) { certify(state.candidate, true); return; }
    var e = state.current && state.current.record.entity;
    if (e) certify({ name: e.name, website: e.website, hq: e.hq, legal_parent: e.legal_parent }, true);
  });

  function download(format) {
    if (!state.current) return;
    if (state.current.query_id === "demo") { say("result-status", "Downloads are disabled in demo mode."); return; }
    fetch("/api/lookups/" + state.current.query_id + "/export?format=" + format, { headers: { "Authorization": "Bearer " + code() } })
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) { var d = null; try { d = JSON.parse(t); } catch (e) {} throw new Error((d && d.error) || "Download failed. Please try again."); });
        var name = (r.headers.get("Content-Disposition") || "").replace(/.*filename="([^"]+)".*/, "$1") || "certification";
        return r.blob().then(function (b) {
          var url = URL.createObjectURL(b), a = el("a", { href: url, download: name });
          document.body.appendChild(a); a.click(); a.remove(); setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
        });
      }).catch(function (err) { say("result-status", err.message, true); });
  }
  $("dl-json").addEventListener("click", function () { download("json"); });
  $("dl-csv").addEventListener("click", function () { download("summary_csv"); });
  $("dl-sources").addEventListener("click", function () { download("sources_csv"); });

  // ---------- rating ----------
  function resetRating() {
    Array.prototype.forEach.call(document.querySelectorAll(".rate"), function (b) { b.setAttribute("aria-pressed", "false"); });
    $("rate-comment").value = ""; say("rate-status", "");
  }
  Array.prototype.forEach.call(document.querySelectorAll(".rate"), function (b) {
    b.addEventListener("click", function () {
      state.rating = b.getAttribute("data-rating");
      Array.prototype.forEach.call(document.querySelectorAll(".rate"), function (o) { o.setAttribute("aria-pressed", String(o === b)); });
    });
  });
  $("rate-send").addEventListener("click", function () {
    if (!state.rating) { say("rate-status", "Choose Great, Good, Okay or Off first.", true); return; }
    if (state.current.query_id === "demo") { say("rate-status", "Thanks. (Demo mode: not saved.)"); return; }
    api("/api/lookups/" + state.current.query_id + "/rating", { method: "POST", body: { rating: state.rating, comment: $("rate-comment").value } })
      .then(function () { say("rate-status", "Thanks. Your rating is logged for review."); })
      .catch(function (err) { say("rate-status", err.message, true); });
  });

  // ---------- recent lookups (this browser only) ----------
  function remember(p) {
    if (p.query_id === "demo") return;
    var h = p.record.headline, c = p.record.confidence;
    var list = get("gtm_recent", []).filter(function (r) { return r.name !== p.record.entity.name; });
    list.unshift({ id: p.query_id, name: p.record.entity.name, count: h.count, qualifier: h.qualifier, score: c.score,
                   level: c.level, date: p.certified_on });
    put("gtm_recent", list.slice(0, 10));
  }
  function renderRecent() {
    var list = get("gtm_recent", []), ul = $("recent-list");
    ul.textContent = "";
    $("recent").hidden = !list.length;
    list.forEach(function (r) {
      var b = el("button", { type: "button" }, [el("span", { text: r.name }),
        el("span", { cls: "r-meta", text: (r.count == null ? "not certified" : num(r.count)) + " · " + r.score + "/5 · " + r.date })]);
      b.addEventListener("click", function () { openStored(r.id); });
      ul.appendChild(el("li", null, [b]));
    });
  }
  function openStored(id, fromHistory) {
    if (!code()) { state.retry = function () { openStored(id); }; needCode(); return; }
    say("home-status", "Opening…");
    api("/api/lookups/" + id).then(function (d) { say("home-status", ""); state.candidate = null; showResult(d, fromHistory); })
      .catch(function (err) { if (!handleAuth(err, function () { openStored(id); })) say("home-status", err.message, true); });
  }

  // ---------- navigation and panels ----------
  Array.prototype.forEach.call(document.querySelectorAll("[data-nav='home']"), function (n) {
    n.addEventListener("click", function (e) { e.preventDefault(); reset(false); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("[data-open]"), function (b) {
    b.addEventListener("click", function () { var d = $(b.getAttribute("data-open")); if (d && d.showModal) d.showModal(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("dialog [data-close]"), function (b) {
    b.addEventListener("click", function () { b.closest("dialog").close(); });
  });
  Array.prototype.forEach.call(document.querySelectorAll("dialog"), function (d) {
    d.addEventListener("click", function (e) { if (e.target === d) d.close(); });  // click on the backdrop
  });
  $("forget-code").addEventListener("click", function () { put("gtm_code", ""); $("forget-code").textContent = "Access code forgotten"; });

  // ---------- demo mode (CERTIFIER_DEMO=1; used for screenshots) ----------
  function demo() {
    var p = new URLSearchParams(location.search), view = p.get("demo");
    if (!view) return;
    if (p.get("motion") !== "on") document.documentElement.classList.add("still");  // screenshots show the settled state
    var mode = p.get("mode");
    if (mode === "light" || mode === "dark") { document.documentElement.setAttribute("data-theme", mode); syncToggle(); }
    if (view === "confirm") {
      state.query = "Stripe";
      state.candidates = [
        { name: "Stripe, Inc.", website: "https://stripe.com", hq: "South San Francisco, CA, USA", description: "Online payments infrastructure for businesses.", org_type: "private_company" },
        { name: "Stripe Payments Europe, Ltd.", website: "https://stripe.com/ie", hq: "Dublin, Ireland", description: "European operating subsidiary of Stripe.", is_subsidiary: true, legal_parent: "Stripe, Inc." }];
      renderCandidates(state.candidates);
      show("confirm");
    } else if (view === "expedition") {
      var theme = THEMES.filter(function (t) { return t.id === p.get("theme"); })[0] || THEMES[0];
      setupExpedition(theme, p.get("name") || "Salesforce, Inc.");
      show("expedition");
      markStage(theme, p.get("stage") || "sweep");
      stopPhrases();
      $("elapsed").textContent = "24 s · a new lookup usually takes 30 to 90 seconds";
    } else if (view === "result") {
      state.theme = THEMES.filter(function (t) { return t.id === p.get("theme"); })[0] || null;
      fetch("/demo/record/" + (p.get("slug") || "salesforce")).then(function (r) { return r.json(); }).then(function (d) { showResult(d); });
    } else if (view === "about") {
      $("dlg-about").showModal();
    } else if (view === "how") {
      $("dlg-how").showModal();
    } else if (view === "code") {
      needCode();
    } else if (view === "home") {
      put("gtm_recent", [{ id: "demo", name: "Salesforce, Inc.", count: 83334, score: 5, level: "Certified, corroborated", date: "2026-10-11" },
                         { id: "demo", name: "Stripe, Inc.", count: 8500, score: 1, level: "Unverified", date: "2026-10-11" }]);
      renderRecent();
    }
  }

  renderRecent();
  if (window.GTM_DEMO) demo();
})();
