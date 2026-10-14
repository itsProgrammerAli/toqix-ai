"""TOQIX AI Studio server — FastAPI.

Serves the studio website and the job APIs. Creating a job runs the
TOQIX prompt engine and exports a job package for the Colab GPU runner;
importing a finished MP4 normalizes it to delivery spec, thumbnails it
and publishes it in the gallery. Zero external calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, curriculum, dataset, jobs, postprocess

app = FastAPI(title="TOQIX AI Studio", version="1.0.0")


class JobCreate(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: str = "cinematic"
    aspect: str = config.DEFAULT_ASPECT
    duration: float = config.DEFAULT_DURATION
    model: str = config.DEFAULT_MODEL
    seed: int = config.DEFAULT_SEED
    consent: bool = False          # flywheel training consent — default OFF
    domain: str = ""               # curriculum domain id; "" = auto-detect


class FeedbackIn(BaseModel):
    rating: int | None = None      # 1-5 (0 clears)
    thumbs: str | None = None      # "up" | "down" | "none"
    feedback: str | None = None    # alias of thumbs ("up" | "down" | "none")
    consent: bool | None = None    # flywheel training consent for this job
    train_consent: bool | None = None  # alias of consent


class DatasetBuildIn(BaseModel):
    include_low_rated: bool = False


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
            consent=body.consent, domain=body.domain,
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
def list_jobs():
    return jobs.list_jobs()


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


@app.post("/api/jobs/{job_id}/import")
async def import_result(job_id: str, file: UploadFile = File(...)):
    """Import a finished MP4 (from the Colab runner): normalize it to
    delivery spec, extract a JPG thumbnail, mark the job done."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if not (file.filename or "").lower().endswith((".mp4", ".mov", ".mkv", ".webm")):
        raise HTTPException(status_code=400, detail="expected a video file")

    raw_path = config.IMPORTS_DIR / f"{job_id}_raw{Path(file.filename).suffix.lower()}"
    with raw_path.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    out_path = config.OUTPUTS_DIR / f"{job_id}.mp4"
    thumb_path = config.THUMBS_DIR / f"{job_id}.jpg"
    try:
        postprocess.normalize(raw_path, out_path)
        postprocess.thumbnail(out_path, thumb_path)
    except Exception as exc:  # ffmpeg error etc.
        jobs.update_job(job_id, status="failed", error=str(exc)[:500])
        raise HTTPException(status_code=422, detail=f"import failed: {exc}")

    jobs.update_job(
        job_id, status="done",
        output_path=f"/outputs/{out_path.name}",
        thumb_path=f"/thumbs/{thumb_path.name}",
    )
    return jobs.get_job(job_id)


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
