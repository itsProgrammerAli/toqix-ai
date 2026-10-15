"""TOQIX AI Studio server — FastAPI.

Serves the studio website and the job APIs. Creating a job runs the
TOQIX prompt engine and exports a job package for the Colab GPU runner;
importing a finished MP4 normalizes it to delivery spec, thumbnails it
and publishes it in the gallery. Generation itself makes zero external
calls; the one owner-requested exception is Google sign-in (accounts),
which only ever talks to Google's OAuth endpoints.

Accounts release: visitors sign in with Google; every creation belongs
to its user and is visible only to them (plus an admin-featured public
showcase). The owner's main Gmail is the admin and gets /admin — all
users, all activity, and an alerts feed fed by the deterministic
abuse watch in auth.check_prompt (blocked attempts are refused AND
reported there). Fleet workers no longer read the job list: they use
POST /api/jobs/claim-next and the server hands them one job at a time.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, auth, config, curriculum, dataset, jobs, postprocess

app = FastAPI(title="TOQIX AI Studio", version="1.0.0")


# ---------------------------------------------------------------------------
# Accounts — who is asking?
# ---------------------------------------------------------------------------

def _api_key_ok(request: Request) -> bool:
    key = auth.api_key()
    return bool(key) and request.headers.get("x-api-key") == key


def _current_user(request: Request) -> dict | None:
    """The signed-in user for this request, or None. A valid machine
    API key acts as the admin (the owner's own automations)."""
    if _api_key_ok(request):
        return auth.get_or_create_admin()
    return auth.user_for_session(request.cookies.get(auth.COOKIE_NAME))


def _require_user(request: Request) -> dict:
    user = _current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign_in_required")
    return user


def _require_admin(request: Request) -> dict:
    user = _require_user(request)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="admin_only")
    return user


def _public_user(user: dict | None) -> dict | None:
    if user is None:
        return None
    return {k: user.get(k) for k in
            ("id", "email", "name", "picture", "is_admin", "banned")}


def _can_see(user: dict | None, job: dict) -> bool:
    """A creation is visible ONLY to its owner and to the admin.
    (Owner decision 2026-10-15: no public showcase — featuring a job
    never makes it visible to anyone else.)"""
    if user is None:
        return False
    return bool(user.get("is_admin")) or job.get("user_id") == user.get("id")


def _cookie_kwargs(max_age: int) -> dict:
    return {
        "max_age": max_age,
        "httponly": True,
        "samesite": "lax",
        "secure": auth.base_url().startswith("https"),
        "path": "/",
    }


def _screen_or_403(user: dict, text: str, event: str) -> dict:
    """Run the abuse watch over one user text. Files the alert (any
    severity) and returns the verdict; the caller refuses the request
    when verdict["blocked"] is set."""
    verdict = auth.check_prompt(text)
    if verdict["severity"]:
        auth.add_alert(user.get("id"), user.get("email", ""),
                       verdict["severity"], verdict["rule"], text)
        auth.log_activity(user.get("id"), user.get("email", ""),
                          event, verdict["rule"])
    return verdict


_BLOCKED_REPLY = {
    "reply": "I can't create that — the request was flagged by the "
             "safety rules. Try a different idea and I'll build it "
             "right away.",
    "project": None,
    "created_jobs": [],
    "state": "blocked",
    "pending_chat_job": None,
}


class JobCreate(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    kind: str = "video"            # "video" | "image" | "audio"
    style: str = "cinematic"
    aspect: str = config.DEFAULT_ASPECT
    duration: float = config.DEFAULT_DURATION
    model: str = config.DEFAULT_MODEL
    seed: int = config.DEFAULT_SEED
    consent: bool = False          # flywheel training consent — default OFF
    domain: str = ""               # curriculum domain id; "" = auto-detect


class ProgressIn(BaseModel):
    progress: int = Field(..., ge=0, le=100)
    status: str | None = None      # optional transition, e.g. "generating"
    worker: str | None = None      # worker identity — heartbeat refresh
    error: str | None = None       # failure detail — stored on the job so a
                                   # failed job always says WHY on the site


class ClaimIn(BaseModel):
    worker: str = Field(..., min_length=1, max_length=120)  # e.g. "colab-a3f9"


class ReplyIn(BaseModel):
    text: str = Field(..., max_length=20000)  # the reply-so-far, in full
    final: bool = False        # True closes the (chat) job as done


class WorkerPingIn(BaseModel):
    worker: str = Field(..., min_length=1, max_length=120)
    caps: list[str] = []       # capabilities served, e.g. ["video", "chat"]


class FeedbackIn(BaseModel):
    rating: int | None = None      # 1-5 (0 clears)
    thumbs: str | None = None      # "up" | "down" | "none"
    feedback: str | None = None    # alias of thumbs ("up" | "down" | "none")
    consent: bool | None = None    # flywheel training consent for this job
    train_consent: bool | None = None  # alias of consent


class DatasetBuildIn(BaseModel):
    include_low_rated: bool = False


class AgentChatIn(BaseModel):
    project_id: str | None = None   # null = no series yet / new series
    message: str = Field(..., max_length=4000)


class ClaimNextIn(BaseModel):
    worker: str = Field(..., min_length=1, max_length=120)
    handled_keys: list = []    # content keys this worker already made
    heavy_only: bool = False   # True = only heavy (10s+) video jobs —
                               # the Kaggle worker's lane


class BanIn(BaseModel):
    banned: bool


class FeaturedIn(BaseModel):
    featured: bool


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "name": "TOQIX AI", "external_apis": "none",
            "accounts": auth.google_configured()}


# ---------------------------------------------------------------------------
# Google sign-in (server-side OAuth) + session endpoints
# ---------------------------------------------------------------------------

@app.get("/auth/google")
def auth_google():
    if not auth.google_configured():
        raise HTTPException(status_code=503,
                            detail="Google sign-in is not configured yet")
    state, cookie = auth.make_state_cookie()
    resp = RedirectResponse(auth.google_auth_url(state))
    resp.set_cookie(auth.STATE_COOKIE, cookie, **_cookie_kwargs(600))
    return resp


@app.get("/auth/google/callback")
def auth_google_callback(request: Request, code: str | None = None,
                         state: str | None = None,
                         error: str | None = None):
    if error or not code:
        return RedirectResponse("/?auth_error=denied")
    if not auth.check_state_cookie(
            request.cookies.get(auth.STATE_COOKIE), state):
        return RedirectResponse("/?auth_error=state")
    try:
        tokens = auth.exchange_code(code)
        info = auth.fetch_userinfo(tokens["access_token"])
    except Exception:
        return RedirectResponse("/?auth_error=google")
    email = (info.get("email") or "").strip().lower()
    if not email or not info.get("sub"):
        return RedirectResponse("/?auth_error=profile")
    user = auth.upsert_google_user(info["sub"], email,
                                   info.get("name") or "",
                                   info.get("picture") or "")
    auth.log_activity(user["id"], email,
                      "login_banned" if user["banned"] else "login",
                      "Google sign-in")
    resp = RedirectResponse("/")
    resp.set_cookie(auth.COOKIE_NAME,
                    auth.make_session_cookie(user["id"]),
                    **_cookie_kwargs(auth.SESSION_SECONDS))
    resp.delete_cookie(auth.STATE_COOKIE, path="/")
    return resp


@app.get("/auth/dev")
def auth_dev(email: str, name: str = ""):
    """Local-development sign-in (creates a real user row + session).
    Exists ONLY when TOQIX_DEV_AUTH=1 — never set in production."""
    if not auth.dev_auth_enabled():
        raise HTTPException(status_code=404, detail="not found")
    user = auth.upsert_google_user("dev:" + email, email,
                                   name or email.split("@")[0], "")
    resp = RedirectResponse("/")
    resp.set_cookie(auth.COOKIE_NAME,
                    auth.make_session_cookie(user["id"]),
                    **_cookie_kwargs(auth.SESSION_SECONDS))
    return resp


@app.post("/auth/logout")
def auth_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@app.get("/api/me")
def api_me(request: Request):
    return {"user": _public_user(_current_user(request)),
            "google_configured": auth.google_configured()}


@app.get("/api/options")
def options():
    from .prompt_engine import STYLE_PRESETS

    return {
        "styles": [
            {"id": k, "label": v["label"]} for k, v in STYLE_PRESETS.items()
        ],
        "aspects": list(config.ASPECT_SIZES.keys()),
        # The composer's Length dropdown (video) is built from this.
        "durations": list(config.VIDEO_DURATIONS),
        "models": [
            {"id": k, "label": v["label"]} for k, v in config.MODELS.items()
        ],
        # The Studio's domain list is driven by the all-in-one curriculum.
        "domains": [
            {
                "id": d["id"],
                "label": d["label"],
                "style": d["style"],
                "examples_en": d["example_prompts_en"],
                "examples_ur": d["example_prompts_ur"],
            }
            for d in curriculum.load_domains()
        ],
        "defaults": {
            "style": "cinematic",
            "aspect": config.DEFAULT_ASPECT,
            "duration": config.DEFAULT_DURATION,
            "model": config.DEFAULT_MODEL,
            "seed": config.DEFAULT_SEED,
        },
    }


@app.get("/api/domains")
def domains():
    """The full all-in-one curriculum taxonomy — exactly what
    data/curriculum/domains.json defines (domains, bilingual keywords,
    example prompts, caption templates, style presets)."""
    return {"domains": curriculum.load_domains()}


@app.post("/api/jobs", status_code=201)
def create_job(request: Request, body: JobCreate):
    """Create a creation job for the signed-in user. The abuse watch
    screens the prompt first: hard-blocked prompts are refused (and
    alerted to the admin panel); softer signals are alerted only.
    A burst of creations files a rate alert and is throttled."""
    user = _require_user(request)
    if user.get("banned"):
        auth.log_activity(user["id"], user["email"],
                          "create_blocked_banned", body.prompt[:200])
        raise HTTPException(status_code=403, detail="account_suspended")
    verdict = _screen_or_403(user, body.prompt, "prompt_flagged")
    if verdict["blocked"]:
        raise HTTPException(
            status_code=400,
            detail="This prompt can't be generated — it was flagged "
                   "by the safety rules.")
    if jobs.recent_job_count(user["id"], 600) >= 12:
        auth.add_alert(user["id"], user["email"], "medium",
                       "rate_abuse", body.prompt,
                       "12+ creations in 10 minutes")
        auth.log_activity(user["id"], user["email"], "rate_limited",
                          body.prompt[:200])
        raise HTTPException(status_code=429,
                            detail="Too many creations at once — "
                                   "wait a few minutes.")
    try:
        job = jobs.create_job(
            prompt=body.prompt, style=body.style, aspect=body.aspect,
            duration=body.duration, model=body.model, seed=body.seed,
            consent=body.consent, domain=body.domain, kind=body.kind,
            user_id=user["id"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    auth.log_activity(user["id"], user["email"], "job_created",
                      f"{body.kind}: {body.prompt[:160]}")
    return job


@app.post("/api/jobs/{job_id}/feedback")
def job_feedback(request: Request, job_id: str, body: FeedbackIn):
    """Record the user's verdict on a job: star rating, thumbs, and the
    flywheel training-consent flag (stored on the job itself). Only the
    job's owner (or the admin) may rate it."""
    user = _require_user(request)
    job = jobs.get_job(job_id)
    if not job or not _can_see(user, job):
        raise HTTPException(status_code=404, detail="job not found")
    fields: dict = {}
    if body.rating is not None:
        fields["rating"] = body.rating
    if body.thumbs is not None:
        fields["thumbs"] = {"up": 1, "down": -1, "none": 0}.get(body.thumbs, 0)
    elif body.feedback is not None:
        fields["thumbs"] = {"up": 1, "down": -1, "none": 0}.get(body.feedback, 0)
    if body.consent is not None:
        fields["consent"] = body.consent
    elif body.train_consent is not None:
        fields["consent"] = body.train_consent
    try:
        return jobs.update_job(job_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/curriculum/batch", status_code=201)
def curriculum_batch(request: Request):
    """Create one job per curriculum domain (its first English example
    prompt, its recommended style) — a balanced all-domain batch for
    the GPU runner. Admin-only (it creates ownerless system jobs)."""
    admin = _require_admin(request)
    created = []
    for domain in curriculum.load_domains():
        job = jobs.create_job(
            prompt=domain["example_prompts_en"][0],
            style=domain["style"],
            domain=domain["id"],
            user_id=admin["id"],
        )
        created.append({
            "domain": domain["id"], "label": domain["label"],
            "job_id": job["id"], "status": job["status"],
        })
    return {"created": created, "count": len(created)}


@app.post("/api/dataset/build")
def dataset_build(request: Request, body: DatasetBuildIn | None = None):
    """Curate the next versioned flywheel training dataset (admin)."""
    _require_admin(request)
    manifest = dataset.build_dataset(
        include_low_rated=bool(body and body.include_low_rated)
    )
    return manifest


@app.get("/api/dataset/latest")
def dataset_latest(request: Request):
    _require_admin(request)
    manifest = dataset.latest_manifest()
    if not manifest:
        return {"version": None, "counts": {"included": 0, "skipped": 0}}
    return {
        "version": manifest["version"],
        "counts": manifest["counts"],
        "created_at": manifest["created_at"],
    }


@app.get("/api/jobs")
def list_jobs(request: Request, include_chat: bool = False):
    # Dead workers' jobs return to the pool before anyone reads the queue.
    # Privacy scoping (accounts release): anonymous visitors see only
    # the admin-featured showcase; a signed-in user sees their own
    # creations + the showcase; the admin (or the machine API key) sees
    # everything. Chat jobs stay out of feeds unless the admin asks.
    jobs.release_stale_claims()
    user = _current_user(request)
    if user is not None and user.get("is_admin"):
        return jobs.list_jobs(include_chat=include_chat)
    if user is not None:
        return jobs.list_jobs(owner_id=user["id"])
    # Signed-out visitors see no creations at all (owner decision
    # 2026-10-15: privacy first — no public showcase).
    return []


@app.post("/api/jobs/claim-next")
def claim_next(body: ClaimNextIn):
    """The worker mesh's door (accounts release): a worker asks for
    work and the server atomically claims the oldest waiting job for
    it — workers never download the (now per-user) job list. Returns
    the claimed job, or 204 when nothing is waiting for this worker.
    A worker may pass heavy_only to claim only heavy (10s+) videos —
    the Kaggle worker's reserved lane."""
    claimed = jobs.claim_next_waiting(body.worker, body.handled_keys,
                                      body.heavy_only)
    if claimed is None:
        return JSONResponse(status_code=204, content=None)
    return claimed


@app.get("/api/stats")
def stats():
    """Counts-only snapshot for the Auto-GPU watchdog — queue depth
    and worker liveness, never prompts or owners."""
    workers = jobs.list_workers()
    return {
        "counts": jobs.queue_counts(),
        "workers_online": sum(1 for w in workers if w["online"]),
        "wake": jobs.wake_status(),
    }


@app.get("/api/zoo")
def zoo():
    """The model zoo's public face: which open models serve which
    kind right now, plus registry counts. Public on purpose — model
    names are published knowledge, and the response carries no
    prompts, users, or queue data."""
    from . import model_zoo

    return {
        "summary": model_zoo.zoo_summary(),
        "active": model_zoo.active_models(),
    }


@app.post("/api/jobs/{job_id}/claim")
def claim_job(job_id: str, body: ClaimIn):
    """Atomically claim one waiting job for a worker (the worker mesh).

    Exactly one worker can win a job: the winner gets 200 + the job
    (now status "generating", stamped with claimed_by / claimed_at);
    everyone else gets 409 {"detail": "already claimed", "status": ...}.
    Stale claims are released first, so a job whose worker died can be
    claimed again here.
    """
    jobs.release_stale_claims()
    if not jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    claimed = jobs.claim_job(job_id, body.worker)
    if claimed is None:
        current = jobs.get_job(job_id)
        return JSONResponse(
            status_code=409,
            content={
                "detail": "already claimed",
                "status": current["status"] if current else "unknown",
            },
        )
    return claimed


@app.post("/api/jobs/{job_id}/progress")
def job_progress(job_id: str, body: ProgressIn):
    """Live progress reports from the generation runner:
    {"progress": 0-100, "status": optional transition, "worker": optional}.

    Every progress post is also a claim HEARTBEAT: it refreshes the
    job's claimed_at stamp (and records claimed_by when the worker
    names itself), so a live worker's job is never mistaken for stale.
    """
    if not jobs.get_job(job_id):
        raise HTTPException(status_code=404, detail="job not found")
    fields: dict = {"progress": body.progress, "claimed_at": time.time()}
    if body.status is not None:
        fields["status"] = body.status
    if body.worker:
        fields["claimed_by"] = body.worker
    if body.error:
        fields["error"] = body.error[:500]
    try:
        return jobs.update_job(job_id, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/jobs/{job_id}/reply")
def job_reply(job_id: str, body: ReplyIn):
    """A chat worker posts its reply for a job: partial snapshots
    while it generates, then one final post that closes the job.

    The final text is post-processed BEFORE it is stored: a hidden
    [[QUEUE ...]] directive (the LLM asking the studio to create a
    video/image/audio) is stripped from the visible reply, turned
    into a real creation job through the normal path, and recorded
    on the chat job as queued_jobs."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if not body.final:
        return jobs.set_reply(job_id, body.text, final=False)
    clean, directive = agent.parse_queue_directive(body.text)
    updated = jobs.set_reply(job_id, clean, final=True)
    if directive:
        queued_id = agent.queue_from_directive(updated, directive)
        if queued_id:
            updated = jobs.add_queued_jobs(job_id, [queued_id]) or updated
    return updated


@app.post("/api/workers/ping")
def worker_ping(body: WorkerPingIn):
    """Fleet workers check in here (name + the capabilities they
    serve); a worker counts as online for 90 s after its last ping."""
    jobs.ping_worker(body.worker, body.caps)
    return {"ok": True}


@app.get("/api/workers")
def get_workers():
    """The worker registry: name, caps, last_seen and computed
    online flag for every worker that ever pinged."""
    return {"workers": jobs.list_workers()}


@app.get("/api/wake")
def get_wake():
    """The site's GPU wake signal: ``needed`` is true when a prompt
    is waiting and no worker is online — the fleet watchdog reads
    this and starts a GPU worker automatically."""
    return jobs.wake_status()


@app.post("/api/wake/ack")
def wake_ack():
    """The watchdog acknowledges a wake once it has dispatched a
    worker start, so it does not dispatch duplicates."""
    jobs.clear_wake()
    return {"ok": True}


@app.get("/api/jobs/{job_id}")
def get_job(request: Request, job_id: str):
    job = jobs.get_job(job_id)
    if not job or not _can_see(_current_user(request), job):
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/jobs/{job_id}/package")
def get_package(request: Request, job_id: str):
    job = jobs.get_job(job_id)
    if not job or not _can_see(_current_user(request), job):
        raise HTTPException(status_code=404, detail="job not found")
    pkg = Path(job["package_path"])
    if not pkg.exists():
        jobs.export_package(job)
    return FileResponse(pkg, media_type="application/json",
                        filename=f"toqix_job_{job_id}.json")


_IMPORT_EXTS = {
    "video": (".mp4", ".mov", ".mkv", ".webm"),
    "image": (".jpg", ".jpeg", ".png", ".webp"),
    "audio": (".mp3", ".wav", ".m4a", ".ogg"),
}


@app.post("/api/jobs/{job_id}/import")
async def import_result(job_id: str, file: UploadFile = File(...)):
    """Import a finished result for a job, per kind:
    video → normalize to delivery spec + JPG thumbnail;
    image → save (PNG/WebP converted to JPG when ffmpeg is available),
    the image itself is its thumbnail;
    audio → save as-is, no thumbnail. Marks the job done at 100%."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    kind = job.get("kind") or "video"
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in _IMPORT_EXTS.get(kind, ()):
        raise HTTPException(status_code=400, detail=f"expected a {kind} file")

    raw_path = config.IMPORTS_DIR / f"{job_id}_raw{suffix}"
    with raw_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    try:
        if kind == "video":
            out_path = config.OUTPUTS_DIR / f"{job_id}.mp4"
            thumb_path = config.THUMBS_DIR / f"{job_id}.jpg"
            postprocess.normalize(raw_path, out_path)
            postprocess.thumbnail(out_path, thumb_path)
            jobs.update_job(
                job_id, status="done", progress=100,
                output_path=f"/outputs/{out_path.name}",
                thumb_path=f"/thumbs/{thumb_path.name}",
                claimed_by=None, claimed_at=None,
            )
        elif kind == "image":
            out_path = config.OUTPUTS_DIR / f"{job_id}.jpg"
            if suffix in (".jpg", ".jpeg"):
                shutil.copyfile(raw_path, out_path)
            elif shutil.which("ffmpeg"):
                postprocess.to_jpg(raw_path, out_path)
            else:  # no ffmpeg: keep the original format as-is
                out_path = config.OUTPUTS_DIR / f"{job_id}{suffix}"
                shutil.copyfile(raw_path, out_path)
            jobs.update_job(
                job_id, status="done", progress=100,
                output_path=f"/outputs/{out_path.name}",
                thumb_path=f"/outputs/{out_path.name}",
                claimed_by=None, claimed_at=None,
            )
        else:  # audio — stored as-is, no thumbnail
            out_path = config.OUTPUTS_DIR / f"{job_id}{suffix}"
            shutil.copyfile(raw_path, out_path)
            jobs.update_job(
                job_id, status="done", progress=100,
                output_path=f"/outputs/{out_path.name}",
                thumb_path=None,
                claimed_by=None, claimed_at=None,
            )
    except Exception as exc:  # ffmpeg error etc.
        jobs.update_job(job_id, status="failed", error=str(exc)[:500],
                        claimed_by=None, claimed_at=None)
        raise HTTPException(status_code=422, detail=f"import failed: {exc}")

    return jobs.get_job(job_id)


@app.post("/api/agent/chat")
def agent_chat(request: Request, body: AgentChatIn):
    """One turn with the TOQIX Agent: chat + consistent-series control.
    The agent (toqix/agent.py) is deterministic-first — it collects a
    series bible (character / style / kind / voice), then queues scene
    jobs that all share the project's character anchor, style and
    FIXED seed via jobs.create_job(project_id=..., seed=...). A
    free-form message it cannot answer itself may instead return
    {"reply": null, "pending_chat_job": <id>} — the conversation was
    handed to the fleet's LLM worker; poll the job below.
    Signed-in users only; the abuse watch screens every message."""
    user = _require_user(request)
    if user.get("banned"):
        raise HTTPException(status_code=403, detail="account_suspended")
    verdict = _screen_or_403(user, body.message, "agent_message_flagged")
    if verdict["blocked"]:
        return _BLOCKED_REPLY
    return agent.chat(body.project_id, body.message,
                      user_id=user["id"],
                      is_admin=bool(user.get("is_admin")))


@app.get("/api/agent/chat/{job_id}")
def agent_chat_poll(request: Request, job_id: str):
    """Poll one chat job for the web layer: its status and, once a
    worker posts it, the reply (final replies are stored cleaned of
    any [[QUEUE ...]] directive; queued_jobs lists the creation
    jobs such a directive produced)."""
    user = _require_user(request)
    job = jobs.get_job(job_id)
    if (not job or job.get("kind") != "chat"
            or not (user.get("is_admin") or job.get("user_id") == user["id"])):
        raise HTTPException(status_code=404, detail="chat job not found")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "reply": job.get("reply") or None,
        "reply_done": job.get("reply_done", 0),
        "queued_jobs": job.get("queued_jobs", []),
    }


@app.get("/api/projects")
def list_projects(request: Request):
    """The signed-in user's own agent series projects (admin: all)."""
    user = _require_user(request)
    return agent.list_projects(user_id=user["id"],
                               is_admin=bool(user.get("is_admin")))


@app.get("/api/projects/{project_id}")
def get_project(request: Request, project_id: str):
    user = _require_user(request)
    owner = agent.project_owner_id(project_id)
    if owner is None and not user.get("is_admin"):
        raise HTTPException(status_code=404, detail="project not found")
    if (owner is not None and owner != user["id"]
            and not user.get("is_admin")):
        raise HTTPException(status_code=404, detail="project not found")
    detail = agent.get_project_detail(project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="project not found")
    return detail


@app.get("/api/gallery")
def gallery(request: Request):
    user = _current_user(request)
    if user is not None and user.get("is_admin"):
        return jobs.gallery()
    if user is not None:
        return jobs.gallery(owner_id=user["id"])
    # Signed-out visitors see no creations at all (owner decision
    # 2026-10-15: privacy first — no public showcase).
    return []


# ---------------------------------------------------------------------------
# Admin panel — the owner's eyes on the whole studio
# ---------------------------------------------------------------------------

@app.get("/admin")
def admin_page(request: Request):
    user = _current_user(request)
    if user is None:
        return RedirectResponse("/auth/google")
    if not user.get("is_admin"):
        return RedirectResponse("/")
    return FileResponse(config.WEB_DIR / "admin.html")


@app.get("/api/admin/overview")
def admin_overview(request: Request):
    _require_admin(request)
    data = auth.overview()
    data["counts"] = jobs.queue_counts()
    workers = jobs.list_workers()
    data["workers_online"] = sum(1 for w in workers if w["online"])
    return data


@app.get("/api/admin/users")
def admin_users(request: Request):
    _require_admin(request)
    keys = ("id", "email", "name", "picture", "is_admin", "banned",
            "created_at", "last_seen", "job_count", "alert_count")
    return [{k: u.get(k) for k in keys} for u in auth.list_users()]


@app.post("/api/admin/users/{user_id}/ban")
def admin_ban_user(request: Request, user_id: str, body: BanIn):
    admin = _require_admin(request)
    if user_id == admin["id"]:
        raise HTTPException(status_code=400,
                            detail="the admin cannot ban itself")
    target = auth.set_banned(user_id, body.banned)
    if target is None:
        raise HTTPException(status_code=404, detail="user not found")
    auth.log_activity(admin["id"], admin["email"],
                      "ban_user" if body.banned else "unban_user",
                      target["email"])
    return _public_user(target)


@app.get("/api/admin/activity")
def admin_activity(request: Request, limit: int = 100):
    _require_admin(request)
    return auth.list_activity(limit=limit)


@app.get("/api/admin/alerts")
def admin_alerts(request: Request, limit: int = 100):
    _require_admin(request)
    return auth.list_alerts(limit=limit)


@app.post("/api/admin/alerts/{alert_id}/review")
def admin_review_alert(request: Request, alert_id: int):
    _require_admin(request)
    auth.review_alert(alert_id)
    return {"ok": True}


@app.get("/api/admin/jobs")
def admin_jobs(request: Request, limit: int = 200):
    _require_admin(request)
    emails = {u["id"]: u["email"] for u in auth.list_users()}
    rows = jobs.list_jobs(limit=limit, include_chat=True)
    for row in rows:
        row["owner_email"] = emails.get(row.get("user_id") or "", "")
    return rows


@app.post("/api/admin/jobs/{job_id}/featured")
def admin_feature_job(request: Request, job_id: str, body: FeaturedIn):
    _require_admin(request)
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return jobs.update_job(job_id, featured=1 if body.featured else 0)


@app.exception_handler(HTTPException)
async def _http_exc(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def _media_privacy(request: Request, call_next):
    """Finished media is private by default: /outputs and /thumbs
    serve a file only to its owner, to the admin, or to anyone when
    the admin featured that creation in the public showcase."""
    path = request.url.path
    if path.startswith(("/outputs/", "/thumbs/")):
        job = jobs.get_job(Path(path).stem)
        if job is not None and not _can_see(_current_user(request), job):
            return JSONResponse(status_code=404,
                                content={"detail": "not found"})
    return await call_next(request)


# Static trees (registered last so API routes win).
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=config.OUTPUTS_DIR), name="outputs")
app.mount("/thumbs", StaticFiles(directory=config.THUMBS_DIR), name="thumbs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
