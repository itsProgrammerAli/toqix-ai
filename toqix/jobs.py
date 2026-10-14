"""TOQIX job store — SQLite-backed queue for generation jobs.

A job is created on the website, exported as a *job package* JSON
(the file the Colab runner notebook reads from Google Drive), and
completed when the finished MP4 is imported back and normalized.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from . import config
from .prompt_engine import enhance_prompt

_LOCK = threading.Lock()

STATUSES = ("queued", "exported", "generating", "running", "done", "failed")
KINDS = ("video", "image", "audio")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id              TEXT PRIMARY KEY,
                prompt          TEXT NOT NULL,
                translated      TEXT DEFAULT '',
                enhanced_prompt TEXT NOT NULL,
                negative_prompt TEXT NOT NULL,
                style           TEXT NOT NULL,
                aspect          TEXT NOT NULL,
                duration        REAL NOT NULL,
                model           TEXT NOT NULL,
                seed            INTEGER NOT NULL,
                status          TEXT NOT NULL DEFAULT 'queued',
                output_path     TEXT DEFAULT '',
                thumb_path      TEXT DEFAULT '',
                package_path    TEXT DEFAULT '',
                error           TEXT DEFAULT '',
                rating          INTEGER NOT NULL DEFAULT 0,
                thumbs          INTEGER NOT NULL DEFAULT 0,
                consent         INTEGER NOT NULL DEFAULT 0,
                domain          TEXT NOT NULL DEFAULT '',
                kind            TEXT NOT NULL DEFAULT 'video',
                progress        INTEGER NOT NULL DEFAULT 0,
                project_id      TEXT DEFAULT NULL,
                claimed_by      TEXT DEFAULT NULL,
                claimed_at      REAL DEFAULT NULL,
                created_at      REAL NOT NULL,
                updated_at      REAL NOT NULL
            )
            """
        )
        # Migration for databases created before the flywheel fields existed.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
        for col, ddl in (
            ("rating", "INTEGER NOT NULL DEFAULT 0"),
            ("thumbs", "INTEGER NOT NULL DEFAULT 0"),
            ("consent", "INTEGER NOT NULL DEFAULT 0"),
            ("domain", "TEXT NOT NULL DEFAULT ''"),
            ("kind", "TEXT NOT NULL DEFAULT 'video'"),
            ("progress", "INTEGER NOT NULL DEFAULT 0"),
            ("project_id", "TEXT DEFAULT NULL"),
            ("claimed_by", "TEXT DEFAULT NULL"),
            ("claimed_at", "REAL DEFAULT NULL"),
        ):
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["kind"] = d.get("kind") or "video"
    d["progress"] = int(d.get("progress") or 0)
    # Series/agent jobs carry their project id; normal jobs are null.
    d["project_id"] = d.get("project_id") or None
    # Worker-mesh claim fields: who holds this job, and when the claim
    # was last touched (claim or progress heartbeat); null when unheld.
    d["claimed_by"] = d.get("claimed_by") or None
    _claimed_at = d.get("claimed_at")
    d["claimed_at"] = float(_claimed_at) if _claimed_at is not None else None
    d["consent"] = bool(d.get("consent", 0))
    # API-surface aliases for the flywheel feedback contract:
    # train_consent mirrors consent; feedback renders thumbs as up/down.
    d["train_consent"] = d["consent"]
    d["feedback"] = {1: "up", -1: "down"}.get(int(d.get("thumbs", 0) or 0), "")
    width, height = config.size_for_aspect(d["aspect"])
    d["width"] = width
    d["height"] = height
    d["num_frames"] = config.frames_for_duration(d["duration"])
    d["fps"] = config.DEFAULT_FPS
    d["steps"] = config.DEFAULT_STEPS
    d["guidance"] = config.DEFAULT_GUIDANCE
    d["model_hf_id"] = config.MODELS.get(d["model"], {}).get("hf_id", "")
    return d


def job_package(job: dict) -> dict:
    """The exact JSON the Colab runner (notebook 03) consumes."""
    return {
        "job_id": job["id"],
        "prompt": job["enhanced_prompt"],
        "negative_prompt": job["negative_prompt"],
        "model": job["model"],
        "model_hf_id": job["model_hf_id"],
        "width": job["width"],
        "height": job["height"],
        "num_frames": job["num_frames"],
        "fps": job["fps"],
        "steps": job["steps"],
        "guidance": job["guidance"],
        "seed": job["seed"],
        "kind": job.get("kind", "video"),
        "domain": job.get("domain", ""),
        "lora_name": config.LORA_NAME,
        "created_by": "TOQIX AI Studio",
    }


def export_package(job: dict) -> Path:
    path = config.EXPORTS_DIR / f"{job['id']}.json"
    path.write_text(json.dumps(job_package(job), indent=2), encoding="utf-8")
    return path


def create_job(
    prompt: str,
    style: str = "cinematic",
    aspect: str = config.DEFAULT_ASPECT,
    duration: float = config.DEFAULT_DURATION,
    model: str = config.DEFAULT_MODEL,
    seed: int = config.DEFAULT_SEED,
    consent: bool = False,
    domain: str = "",
    kind: str = "video",
    project_id: str | None = None,
) -> dict:
    if model not in config.MODELS:
        raise ValueError(f"unknown model: {model}")
    if aspect not in config.ASPECT_SIZES:
        raise ValueError(f"unknown aspect: {aspect}")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")

    enhanced = enhance_prompt(
        prompt, style=style, aspect=aspect, duration=duration,
        domain_id=domain or None, kind=kind,
    )
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with _LOCK, _conn() as conn:
        conn.execute(
            """
            INSERT INTO jobs (id, prompt, translated, enhanced_prompt,
                              negative_prompt, style, aspect, duration,
                              model, seed, status, consent, domain, kind,
                              progress, project_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                job_id, enhanced["original"], enhanced["translated"],
                enhanced["enhanced_prompt"], enhanced["negative_prompt"],
                style, aspect, float(duration), model, int(seed),
                1 if consent else 0,
                domain or enhanced.get("domain", ""), kind,
                project_id or None, now, now,
            ),
        )
    job = get_job(job_id)
    pkg_path = export_package(job)
    with _LOCK, _conn() as conn:
        conn.execute(
            "UPDATE jobs SET package_path = ? WHERE id = ?",
            (str(pkg_path), job_id),
        )
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_project_jobs(project_id: str, limit: int = 500) -> list[dict]:
    """All jobs of one agent series project, oldest first (Part 1, 2, …)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE project_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (project_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def gallery(limit: int = 100) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'done' ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_job(job_id: str, **fields) -> dict | None:
    allowed = {
        "status", "output_path", "thumb_path", "error", "package_path",
        "rating", "thumbs", "consent", "domain", "progress",
        "claimed_by", "claimed_at",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return get_job(job_id)
    if "status" in fields and fields["status"] not in STATUSES:
        raise ValueError(f"bad status: {fields['status']}")
    if "progress" in fields:
        fields["progress"] = int(fields["progress"])
        if not (0 <= fields["progress"] <= 100):
            raise ValueError("progress must be 0-100")
    if "rating" in fields and not (0 <= int(fields["rating"]) <= 5):
        raise ValueError("rating must be 0-5")
    if "thumbs" in fields and int(fields["thumbs"]) not in (-1, 0, 1):
        raise ValueError("thumbs must be -1, 0 or 1")
    if "consent" in fields:
        fields["consent"] = 1 if fields["consent"] else 0
    fields["updated_at"] = time.time()
    assignments = ", ".join(f"{k} = ?" for k in fields)
    with _LOCK, _conn() as conn:
        conn.execute(
            f"UPDATE jobs SET {assignments} WHERE id = ?",
            (*fields.values(), job_id),
        )
    return get_job(job_id)


# ---------------------------------------------------------------------------
# Worker mesh — atomic claims.
#
# Many free-GPU sessions (Colab on any account, Kaggle, ...) can work the
# SAME queue in parallel: a worker atomically claims one waiting job, the
# claim is stamped with the worker's name, and progress posts act as a
# heartbeat that refreshes the stamp. If a session dies silently, its
# claim goes stale and the job returns to the pool automatically.
# ---------------------------------------------------------------------------

STALE_CLAIM_SECONDS = 45 * 60  # 45 minutes without a heartbeat = dead worker
WAITING_STATUSES = ("queued", "exported")


def release_stale_claims(max_age: float = STALE_CLAIM_SECONDS) -> int:
    """Return jobs held by (presumably dead) workers to the waiting pool.

    A claim is stale when the job is still 'generating', its last claim /
    heartbeat stamp is older than ``max_age`` seconds, and it produced
    no output. Returns how many jobs were released.
    """
    cutoff = time.time() - max_age
    with _LOCK, _conn() as conn:
        cur = conn.execute(
            """
            UPDATE jobs
               SET status = 'queued', progress = 0,
                   claimed_by = NULL, claimed_at = NULL,
                   updated_at = ?
             WHERE status = 'generating'
               AND claimed_at IS NOT NULL
               AND claimed_at < ?
               AND (output_path IS NULL OR output_path = '')
            """,
            (time.time(), cutoff),
        )
        return cur.rowcount


def claim_job(job_id: str, worker: str) -> dict | None:
    """Atomically claim one waiting job for ``worker``.

    The status check and the claim stamp happen inside a single
    BEGIN IMMEDIATE transaction, so two workers racing for the same job
    cannot both win: exactly one gets the job; the other gets None.
    Returns the claimed job dict, or None when the job is not waiting
    (already claimed, generating, done, failed, or unknown).
    """
    now = time.time()
    with _LOCK:
        conn = _conn()
        conn.isolation_level = None  # manual transaction control
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None or row["status"] not in WAITING_STATUSES:
                conn.execute("ROLLBACK")
                return None
            conn.execute(
                """
                UPDATE jobs
                   SET status = 'generating', progress = 1,
                       claimed_by = ?, claimed_at = ?, updated_at = ?
                 WHERE id = ?
                """,
                (worker, now, now, job_id),
            )
            conn.execute("COMMIT")
        finally:
            conn.close()
    return get_job(job_id)


init_db()
