// TOQIX AI — Liquid Glass studio UI. Plain JS, same-origin API only. No external requests.
(function () {
  "use strict";

  var state = {
    kind: "video", style: "cinematic", voice: "Ava", aspect: "16:9",
    view: "studio", activeProject: null, projects: [],
    agentBusy: false, agentGreeted: false
  };
  var lastSig = null;
  var seen = {};
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

  function loadOptions() {
    fetch("/api/options").then(function (r) { return r.json(); }).then(function (o) {
      state.style = o.defaults.style;
      state.aspect = o.defaults.aspect;
      styleItems = o.styles.map(function (s) { return { value: s.id, label: s.label }; });
      renderChips();
      chipRow($("aspects"),
        o.aspects.map(function (a) { return { value: a, label: a }; }),
        state.aspect,
        function (v) { state.aspect = v; });
      $("duration").value = String(o.defaults.duration);
    }).catch(function () { /* offline: chips stay empty, Generate still posts defaults */ });
  }

  /* sliding highlight for the Video|Image|Audio segmented control */
  function moveThumb() {
    var thumb = $("seg-thumb");
    if (!thumb) return;
    var active = null;
    Array.prototype.forEach.call($("kind-seg").children, function (b) {
      if (b.tagName === "BUTTON" && b.getAttribute("data-kind") === state.kind) active = b;
    });
    if (!active) return;
    thumb.style.width = active.offsetWidth + "px";
    thumb.style.transform = "translateX(" + active.offsetLeft + "px)";
  }

  function applyKind() {
    Array.prototype.forEach.call($("kind-seg").children, function (b) {
      if (b.tagName === "BUTTON") {
        b.classList.toggle("active", b.getAttribute("data-kind") === state.kind);
      }
    });
    $("media-opts").classList.toggle("hidden", state.kind === "audio");
    $("duration-wrap").classList.toggle("hidden", state.kind !== "video");
    $("prompt").placeholder = PLACEHOLDERS[state.kind];
    renderChips();
    moveThumb();
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
        aspect: state.aspect,
        duration: parseFloat($("duration").value || "3")
      })
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      btn.disabled = false;
      if (!res.ok) {
        msg.textContent = "Error: " + (res.j.detail || "could not create");
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
    thumb.style.width = active.offsetWidth + "px";
    thumb.style.transform = "translateX(" + active.offsetLeft + "px)";
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
      if (j.kind === "image") {
        return '<div class="media filled"><img src="' + esc(j.output_path) +
          '" alt=""></div>';
      }
      if (j.kind === "audio") {
        return '<div class="media"><div class="audio-glyph">♪</div>' +
          '<audio controls src="' + esc(j.output_path) + '"></audio></div>';
      }
      return '<div class="media filled"><video controls preload="metadata" src="' +
        esc(j.output_path) + '"' +
        (j.thumb_path ? ' poster="' + esc(j.thumb_path) + '"' : "") +
        "></video></div>";
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
    return div;
  }

  function renderFeed(jobs) {
    var sig = JSON.stringify(jobs.map(function (j) {
      return [j.id, j.status, j.progress, j.output_path, j.rating, j.thumbs, j.project_id];
    }));
    if (sig === lastSig) return;
    lastSig = sig;
    var box = $("feed");
    box.innerHTML = "";
    if (!jobs.length) {
      box.innerHTML = '<p class="empty">Nothing here yet — write your first idea in the box below.</p>';
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
  loadProjects();
  refresh();
  setInterval(refresh, 4000);
  requestAnimationFrame(moveThumb);
  requestAnimationFrame(moveViewThumb);
})();
