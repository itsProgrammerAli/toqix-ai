// TOQIX AI — Liquid Glass studio UI. Plain JS, same-origin API only. No external requests.
(function () {
  "use strict";

  var state = {
    kind: "video", style: "cinematic", voice: "Ava", aspect: "16:9",
    view: "studio", activeProject: null, projects: [],
    agentBusy: false, agentGreeted: false,
    user: null, meLoaded: false, googleConfigured: false
  };
  var lastSig = null;
  var seen = {};
  var feedJobs = [];
  var styleItems = [];

  /* Audio mode: the chips row offers voice characters instead of styles.
     The selected voice name travels in the job's existing style field. */
  var VOICES = [
    { value: "Ava", label: "Ava · Warm female" },
    { value: "Emma", label: "Emma · British female" },
    { value: "Michael", label: "Michael · Deep male" },
    { value: "George", label: "George · British male" },
    { value: "Sky", label: "Sky · Young female" },
    { value: "Adam", label: "Adam · Casual male" }
  ];

  var PLACEHOLDERS = {
    video: "Describe anything… a panda astronaut planting a flag on the moon",
    image: "Describe the image… a lighthouse at golden hour",
    audio: "Type the words to speak…"
  };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  /* ---------------- composer ---------------- */

  function chipRow(box, items, current, onPick) {
    box.innerHTML = "";
    items.forEach(function (it) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (it.value === current ? " active" : "");
      b.textContent = it.label;
      b.addEventListener("click", function () {
        onPick(it.value);
        Array.prototype.forEach.call(box.children, function (c) {
          c.classList.toggle("active", c.textContent === it.label);
        });
      });
      box.appendChild(b);
    });
  }

  /* The chips row shows styles for video/image, voices for audio. */
  function renderChips() {
    var label = $("chips-label");
    if (state.kind === "audio") {
      if (label) label.textContent = "Voice";
      chipRow($("styles"), VOICES, state.voice,
        function (v) { state.voice = v; });
    } else {
      if (label) label.textContent = "Style";
      chipRow($("styles"), styleItems, state.style,
        function (v) { state.style = v; });
    }
  }

  /* ---------------- accounts ---------------- */

  function renderAuth() {
    var box = $("auth-area");
    if (!box) return;
    box.innerHTML = "";
    if (!state.meLoaded) return;
    if (!state.user) {
      if (state.googleConfigured) {
        var a = document.createElement("a");
        a.className = "auth-btn signin-btn";
        a.href = "/auth/google";
        a.innerHTML = 'Sign in <span class="wide-only">with Google</span>';
        box.appendChild(a);
      }
      return;
    }
    var u = state.user;
    var label = u.name || u.email || "Account";
    var chip = document.createElement("div");
    chip.className = "user-chip";
    chip.innerHTML = '<span class="avatar init">' +
      esc(label.charAt(0).toUpperCase()) + '</span>' +
      '<span class="user-name">' + esc(label) + "</span>";
    box.appendChild(chip);
    if (u.is_admin) {
      var adm = document.createElement("a");
      adm.className = "auth-btn admin-link";
      adm.href = "/admin";
      adm.textContent = "Admin";
      box.appendChild(adm);
    }
    var out = document.createElement("button");
    out.type = "button";
    out.className = "auth-btn";
    out.textContent = "Sign out";
    out.addEventListener("click", function () {
      fetch("/auth/logout", { method: "POST" })
        .then(function () { window.location.reload(); });
    });
    box.appendChild(out);
  }

  function updateFeedHeading() {
    var h = $("feed-title");
    if (!h) return;
    h.textContent = !state.user ? "Creations"
      : state.user.is_admin ? "Creations" : "Your creations";
  }

  function loadMe() {
    fetch("/api/me").then(function (r) { return r.json(); })
      .then(function (d) {
        state.user = d.user || null;
        state.googleConfigured = !!d.google_configured;
        state.meLoaded = true;
        renderAuth();
        updateFeedHeading();
        if (state.user && state.user.banned) {
          var m = $("msg");
          m.textContent = "Your account is suspended — creations are disabled.";
          m.className = "msg err";
        }
        lastSig = null;
        refresh();
        if (state.user) loadProjects();
      })
      .catch(function () { state.meLoaded = true; renderAuth(); });
  }

  function loadOptions() {
    fetch("/api/options").then(function (r) { return r.json(); }).then(function (o) {
      state.style = o.defaults.style;
      state.aspect = o.defaults.aspect;
      styleItems = o.styles.map(function (s) { return { value: s.id, label: s.label }; });
      renderChips();
      var sel = $("aspect");
      sel.innerHTML = "";
      o.aspects.forEach(function (a) {
        var op = document.createElement("option");
        op.value = a;
        op.textContent = a;
        sel.appendChild(op);
      });
      sel.value = state.aspect;
      sel.addEventListener("change", function () { state.aspect = sel.value; });
      if (o.durations && o.durations.length) {
        var dsel = $("duration");
        dsel.innerHTML = "";
        o.durations.forEach(function (d) {
          var dop = document.createElement("option");
          dop.value = String(d);
          dop.textContent = d + "s";
          dsel.appendChild(dop);
        });
      }
      $("duration").value = String(o.defaults.duration);
    }).catch(function () { /* offline: chips stay empty, Generate still posts defaults */ });
  }

  /* sliding highlight for the Video|Image|Audio segmented control.
     Position is measured from the buttons' real rendered boxes
     (relative to the seg itself), so the bubble always sits exactly
     under the active label — offsetLeft alone can drift a few pixels
     when the seg's parent layout changes (grid tracks, wrapping). */
  function moveThumb() {
    var thumb = $("seg-thumb");
    if (!thumb) return;
    var seg = $("kind-seg");
    var active = null;
    Array.prototype.forEach.call(seg.children, function (b) {
      if (b.tagName === "BUTTON" && b.getAttribute("data-kind") === state.kind) active = b;
    });
    if (!active) return;
    var sr = seg.getBoundingClientRect();
    var br = active.getBoundingClientRect();
    thumb.style.width = br.width + "px";
    thumb.style.transform =
      "translateX(" + (br.left - sr.left - seg.clientLeft) + "px)";
  }

  function applyKind() {
    Array.prototype.forEach.call($("kind-seg").children, function (b) {
      if (b.tagName === "BUTTON") {
        b.classList.toggle("active", b.getAttribute("data-kind") === state.kind);
      }
    });
    $("media-opts").classList.toggle("hidden", state.kind === "audio");
    document.body.classList.toggle("kind-audio", state.kind === "audio");
    $("duration-wrap").classList.toggle("hidden", state.kind !== "video");
    $("prompt").placeholder = PLACEHOLDERS[state.kind];
    renderChips();
    moveThumb();
    /* the controls reflow when options hide/show — re-measure after
       the browser has painted the new layout */
    requestAnimationFrame(moveThumb);
  }

  Array.prototype.forEach.call($("kind-seg").children, function (b) {
    if (b.tagName !== "BUTTON") return;
    b.addEventListener("click", function () {
      state.kind = b.getAttribute("data-kind");
      applyKind();
    });
  });
  window.addEventListener("resize", moveThumb);

  /* textarea auto-grow, up to ~5 lines */
  var ta = $("prompt");
  function grow() {
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 148) + "px";
  }
  ta.addEventListener("input", grow);

  function generate() {
    var msg = $("msg");
    var prompt = ta.value.trim();
    msg.textContent = ""; msg.className = "msg";
    if (state.meLoaded && !state.user) {
      if (state.googleConfigured) { window.location.href = "/auth/google"; return; }
      msg.textContent = "Sign-in is not available yet.";
      msg.className = "msg err";
      return;
    }
    if (!prompt) {
      msg.textContent = "Write your idea first.";
      msg.className = "msg err";
      return;
    }
    var btn = $("generate");
    btn.disabled = true;
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: prompt,
        kind: state.kind,
        style: state.kind === "audio" ? state.voice : state.style,
        aspect: ($("aspect") && $("aspect").value) || state.aspect,
        duration: parseFloat($("duration").value || "3")
      })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) {
        if (res.j && res.j.detail === "sign_in_required") {
          window.location.href = "/auth/google";
          return;
        }
        if (res.j && res.j.detail === "account_suspended") {
          msg.textContent = "Your account is suspended — creations are disabled.";
        } else {
          msg.textContent = "Error: " + ((res.j && res.j.detail) || "could not create");
        }
        msg.className = "msg err";
        return;
      }
      ta.value = "";
      grow();
      lastSig = null;
      refresh();
    }).catch(function (e) {
      btn.disabled = false;
      msg.textContent = "Network error: " + e.message;
      msg.className = "msg err";
    });
  }
  $("generate").addEventListener("click", generate);

  /* ---------------- Studio | Agent view switch ---------------- */

  function moveViewThumb() {
    var thumb = $("view-thumb");
    if (!thumb) return;
    var active = null;
    Array.prototype.forEach.call($("view-seg").children, function (b) {
      if (b.tagName === "BUTTON" && b.getAttribute("data-view") === state.view) active = b;
    });
    if (!active) return;
    var seg = $("view-seg");
    var sr = seg.getBoundingClientRect();
    var br = active.getBoundingClientRect();
    thumb.style.width = br.width + "px";
    thumb.style.transform =
      "translateX(" + (br.left - sr.left - seg.clientLeft) + "px)";
  }

  function applyView() {
    var agent = state.view === "agent";
    Array.prototype.forEach.call($("view-seg").children, function (b) {
      if (b.tagName === "BUTTON") {
        b.classList.toggle("active", b.getAttribute("data-view") === state.view);
      }
    });
    $("composer").classList.toggle("hidden", agent);
    $("agent-panel").classList.toggle("hidden", !agent);
    document.querySelector("main").classList.toggle("agent-mode", agent);
    requestAnimationFrame(moveViewThumb);
    if (agent) enterAgent();
  }

  Array.prototype.forEach.call($("view-seg").children, function (b) {
    if (b.tagName !== "BUTTON") return;
    b.addEventListener("click", function () {
      state.view = b.getAttribute("data-view");
      applyView();
    });
  });
  window.addEventListener("resize", moveViewThumb);

  /* ---------------- TOQIX Agent ---------------- */

  var AGENT_ERR = "Agent is warming up — try again in a moment";

  function enterAgent() {
    loadProjects();
    if (!state.activeProject && !state.agentGreeted) {
      state.agentGreeted = true;
      agentRequest("hi", true);
    }
  }

  function loadProjects() {
    fetch("/api/projects").then(function (r) { return r.ok ? r.json() : []; })
      .then(function (list) {
        if (Array.isArray(list)) state.projects = list;
        renderSeriesChips();
        renderBible();
        lastSig = null; // let the feed re-render with series tags
      }).catch(function () { /* agent endpoints may not be live yet */ });
  }

  function projectById(id) {
    for (var i = 0; i < state.projects.length; i++) {
      if (state.projects[i].id === id) return state.projects[i];
    }
    return null;
  }

  function setActiveProject(p) {
    state.activeProject = p || null;
    renderSeriesChips();
    renderBible();
  }

  function upsertProject(p) {
    var found = false;
    for (var i = 0; i < state.projects.length; i++) {
      if (state.projects[i].id === p.id) { state.projects[i] = p; found = true; break; }
    }
    if (!found) state.projects.push(p);
    setActiveProject(p);
  }

  function renderSeriesChips() {
    var strip = $("series-strip");
    if (!strip) return;
    strip.innerHTML = "";
    if (!state.projects.length) {
      var s = document.createElement("span");
      s.className = "muted-note";
      s.textContent = "No series yet";
      strip.appendChild(s);
      return;
    }
    state.projects.forEach(function (p) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip" +
        (state.activeProject && state.activeProject.id === p.id ? " active" : "");
      b.textContent = p.name || "Series";
      b.addEventListener("click", function () { setActiveProject(p); });
      strip.appendChild(b);
    });
  }

  function renderBible() {
    var box = $("bible");
    if (!box) return;
    var p = state.activeProject;
    if (!p) { box.classList.add("hidden"); box.innerHTML = ""; return; }
    function row(k, v) {
      return '<div class="bible-row"><span>' + esc(k) + "</span><p>" + esc(v) + "</p></div>";
    }
    var html = '<div class="bible-name">' + esc(p.name || "Series") + "</div>";
    if (p.character) html += row("Character", p.character);
    if (p.style) html += row("Style", p.style);
    if (p.kind_default) html += row("Kind", KIND_LABEL[p.kind_default] || p.kind_default);
    if (p.aspect) html += row("Ratio", p.aspect);
    if (p.voice) html += row("Voice", p.voice);
    if (p.seed !== null && p.seed !== undefined && p.seed !== "") html += row("Seed", p.seed);
    box.innerHTML = html;
    box.classList.remove("hidden");
  }

  function addBubble(text, cls) {
    var chat = $("chat");
    var d = document.createElement("div");
    d.className = "bubble " + cls;
    d.textContent = text;
    chat.appendChild(d);
    chat.scrollTop = chat.scrollHeight;
    return d;
  }

  function addTyping() {
    var chat = $("chat");
    var d = document.createElement("div");
    d.className = "bubble agent typing";
    d.innerHTML = "<i></i><i></i><i></i>";
    chat.appendChild(d);
    chat.scrollTop = chat.scrollHeight;
    return d;
  }

  var CHAT_FALLBACK = "My thinking worker went offline — ask me about " +
    "creating something, or try again in a moment.";

  /*CHATPOLL-BEGIN*/
  /* Async agent replies: when the chat POST answers with a
     pending_chat_job, a GPU worker is writing the reply. The pending
     bubble polls for it and streams partial text in until it is done.
     Each job id gets at most one poller; every exit path (done,
     failed, timeout, cancel) stops the timer chain and drops the
     registry entry, so nothing leaks or double-polls. */
  var CHAT_POLL_MS = 2000;
  var CHAT_POLL_TIMEOUT_MS = 150000;
  var pendingPolls = {}; // chat job id -> { stop: fn }

  function chatScroll() {
    var chat = $("chat");
    chat.scrollTop = chat.scrollHeight;
  }

  function addPendingBubble() {
    var chat = $("chat");
    var d = document.createElement("div");
    d.className = "bubble agent pending";
    var txt = document.createElement("span");
    txt.className = "think-text";
    txt.textContent = "TOQIX is thinking…";
    var dots = document.createElement("span");
    dots.className = "think-dots";
    dots.setAttribute("aria-hidden", "true");
    dots.innerHTML = "<i></i><i></i><i></i>";
    d.appendChild(txt);
    d.appendChild(dots);
    chat.appendChild(d);
    chatScroll();
    return { bubble: d, dots: dots, text: txt };
  }

  function addChatNote(text) {
    var chat = $("chat");
    var d = document.createElement("div");
    d.className = "chat-note";
    d.textContent = text;
    chat.appendChild(d);
    chatScroll();
  }

  function startChatPoll(jobId, ui) {
    if (!jobId || pendingPolls[jobId]) return; // one poller per job
    var started = Date.now();
    var timer = null;
    var stopped = false;

    function stop() {
      if (stopped) return;
      stopped = true;
      if (timer) { clearTimeout(timer); timer = null; }
      delete pendingPolls[jobId];
    }
    pendingPolls[jobId] = { stop: stop };

    function finish(d) {
      stop();
      ui.dots.remove();
      ui.bubble.classList.remove("pending");
      ui.text.textContent = d.reply;
      chatScroll();
      if (d.queued_jobs && d.queued_jobs.length) {
        addChatNote("Added to your creations");
        lastSig = null; // feed re-renders and picks the new job up
        refresh();
      }
    }

    function fail() {
      stop();
      ui.dots.remove();
      ui.bubble.classList.remove("pending");
      ui.bubble.classList.add("err");
      ui.text.textContent = CHAT_FALLBACK;
      chatScroll();
    }

    function schedule() {
      if (stopped) return;
      if (Date.now() - started >= CHAT_POLL_TIMEOUT_MS) { fail(); return; }
      timer = setTimeout(tick, CHAT_POLL_MS);
    }

    function tick() {
      timer = null;
      if (stopped) return;
      if (Date.now() - started >= CHAT_POLL_TIMEOUT_MS) { fail(); return; }
      fetch("/api/agent/chat/" + encodeURIComponent(jobId))
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; })
        .then(function (d) {
          if (stopped) return; // finished/cancelled while fetching
          if (!d) { schedule(); return; } // transient hiccup: keep trying
          if (d.status === "done") {
            if (d.reply) finish(d); else fail();
            return;
          }
          if (d.status === "failed") { fail(); return; }
          // queued | generating: stream any partial text, keep the dots
          if (d.reply) { ui.text.textContent = d.reply; chatScroll(); }
          schedule();
        });
    }

    schedule();
  }

  function cancelAllChatPolls() {
    Object.keys(pendingPolls).forEach(function (id) {
      pendingPolls[id].stop();
    });
  }
  /*CHATPOLL-END*/

  function agentRequest(text, isGreeting) {
    if (state.agentBusy) return;
    if (state.meLoaded && !state.user) {
      if (!isGreeting) addBubble(text, "user");
      addBubble("Sign in with Google (top right) to use the Agent — " +
        "your series and creations stay private to your account.", "agent");
      return;
    }
    state.agentBusy = true;
    if (!isGreeting) addBubble(text, "user");
    var typing = addTyping();
    fetch("/api/agent/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: state.activeProject ? state.activeProject.id : null,
        message: text
      })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; })
        .catch(function () { return { ok: false, j: null }; });
    }).then(function (res) {
      typing.remove();
      state.agentBusy = false;
      if (!res.ok || !res.j) { addBubble(AGENT_ERR, "agent err"); return; }
      var d = res.j;
      if (d.project) upsertProject(d.project);
      if (d.pending_chat_job) {
        /* Async reply: agentBusy is already cleared above, so the
           input stays free; this bubble polls and streams on its own. */
        startChatPoll(d.pending_chat_job, addPendingBubble());
      } else if (d.reply) {
        addBubble(d.reply, "agent");
      }
      if (d.created_jobs && d.created_jobs.length) { lastSig = null; refresh(); }
    }).catch(function () {
      typing.remove();
      state.agentBusy = false;
      addBubble(AGENT_ERR, "agent err");
    });
  }

  function sendFromInput() {
    var input = $("agent-input");
    var v = input.value.trim();
    if (!v || state.agentBusy) return;
    input.value = "";
    agentRequest(v, false);
  }
  $("agent-send").addEventListener("click", sendFromInput);
  $("agent-input").addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); sendFromInput(); }
  });

  /* Knowledge shortcuts: two extra quick chips, built here so the
     markup stays untouched. They sit in the same row and send their
     words exactly like the static chips (bound by the loop below). */
  (function addKnowledgeChips() {
    var row = document.querySelector(".quick-chips");
    if (!row) return;
    ["Give me an idea", "Plan a series"].forEach(function (label) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "chip";
      b.setAttribute("data-quick", label);
      b.textContent = label;
      row.appendChild(b);
    });
  })();

  Array.prototype.forEach.call(document.querySelectorAll("[data-quick]"), function (b) {
    b.addEventListener("click", function () {
      if (state.agentBusy) return;
      agentRequest(b.getAttribute("data-quick"), false);
    });
  });

  $("new-series").addEventListener("click", function () {
    if (state.agentBusy) return;
    cancelAllChatPolls(); // pending bubbles are about to be wiped
    setActiveProject(null);
    $("chat").innerHTML = "";
    state.agentGreeted = true;
    agentRequest("hi", true);
  });

  /* ---------------- creations feed ---------------- */

  function displayStatus(j) {
    if (j.status === "exported" || j.status === "queued") return "queued";
    if (j.status === "running") return "generating";
    return j.status; // generating | done | failed
  }

  function mediaHTML(j, st) {
    if (st === "done" && j.output_path) {
      /* Done media opens in the big lightbox player on click — the
         tile itself is just a preview (owner's gallery rule). */
      if (j.kind === "image") {
        return '<div class="media filled openable" data-open="' + j.id +
          '"><img src="' + esc(j.output_path) + '" alt="">' +
          '<span class="open-hint">View</span></div>';
      }
      if (j.kind === "audio") {
        return '<div class="media"><div class="audio-glyph">♪</div>' +
          '<audio controls src="' + esc(j.output_path) + '"></audio>' +
          '<button type="button" class="open-player" data-open="' + j.id +
          '">Open player</button></div>';
      }
      return '<div class="media filled openable" data-open="' + j.id +
        '"><video preload="metadata" src="' + esc(j.output_path) + '"' +
        (j.thumb_path ? ' poster="' + esc(j.thumb_path) + '"' : "") +
        '></video><span class="play-overlay">&#9654;</span></div>';
    }
    if (st === "generating") {
      var p = Math.max(0, Math.min(100, j.progress || 0));
      return '<div class="media generating"><div class="pct">' + p + '<small>%</small></div>' +
        '<div class="bar"><i style="width:' + p + '%"></i></div>' +
        '<div class="note">Generating</div></div>';
    }
    if (st === "failed") {
      return '<div class="media failed"><div class="fail">Failed — try again' +
        (j.error ? "<br><span>" + esc(j.error) + "</span>" : "") + "</div></div>";
    }
    if (st === "cancelled") {
      return '<div class="media cancelled"><div class="note">Cancelled</div></div>';
    }
    // queued
    return '<div class="media queued"><div class="note big">In queue — generation will start soon</div></div>';
  }

  function sendFeedback(jobId, fields) {
    fetch("/api/jobs/" + jobId + "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields)
    }).then(function () { lastSig = null; refresh(); });
  }

  function feedbackRow(j) {
    var wrap = document.createElement("div");
    wrap.className = "feedback";
    var stars = document.createElement("span");
    stars.className = "stars";
    for (var i = 1; i <= 5; i++) {
      (function (n) {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = "★";
        if (j.rating >= n) b.className = "on";
        b.addEventListener("click", function () {
          sendFeedback(j.id, { rating: j.rating === n ? 0 : n });
        });
        stars.appendChild(b);
      })(i);
    }
    wrap.appendChild(stars);
    [["up", "👍"], ["down", "👎"]].forEach(function (pair) {
      var active = (pair[0] === "up" && j.thumbs === 1) ||
                   (pair[0] === "down" && j.thumbs === -1);
      var b = document.createElement("button");
      b.type = "button";
      b.className = "thumb-btn" + (active ? " on" : "");
      b.textContent = pair[1];
      b.addEventListener("click", function () {
        sendFeedback(j.id, { thumbs: active ? "none" : pair[0] });
      });
      wrap.appendChild(b);
    });
    return wrap;
  }

  var KIND_LABEL = { video: "Video", image: "Image", audio: "Audio" };
  var STATUS_LABEL = {
    queued: "In queue", generating: "Generating",
    done: "Done", failed: "Failed"
  };

  function seriesTag(j) {
    if (!j.project_id) return "";
    var p = projectById(j.project_id);
    var name = p ? (p.name || "") : "";
    return '<div><span class="series-tag">Agent series' +
      (name ? " · " + esc(name) : "") + "</span></div>";
  }

  function card(j) {
    var st = displayStatus(j);
    var div = document.createElement("div");
    div.className = "card glass";
    var meta = [KIND_LABEL[j.kind] || "Video", j.style, j.aspect];
    if (j.kind === "video") meta.push(j.duration + "s");
    div.innerHTML =
      mediaHTML(j, st) +
      '<div class="body">' +
        '<div class="prompt-line">' + esc(j.prompt) + "</div>" +
        seriesTag(j) +
        '<div class="meta-line"><span>' + esc(meta.join(" · ")) + "</span>" +
          '<span class="status ' + st + '">' + STATUS_LABEL[st] + "</span></div>" +
        (st !== "failed"
          ? '<details class="dprompt"><summary>Director\'s prompt</summary><p>' +
            esc(j.enhanced_prompt) + "</p></details>"
          : "") +
      "</div>";
    if (st === "done") {
      div.querySelector(".body").appendChild(feedbackRow(j));
    }
    var opener = div.querySelector("[data-open]");
    if (opener) {
      opener.addEventListener("click", function () { openLightbox(j.id); });
    }
    return div;
  }

  /* ---------------- lightbox player ----------------
     Clicking a creation opens it like a gallery piece: big player,
     full controls, prompt caption, prev/next through the feed. */

  var lbIndex = -1;

  function lbList() {
    return feedJobs.filter(function (j) {
      return displayStatus(j) === "done" && j.output_path;
    });
  }

  function lbRender() {
    var list = lbList();
    if (lbIndex < 0 || lbIndex >= list.length) return;
    var j = list[lbIndex];
    var box = $("lb-media");
    if (j.kind === "image") {
      box.innerHTML = '<img src="' + esc(j.output_path) + '" alt="">';
    } else if (j.kind === "audio") {
      box.innerHTML = '<div class="lb-audio"><div class="audio-glyph big">♪</div>' +
        '<audio controls autoplay src="' + esc(j.output_path) + '"></audio></div>';
    } else {
      box.innerHTML = '<video controls autoplay playsinline src="' +
        esc(j.output_path) + '"' +
        (j.thumb_path ? ' poster="' + esc(j.thumb_path) + '"' : "") +
        "></video>";
    }
    $("lb-prompt").textContent = j.prompt || "";
    var meta = [KIND_LABEL[j.kind] || "Video", j.style, j.aspect];
    if (j.kind === "video") meta.push(j.duration + "s");
    $("lb-meta").textContent = meta.join(" · ") + "  ·  " +
      (lbIndex + 1) + " / " + list.length;
    var dl = $("lb-download");
    dl.href = j.output_path;
    dl.setAttribute("download", "");
    var multi = list.length > 1;
    $("lb-prev").style.display = multi ? "" : "none";
    $("lb-next").style.display = multi ? "" : "none";
  }

  function openLightbox(jobId) {
    var list = lbList();
    lbIndex = -1;
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === jobId) { lbIndex = i; break; }
    }
    if (lbIndex < 0) return;
    $("lightbox").classList.remove("hidden");
    document.body.classList.add("lb-open");
    lbRender();
  }

  function closeLightbox() {
    $("lightbox").classList.add("hidden");
    document.body.classList.remove("lb-open");
    $("lb-media").innerHTML = ""; // stops any playing media
    lbIndex = -1;
  }

  function stepLightbox(dir) {
    var list = lbList();
    if (list.length < 2 || lbIndex < 0) return;
    lbIndex = (lbIndex + dir + list.length) % list.length;
    lbRender();
  }

  $("lb-close").addEventListener("click", closeLightbox);
  $("lb-backdrop").addEventListener("click", closeLightbox);
  $("lb-prev").addEventListener("click", function () { stepLightbox(-1); });
  $("lb-next").addEventListener("click", function () { stepLightbox(1); });
  document.addEventListener("keydown", function (e) {
    if ($("lightbox").classList.contains("hidden")) return;
    if (e.key === "Escape") closeLightbox();
    if (e.key === "ArrowLeft") stepLightbox(-1);
    if (e.key === "ArrowRight") stepLightbox(1);
  });

  function renderFeed(jobs) {
    feedJobs = jobs;
    var sig = JSON.stringify(jobs.map(function (j) {
      return [j.id, j.status, j.progress, j.output_path, j.rating, j.thumbs, j.project_id];
    }));
    if (sig === lastSig) return;
    lastSig = sig;
    var box = $("feed");
    box.innerHTML = "";
    if (!jobs.length) {
      box.innerHTML = state.user
        ? '<p class="empty">Nothing here yet — write your first idea in the box below.</p>'
        : '<p class="empty">Sign in with Google to create your own videos, images and voice — your creations stay private to you.</p>';
      return;
    }
    var fresh = 0;
    jobs.forEach(function (j) {
      var c = card(j);
      if (!seen[j.id]) {
        seen[j.id] = true;
        c.classList.add("enter");
        c.style.animationDelay = Math.min(fresh * 70, 490) + "ms";
        fresh++;
      }
      box.appendChild(c);
    });
  }

  function refresh() {
    fetch("/api/jobs").then(function (r) { return r.json(); })
      .then(renderFeed).catch(function () { /* keep last render */ });
  }

  applyKind();
  loadOptions();
  loadMe();
  refresh();
  setInterval(refresh, 4000);
  requestAnimationFrame(moveThumb);
  requestAnimationFrame(moveViewThumb);
})();
