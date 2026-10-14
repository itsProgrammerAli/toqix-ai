// TOQIX AI — Liquid Glass studio UI. Plain JS, same-origin API only. No external requests.
(function () {
  "use strict";

  var state = { kind: "video", style: "cinematic", aspect: "16:9" };
  var lastSig = null;
  var seen = {};

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

  function loadOptions() {
    fetch("/api/options").then(function (r) { return r.json(); }).then(function (o) {
      state.style = o.defaults.style;
      state.aspect = o.defaults.aspect;
      chipRow($("styles"),
        o.styles.map(function (s) { return { value: s.id, label: s.label }; }),
        state.style,
        function (v) { state.style = v; });
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
        style: state.style,
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
      return [j.id, j.status, j.progress, j.output_path, j.rating, j.thumbs];
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
  refresh();
  setInterval(refresh, 4000);
  requestAnimationFrame(moveThumb);
})();
