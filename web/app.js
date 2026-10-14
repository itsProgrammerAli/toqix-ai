// TOQIX AI Studio — plain JS, same-origin API only. No external requests.
(function () {
  "use strict";

  var state = { aspect: "16:9", domains: {} };

  function $(id) { return document.getElementById(id); }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function loadOptions() {
    fetch("/api/options").then(function (r) { return r.json(); }).then(function (o) {
      var styleSel = $("style");
      o.styles.forEach(function (s) {
        var opt = document.createElement("option");
        opt.value = s.id; opt.textContent = s.label;
        styleSel.appendChild(opt);
      });
      styleSel.value = o.defaults.style;

      var modelSel = $("model");
      o.models.forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m.id; opt.textContent = m.label;
        modelSel.appendChild(opt);
      });
      modelSel.value = o.defaults.model;

      var chips = $("aspects");
      o.aspects.forEach(function (a) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "chip" + (a === state.aspect ? " active" : "");
        b.textContent = a;
        b.addEventListener("click", function () {
          state.aspect = a;
          Array.prototype.forEach.call(chips.children, function (c) {
            c.classList.toggle("active", c.textContent === a);
          });
        });
        chips.appendChild(b);
      });

      // Domain list is driven by the all-in-one curriculum.
      var domainSel = $("domain");
      (o.domains || []).forEach(function (d) {
        state.domains[d.id] = d;
        var opt = document.createElement("option");
        opt.value = d.id; opt.textContent = d.label;
        domainSel.appendChild(opt);
      });
      domainSel.addEventListener("change", function () {
        var d = state.domains[domainSel.value];
        var box = $("domain-examples");
        box.innerHTML = "";
        if (!d) { box.classList.add("hidden"); return; }
        $("style").value = d.style;   // the domain's recommended style
        d.examples_en.concat(d.examples_ur).forEach(function (ex) {
          var chip = document.createElement("button");
          chip.type = "button";
          chip.className = "ex";
          chip.textContent = ex;
          chip.addEventListener("click", function () { $("prompt").value = ex; });
          box.appendChild(chip);
        });
        box.classList.remove("hidden");
      });
    });
  }

  function createJob() {
    var msg = $("create-msg");
    msg.textContent = ""; msg.className = "msg";
    var payload = {
      prompt: $("prompt").value,
      style: $("style").value,
      aspect: state.aspect,
      duration: parseFloat($("duration").value),
      model: $("model").value,
      seed: parseInt($("seed").value || "42", 10),
      consent: $("consent").checked,
      domain: $("domain").value
    };
    if (!payload.prompt.trim()) {
      msg.textContent = "Pehle apna idea likho — koi si bhi bhasha mein.";
      msg.className = "msg err";
      return;
    }
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then(function (r) {
      return r.json().then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      if (!res.ok) {
        msg.textContent = "Error: " + (res.j.detail || "job failed");
        msg.className = "msg err";
        return;
      }
      var j = res.j;
      msg.textContent = "Job " + j.id + " tayyar hai — package export ho gaya.";
      $("enhanced-text").textContent = j.enhanced_prompt;
      $("negative-text").textContent = j.negative_prompt;
      $("enhanced-box").classList.remove("hidden");
      refresh();
    }).catch(function (e) {
      msg.textContent = "Network error: " + e.message;
      msg.className = "msg err";
    });
  }

  function jobRow(j) {
    var div = document.createElement("div");
    div.className = "job";
    var canImport = j.status !== "done";
    div.innerHTML =
      '<div class="meta">' +
        '<div class="prompt-line">' + esc(j.prompt) + "</div>" +
        '<div class="small-line">' + esc(j.id) + " · " + esc(j.style) + " · " +
          esc(j.aspect) + " · " + esc(j.duration) + "s · " + esc(j.model) + "</div>" +
        '<div class="small-line">' + esc(j.enhanced_prompt) + "</div>" +
        (j.error ? '<div class="small-line" style="color:#ff5d5d">' + esc(j.error) + "</div>" : "") +
      "</div>" +
      '<span class="badge ' + esc(j.status) + '">' + esc(j.status) + "</span>" +
      (canImport
        ? '<label class="small" style="border:1px solid #262a3f;padding:7px 12px;border-radius:8px;cursor:pointer;font-size:13px">' +
            "⬆ Import finished MP4" +
            '<input type="file" accept="video/*" style="display:none" data-import="' + esc(j.id) + '">' +
          "</label>"
        : '<a class="small" style="border:1px solid #262a3f;padding:7px 12px;border-radius:8px;font-size:13px;color:#e8eaf2;text-decoration:none" href="' +
            esc(j.output_path) + '" download>⬇ Download</a>');
    var input = div.querySelector("input[data-import]");
    if (input) {
      input.addEventListener("change", function () {
        if (input.files && input.files[0]) importResult(j.id, input.files[0]);
      });
    }
    div.querySelector(".meta").appendChild(feedbackRow(j));
    return div;
  }

  function sendFeedback(jobId, fields) {
    fetch("/api/jobs/" + jobId + "/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields)
    }).then(function () { refresh(); });
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
        b.title = "Rate " + n + "/5";
        b.addEventListener("click", function () {
          sendFeedback(j.id, { rating: j.rating === n ? 0 : n });
        });
        stars.appendChild(b);
      })(i);
    }
    wrap.appendChild(stars);

    [["up", "👍"], ["down", "👎"]].forEach(function (pair) {
      var b = document.createElement("button");
      b.type = "button";
      b.className = "thumb-btn" +
        ((pair[0] === "up" && j.thumbs === 1) || (pair[0] === "down" && j.thumbs === -1) ? " on" : "");
      b.textContent = pair[1];
      b.addEventListener("click", function () {
        var active = (pair[0] === "up" && j.thumbs === 1) || (pair[0] === "down" && j.thumbs === -1);
        sendFeedback(j.id, { thumbs: active ? "none" : pair[0] });
      });
      wrap.appendChild(b);
    });

    var label = document.createElement("label");
    label.className = "consent-mini";
    var cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = !!j.consent;
    cb.addEventListener("change", function () {
      sendFeedback(j.id, { consent: cb.checked });
    });
    label.appendChild(cb);
    label.appendChild(document.createTextNode("use for TOQIX training"));
    wrap.appendChild(label);

    return wrap;
  }

  function importResult(jobId, file) {
    var fd = new FormData();
    fd.append("file", file);
    fetch("/api/jobs/" + jobId + "/import", { method: "POST", body: fd })
      .then(function (r) { return r.json(); })
      .then(function () { refresh(); })
      .catch(function () { refresh(); });
  }

  function renderJobs(jobs) {
    var box = $("jobs");
    box.innerHTML = "";
    if (!jobs.length) {
      box.innerHTML = '<p class="empty">No jobs yet. Create your first one above.</p>';
      return;
    }
    jobs.forEach(function (j) { box.appendChild(jobRow(j)); });
  }

  function renderGallery(items) {
    var box = $("gallery");
    box.innerHTML = "";
    if (!items.length) {
      box.innerHTML = '<p class="empty">Finished videos will appear here.</p>';
      return;
    }
    items.forEach(function (j) {
      var card = document.createElement("div");
      card.className = "card";
      card.innerHTML =
        '<video controls preload="metadata" src="' + esc(j.output_path) + '"' +
        (j.thumb_path ? ' poster="' + esc(j.thumb_path) + '"' : "") + "></video>" +
        '<div class="cap">' + esc(j.prompt) +
          '<div class="small-line">' + esc(j.style) + " · " + esc(j.aspect) + " · " +
          esc(j.duration) + "s</div></div>";
      box.appendChild(card);
    });
  }

  function refresh() {
    fetch("/api/jobs").then(function (r) { return r.json(); }).then(renderJobs);
    fetch("/api/gallery").then(function (r) { return r.json(); }).then(renderGallery);
  }

  $("create-btn").addEventListener("click", createJob);
  $("dataset-btn").addEventListener("click", function () {
    var msg = $("dataset-msg");
    msg.textContent = "Curating dataset…"; msg.className = "msg";
    fetch("/api/dataset/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}"
    }).then(function (r) { return r.json(); }).then(function (m) {
      msg.textContent = "Dataset v" + m.version + " built: " +
        m.counts.included + " clips included, " + m.counts.skipped +
        " skipped (consent/rating rules — see manifest.json). " +
        "Sync data/datasets/v" + m.version + " to Drive → TOQIX/datasets and run notebook 04.";
    }).catch(function (e) {
      msg.textContent = "Error: " + e.message; msg.className = "msg err";
    });
  });
  $("batch-btn").addEventListener("click", function () {
    var msg = $("dataset-msg");
    msg.textContent = "Creating curriculum batch…"; msg.className = "msg";
    fetch("/api/curriculum/batch", { method: "POST" })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        msg.textContent = "Curriculum batch created: " + res.count +
          " jobs, one per domain. See the job queue above.";
        refresh();
      }).catch(function (e) {
        msg.textContent = "Error: " + e.message; msg.className = "msg err";
      });
  });
  loadOptions();
  refresh();
  setInterval(refresh, 8000);
})();
