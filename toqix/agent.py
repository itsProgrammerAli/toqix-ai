"""TOQIX Agent — chat-driven *consistent series* for the TOQIX studio.

The normal studio flow makes one-off jobs. The Agent exists for users who
want a SERIES: many videos / images / voice parts that all share the SAME
character, the SAME style and the SAME seed, so part 12 still looks like
part 1. The user just talks to it:

    "hi, start a series"            -> agent asks for the character
    "<character description>"       -> locked in as the consistency anchor
    "cinematic"                     -> style locked
    "video"                         -> kind locked, series is "ready"
    "Part 1: he walks into ..."    -> a job is queued for that scene
    "Part 2: ..."                   -> next job, same anchor/style/seed
    "status" / "parts"              -> progress of the series
    "change style to anime"         -> bible edits, mid-series
    "new series"                    -> start over

How consistency is enforced
----------------------------
Every series job is created through the normal jobs.create_job flow with:
  * raw prompt = "<character anchor>. <scene>" (video/image), so BOTH the
    stored original prompt and the enhanced prompt carry the anchor into
    the runner (the runner generates from job.enhanced_prompt);
  * style / aspect taken from the project bible;
  * seed = the project's seed — FIXED at project creation, reused for
    every part (same seed + same anchor text is the consistency trick);
  * project_id set on the job row.

Audio is the one exception, by design: the runner SPEAKS job.prompt aloud,
so an audio part's original prompt stays the scene text alone — reciting
the character description would be nonsense. For audio, consistency is
the project's VOICE (passed as the job's style, which is what the runner
maps to a TTS voice), plus the same fixed seed.

The brain is fully local and deterministic: a small keyword state
machine over a SQLite `projects` table (same DB as jobs). No LLM calls,
no network, no external APIs — same input, same reply, every time.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid

from . import config, jobs
from .prompt_engine import STYLE_PRESETS

_LOCK = threading.Lock()

# Voice characters for audio parts (the runner maps these names to TTS
# voices; the website composer offers the same six).
VOICES = ["Ava", "Emma", "Michael", "George", "Sky", "Adam"]
DEFAULT_VOICE = "Ava"

STATES = ("ask_character", "ask_style", "ask_kind", "ask_voice", "ready")

# Fields the API contract exposes for a project — nothing more.
_PROJECT_KEYS = (
    "id", "name", "character", "style", "aspect", "voice", "seed",
    "kind_default", "created_at",
)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL DEFAULT '',
                character    TEXT NOT NULL DEFAULT '',
                style        TEXT NOT NULL DEFAULT '',
                aspect       TEXT NOT NULL DEFAULT '16:9',
                voice        TEXT NOT NULL DEFAULT '',
                seed         INTEGER NOT NULL,
                kind_default TEXT NOT NULL DEFAULT 'video',
                state        TEXT NOT NULL DEFAULT 'ask_character',
                created_at   REAL NOT NULL,
                updated_at   REAL NOT NULL
            )
            """
        )


def _public(row: dict) -> dict:
    """Strip a project row down to the API contract shape."""
    return {k: row.get(k) for k in _PROJECT_KEYS}


def _get_row(project_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
    return dict(row) if row else None


def get_project(project_id: str) -> dict | None:
    row = _get_row(project_id) if project_id else None
    return _public(row) if row else None


def list_projects() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY created_at DESC"
        ).fetchall()
    return [_public(dict(r)) for r in rows]


def get_project_detail(project_id: str) -> dict | None:
    project = get_project(project_id)
    if not project:
        return None
    return {"project": project, "jobs": jobs.list_project_jobs(project_id)}


def _derive_name(character: str) -> str:
    text = " ".join(character.split())
    if len(text) <= 48:
        return text
    return text[:45].rsplit(" ", 1)[0].rstrip(",.;") + "…"


def _create_project(character: str) -> dict:
    project_id = uuid.uuid4().hex[:12]
    # Fixed for the whole series — same seed + same anchor = same face.
    seed = int(uuid.uuid4().hex[:8], 16) % 1_000_000 + 1
    now = time.time()
    with _LOCK, _conn() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, character, style, aspect, voice,
                                  seed, kind_default, state,
                                  created_at, updated_at)
            VALUES (?, ?, ?, '', ?, '', ?, 'video', 'ask_style', ?, ?)
            """,
            (
                project_id, _derive_name(character), character,
                config.DEFAULT_ASPECT, seed, now, now,
            ),
        )
    return _get_row(project_id)


def _update_project(project_id: str, **fields) -> dict:
    allowed = {
        "name", "character", "style", "aspect", "voice", "seed",
        "kind_default", "state",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if fields:
        fields["updated_at"] = time.time()
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with _LOCK, _conn() as conn:
            conn.execute(
                f"UPDATE projects SET {assignments} WHERE id = ?",
                (*fields.values(), project_id),
            )
    return _get_row(project_id)


# ---------------------------------------------------------------------------
# Keyword brain — parsing helpers (English + a little Roman Urdu)
# ---------------------------------------------------------------------------
_GREETING_WORDS = {
    "hi", "hello", "hey", "salam", "aoa", "start", "begin", "new", "a",
    "an", "the", "series", "project", "story", "stories", "kahani",
    "please", "pls", "banao", "make", "i", "want", "to", "ek",
}


def _is_greeting(low: str) -> bool:
    """True for 'hi', 'start a series', 'ek kahani banao', … — messages
    made only of greeting/start words, with no real content yet."""
    words = re.findall(r"[a-z']+", low)
    if not words:
        return True
    return len(low) <= 60 and all(w in _GREETING_WORDS for w in words)


def _is_new_series(low: str) -> bool:
    norm = re.sub(r"[^a-z ]", "", low).strip()
    return norm in {
        "new series", "start new series", "start a new series",
        "new project", "start over", "restart", "another series",
    }


_CHANGE_STYLE = re.compile(r"change style to\s+(.+)", re.IGNORECASE)
_CHANGE_VOICE = re.compile(r"change voice to\s+(.+)", re.IGNORECASE)
_CHANGE_ASPECT = re.compile(r"change aspect to\s+(.+)", re.IGNORECASE)
_NEW_CHARACTER = re.compile(r"new character\s*:\s*(.+)", re.IGNORECASE | re.DOTALL)

_PART_PREFIX = re.compile(
    r"^(?:part\s*\d+|next\s+(?:scene|part)|scene\s*\d+|"
    r"agla\s+(?:scene|hissa|part)|agla)\s*[:\-–—]?\s*",
    re.IGNORECASE,
)
_IMAGE_PREFIX = re.compile(
    r"^(?:make\s+an?\s+image\s+of|create\s+an?\s+image\s+of|"
    r"image\s+of|picture\s+of|photo\s+of|image|picture|photo)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_AUDIO_PREFIX = re.compile(
    r"^(?:voice\s*note|audio|say)\s*[:\-]\s*", re.IGNORECASE
)
_VIDEO_PREFIX = re.compile(r"^video\s*[:\-]\s*", re.IGNORECASE)


def _resolve_style(text: str) -> str:
    """Map a style answer to a preset id when it matches one (by id or
    label); otherwise keep the user's free text."""
    t = " ".join(text.strip().lower().split())
    if t in STYLE_PRESETS:
        return t
    for preset_id, preset in STYLE_PRESETS.items():
        if preset["label"].lower() == t:
            return preset_id
    squashed = t.replace(" ", "_").replace("-", "_")
    for preset_id in STYLE_PRESETS:
        if squashed == preset_id or preset_id.startswith(squashed):
            return preset_id
    return text.strip()


def _style_label(style: str) -> str:
    preset = STYLE_PRESETS.get(style)
    return preset["label"] if preset else style


def _resolve_voice(text: str) -> str | None:
    low = text.lower()
    for voice in VOICES:
        if voice.lower() in low:
            return voice
    return None


def _resolve_kind(text: str) -> str:
    low = text.lower()
    if any(w in low for w in ("audio", "voice", "sound", "bolna", "bol")):
        return "audio"
    if any(w in low for w in ("image", "photo", "picture", "tasveer")):
        return "image"
    return "video"  # contract default


def _style_options_text() -> str:
    return ", ".join(STYLE_PRESETS.keys())


# ---------------------------------------------------------------------------
# Reply builders
# ---------------------------------------------------------------------------
def _ask_character_reply() -> str:
    return (
        "Hi! I'm the TOQIX Agent — I run whole series with the SAME "
        "character and style in every part.\n"
        "Describe your character once — looks, clothes, age, vibe. "
        "I'll keep them the same in every part."
    )


def _ask_style_reply(project: dict) -> str:
    return (
        "Character locked in — that description is now the anchor for "
        "every part.\n"
        f"Pick a style: {_style_options_text()} — or describe your own."
    )


def _ask_kind_reply(project: dict) -> str:
    return (
        f"Style set to {_style_label(project['style'])}. "
        "Last choice: what should I make — video, image, or audio? "
        "(video is the default)"
    )


def _ask_voice_reply(project: dict) -> str:
    return (
        "Audio it is. Pick the voice for the whole series: "
        + ", ".join(VOICES)
        + f". ({DEFAULT_VOICE} is the default)"
    )


def _ready_reply(project: dict) -> str:
    kind = project["kind_default"]
    kind_line = f"Kind: {kind}"
    if kind == "audio" and project["voice"]:
        kind_line += f" · Voice: {project['voice']}"
    return (
        f"Series ready — \"{project['name']}\"\n"
        f"Character: {project['character']}\n"
        f"Style: {_style_label(project['style'])} · {kind_line} · "
        f"Aspect: {project['aspect']} · Seed: {project['seed']} "
        "(locked — same seed and same character in every part, "
        "that's the consistency trick).\n"
        "Now just send scenes, like \"Part 1: he walks into the old "
        "city at dawn\" — each one queues a new part. "
        "Say \"status\" anytime to check progress."
    )


def _scene_summary(project: dict, job: dict) -> str:
    """The scene part of a stored job prompt (anchor stripped for audio
    there is no anchor — the prompt IS the scene)."""
    prompt = job.get("prompt") or ""
    anchor = f"{project['character']}. "
    if prompt.startswith(anchor):
        prompt = prompt[len(anchor):]
    prompt = " ".join(prompt.split())
    return prompt[:70] + ("…" if len(prompt) > 70 else "")


# ---------------------------------------------------------------------------
# Commands (work in any state, once a project exists)
# ---------------------------------------------------------------------------
def _status_reply(project: dict) -> str:
    project_jobs = jobs.list_project_jobs(project["id"])
    total = len(project_jobs)
    if total == 0:
        return (
            f"\"{project['name']}\" has no parts yet — "
            "send your first scene and I'll queue Part 1."
        )
    counts: dict[str, int] = {}
    for job in project_jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    bits = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
    return (
        f"Your series \"{project['name']}\" has {total} parts: {bits}. "
        f"Last part: Part {total}."
    )


def _parts_reply(project: dict) -> str:
    project_jobs = jobs.list_project_jobs(project["id"])
    if not project_jobs:
        return "No parts yet — send a scene and I'll queue Part 1."
    lines = [f"Parts of \"{project['name']}\":"]
    for i, job in enumerate(project_jobs, start=1):
        summary = _scene_summary(project, job)
        lines.append(f"Part {i} — {summary} [{job['status']}]")
    return "\n".join(lines)


def _handle_command(project: dict, message: str, low: str) -> dict | None:
    """Return a chat result if the message is a command, else None."""
    pid = project["id"]

    m = _NEW_CHARACTER.search(message)
    if m:
        character = m.group(1).strip()
        fields = {"character": character, "name": _derive_name(character)}
        if project["state"] == "ask_character":
            fields["state"] = "ask_style"
        project = _update_project(pid, **fields)
        reply = (
            "New character locked in — from the next part on, this is "
            "the anchor. (Style and seed stay the same.)"
        )
        if project["state"] == "ask_style":
            reply += "\n" + _ask_style_reply(project)
        return _result(reply, project)

    m = _CHANGE_STYLE.search(message)
    if m:
        style = _resolve_style(m.group(1))
        fields = {"style": style}
        advanced = project["state"] == "ask_style"
        if advanced:
            fields["state"] = "ask_kind"
        project = _update_project(pid, **fields)
        reply = f"Style changed to {_style_label(style)} — new parts will use it."
        if advanced:
            reply += "\n" + _ask_kind_reply(project)
        return _result(reply, project)

    m = _CHANGE_VOICE.search(message)
    if m:
        voice = _resolve_voice(m.group(1))
        if not voice:
            return _result(
                "I don't know that voice — pick one of: "
                + ", ".join(VOICES) + ".",
                project,
            )
        project = _update_project(pid, voice=voice)
        return _result(
            f"Voice changed to {voice} — audio parts will use it now.",
            project,
        )

    m = _CHANGE_ASPECT.search(message)
    if m:
        aspect = m.group(1).strip()
        if aspect not in config.ASPECT_SIZES:
            return _result(
                "Aspect must be one of: "
                + ", ".join(config.ASPECT_SIZES.keys()) + ".",
                project,
            )
        project = _update_project(pid, aspect=aspect)
        return _result(f"Aspect changed to {aspect} for new parts.", project)

    if low.strip() == "status" or low.startswith("status "):
        return _result(_status_reply(project), project)

    if low.strip() in ("parts", "list parts", "show parts", "parts list"):
        return _result(_parts_reply(project), project)

    return None


# ---------------------------------------------------------------------------
# Scene -> job
# ---------------------------------------------------------------------------
def _queue_scene(project: dict, message: str) -> dict:
    text = " ".join(message.split())
    scene = text

    # "Part 2: ...", "Next scene: ...", "agla scene ..." prefixes.
    m = _PART_PREFIX.match(scene)
    if m:
        scene = scene[m.end():].strip()

    kind = project["kind_default"]
    m = _AUDIO_PREFIX.match(scene)
    if m:
        kind, scene = "audio", scene[m.end():].strip()
    else:
        m = _IMAGE_PREFIX.match(scene)
        if m:
            kind, scene = "image", scene[m.end():].strip()
        else:
            m = _VIDEO_PREFIX.match(scene)
            if m:
                kind, scene = "video", scene[m.end():].strip()

    if len(scene) < 3:
        return _result(
            "Send me a scene to queue — e.g. \"Part 1: he walks into "
            "the rainy neon market\".",
            project,
        )

    part_no = len(jobs.list_project_jobs(project["id"])) + 1
    if kind == "audio":
        # Spoken aloud by the runner: prompt stays the scene text alone;
        # consistency for audio is the project voice (job style) + seed.
        raw_prompt = scene
        style = project["voice"] or DEFAULT_VOICE
    else:
        # Anchor prepended so original AND enhanced prompts carry it.
        raw_prompt = f"{project['character']}. {scene}"
        style = project["style"]

    try:
        job = jobs.create_job(
            prompt=raw_prompt,
            style=style,
            aspect=project["aspect"],
            kind=kind,
            seed=project["seed"],
            project_id=project["id"],
        )
    except ValueError as exc:
        return _result(f"Couldn't queue that part: {exc}", project)

    summary = scene[:60] + ("…" if len(scene) > 60 else "")
    reply = (
        f"Queued Part {part_no} — {summary}. "
        "Same character, same style."
    )
    return _result(reply, project, created_jobs=[job["id"]])


# ---------------------------------------------------------------------------
# Chat entry point
# ---------------------------------------------------------------------------
def _result(reply: str, project: dict | None,
            created_jobs: list[str] | None = None) -> dict:
    return {
        "reply": reply,
        "project": _public(project) if project else None,
        "created_jobs": created_jobs or [],
        "state": project["state"] if project else "ask_character",
    }


def chat(project_id: str | None, message: str) -> dict:
    """One turn of the TOQIX Agent conversation.

    project_id None (or unknown) = no series context yet: a greeting
    gets the character question; anything else IS the character
    description and creates the project.
    """
    message = (message or "").strip()
    low = message.lower()

    # "new series" works from anywhere, including mid-flow.
    if _is_new_series(low):
        return _result(_ask_character_reply(), None)

    project = _get_row(project_id) if project_id else None

    if project is None:
        if _is_greeting(low):
            return _result(_ask_character_reply(), None)
        # First substantive message = the character description.
        project = _create_project(message)
        return _result(_ask_style_reply(project), project)

    # Commands work in every state.
    command = _handle_command(project, message, low)
    if command is not None:
        return command

    state = project["state"]

    if state == "ask_character":
        if _is_greeting(low):
            return _result(_ask_character_reply(), project)
        project = _update_project(
            project["id"], character=message,
            name=_derive_name(message), state="ask_style",
        )
        return _result(_ask_style_reply(project), project)

    if state == "ask_style":
        style = _resolve_style(message)
        project = _update_project(
            project["id"], style=style, state="ask_kind"
        )
        return _result(_ask_kind_reply(project), project)

    if state == "ask_kind":
        kind = _resolve_kind(message)
        if kind == "audio":
            project = _update_project(
                project["id"], kind_default="audio", state="ask_voice"
            )
            return _result(_ask_voice_reply(project), project)
        project = _update_project(
            project["id"], kind_default=kind, state="ready"
        )
        return _result(_ready_reply(project), project)

    if state == "ask_voice":
        voice = _resolve_voice(message) or DEFAULT_VOICE
        project = _update_project(
            project["id"], voice=voice, state="ready"
        )
        return _result(_ready_reply(project), project)

    # state == "ready": greetings get a nudge, everything else is a scene.
    if _is_greeting(low):
        return _result(
            "Your series is ready — send the next scene, or say "
            "\"status\" to see the parts so far.",
            project,
        )
    return _queue_scene(project, message)


init_db()
