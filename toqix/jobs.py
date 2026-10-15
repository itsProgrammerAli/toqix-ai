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

STATUSES = ("queued", "exported", "generating", "running", "done", "failed",
            "cancelled")
KINDS = ("video", "image", "audio", "chat")


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
                user_id         TEXT DEFAULT NULL,
                featured        INTEGER NOT NULL DEFAULT 0,
                claimed_by      TEXT DEFAULT NULL,
                claimed_at      REAL DEFAULT NULL,
                reply           TEXT DEFAULT NULL,
                reply_done      INTEGER NOT NULL DEFAULT 0,
                queued_jobs     TEXT NOT NULL DEFAULT '',
                created_at      REAL NOT NULL,
                updated_at      REAL NOT NULL
            )
            """
        )
        # Worker registry: every fleet worker pings in with the
        # capabilities it can serve (e.g. ["video", "chat"]); a worker
        # counts as online while its last ping is fresh (list_workers).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS workers (
                name      TEXT PRIMARY KEY,
                caps      TEXT NOT NULL DEFAULT '[]',
                last_seen REAL NOT NULL DEFAULT 0
            )
            """
        )
        # Key-value store for site-level signals (the GPU wake flag).
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
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
            ("user_id", "TEXT DEFAULT NULL"),
            ("featured", "INTEGER NOT NULL DEFAULT 0"),
            ("claimed_by", "TEXT DEFAULT NULL"),
            ("claimed_at", "REAL DEFAULT NULL"),
            ("reply", "TEXT DEFAULT NULL"),
            ("reply_done", "INTEGER NOT NULL DEFAULT 0"),
            ("queued_jobs", "TEXT NOT NULL DEFAULT ''"),
        ):
            if col not in existing:
                conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {ddl}")


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["kind"] = d.get("kind") or "video"
    d["progress"] = int(d.get("progress") or 0)
    # Heavy flag: a 10s+ video is the heavy class of work (see
    # config.HEAVY_DURATION) — derived here, never stored, so rows
    # written before the flag existed behave exactly as before.
    try:
        _duration = float(d.get("duration") or 0)
    except (TypeError, ValueError):
        _duration = 0.0
    d["heavy"] = bool(d["kind"] == "video"
                      and _duration >= config.HEAVY_DURATION)
    # Sound bed + scene structure (video quality upgrade): derived
    # here, never stored — the prompt engine is deterministic, so
    # recomputing from the stored prompt/style/aspect/duration gives
    # exactly what create-time enhancement produced, and jobs queued
    # BEFORE these fields existed gain them retroactively. Video
    # jobs only; every other kind carries the empty defaults, and
    # the runner treats missing/empty values as "no sound/scene
    # instructions" and falls back on its own.
    d["sound_prompt"] = ""
    d["scenes"] = []
    if d["kind"] == "video":
        try:
            _extra = enhance_prompt(
                d.get("prompt") or "",
                style=d.get("style") or "cinematic",
                aspect=d.get("aspect") or config.DEFAULT_ASPECT,
                duration=_duration,
                domain_id=d.get("domain") or None,
                kind="video",
            )
            d["sound_prompt"] = _extra.get("sound_prompt", "")
            d["scenes"] = _extra.get("scenes", [])
        except Exception:
            d["sound_prompt"] = ""
            d["scenes"] = []
    # Series/agent jobs carry their project id; normal jobs are null.
    d["project_id"] = d.get("project_id") or None
    # Worker-mesh claim fields: who holds this job, and when the claim
    # was last touched (claim or progress heartbeat); null when unheld.
    d["claimed_by"] = d.get("claimed_by") or None
    _claimed_at = d.get("claimed_at")
    d["claimed_at"] = float(_claimed_at) if _claimed_at is not None else None
    # Chat jobs: the worker's reply text (None until one is posted),
    # whether the final reply landed, and the real creation jobs a
    # [[QUEUE ...]] directive in that reply produced.
    d["reply"] = d.get("reply") or None
    d["reply_done"] = int(d.get("reply_done") or 0)
    try:
        d["queued_jobs"] = json.loads(d.get("queued_jobs") or "[]")
    except (TypeError, ValueError):
        d["queued_jobs"] = []
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
        "duration": job["duration"],
        "heavy": bool(job.get("heavy", False)),
        "sound_prompt": job.get("sound_prompt", ""),
        "scenes": job.get("scenes", []),
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
    user_id: str | None = None,
) -> dict:
    if model not in config.MODELS:
        raise ValueError(f"unknown model: {model}")
    if aspect not in config.ASPECT_SIZES:
        raise ValueError(f"unknown aspect: {aspect}")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")

    if kind == "chat":
        # A chat job's prompt is a ready-made JSON conversation pack
        # for the fleet's LLM worker — it must reach the worker
        # byte-for-byte, so the prompt engine never touches it.
        enhanced = {
            "original": prompt, "translated": "",
            "enhanced_prompt": prompt, "negative_prompt": "",
            "domain": "",
        }
    else:
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
                              progress, project_id, user_id,
                              created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                job_id, enhanced["original"], enhanced["translated"],
                enhanced["enhanced_prompt"], enhanced["negative_prompt"],
                style, aspect, float(duration), model, int(seed),
                1 if consent else 0,
                domain or enhanced.get("domain", ""), kind,
                project_id or None, user_id or None, now, now,
            ),
        )
    job = get_job(job_id)
    pkg_path = export_package(job)
    with _LOCK, _conn() as conn:
        conn.execute(
            "UPDATE jobs SET package_path = ? WHERE id = ?",
            (str(pkg_path), job_id),
        )
    # Website-integrated GPU dispatch: if no worker is online, the
    # site itself raises the wake signal so a GPU gets started.
    if not any(w["online"] for w in list_workers()):
        request_wake(job_id, kind)
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_jobs(limit: int = 100, include_chat: bool = False,
              owner_id: str | None = None,
              featured_only: bool = False) -> list[dict]:
    # Chat jobs are conversations, not creations: they stay out of the
    # public feed (and the dataset curation) unless include_chat is set.
    # Privacy scoping (accounts release): with featured_only, ONLY the
    # admin-featured showcase is visible (anonymous visitors); with
    # owner_id, that user's own jobs plus the featured showcase;
    # with neither, the full list (admin / machine access only — the
    # server enforces who may ask for it).
    clauses: list[str] = []
    params: list = []
    if not include_chat:
        clauses.append("kind != 'chat'")
    if featured_only:
        # Owner decision 2026-10-15: there is NO public showcase.
        # Signed-out visitors never see any creations.
        clauses.append("1 = 0")
    elif owner_id is not None:
        clauses.append("user_id = ?")
        params.append(owner_id)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs" + where
            + " ORDER BY created_at DESC LIMIT ?", (*params, limit)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_project_jobs(project_id: str, limit: int = 500) -> list[dict]:
    """All jobs of one agent series project, oldest first (Part 1, 2, …)."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE project_id = ? AND kind != 'chat' "
            "ORDER BY created_at ASC LIMIT ?",
            (project_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def gallery(limit: int = 100, owner_id: str | None = None,
            featured_only: bool = False) -> list[dict]:
    # Same privacy scoping as list_jobs, over finished creations.
    scope = ""
    params: list = []
    if featured_only:
        # Owner decision 2026-10-15: no public showcase — always empty.
        scope = " AND 1 = 0"
    elif owner_id is not None:
        scope = " AND user_id = ?"
        params.append(owner_id)
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'done'" + scope
            + " ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def recent_job_count(user_id: str, seconds: float) -> int:
    """Jobs one user created inside a window (rate-abuse watch)."""
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE user_id = ?"
            " AND created_at > ?",
            (user_id, time.time() - seconds),
        ).fetchone()
    return int(row["n"])


def queue_counts() -> dict:
    """Counts-only snapshot for the fleet watchdog / stats endpoint —
    never exposes prompts or owners."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
        ).fetchall()
    counts = {r["status"]: r["n"] for r in rows}
    return {
        "queued": counts.get("queued", 0) + counts.get("exported", 0),
        "generating": counts.get("generating", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "cancelled": counts.get("cancelled", 0),
    }


def claim_next_waiting(worker: str,
                       handled_keys: list | None = None,
                       heavy_only: bool = False) -> dict | None:
    """Server-side claim for the worker mesh (accounts release).

    Workers no longer download the whole job list (it now carries
    per-user creations): they POST here and the server atomically
    claims the oldest waiting job for them — real user submissions
    ("queued") before legacy "exported" packages, oldest first.
    Same-content duplicates within the waiting pool collapse to one
    candidate, and content keys the worker already handled this
    session (``handled_keys``: [kind, prompt, aspect, duration,
    style]) are skipped, preserving the runner's dedupe behaviour.

    With ``heavy_only`` set, only heavy jobs (10s+ videos — see
    config.HEAVY_DURATION) are candidates: the Kaggle worker, whose
    GPU hours are reserved for the heavy class, takes those while
    the Colab fleet keeps working the normal queue oldest-first.
    """
    release_stale_claims()
    handled = {tuple(str(x) for x in key) for key in (handled_keys or [])}
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued', 'exported')"
            " ORDER BY CASE status WHEN 'queued' THEN 0 ELSE 1 END,"
            " created_at ASC"
        ).fetchall()
    seen: set = set()
    for row in rows:
        job = _row_to_dict(row)
        if heavy_only and not job.get("heavy"):
            continue
        key = (str(job.get("kind") or "video"),
               str((job.get("prompt") or "").strip().lower()),
               str(job.get("aspect")), str(job.get("duration")),
               str(job.get("style")))
        if key in handled or key in seen:
            continue
        seen.add(key)
        claimed = claim_job(job["id"], worker)
        if claimed is not None:
            return claimed
    return None


def update_job(job_id: str, **fields) -> dict | None:
    allowed = {
        "status", "output_path", "thumb_path", "error", "package_path",
        "rating", "thumbs", "consent", "domain", "progress",
        "claimed_by", "claimed_at", "featured", "user_id",
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


# ---------------------------------------------------------------------------
# Chat jobs — replies posted back by the fleet's LLM worker.
#
# A kind="chat" job carries a JSON conversation pack in its prompt.
# The worker that claims it streams its answer as reply snapshots
# (partial posts) and closes the job with one final post. The server
# post-processes the final text (see agent.parse_queue_directive)
# BEFORE it is stored here, so a stored reply is always clean.
# ---------------------------------------------------------------------------

def set_reply(job_id: str, text: str, final: bool = False) -> dict | None:
    """Store a worker's reply on a job. Returns the updated job, or
    None for an unknown id.

    ``text`` is the reply-so-far in full — workers send cumulative
    snapshots, not deltas. A partial post only updates the text; a
    final post also closes the job: status 'done', reply_done 1,
    progress 100, and the worker's claim released.
    """
    now = time.time()
    with _LOCK, _conn() as conn:
        if final:
            cur = conn.execute(
                """
                UPDATE jobs
                   SET reply = ?, reply_done = 1, status = 'done',
                       progress = 100, claimed_by = NULL,
                       claimed_at = NULL, updated_at = ?
                 WHERE id = ?
                """,
                (text, now, job_id),
            )
        else:
            cur = conn.execute(
                "UPDATE jobs SET reply = ?, updated_at = ? WHERE id = ?",
                (text, now, job_id),
            )
        if cur.rowcount == 0:
            return None
    return get_job(job_id)


def add_queued_jobs(job_id: str, new_ids: list[str]) -> dict | None:
    """Record creation jobs spawned from a chat job's reply (its
    [[QUEUE ...]] directive) on the chat job itself, so the chat
    poll endpoint can report them as ``queued_jobs``."""
    job = get_job(job_id)
    if job is None:
        return None
    merged = list(job.get("queued_jobs") or [])
    for nid in new_ids:
        if nid and nid not in merged:
            merged.append(nid)
    with _LOCK, _conn() as conn:
        conn.execute(
            "UPDATE jobs SET queued_jobs = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged), time.time(), job_id),
        )
    return get_job(job_id)


def list_chat_jobs(project_id: str | None, limit: int = 24) -> list[dict]:
    """Completed chat jobs of one conversation, oldest first.

    ``project_id`` None selects the lobby (chat jobs with no project).
    Only finished turns (reply_done) count — they are the agent's
    conversation history.
    """
    with _conn() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE kind = 'chat' AND reply_done = 1 "
                "AND project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE kind = 'chat' AND reply_done = 1 "
                "AND project_id IS NULL "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [_row_to_dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Worker registry — who is out there and what can they serve?
# ---------------------------------------------------------------------------

WORKER_ONLINE_SECONDS = 90  # a ping this old (or newer) = worker online


def ping_worker(name: str, caps_list) -> dict:
    """Upsert a worker's heartbeat: its name, the capability list it
    serves (e.g. ["video", "image", "chat"]) and the current time."""
    caps = [str(c) for c in (caps_list or [])]
    now = time.time()
    with _LOCK, _conn() as conn:
        conn.execute(
            """
            INSERT INTO workers (name, caps, last_seen) VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET caps = excluded.caps,
                                            last_seen = excluded.last_seen
            """,
            (name, json.dumps(caps), now),
        )
    # A worker checking in satisfies any outstanding GPU wake request.
    clear_wake()
    return {"name": name, "caps": caps, "last_seen": now, "online": True}


def list_workers() -> list[dict]:
    """All known workers with their caps and a computed ``online``
    flag (last ping within WORKER_ONLINE_SECONDS)."""
    now = time.time()
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM workers ORDER BY name").fetchall()
    workers = []
    for row in rows:
        d = dict(row)
        try:
            caps = json.loads(d.get("caps") or "[]")
        except (TypeError, ValueError):
            caps = []
        last_seen = float(d.get("last_seen") or 0)
        workers.append({
            "name": d["name"],
            "caps": caps,
            "last_seen": last_seen,
            "online": (now - last_seen) <= WORKER_ONLINE_SECONDS,
        })
    return workers


# ---------------------------------------------------------------------------
# GPU wake signal — the website itself asks for a GPU the moment a job
# lands while no worker is online. The fleet watchdog polls /api/wake
# and starts a worker; a worker's ping clears the request.
# ---------------------------------------------------------------------------

def _meta_get(key: str) -> str | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    return row[0] if row else None


def _meta_set(key: str, value: str) -> None:
    with _LOCK, _conn() as conn:
        conn.execute(
            """
            INSERT INTO meta (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _meta_del(key: str) -> None:
    with _LOCK, _conn() as conn:
        conn.execute("DELETE FROM meta WHERE key = ?", (key,))


def request_wake(job_id: str, kind: str) -> None:
    """Record that a GPU is needed. Keeps the FIRST unmet request, so
    ``since`` reflects the oldest job still waiting for a GPU."""
    if _meta_get("wake") is None:
        _meta_set("wake", json.dumps(
            {"since": time.time(), "job_id": job_id, "kind": kind}
        ))


def clear_wake() -> None:
    _meta_del("wake")


def wake_status() -> dict:
    """The site's GPU dispatch state: ``needed`` is true exactly when
    a wake was requested, jobs are still waiting, and no worker is
    online — the watchdog acts on this."""
    wake = None
    raw = _meta_get("wake")
    if raw:
        try:
            wake = json.loads(raw)
        except (TypeError, ValueError):
            wake = None
    with _conn() as conn:
        waiting, oldest = conn.execute(
            "SELECT COUNT(*), MIN(created_at) FROM jobs "
            "WHERE status IN ('queued', 'exported')"
        ).fetchone()
    online = sum(1 for w in list_workers() if w["online"])
    needed = bool(wake) and waiting > 0 and online == 0
    since = (wake or {}).get("since")
    if not needed and waiting > 0 and online == 0 and oldest is not None:
        # Jobs queued while a worker was alive never raised the flag.
        # If the fleet has since died and a job has been waiting a
        # while, that backlog IS a wake request.
        if time.time() - float(oldest) > 180:
            needed = True
            since = float(oldest)
    return {
        "needed": needed,
        "since": since,
        "job_id": (wake or {}).get("job_id"),
        "kind": (wake or {}).get("kind"),
        "waiting_jobs": waiting,
        "workers_online": online,
    }


init_db()
