"""TOQIX AI Studio server — FastAPI.

Serves the studio website and the job APIs. Creating a job runs the
TOQIX prompt engine and exports a job package for the Colab GPU runner;
importing a finished MP4 normalizes it to delivery spec, thumbnails it
and publishes it in the gallery. Zero external calls.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import agent, config, curriculum, dataset, jobs, postprocess

app = FastAPI(title="TOQIX AI Studio", version="1.0.0")


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


@app.get("/")
def index():
    return FileResponse(config.WEB_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "name": "TOQIX AI", "external_apis": "none"}


@app.get("/api/options")
def options():
    from .prompt_engine import STYLE_PRESETS

    return {
        "styles": [
            {"id": k, "label": v["label"]} for k, v in STYLE_PRESETS.items()
        ],
        "aspects": list(config.ASPECT_SIZES.keys()),
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
def create_job(body: JobCreate):
    try:
        job = jobs.create_job(
            prompt=body.prompt, style=body.style, aspect=body.aspect,
            duration=body.duration, model=body.model, seed=body.seed,
            consent=body.consent, domain=body.domain, kind=body.kind,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return job


@app.post("/api/jobs/{job_id}/feedback")
def job_feedback(job_id: str, body: FeedbackIn):
    """Record the user's verdict on a job: star rating, thumbs, and the
    flywheel training-consent flag (stored on the job itself)."""
    job = jobs.get_job(job_id)
    if not job:
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
def curriculum_batch():
    """Create one job per curriculum domain (its first English example
    prompt, its recommended style) — a balanced all-domain batch for the
    GPU runner."""
    created = []
    for domain in curriculum.load_domains():
        job = jobs.create_job(
            prompt=domain["example_prompts_en"][0],
            style=domain["style"],
            domain=domain["id"],
        )
        created.append({
            "domain": domain["id"], "label": domain["label"],
            "job_id": job["id"], "status": job["status"],
        })
    return {"created": created, "count": len(created)}


@app.post("/api/dataset/build")
def dataset_build(body: DatasetBuildIn | None = None):
    """Curate the next versioned flywheel training dataset."""
    manifest = dataset.build_dataset(
        include_low_rated=bool(body and body.include_low_rated)
    )
    return manifest


@app.get("/api/dataset/latest")
def dataset_latest():
    manifest = dataset.latest_manifest()
    if not manifest:
        return {"version": None, "counts": {"included": 0, "skipped": 0}}
    return {
        "version": manifest["version"],
        "counts": manifest["counts"],
        "created_at": manifest["created_at"],
    }


@app.get("/api/jobs")
def list_jobs(include_chat: bool = False):
    # Dead workers' jobs return to the pool before anyone reads the queue.
    # The public feed hides chat jobs (conversations, not creations);
    # workers pass include_chat=1 so they can see and claim them.
    jobs.release_stale_claims()
    return jobs.list_jobs(include_chat=include_chat)


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


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/jobs/{job_id}/package")
def get_package(job_id: str):
    job = jobs.get_job(job_id)
    if not job:
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
def agent_chat(body: AgentChatIn):
    """One turn with the TOQIX Agent: chat + consistent-series control.
    The agent (toqix/agent.py) is deterministic-first — it collects a
    series bible (character / style / kind / voice), then queues scene
    jobs that all share the project's character anchor, style and
    FIXED seed via jobs.create_job(project_id=..., seed=...). A
    free-form message it cannot answer itself may instead return
    {"reply": null, "pending_chat_job": <id>} — the conversation was
    handed to the fleet's LLM worker; poll the job below."""
    return agent.chat(body.project_id, body.message)


@app.get("/api/agent/chat/{job_id}")
def agent_chat_poll(job_id: str):
    """Poll one chat job for the web layer: its status and, once a
    worker posts it, the reply (final replies are stored cleaned of
    any [[QUEUE ...]] directive; queued_jobs lists the creation
    jobs such a directive produced)."""
    job = jobs.get_job(job_id)
    if not job or job.get("kind") != "chat":
        raise HTTPException(status_code=404, detail="chat job not found")
    return {
        "job_id": job["id"],
        "status": job["status"],
        "reply": job.get("reply") or None,
        "reply_done": job.get("reply_done", 0),
        "queued_jobs": job.get("queued_jobs", []),
    }


@app.get("/api/projects")
def list_projects():
    """All agent series projects, newest first."""
    return agent.list_projects()


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    detail = agent.get_project_detail(project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="project not found")
    return detail


@app.get("/api/gallery")
def gallery():
    return jobs.gallery()


@app.exception_handler(HTTPException)
async def _http_exc(_request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


# Static trees (registered last so API routes win).
app.mount("/static", StaticFiles(directory=config.WEB_DIR), name="static")
app.mount("/outputs", StaticFiles(directory=config.OUTPUTS_DIR), name="outputs")
app.mount("/thumbs", StaticFiles(directory=config.THUMBS_DIR), name="thumbs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
