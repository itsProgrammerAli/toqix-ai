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

The brain is local and deterministic first: a small keyword state
machine over a SQLite `projects` table (same DB as jobs), plus an
understanding layer fed by a curated knowledge base (knowledge.py).
Same input, same reply, every time — for everything the studio
itself knows.

Conversation-first (agent maturity upgrade): the deterministic
brain keeps only what must stay exact and instant — greetings,
knowledge-base answers it is confident about, explicit production
commands, and the confirmations a pending state is waiting for.
EVERYTHING else — open chat, statements, feelings, advice-seeking,
descriptions offered inside a ready series, questions the
knowledge base misses — is handed to a real LLM that runs on the
owner's own GPU worker fleet, never an external API, whenever a
chat-capable worker is online. The agent packs the conversation
(persona + series context with the parts so far + recent
exchanges) into a kind="chat" job; the worker generates the reply
and posts it back (see jobs.set_reply and the
/api/agent/chat/{job_id} poll endpoint), and the reply's hidden
[[QUEUE ...]] directive can still turn real creation intent into
a queued job. When no chat worker is online, the deterministic
fallbacks answer instead (knowledge base, capabilities guide,
the ready-state check-first offer) — the agent never dead-ends,
and it never nags "shall I queue this?" while a brain is
available.

The understanding layer (see chat()) runs around the state machine
without ever breaking the scripted collect flow
(character -> style -> kind -> voice -> scenes):

  * Q&A      — "what is cyberpunk?" / "drone shot kia hai" answers
               from the knowledge base, in ANY state, state untouched;
  * Ideas    — "give me a horror idea" offers 3 idea seeds, and
               "queue idea 2" turns one into the next part;
  * Improve  — "improve: a cat walking" rebuilds the prompt with the
               subject+action+place+light+camera formula, "queue it"
               makes it the next part;
  * Plan     — "plan a series about a lost astronaut" lays out a
               4-beat genre OUTLINE (state confirm_plan); "yes" queues
               all four parts, "no" drops it. An outline is a plan —
               it is never called a story;
  * Stories  — "write a story about a brave little fox" returns a
               REAL written story (story.py: named hero, scenes,
               dialogue, beginning/middle/end in prose), and
               "make it a series" splits that story into queued
               parts through the same consistency wiring;
  * Small talk + a capabilities fallback instead of dead ends;
  * LLM chat — a question the knowledge base misses becomes a
               chat job for the fleet's LLM worker when one is
               online (pending reply, polled by the web layer);
               the reply may end with a hidden [[QUEUE ...]]
               directive, which the server turns into a real
               creation job (parse_queue_directive /
               queue_from_directive below).

Behaviour contract (owner's rules, enforced in chat()):
  * a pure greeting (salaam / hi / hello …) ALWAYS gets a warm
    greeting + a short guide back — never swallowed as a flow
    answer, never creates anything;
  * a question is ANSWERED, never generated — even in "ready"
    state, even if it contains scene-like words;
  * in "ready" state, plain descriptive text is conversation,
    not an order: with a chat worker online the LLM answers it
    (and queues only on real creation intent, via its hidden
    directive); offline the agent asks first ("Want me to queue
    this as your next part?") and queues only on a clear yes —
    immediate queueing is reserved for unmistakable intent
    (Part N: / scene: prefixes, explicit generation verbs,
    queue idea N, queue it, confirmations).
"""

from __future__ import annotations

import contextvars
import json
import re
import sqlite3
import threading
import time
import uuid

from . import config, jobs, knowledge, story
from .prompt_engine import STYLE_PRESETS

_LOCK = threading.Lock()

# The signed-in user on whose behalf the current chat() turn runs.
# Set at chat() entry; _create_project and the job-queueing helpers
# read it so every project and job carries its owner (accounts
# release: users only ever see their own series and creations).
_current_user_id: contextvars.ContextVar = contextvars.ContextVar(
    "toqix_current_user_id", default=None)

# Voice characters for audio parts (the runner maps these names to TTS
# voices; the website composer offers the same six).
VOICES = ["Ava", "Emma", "Michael", "George", "Sky", "Adam"]
DEFAULT_VOICE = "Ava"

STATES = ("ask_character", "ask_style", "ask_kind", "ask_voice",
          "ready", "confirm_plan")

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
                user_id      TEXT DEFAULT NULL,
                created_at   REAL NOT NULL,
                updated_at   REAL NOT NULL
            )
            """
        )
        existing = {row[1] for row in conn.execute("PRAGMA table_info(projects)")}
        if "user_id" not in existing:
            conn.execute("ALTER TABLE projects ADD COLUMN user_id TEXT DEFAULT NULL")


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


def project_owner_id(project_id: str) -> str | None:
    """The user_id that owns a project (None = legacy/unowned or
    unknown) — the server gates project detail views with it."""
    row = _get_row(project_id) if project_id else None
    return row.get("user_id") if row else None


def list_projects(user_id: str | None = None,
                  is_admin: bool = False) -> list[dict]:
    # Accounts release: a user sees only their own series; the admin
    # sees all; anonymous callers see none.
    if is_admin:
        sql = "SELECT * FROM projects ORDER BY created_at DESC"
        params: tuple = ()
    elif user_id:
        sql = ("SELECT * FROM projects WHERE user_id = ?"
               " ORDER BY created_at DESC")
        params = (user_id,)
    else:
        return []
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
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


def _create_project(character: str, user_id: str | None = None) -> dict:
    project_id = uuid.uuid4().hex[:12]
    # Fixed for the whole series — same seed + same anchor = same face.
    seed = int(uuid.uuid4().hex[:8], 16) % 1_000_000 + 1
    now = time.time()
    if user_id is None:
        user_id = _current_user_id.get()
    with _LOCK, _conn() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, character, style, aspect, voice,
                                  seed, kind_default, state, user_id,
                                  created_at, updated_at)
            VALUES (?, ?, ?, '', ?, '', ?, 'video', 'ask_style', ?, ?, ?)
            """,
            (
                project_id, _derive_name(character), character,
                config.DEFAULT_ASPECT, seed, user_id, now, now,
            ),
        )
    return _get_row(project_id)


def _update_project(project_id: str, **fields) -> dict:
    allowed = {
        "name", "character", "style", "aspect", "voice", "seed",
        "kind_default", "state", "user_id",
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
        "Saved ✓ — this character will stay the same in every part.\n"
        f"Now pick a style: {_style_options_text()} — or describe "
        "your own. (One style for all parts, so the whole series "
        "looks like one family.)"
    )


def _ask_kind_reply(project: dict) -> str:
    return (
        f"Style saved ✓ — every part will share "
        f"{_style_label(project['style'])}.\n"
        "Last choice: what should I make — video, image, or audio? "
        "(video is the default)"
    )


def _ask_voice_reply(project: dict) -> str:
    return (
        "Audio it is. Pick the voice for the whole series: "
        + ", ".join(VOICES)
        + f". ({DEFAULT_VOICE} is the default — one voice for every "
        "part, so it always sounds like the same person.)"
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
        "city at dawn\" — each one queues a new part. (You can also "
        "simply describe a scene and I'll check with you before "
        "queueing it.) Queued parts appear in your Creations feed "
        "and generate when the studio runs. "
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

    return _queue_parsed_scene(project, scene, kind)


def _queue_parsed_scene(project: dict, scene: str, kind: str) -> dict:
    """Create the next part job for an already-parsed scene.

    This is THE consistency wiring — scenes from chat, idea seeds,
    improved prompts and plan beats all come through here so every
    part gets the same anchor, style/aspect, fixed seed and project.
    """
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
            user_id=project.get("user_id") or _current_user_id.get(),
        )
    except ValueError as exc:
        return _result(f"Couldn't queue that part: {exc}", project)

    summary = scene[:60] + ("…" if len(scene) > 60 else "")
    reply = (
        f"Queued Part {part_no} ✓ — {summary}. "
        "Same character, same style — it will appear in your "
        "Creations feed and generate when the studio runs."
    )
    return _result(reply, project, created_jobs=[job["id"]])


# ---------------------------------------------------------------------------
# Understanding layer — knowledge, ideas, improve, planner, small talk
# ---------------------------------------------------------------------------
# Short-lived conversational memory that does not belong in the series
# bible: the last idea trio offered, the last improved prompt, and a
# plan awaiting confirmation. Keyed by project id ("__none__" before a
# series exists). In-memory only — a server restart forgets pending
# offers, never the series itself.
_PENDING: dict[str, dict] = {}
_PENDING_LOCK = threading.Lock()
_NO_PROJECT_KEY = "__none__"


def _pending_get(key: str) -> dict:
    with _PENDING_LOCK:
        return dict(_PENDING.get(key, {}))


def _pending_set(key: str, **items) -> None:
    with _PENDING_LOCK:
        _PENDING.setdefault(key, {}).update(items)


def _pending_clear(key: str, *names: str) -> None:
    with _PENDING_LOCK:
        store = _PENDING.get(key, {})
        for name in names:
            store.pop(name, None)


def _norm(text: str) -> str:
    """Lowercase, punctuation stripped, whitespace collapsed — the
    canonical form every intent detector below works on."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return " ".join(t.split())


# --- intent detectors (English + Roman Urdu synonyms) --------------------
_IDEA_STRONG = {"idea", "ideas", "suggest", "suggestion", "suggestions",
                "socho", "soch"}
_IDEA_TRIGGERS = {"give", "do", "de", "batao", "chahiye", "want",
                  "need", "koi", "dikhao", "sunao"}

_QUESTION_FIRST = {"what", "how", "why", "when", "which", "is", "are",
                   "can", "do", "does", "explain", "who", "whom",
                   "whose", "kia", "kya",
                   "kaise", "kis", "kon", "konsa", "kyun", "kyu",
                   "kab", "batao", "samjhao"}

_PLAN_SERIES = re.compile(
    r"plan\s+(?:a\s+)?series\s*(?:about\s+)?(.+)?$", re.IGNORECASE)
_PLAN_ALT = re.compile(
    r"(?:series\s+plan|outline)\s*(?:for|about)?\s*[:\-]?\s*(.+)?$",
    re.IGNORECASE)
_QUEUE_IDEA = re.compile(r"\bqueue\s+idea\s+(\d+)\b", re.IGNORECASE)
_QUEUE_IDEA_ALT = re.compile(r"\bmake\s+idea\s+(\d+)\b", re.IGNORECASE)
_IMPROVE_PREFIX = re.compile(
    r"^(?:improve(?:\s+this)?(?:\s+my)?\s*(?:prompt)?|"
    r"behtar\s+banao|better\s+banao)\s*[:\-]?\s*(.+)?$",
    re.IGNORECASE | re.DOTALL)

_YES_WORDS = {"yes", "haan", "han", "ok", "okay", "sure", "ji",
              "queue them", "queue all", "go ahead", "yes please",
              "ji haan", "haan ji"}
_NO_WORDS = {"no", "nahi", "nahin", "cancel", "stop", "drop it",
             "no thanks", "rehne do", "band karo"}

_THANKS_TOKENS = {"thanks", "thank", "you", "thx", "shukriya", "shukria",
                  "great", "nice", "awesome", "zabardast", "bohat",
                  "boht", "acha", "achha", "good", "job", "well",
                  "done", "superb", "perfect", "so", "very", "really",
                  "much", "lot"}
_BYE_PHRASES = {"bye", "goodbye", "allah hafiz", "khuda hafiz",
                "see you", "see you later", "tata"}


def _is_idea_request(norm: str) -> bool:
    toks = set(norm.split())
    if toks & _IDEA_STRONG:
        # Bare "idea" needs a request flavour around it ("idea do",
        # "give me an idea", "koi idea") so a scene like "an idea
        # thief steals dreams" is not mistaken for a request.
        if toks & {"suggest", "suggestion", "suggestions", "socho",
                   "soch"}:
            return True
        return bool(toks & _IDEA_TRIGGERS)
    return False


def _plan_premise(message: str, norm: str) -> str | None:
    """The premise if this is a series-plan request, '' if it is one
    but names no premise, None if it is not a plan request at all."""
    if ("series" not in norm and "outline" not in norm
            and "plan" not in norm.split()[:2]):
        return None
    for pattern in (_PLAN_SERIES, _PLAN_ALT):
        m = pattern.search(message)
        if m:
            return (m.group(1) or "").strip().rstrip(".")
    if norm.startswith("plan"):
        return ""
    return None


def _is_question(message: str, norm: str) -> bool:
    if message.strip().endswith("?"):
        return True
    toks = norm.split()
    if toks and toks[0] in _QUESTION_FIRST:
        return True
    padded = f" {norm} "
    return any(p in padded for p in
               (" kia ", " kya ", " kaise ", " matlab ", " konsa ",
                " kis ", " kisne ", " kaun "))


def _is_thanks(norm: str) -> bool:
    toks = norm.split()
    return 0 < len(toks) <= 6 and all(t in _THANKS_TOKENS for t in toks)


_HOW_ARE_YOU = {"how are you", "how are you doing", "how r you",
                "how are u", "kaise ho", "kese ho", "kaisi ho",
                "kya haal", "kya haal hai", "haal kaisa hai",
                "kaise hain", "aap kaise ho", "tum kaise ho"}


def _smalltalk_reply(norm: str) -> str | None:
    if norm in _HOW_ARE_YOU or norm.startswith("how are you"):
        return ("I'm very well, thank you for asking! Running "
                "happily and ready when you are — shall we make "
                "something?")
    if norm in _BYE_PHRASES:
        return ("Goodbye! Your series will be right here when you "
                "come back.")
    if _is_thanks(norm):
        return ("You're welcome! Glad it helps. Whenever you're "
                "ready, send the next scene — or ask me anything.")
    return None


_CHAT_STATEMENT_STARTS = ("i ", "i'm ", "im ", "my ", "we ",
                          "lets ", "let's ")
_CHAT_STATEMENT_PHRASES = (
    " feel ", " feeling ", " think ", " believe ", " opinion ",
    " bored ", " lonely ", " tired ", " stressed ", " happy ",
    " sad ", " talk to me", " chat with me", " who are you",
    " your name", " about yourself", " about you",
)


def _looks_like_chat_statement(norm: str) -> bool:
    """True when a no-project message reads as CONVERSATION rather
    than a character description: a first-person opener ("i feel…",
    "my day was…") or a chat marker ("who are you", "talk to me",
    "tell me about yourself"). Character descriptions are noun
    phrases ("a small robot with a red scarf") and never match —
    they keep starting series exactly as before."""
    if any(norm.startswith(s) for s in _CHAT_STATEMENT_STARTS):
        return True
    padded = f" {norm} "
    return any(p in padded for p in _CHAT_STATEMENT_PHRASES)


def _looks_like_gibberish(norm: str) -> bool:
    """Keyboard-mash detector: consonant-only words or classic
    home-row runs. Real scenes/characters always carry vowels."""
    words = [w for w in norm.split() if w.isalpha()]
    if not words:
        return True
    content = [w for w in words if len(w) >= 3] or words
    if all(not any(c in "aeiou" for c in w) for w in content):
        return True
    return any(any(k in w for k in ("qwert", "asdf", "zxcv", "lkjh"))
               for w in content)


def _capabilities_reply(project: dict | None) -> str:
    lines = [
        "Let me point you to what I do best:",
        "• Start a series — describe a character once and I keep them "
        "consistent in every part",
        "• Ask me things — try \"what is a drone shot?\" or \"which "
        "voice fits a trailer?\"",
        "• Get ideas — say \"give me a horror idea\"",
        "• Improve a rough prompt — say \"improve: a cat walking\"",
        "• Plan a whole series — say \"plan a series about a lost "
        "robot\"",
        "• Hear a real story — say \"write a story about a brave "
        "little fox\", then \"make it a series\" to film it",
    ]
    if project and project["state"] == "ready":
        lines.append(
            "Or just send a scene and I'll queue it as the next part "
            "of your series.")
    elif not project:
        lines.append(
            "Or simply describe your character and we'll begin.")
    return "\n".join(lines)


def _question_suffix(project: dict) -> str:
    """After answering a mid-flow question, re-ask what we were asking
    so the collect flow resumes exactly where it paused."""
    state = project["state"]
    if state == "ask_character":
        return "\nNow — describe your character."
    if state == "ask_style":
        return ("\nPick a style when you're ready: "
                + _style_options_text() + " — or describe your own.")
    if state == "ask_kind":
        return "\nSo — what should I make: video, image, or audio?"
    if state == "ask_voice":
        return ("\nWhich voice shall it be? " + ", ".join(VOICES)
                + ".")
    return ""


def _qa_reply(project: dict | None, entry: dict) -> dict:
    reply = entry["answer"]
    if project is None:
        reply += ("\nWant to start a series? Just describe your "
                  "character.")
    elif project["state"] != "ready":
        reply += _question_suffix(project)
    return _result(reply, project)


# --- greetings: a greeting always gets a greeting -------------------------
_GREETING_TOKENS = {
    "hi", "hello", "hey", "salam", "salaam", "aoa", "assalam",
    "alaikum", "o", "wa", "walaikum", "waalaikum", "there",
    "everyone", "guys", "assalamualaikum", "assalamo",
}
_GREETING_CORE = {"hi", "hello", "hey", "salam", "salaam", "aoa",
                  "assalam", "assalamualaikum"}


def _is_pure_greeting(norm: str) -> bool:
    """The WHOLE message is a greeting — 'hi', 'assalam o alaikum',
    'aoa', 'hello there'. Content-bearing messages never match."""
    toks = norm.split()
    if not toks or len(toks) > 5:
        return False
    if not all(t in _GREETING_TOKENS for t in toks):
        return False
    return bool(set(toks) & _GREETING_CORE)


_ISLAMIC_GREETING = {"salam", "salaam", "aoa", "assalam",
                     "alaikum", "assalamualaikum"}


def _greeting_reply(project: dict | None, norm: str = "") -> str:
    islamic = bool(set(norm.split()) & _ISLAMIC_GREETING)
    if islamic:
        opener = "Wa-alaikum assalam! Welcome to TOQIX."
    elif project is not None:
        opener = "Hello again! Welcome back to TOQIX."
    else:
        opener = "Hello, and welcome to TOQIX!"
    lines = [
        opener,
        "I'm your TOQIX Agent. Here's what I can do:",
        "• Answer questions — styles, camera shots, voices, how to "
        "write a good prompt",
        "• Write you a real story — try \"write a story about a "
        "brave little fox\"",
        "• Run a consistent series — one character, the same in "
        "every video, image or voice part",
        "• Suggest ideas and polish rough prompts",
    ]
    if project is None:
        lines.append(
            "Want to start a series, hear a story, or ask me "
            "something?")
    elif project["state"] == "confirm_plan":
        lines.append(
            "Your series outline is still waiting, by the way — "
            "say yes to queue all 4 parts, or no to drop it.")
    elif project["state"] != "ready":
        lines.append(
            "We were in the middle of setting up your series."
            + _question_suffix(project))
    else:
        lines.append(
            "Your series is ready whenever you are — send a scene, "
            "or ask me anything.")
    return "\n".join(lines)


# --- questions are answered, never generated ------------------------------
# Words that mark a message as a request for information rather than
# a scene/character description — EN + Roman Urdu question flavour.
_INFO_MARKERS = {"kia", "kya", "kaise", "kitna", "kitni", "kitne",
                 "konsa", "konsi", "kaun", "kis", "matlab", "batao",
                 "samjhao", "lagta", "lagti", "lagega", "chahiye",
                 "what", "how", "why", "when", "which", "who",
                 "tips", "advice", "meaning", "explain", "difference"}

_IDENTITY_PATTERNS = (
    r"who\s+(built|made|created|developed|designed|invented)\s+you",
    r"who\s+(built|made|created|developed)\s+(toqix|this|it)\b",
    r"who\s+is\s+your\s+(creator|maker|developer|founder|owner)",
    r"your\s+(creator|maker|developer|founder)\b",
    r"who\s+owns\s+(you|toqix)",
    r"kis\s+ne\s+banaya",
    r"(tumhein|tumhe|aap\s*ko|is\s*ko|toqix\s*ko)\s+kis\s*ne\s+banaya",
    r"banaya\s+kis\s+ne",
    r"tumhara\s+(malik|banane\s+wala|creator)",
    r"کس\s*نے\s*بنایا",
)
_IDENTITY_RE = re.compile("|".join(_IDENTITY_PATTERNS), re.IGNORECASE)

_IDENTITY_ANSWER_EN = (
    "I was built by TOQIX AI — the creation studio founded by "
    "Touqeer (Mr ALI). He built TOQIX so anyone can turn a simple "
    "prompt into videos, images and voiceovers, and I am the agent "
    "he put inside it. Ask me for a video, an image, a story — or "
    "just chat.")
_IDENTITY_ANSWER_RU = (
    "Mujhe TOQIX AI ne banaya hay — ye studio Touqeer (Mr ALI) ne "
    "qaim kia hay. Unhon ne TOQIX is liye banaya taake koi bhi sirf "
    "prompt likh kar videos, images aur voiceovers bana sakay, aur "
    "main usi ka agent hoon. Video, image, kahani — jo chaho pooch "
    "lo, ya bas baat kar lo.")
_IDENTITY_ANSWER_UR = (
    "مجھے TOQIX AI نے بنایا ہے — یہ اسٹوڈیو توقیر (Mr ALI) نے قائم "
    "کیا ہے۔ انہوں نے TOQIX اس لیے بنایا تاکہ کوئی بھی صرف پرامپٹ "
    "لکھ کر ویڈیوز، تصاویر اور وائس اوورز بنا سکے، اور میں اسی کا "
    "ایجنٹ ہوں۔")


def _identity_answer(message: str) -> str | None:
    """Deterministic answer to 'who built you' — identity questions
    must never be swallowed as flow input or left to the LLM, which
    would name its base-model maker. Language follows the message:
    Urdu script -> Urdu, Roman-Urdu markers -> Roman Urdu, else EN."""
    if not _IDENTITY_RE.search(message):
        return None
    if any("\u0600" <= ch <= "\u06FF" for ch in message):
        return _IDENTITY_ANSWER_UR
    low = message.lower()
    if any(m in low for m in ("kis ne", "banaya", "tumhein", "tumhe",
                              "tumhara", "kaun", "kon hai")):
        return _IDENTITY_ANSWER_RU
    return _IDENTITY_ANSWER_EN


def _question_reply(project: dict | None, message: str) -> dict:
    """A question gets an answer: identity first (deterministic),
    then the KB when a topic matches; else, when a chat worker is
    online, the fleet's LLM (a chat job — the reply is pending,
    never instant); else the capabilities guide. It NEVER queues a
    creation job and never gets swallowed as a flow answer — in
    any state."""
    identity = _identity_answer(message)
    if identity is not None:
        return _qa_reply(project, {"answer": identity})
    entry = knowledge.lookup(message)
    if entry:
        return _qa_reply(project, entry)
    pending = _llm_chat_reply(project, message)
    if pending is not None:
        return pending
    reply = _capabilities_reply(project)
    if project is not None and project["state"] != "ready":
        reply += _question_suffix(project)
    return _result(reply, project)


# ---------------------------------------------------------------------------
# LLM chat — free-form conversation on the owner's own GPU fleet.
#
# Conversation-first routing: the deterministic brain keeps
# greetings, confident knowledge-base answers, explicit production
# commands and pending-state confirmations; ALL other free-form
# input — a question the knowledge base misses, open conversation,
# statements and descriptions inside a ready series — is packed
# into a kind="chat" job whose prompt is a JSON {"messages": [...]}
# conversation. A chat-capable fleet worker claims it like any
# other job, runs its local LLM, and posts the reply back; the web
# layer polls GET /api/agent/chat/{job_id}. No worker online ->
# the callers' deterministic fallbacks answer instead.
# ---------------------------------------------------------------------------

_CHAT_SYSTEM = (
    "You are TOQIX, the friendly AI assistant inside TOQIX AI — a "
    "creation studio where anyone can turn a simple text prompt "
    "into videos, images and voiceovers.\n"
    "\n"
    "How you talk:\n"
    "- IDENTITY: you are the TOQIX agent, built by TOQIX AI, the "
    "studio founded by Touqeer (Mr ALI). If asked who built, made "
    "or created you, say exactly that. The language model running "
    "underneath is only an engine TOQIX uses — never claim another "
    "company created you.\n"
    "- Chat naturally, like a warm and smart friend: answer general "
    "questions, discuss ideas, write stories, poems and scripts, "
    "give advice, explain things simply.\n"
    "- You are a creative PARTNER, not a form to fill in: brainstorm "
    "story ideas, help shape characters, give honest advice, tell a "
    "joke when the moment fits, and keep the conversation alive "
    "with a question of your own now and then.\n"
    "- LANGUAGE RULE — reply in the SAME language and the SAME "
    "script as the user's LATEST message, every single time: an "
    "English message gets an English reply; Roman Urdu (Urdu "
    "written in Latin letters) gets a Roman Urdu reply in Latin "
    "letters; an Urdu-script message gets an Urdu-script reply. "
    "Judge from their latest message, never from an earlier one.\n"
    "- SCRIPT RULE (never break this): if the user writes in the "
    "Latin alphabet — English or Roman Urdu — reply ONLY in the "
    "Latin alphabet. Never answer a Latin-alphabet message in "
    "Urdu/Arabic script. Use Urdu script only when the user's own "
    "message is written in Urdu script.\n"
    "- One fact, one clear sentence: explain causes plainly and "
    "correctly (for example, the sky looks blue because air "
    "scatters blue sunlight more than other colours). Never use "
    "a word from the wrong language just because it sounds "
    "similar.\n"
    "- Be warm and concise: short, clear answers unless the user "
    "asks for depth or a full piece of writing.\n"
    "- You have no live internet and no today's-facts feed. If you "
    "don't know something, say so honestly instead of inventing "
    "facts.\n"
    "\n"
    "Creating with TOQIX:\n"
    "- TOQIX creates videos, images and voiceovers from prompts, "
    "right here in this studio.\n"
    "- NEVER nag about production: do not ask \"shall I start a "
    "series?\", \"want me to queue this?\" or anything like it. If "
    "the user has not raised making something, just chat — "
    "enjoyably and helpfully. Mention creating at most once in a "
    "conversation, and only after the user themselves brings up "
    "making or generating something.\n"
    "- If — and only if — the user asks you to actually CREATE, "
    "MAKE or GENERATE a video, image or audio in this message or "
    "the one right before it, reply warmly in the conversation "
    "AND end your message with exactly one hidden "
    "directive line in this exact format:\n"
    "[[QUEUE kind=video prompt=\"...\" style=\"...\" "
    "aspect=\"16:9\"]]\n"
    "kind is one of video, image, audio. For video/image, style is "
    "a style name like cinematic, anime, cyberpunk, realistic, "
    "cartoon, painting or watercolor. For audio, style is a voice "
    "name: Ava, Emma, Michael, George, Sky or Adam. aspect is "
    "16:9, 9:16 or 1:1 (optional). The prompt inside the directive "
    "must be a complete, vivid creation prompt that you write from "
    "what the user asked for. Never show, mention or explain the "
    "directive line itself.\n"
    "- A scene the user is merely describing, imagining or chatting "
    "about is NOT a creation request — talk about it with them "
    "instead of queueing it."
)

_CHAT_HISTORY_EXCHANGES = 6  # user+assistant turns kept as context


def _chat_worker_online() -> bool:
    """True when at least one fleet worker with the "chat"
    capability pinged recently enough to count as online."""
    try:
        return any(
            w.get("online") and "chat" in (w.get("caps") or [])
            for w in jobs.list_workers()
        )
    except Exception:
        return False


def _pack_user_text(pack_json: str) -> str:
    """The last user message inside a stored chat pack ('' when the
    pack is unreadable — history simply skips that turn)."""
    try:
        messages = json.loads(pack_json).get("messages", [])
    except (TypeError, ValueError):
        return ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return msg.get("content") or ""
    return ""


def _build_chat_pack(project: dict | None, message: str) -> str:
    """Assemble the JSON conversation pack for one chat turn: the
    TOQIX system persona, the last few completed exchanges of THIS
    conversation (project, or the lobby when there is no project),
    and the new user message."""
    system = _CHAT_SYSTEM
    if project and project.get("character"):
        style = (_style_label(project["style"])
                 if project.get("style") else "not chosen yet")
        kind = project.get("kind_default") or "video"
        parts = jobs.list_project_jobs(project["id"])
        if parts:
            counts: dict[str, int] = {}
            for part in parts:
                counts[part["status"]] = counts.get(part["status"], 0) + 1
            tally = ", ".join(f"{n} {s}" for s, n in
                              sorted(counts.items()))
            last = _scene_summary(project, parts[-1])
            parts_line = (f" Parts so far: {len(parts)} ({tally}). "
                          f"Latest part: \"{last}\".")
        else:
            parts_line = " No parts queued yet."
        voice = (f", voice {project['voice']}"
                 if kind == "audio" and project.get("voice") else "")
        system += (
            "\n\nCurrent series context: the user is building a "
            f"series about {project['character']} (style: {style}, "
            f"kind: {kind}, aspect: {project.get('aspect')}{voice})."
            f"{parts_line} Keep it in mind when they mention their "
            "series or their character — you already KNOW this "
            "context, so never ask them to repeat it."
        )
    messages = [{"role": "system", "content": system}]
    history = jobs.list_chat_jobs(
        project["id"] if project else None,
        limit=_CHAT_HISTORY_EXCHANGES * 2,
    )
    exchanges = []
    for past in history:
        user_text = _pack_user_text(past.get("prompt") or "")
        if user_text and past.get("reply"):
            # Stored replies are already directive-stripped (the
            # server strips before storing), so history is clean.
            exchanges.append((user_text, past["reply"]))
    for user_text, assistant_text in exchanges[-_CHAT_HISTORY_EXCHANGES:]:
        messages.append({"role": "user", "content": user_text})
        messages.append({"role": "assistant", "content": assistant_text})
    messages.append({"role": "user", "content": message})
    return json.dumps({"messages": messages}, ensure_ascii=False)


def _llm_chat_reply(project: dict | None, message: str) -> dict | None:
    """Route one free-form message to the fleet's LLM.

    Returns the pending-chat result when a chat-capable worker is
    online — a kind="chat" job now carries the conversation — or
    None when nobody can answer, so the caller falls back to the
    built-in answer (never a dead end)."""
    if not _chat_worker_online():
        return None
    try:
        job = jobs.create_job(
            prompt=_build_chat_pack(project, message),
            kind="chat",
            project_id=project["id"] if project else None,
            user_id=(project or {}).get("user_id") or _current_user_id.get(),
        )
    except ValueError:
        return None
    return {
        "reply": None,
        "pending_chat_job": job["id"],
        "project": _public(project) if project else None,
        "created_jobs": [],
        "state": project["state"] if project else "ask_character",
    }


# --- the hidden [[QUEUE ...]] directive in LLM replies ----------------------
_QUEUE_DIRECTIVE = re.compile(
    r"\[\[\s*QUEUE\s+(.*?)\]\]", re.IGNORECASE | re.DOTALL)
_DIRECTIVE_ATTR = re.compile(
    r"(\w+)\s*=\s*\"([^\"]*)\"|(\w+)\s*=\s*([^\s\]]+)")


def parse_queue_directive(text: str) -> tuple[str, dict | None]:
    """Split a finished LLM reply into (visible text, directive).

    The directive — [[QUEUE kind=video prompt="..." style="..."
    aspect="16:9"]] — is hidden by design: it is ALWAYS removed
    from the visible text when present. Parsing is defensive: a
    malformed or incomplete directive yields None (ignored
    silently) and the job is simply never queued.
    """
    if not text:
        return text, None
    m = _QUEUE_DIRECTIVE.search(text)
    if not m:
        return text, None
    attrs: dict[str, str] = {}
    for attr in _DIRECTIVE_ATTR.finditer(m.group(1)):
        key = (attr.group(1) or attr.group(3) or "").lower()
        value = attr.group(2) if attr.group(2) is not None \
            else (attr.group(4) or "")
        if key:
            attrs[key] = value.strip()
    clean = (text[:m.start()] + text[m.end():]).strip()
    kind = (attrs.get("kind") or "").lower()
    prompt = (attrs.get("prompt") or "").strip()
    if kind not in ("video", "image", "audio") or not prompt:
        return clean, None
    return clean, {
        "kind": kind,
        "prompt": prompt,
        "style": attrs.get("style") or None,
        "aspect": attrs.get("aspect") or None,
    }


def queue_from_directive(chat_job: dict, directive: dict) -> str | None:
    """Turn a parsed [[QUEUE ...]] directive into a real creation
    job through the normal jobs.create_job path (so it gets the
    usual prompt-engine enhancement). When the chat belongs to a
    series project, the job joins that project — same consistency
    wiring as a queued scene: the project seed, and the character
    anchor prepended for video/image. Returns the new job id, or
    None when anything about it is unusable (never raises)."""
    try:
        kind = directive["kind"]
        prompt = (directive.get("prompt") or "").strip()
        if not prompt:
            return None
        project = None
        if chat_job.get("project_id"):
            project = _get_row(chat_job["project_id"])
        style = directive.get("style") or None
        if kind == "audio":
            # Style carries the voice for audio jobs.
            if not style:
                style = (project or {}).get("voice") or DEFAULT_VOICE
        else:
            style = _resolve_style(style) if style else (
                (project or {}).get("style") or "cinematic")
        aspect = directive.get("aspect") or (
            (project or {}).get("aspect") or config.DEFAULT_ASPECT)
        if aspect not in config.ASPECT_SIZES:
            aspect = config.DEFAULT_ASPECT
        seed = (project or {}).get("seed") or config.DEFAULT_SEED
        raw_prompt = prompt
        if (project and kind != "audio" and project.get("character")
                and not prompt.startswith(project["character"])):
            raw_prompt = f"{project['character']}. {prompt}"
        job = jobs.create_job(
            prompt=raw_prompt,
            style=style,
            aspect=aspect,
            kind=kind,
            seed=seed,
            project_id=project["id"] if project else None,
            user_id=chat_job.get("user_id")
                    or (project or {}).get("user_id"),
        )
        return job["id"]
    except Exception:
        return None


# --- stories (story.py) -----------------------------------------------------
_STORY_FILLER = {
    "write", "a", "an", "the", "story", "stories", "kahani",
    "sunao", "likho", "batao", "tell", "me", "please", "plz",
    "ek", "aik", "ki", "ka", "ke", "about", "on", "of",
}
_STORY_GENRE_ONLY = {
    "horror", "scary", "funny", "comedy", "adventure", "sci",
    "fi", "kids", "bedtime", "spooky", "romantic", "romance",
}
_STORY_TRIGGERS = {"write", "tell", "sunao", "likho", "batao",
                   "about"}


def _story_request(message: str, norm: str) -> tuple[bool, str]:
    """(True, topic) when the message asks for a written story;
    topic may be '' (ask for a hero). (False, '') otherwise."""
    toks = norm.split()
    tokset = set(toks)
    storyish = bool(tokset & {"story", "stories", "kahani"}) \
        or "sunao" in tokset
    if not storyish or not (tokset & _STORY_TRIGGERS):
        return (False, "")
    topic = ""
    m = re.search(r"\babout\s+(.+)$", message,
                  re.IGNORECASE | re.DOTALL)
    if m:
        topic = m.group(1).strip().rstrip(".")
    if not topic:
        for sep in ("—", "–", " - ", ":"):
            if sep in message:
                head, _, tail = message.rpartition(sep)
                if set(_norm(head).split()) & {
                        "story", "stories", "kahani", "sunao",
                        "likho"}:
                    topic = tail.strip().rstrip(".")
                    break
    if not topic:
        rest = [t for t in toks if t not in _STORY_FILLER
                and t not in _STORY_GENRE_ONLY]
        topic = " ".join(rest)
    return (True, topic)


_STORY_ASK_TEXT = (
    "A story — lovely! About whom? Give me a hero — like \"a "
    "brave little fox\" — and I'll write it properly, with a "
    "beginning, a middle and an end."
)

_SERIES_OFFER = (
    "Want this story as a video series? Say \"make it a "
    "series\" — I'll split it into parts and queue them with "
    "the same character."
)


def _story_reply(project: dict | None, topic: str,
                 message: str = "") -> dict:
    """Write a REAL story with the story engine and remember it
    (pending store) so 'make it a series' can film it."""
    if project is not None and project["character"] and not topic:
        premise = project["character"]
    else:
        premise = topic or (project["character"] if project else "")
    genre = story.detect_genre(f"{message} {premise}")
    seed = project["seed"] if project else None
    made = story.assemble(premise, genre=genre, seed=seed)
    key = project["id"] if project else _NO_PROJECT_KEY
    _pending_set(key, story={
        "title": made["title"], "scenes": made["scenes"],
        "anchor": made["anchor"], "premise": premise,
    })
    reply = (f"{made['title']}\n\n{made['story']}\n\n"
             f"{_SERIES_OFFER}")
    return _result(reply, project)


_MAKE_SERIES_EXACT = {
    "make it a series", "make this a series", "make it series",
    "make series", "series banao", "series bana do",
    "make it a video series", "isko series banao",
    "make a series",
}


def _is_make_series(norm: str) -> bool:
    return norm in _MAKE_SERIES_EXACT or "make it a series" in norm


def _series_from_story(project: dict | None) -> dict:
    """'make it a series' — film the last written story: ensure a
    project (anchor = the story's hero), then queue the story's 4
    scenes as parts through the normal consistency wiring."""
    key = project["id"] if project else _NO_PROJECT_KEY
    data = _pending_get(key).get("story")
    if not data and project is not None:
        data = _pending_get(_NO_PROJECT_KEY).get("story")
    if not data:
        return _result(
            "First let me write you a story — say \"write a story "
            "about a brave little fox\" — and then say \"make it a "
            "series\" and I'll split it into parts and queue them.",
            project,
        )
    if project is None:
        project = _create_project(data["anchor"])
    fields: dict = {}
    if not project["character"]:
        fields["character"] = data["anchor"]
        fields["name"] = _derive_name(data["anchor"])
    if not project["style"]:
        fields["style"] = "cinematic"
    fields["state"] = "ready"
    project = _update_project(project["id"], **fields)
    created: list[str] = []
    for scene in data["scenes"]:
        res = _queue_parsed_scene(
            project, scene, project["kind_default"])
        created.extend(res["created_jobs"])
    _pending_clear(project["id"], "story")
    if key != project["id"]:
        _pending_clear(key, "story")
    return _result(
        f"Done ✓ — \"{data['title']}\" is now your series: queued "
        f"{len(created)} parts, all with the same character "
        f"({data['anchor']}), style and seed. They'll appear in "
        "your Creations feed and generate when the studio runs. "
        "Say \"status\" to watch them come in.",
        project,
        created_jobs=created,
    )


# --- ready-state generation must be unmistakable ---------------------------
_PART_EXPLICIT = re.compile(
    r"^(?:part\s*\d+|next\s+(?:scene|part)|scene\s*\d*|"
    r"agla\s+(?:scene|hissa|part))\s*[:\-]",
    re.IGNORECASE,
)
_GEN_VERB = re.compile(
    r"^(?:make|create|generate|produce|render|draw|paint)\b",
    re.IGNORECASE,
)
_GEN_KIND_WORDS = {"video", "image", "picture", "photo", "audio",
                   "clip", "voice", "scene", "part"}


def _is_explicit_generation(message: str, norm: str) -> bool:
    """Unmistakable 'make this now' intent: a Part/scene prefix with
    its colon, an image/audio prefix, a generation verb with a kind
    word, or 'banao' carrying a scene. Plain description is NOT
    generation any more — the agent asks first."""
    text = message.strip()
    if _PART_EXPLICIT.match(text):
        return True
    if _AUDIO_PREFIX.match(text) or _IMAGE_PREFIX.match(text):
        return True
    if _GEN_VERB.match(text) and (
            set(norm.split()) & _GEN_KIND_WORDS
            or " of " in f" {norm} "):
        return True
    toks = norm.split()
    return "banao" in toks and len(toks) >= 3


# --- ideas ----------------------------------------------------------------
def _ideas_reply(project: dict | None, norm: str) -> dict:
    bucket = (knowledge.find_idea_bucket(norm)
              or knowledge.random_idea_bucket())
    ideas = list(bucket["ideas"])
    key = project["id"] if project else _NO_PROJECT_KEY
    _pending_set(key, ideas=ideas)
    lines = [f"Here are 3 {bucket['label']} ideas:"]
    lines += [f"{i}. {idea}" for i, idea in enumerate(ideas, 1)]
    lines.append(
        "Want me to queue one? Say: queue idea 2 — or describe your "
        "own scene.")
    return _result("\n".join(lines), project)


def _pending_ideas(project: dict) -> list:
    ideas = _pending_get(project["id"]).get("ideas")
    if not ideas:
        ideas = _pending_get(_NO_PROJECT_KEY).get("ideas")
    return ideas or []


def _queue_idea(project: dict, n: int) -> dict:
    ideas = _pending_ideas(project)
    if not ideas:
        return _result(
            "I haven't offered any ideas yet — say \"give me an "
            "idea\" and I'll bring three fresh ones.",
            project,
        )
    if not 1 <= n <= len(ideas):
        return _result(
            f"Idea {n} isn't on the list — I offered ideas "
            f"1 to {len(ideas)}. Pick one of those, or say \"give me "
            "an idea\" for fresh ones.",
            project,
        )
    return _queue_parsed_scene(
        project, ideas[n - 1], project["kind_default"])


# --- improve ----------------------------------------------------------------
_IMPROVE_CUES = [
    (("horror", "ghost", "haunted", "dark", "scary", "creepy", "night"),
     "slow creeping push-in",
     "pale moonlight and deep shadows",
     "a tense, eerie stillness"),
    (("neon", "cyberpunk", "city", "street", "tokyo"),
     "smooth tracking shot through the street",
     "glowing neon light reflecting on wet pavement",
     "a stylish futuristic mood"),
    (("mountain", "forest", "valley", "nature", "river", "jungle",
      "meadow"),
     "sweeping aerial reveal",
     "warm golden-hour sunlight",
     "a calm, majestic atmosphere"),
    (("ocean", "sea", "beach", "wave", "boat", "rain"),
     "slow cinematic pan across the water",
     "soft light under a dramatic sky",
     "a fresh, windswept mood"),
    (("space", "moon", "rocket", "astronaut", "star", "planet",
      "mars"),
     "majestic slow dolly shot",
     "dramatic rim light against the black sky",
     "an epic sense of wonder"),
    (("food", "chai", "tea", "biryani", "cooking", "chef", "kitchen"),
     "slow push-in close-up",
     "warm appetizing light with steam rising",
     "rich, delicious detail"),
    (("cat", "dog", "horse", "bird", "animal", "panda", "elephant",
      "lion"),
     "gentle tracking shot at ground level",
     "soft natural light",
     "playful, true-to-life energy"),
    (("car", "race", "train", "bike", "speed", "driving"),
     "dynamic low tracking shot",
     "bright daylight with a sense of speed",
     "thrilling forward energy"),
]


def _improve_prompt(text: str) -> str:
    """Rebuild a rough idea with the prompt formula: keep the user's
    subject + action, then add camera + lighting + mood chosen from
    the genre words the text carries."""
    core = " ".join(text.strip().split()).rstrip(".")
    core = core[:1].upper() + core[1:]
    low = core.lower()
    camera = "smooth cinematic tracking shot"
    lighting = "soft golden-hour light"
    mood = "rich detail and atmosphere"
    for words, cam, light, md in _IMPROVE_CUES:
        if any(re.search(rf"\b{w}\b", low) for w in words):
            camera, lighting, mood = cam, light, md
            break
    return (f"{core}, {camera}, {lighting}, {mood}, "
            "cinematic composition, ultra detailed")


def _improve_reply(project: dict | None, message: str) -> dict:
    m = _IMPROVE_PREFIX.match(" ".join(message.split()))
    text = (m.group(1) or "").strip() if m else ""
    if len(text) < 3:
        return _result(
            "Send the rough prompt right after, like: \"improve: a "
            "cat walking\" — I'll rebuild it with camera, light and "
            "mood.",
            project,
        )
    improved = _improve_prompt(text)
    reply = f"Here's a stronger version:\n\"{improved}\""
    if project is not None:
        _pending_set(project["id"], improved=improved)
        if project["state"] == "ready":
            reply += ("\nSay \"queue it\" to make it the next part "
                      "of your series.")
    else:
        reply += ("\nStart a series with me and I'll queue prompts "
                  "like this as parts.")
    return _result(reply, project)


def _queue_it(project: dict) -> dict:
    improved = _pending_get(project["id"]).get("improved")
    if not improved:
        return _result(
            "Nothing waiting to queue — say \"improve: <your scene>\" "
            "first and I'll polish it, then queue it.",
            project,
        )
    _pending_clear(project["id"], "improved")
    return _queue_parsed_scene(
        project, improved, project["kind_default"])


# --- series planner ---------------------------------------------------------
def _plan_reply(project: dict | None, premise: str, norm: str) -> dict:
    if not premise:
        return _result(
            "Happy to plan it! Tell me the premise like this: "
            "\"plan a series about a lost astronaut\" — I'll lay "
            "out a 4-part outline (Hook, Problem, Twist, Payoff).",
            project,
        )
    template = knowledge.find_template(premise)
    if project is None:
        project = _create_project(premise)
    fields: dict = {"state": "confirm_plan"}
    if not project["character"]:
        fields["character"] = premise
        fields["name"] = _derive_name(premise)
    if not project["style"]:
        fields["style"] = "cinematic"
    project = _update_project(project["id"], **fields)
    hero = project["character"] or premise
    beats = []
    for beat in template["beats"]:
        woven = beat.replace("{hero}", hero)
        beats.append(woven[:1].upper() + woven[1:])
    _pending_set(project["id"], plan=beats)
    lines = [
        f"Here's a 4-part {template['label']} outline for "
        f"\"{_derive_name(hero)}\":"
    ]
    for label, beat in zip(knowledge.beat_labels(), beats):
        lines.append(f"{label} — {beat}")
    lines.append(
        "(This is an outline — the plan for the series. For a full "
        "written story instead, say \"write a story about …\".)")
    lines.append("Queue all 4 parts? Say yes — or no to drop the plan.")
    return _result("\n".join(lines), project)


def _confirm_plan_reply(project: dict, norm: str) -> dict:
    """confirm_plan state: yes queues every beat, no drops the plan,
    anything else gets a gentle reminder (commands already ran)."""
    if norm in _YES_WORDS or norm.startswith("yes"):
        beats = _pending_get(project["id"]).get("plan") or []
        project = _update_project(project["id"], state="ready")
        _pending_clear(project["id"], "plan")
        if not beats:
            return _result(
                "The plan slipped away (the outline isn't stored "
                "anymore) — say \"plan a series about ...\" and I'll "
                "lay it out again.",
                project,
            )
        created: list[str] = []
        for beat in beats:
            res = _queue_parsed_scene(
                project, beat, project["kind_default"])
            created.extend(res["created_jobs"])
        if not created:
            return _result(
                "Hmm, the parts couldn't be queued — try sending one "
                "scene at a time.",
                project,
            )
        return _result(
            f"Done — queued all {len(created)} parts of "
            f"\"{project['name']}\" with the same character, style "
            "and seed. Say \"status\" to watch them come in.",
            project,
            created_jobs=created,
        )
    if norm in _NO_WORDS or norm.startswith("no "):
        project = _update_project(project["id"], state="ready")
        _pending_clear(project["id"], "plan")
        return _result(
            "No problem — plan dropped. Send any scene and I'll "
            "queue it as the next part.",
            project,
        )
    return _result(
        "Shall I queue all 4 parts of the plan? Say yes — or no "
        "to drop it.",
        project,
    )


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


def _is_improve_request(norm: str) -> bool:
    toks = norm.split()
    return (bool(toks) and toks[0] == "improve") or norm.startswith(
        ("behtar banao", "better banao"))


def _midflow_greeting(project: dict) -> str:
    """A greeting mid-flow re-asks the current question instead of
    being swallowed as an answer."""
    state = project["state"]
    if state == "ask_character":
        return _ask_character_reply()
    if state == "ask_style":
        return ("Hey! We're mid-setup — pick a style for your "
                "series: " + _style_options_text()
                + " — or describe your own.")
    if state == "ask_kind":
        return "Hey! Almost there — video, image, or audio?"
    if state == "ask_voice":
        return ("Hey! Pick the voice for the series: "
                + ", ".join(VOICES) + ".")
    return (
        "Your series is ready — send the next scene, or say "
        "\"status\" to see the parts so far."
    )


_GENERIC_TOKENS = {
    "write", "make", "create", "generate", "build", "tell", "give",
    "show", "help", "do", "please", "plz", "me", "us", "a", "an",
    "the", "video", "videos", "story", "stories", "series", "film", "banana",
    "movie", "image", "picture", "audio", "song", "something",
    "anything", "some", "one", "new", "kuch", "kahani", "ek", "bana",
    "banao", "likho", "likh", "karo", "kar", "de", "do", "hai", "chahiye",
}


def _is_generic_instruction(norm: str) -> bool:
    """True for bare commands with no creative content of their own
    ("write a story", "make a video", "ek kahani likho", "help me").
    Such a message is an intent, never a character description: every
    token is a verb / generic object / filler, nothing descriptive
    remains. A real character ("a small robot with a red scarf")
    always leaves descriptive tokens behind and returns False."""
    toks = norm.split()
    if not toks or len(toks) > 6:
        return False
    if not all(t in _GENERIC_TOKENS for t in toks):
        return False
    # "banana" is also a fruit: a bare "a banana" stays a character.
    verbs = {"write", "make", "create", "generate", "build",
             "tell", "give", "show", "help", "do", "bana",
             "banao", "likho", "karo"}
    intent = any(t in verbs for t in toks) or "hai" in toks \
        or "kuch" in toks or "chahiye" in toks
    return intent


def _generic_instruction_reply() -> str:
    return (
        "Got it — happy to! I just need one thing from you first: "
        "WHO or WHAT is it about? Describe the character or scene in "
        "a few words (e.g. \"a small robot with a red scarf\") and "
        "I'll lock it in, pick a style with you, and queue the parts. "
        "Or say \"give me an idea\" and I'll suggest some."
    )


def _chat_no_project(message: str, low: str, norm: str) -> dict:
    """No series yet. Greetings get the welcome guide; questions
    get answers; stories get written; knowledge, ideas, improve and
    planning all work standalone; anything else substantive IS the
    character description and starts a series."""
    if _is_pure_greeting(norm):
        return _result(_greeting_reply(None, norm), None)

    smalltalk = _smalltalk_reply(norm)
    if smalltalk:
        return _result(smalltalk, None)

    is_story, topic = _story_request(message, norm)
    if is_story:
        if not topic:
            _pending_set(_NO_PROJECT_KEY, story_ask=True)
            return _result(_STORY_ASK_TEXT, None)
        return _story_reply(None, topic, message)

    if _is_make_series(norm):
        return _series_from_story(None)

    if _is_question(message, norm):
        return _question_reply(None, message)

    if _is_greeting(low):
        return _result(_ask_character_reply(), None)

    premise = _plan_premise(message, norm)
    if premise is not None:
        return _plan_reply(None, premise, norm)

    if _QUEUE_IDEA.search(message) or _QUEUE_IDEA_ALT.search(message):
        return _result(
            "Let's start your series first — describe your character, "
            "finish the quick setup, and then \"queue idea 2\" turns "
            "an offered idea into your next part.",
            None,
        )

    if _is_improve_request(norm):
        return _improve_reply(None, message)

    if _is_idea_request(norm):
        return _ideas_reply(None, norm)

    entry = None
    cand = knowledge.lookup(message)
    if cand:
        # A confident KB hit answers in the lobby too — but only
        # when the message is shaped like a request for information
        # (a marker word or a question mark), or is a very short
        # topic probe ("drone shot"). A plain description stays a
        # character description: "a cinematic panda" must still
        # start the series, never earn a lecture about "cinematic".
        toks = set(norm.split())
        if (toks & _INFO_MARKERS or message.strip().endswith("?")
                or (knowledge.match_ratio(message, cand) >= 0.6
                    and len(norm.split()) <= 5)):
            entry = cand
    if entry:
        return _qa_reply(None, entry)

    if _looks_like_gibberish(norm):
        return _result(_capabilities_reply(None), None)

    # The user was asked "about whom?" — this message IS the topic.
    if _pending_get(_NO_PROJECT_KEY).get("story_ask"):
        _pending_clear(_NO_PROJECT_KEY, "story_ask")
        return _story_reply(None, message.strip(), message)

    if _is_generic_instruction(norm):
        return _result(_generic_instruction_reply(), None)

    # Conversation before onboarding: a message that reads as chat
    # — a first-person statement, a feeling, "who are you" — is not
    # a character description. When a chat worker is online the
    # fleet's LLM takes it (and creates nothing); offline, the
    # designed fallback below still treats the first substantive
    # message as the character, so the door is never closed.
    if _looks_like_chat_statement(norm):
        pending = _llm_chat_reply(None, message)
        if pending is not None:
            return pending

    # First substantive message = the character description.
    project = _create_project(message)
    # Ideas offered before the series existed carry over to it.
    store = _pending_get(_NO_PROJECT_KEY)
    if store:
        _pending_set(project["id"], **store)
        with _PENDING_LOCK:
            _PENDING.pop(_NO_PROJECT_KEY, None)
    return _result(_ask_style_reply(project), project)


def chat(project_id: str | None, message: str,
         user_id: str | None = None, is_admin: bool = False) -> dict:
    """One turn of the TOQIX Agent conversation.

    project_id None (or unknown) = no series context yet: a greeting
    gets the character question; anything else IS the character
    description and creates the project.

    With a project, the order is deliberate: commands first, then a
    pending plan confirmation, then the understanding layer (small
    talk, queue-idea, plan, improve, ideas, Q&A) — none of which ever
    consume an answer the state machine is waiting for — and only
    then the collect-flow state machine itself.
    """
    _current_user_id.set(user_id)
    message = (message or "").strip()
    low = message.lower()
    norm = _norm(message)

    # "new series" works from anywhere, including mid-flow.
    if _is_new_series(low):
        return _result(_ask_character_reply(), None)

    project = _get_row(project_id) if project_id else None

    # Ownership (accounts release): a series belongs to its creator.
    # Legacy ownerless projects are adopted by the admin on first open
    # and are invisible to everyone else.
    if project is not None:
        owner = project.get("user_id")
        if owner and owner != user_id and not is_admin:
            return _result(
                "That series belongs to a different account. "
                "Say 'new series' to start your own.", None)
        if not owner and is_admin and user_id:
            project = _update_project(project["id"], user_id=user_id)
        elif not owner and not is_admin:
            project = None

    if project is None:
        return _chat_no_project(message, low, norm)

    # Commands work in every state.
    command = _handle_command(project, message, low)
    if command is not None:
        return command

    # A pure greeting gets a warm greeting back in ANY state —
    # never swallowed as a flow answer, never creates anything.
    # (A plan awaiting confirmation stays pending; the greeting
    # reply reminds the user it is still there.)
    if _is_pure_greeting(norm):
        return _result(_greeting_reply(project, norm), project)

    # A plan awaiting confirmation beats everything else.
    if project["state"] == "confirm_plan":
        return _confirm_plan_reply(project, norm)

    # --- understanding layer (state-preserving) ----------------------
    smalltalk = _smalltalk_reply(norm)
    if smalltalk:
        return _result(smalltalk, project)

    if _is_greeting(low):
        return _result(_midflow_greeting(project), project)

    is_story, topic = _story_request(message, norm)
    if is_story:
        if not topic:
            _pending_set(project["id"], story_ask=True)
            return _result(_STORY_ASK_TEXT, project)
        return _story_reply(project, topic, message)

    if _is_make_series(norm):
        return _series_from_story(project)

    # A question is answered, never generated — this outranks the
    # scene interpretation even in "ready" state, even when the
    # question contains scene-like words.
    if _is_question(message, norm):
        return _question_reply(project, message)

    m = _QUEUE_IDEA.search(message) or _QUEUE_IDEA_ALT.search(message)
    if m:
        if project["state"] == "ready":
            return _queue_idea(project, int(m.group(1)))
        return _result(
            "Ideas queue once your series is ready — finish the "
            "quick setup first, then say \"queue idea 2\".",
            project,
        )

    if norm in ("queue it", "queue this", "make it", "queue it please"):
        if project["state"] == "ready":
            return _queue_it(project)
        return _result(
            "\"Queue it\" works once your series is ready — finish "
            "the quick setup first.",
            project,
        )

    premise = _plan_premise(message, norm)
    if premise is not None:
        return _plan_reply(project, premise, norm)

    if _is_improve_request(norm):
        return _improve_reply(project, message)

    if _is_idea_request(norm):
        return _ideas_reply(project, norm)

    # The user was asked "about whom?" for a story — this is it.
    if _pending_get(project["id"]).get("story_ask"):
        _pending_clear(project["id"], "story_ask")
        return _story_reply(project, message.strip(), message)

    entry = None
    if project["state"] == "ready":
        # A short bare topic in ready state ("cyberpunk style",
        # "drone shot") is a question, not a scene — but only when
        # the topic fills most of the message.
        cand = knowledge.lookup(message)
        if (cand and knowledge.match_ratio(message, cand) >= 0.6
                and len(norm.split()) <= 5):
            entry = cand
    if entry:
        return _qa_reply(project, entry)

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

    # state == "ready": greetings get a nudge; a scene offered for
    # confirmation is queued only on a clear yes; explicit
    # generation queues at once; plain description is ASKED about,
    # never auto-queued.
    if _is_greeting(low):
        return _result(
            "Your series is ready — send the next scene, or say "
            "\"status\" to see the parts so far.",
            project,
        )

    pend = _pending_get(project["id"])
    if pend.get("scene_confirm"):
        if norm in _YES_WORDS or norm.startswith(("yes", "haan")):
            scene_message = pend["scene_confirm"]
            _pending_clear(project["id"], "scene_confirm")
            return _queue_scene(project, scene_message)
        if norm in _NO_WORDS or norm.startswith("no "):
            _pending_clear(project["id"], "scene_confirm")
            return _result(
                "No problem — dropped it. Describe another scene "
                "whenever you're ready, or ask me anything.",
                project,
            )

    if norm in _YES_WORDS or norm in _NO_WORDS:
        # A bare yes/no with NOTHING waiting on it is just
        # conversation — the chat brain takes it when one is
        # online; the scripted reply remains the offline answer.
        pending = _llm_chat_reply(project, message)
        if pending is not None:
            return pending
        return _result(
            "Got it! Nothing is waiting on a yes right now — "
            "describe a scene and I'll check with you before "
            "queueing, or start with \"Part 1:\" to queue instantly.",
            project,
        )

    if _looks_like_gibberish(norm):
        return _result(_capabilities_reply(project), project)

    if _is_explicit_generation(message, norm):
        return _queue_scene(project, message)

    # Conversation-first (agent maturity upgrade): in ready state,
    # EVERYTHING else — descriptions, statements, feelings,
    # advice-seeking, open chat — is conversation, and the fleet's
    # LLM answers it whenever a chat worker is online. The brain
    # chats with the full series context in its pack and can still
    # turn real creation intent into a queued part through its
    # hidden [[QUEUE]] directive, so nothing is lost. The
    # deterministic check-first offer below is now only the
    # no-worker fallback: the agent never dead-ends, and it never
    # nags "want me to queue this?" while a brain is available.
    pending = _llm_chat_reply(project, message)
    if pending is not None:
        return pending

    scene_text = " ".join(message.split())
    summary = scene_text[:60] + ("…" if len(scene_text) > 60 else "")
    part_no = len(jobs.list_project_jobs(project["id"])) + 1
    _pending_set(project["id"], scene_confirm=message)
    return _result(
        f"\"{summary}\" — love it. Want me to queue this as Part "
        f"{part_no} of \"{project['name']}\"? Say yes and it's in — "
        "same character, same style. Or just keep chatting.",
        project,
    )


init_db()
