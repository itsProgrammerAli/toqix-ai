"""TOQIX model zoo — the registry of open models TOQIX runs on.

TOQIX is not one model. It is a small zoo of best-in-class OPEN
models — one per job kind — behind one website and one queue, with
this module as the single place that records which model serves
which kind today, which models are evaluated candidates, and which
are merely on the watch list.

Honesty rules baked into this file:

* ``active`` means the fleet ACTUALLY runs it today — proven end to
  end on the owner's free GPUs (see the production log). Nothing is
  marked active for looking good on a leaderboard.
* ``candidate`` means evaluated on paper (license, size, VRAM fit,
  diffusers support) but NOT yet GPU-tested by us. Adoption is a
  deliberate step: GPU smoke test -> output QA -> flip the status
  here + update the runner -> owner-visible deploy. Never automatic.
* ``watch`` means known to exist and not yet evaluated. Sizes and
  licenses in watch entries are from public model cards and are
  UNVERIFIED — re-check them before any adoption step.
* There is no real-time weight learning anywhere in TOQIX, and the
  big closed models (Veo, Sora, ...) publish no weights at all, so
  they can never appear here. The zoo can only ever hold models
  whose weights are public.

Quality tiers are a rough internal scale: 1 = draft quality,
3 = solid production quality on free hardware, 5 = best open
weights available anywhere (usually needs a datacenter GPU).
Sizes are approximate total download sizes in GB; ``vram_gb`` is
the approximate peak VRAM of the way WE run it (with the runner's
offload / quantization recipe), not the vendor's headline number.
"""

from __future__ import annotations

KINDS = ("video", "image", "audio_tts", "audio_music", "chat")
STATUSES = ("active", "candidate", "watch")

# The job kinds in jobs.KINDS are coarser than the zoo's: a site
# "audio" job is a character-voice (TTS) job, so it routes to the
# zoo's audio_tts lane. audio_music is a stage inside video jobs
# (the sound bed), not a job kind of its own.
JOB_KIND_TO_ZOO_KIND = {
    "video": "video",
    "image": "image",
    "audio": "audio_tts",
    "chat": "chat",
}

MODELS: list[dict] = [
    # ------------------------------------------------------------------
    # ACTIVE — what the fleet runs today, proven end to end.
    # ------------------------------------------------------------------
    {
        "id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "name": "Wan 2.1 Text-to-Video 1.3B",
        "kind": "video",
        "task": "t2v",
        "license": "Apache-2.0",
        "size_gb": 13.0,
        "vram_gb": 14.0,
        "quality_tier": 2,
        "status": "active",
        "note": "The fleet's video engine since 2026-10-14 (runner "
                "notebook 03: 8-bit text encoder, sequential offload, "
                "fp16 — fits a free 16 GB T4). Small: famous "
                "characters and exact real-world details are weak; "
                "the prompt engine compensates where it can.",
    },
    {
        "id": "stabilityai/sdxl-turbo",
        "name": "SDXL Turbo",
        "kind": "image",
        "task": "t2i",
        "license": "Stability AI Community License (free for "
                   "research/personal and orgs under $1M revenue)",
        "size_gb": 7.0,
        "vram_gb": 8.0,
        "quality_tier": 3,
        "status": "active",
        "note": "The fleet's image engine (fp16, 4 steps, guidance "
                "0.0). Fast and sharp; fine text and exact emblems "
                "still need the prompt engine's detail clauses + QA.",
    },
    {
        "id": "hexgrad/Kokoro-82M",
        "name": "Kokoro 82M",
        "kind": "audio_tts",
        "task": "tts",
        "license": "Apache-2.0",
        "size_gb": 0.35,
        "vram_gb": 1.0,
        "quality_tier": 3,
        "status": "active",
        "note": "The fleet's voice engine (6 character voices). "
                "Runs in the runner's isolated Python 3.12 venv; "
                "tiny enough to run on CPU if a GPU is busy.",
    },
    {
        "id": "facebook/musicgen-small",
        "name": "MusicGen Small",
        "kind": "audio_music",
        "task": "text-to-music",
        "license": "CC-BY-NC 4.0 (weights — non-commercial)",
        "size_gb": 3.0,
        "vram_gb": 4.0,
        "quality_tier": 2,
        "status": "active",
        "note": "Generates the sound bed muxed onto every video "
                "(runner sound stage, fp16). Licence is "
                "NON-COMMERCIAL — fine for the owner's own channel "
                "experiments, must be revisited before any paid "
                "product use.",
    },
    {
        "id": "Qwen/Qwen2.5-7B-Instruct",
        "name": "Qwen 2.5 7B Instruct",
        "kind": "chat",
        "task": "chat",
        "license": "Apache-2.0",
        "size_gb": 15.0,
        "vram_gb": 10.0,
        "quality_tier": 3,
        "status": "active",
        "note": "The Agent's chat brain on the fleet (8-bit). "
                "Proven live 2026-10-14. Its Urdu is weak; the "
                "persona's language rule mitigates, a bigger Qwen "
                "is the candidate below.",
    },
    # ------------------------------------------------------------------
    # CANDIDATES — evaluated on paper, not yet GPU-tested by us.
    # ------------------------------------------------------------------
    {
        "id": "Qwen/Qwen3-8B",
        "name": "Qwen 3 8B",
        "kind": "chat",
        "task": "chat",
        "license": "Apache-2.0",
        "size_gb": 16.0,
        "vram_gb": 10.0,
        "quality_tier": 4,
        "status": "candidate",
        "note": "Next chat brain: already prepped in runner "
                "notebook 03 (CHAT_MODEL_ID, non-thinking mode) "
                "with automatic fallback to the active 7B. "
                "Adoption = the pending one-worker A/B test, then "
                "fleet deploy.",
    },
    {
        "id": "Wan-AI/Wan2.2-TI2V-5B",
        "name": "Wan 2.2 Text+Image-to-Video 5B",
        "kind": "video",
        "task": "t2v",
        "license": "Apache-2.0",
        "size_gb": 11.0,
        "vram_gb": 24.0,
        "quality_tier": 4,
        "status": "candidate",
        "note": "The natural video upgrade: 720p-native, much "
                "stronger motion than the 1.3B. Vendor says it fits "
                "a 24 GB consumer card — our free T4s have 16 GB, "
                "so adoption needs an offload/quantization smoke "
                "test before believing it.",
    },
    {
        "id": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
        "name": "Wan 2.1 Text-to-Video 14B",
        "kind": "video",
        "task": "t2v",
        "license": "Apache-2.0",
        "size_gb": 65.0,
        "vram_gb": 40.0,
        "quality_tier": 4,
        "status": "candidate",
        "note": "Already listed in config.MODELS. Best Wan 2.1 "
                "quality, but it needs an A100-class GPU the free "
                "fleet does not have; candidate for any future "
                "paid-GPU day, not for the free fleet.",
    },
    {
        "id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "name": "Wan 2.1 Image-to-Video 14B 480P",
        "kind": "video",
        "task": "i2v",
        "license": "Apache-2.0",
        "size_gb": 65.0,
        "vram_gb": 40.0,
        "quality_tier": 4,
        "status": "candidate",
        "note": "Animate-a-still variant, already listed in "
                "config.MODELS. Same A100 caveat as the 14B T2V. "
                "pick() never routes plain video jobs here — it "
                "only serves an explicit i2v task.",
    },
    {
        "id": "black-forest-labs/FLUX.1-schnell",
        "name": "FLUX.1 Schnell",
        "kind": "image",
        "task": "t2i",
        "license": "Apache-2.0",
        "size_gb": 24.0,
        "vram_gb": 12.0,
        "quality_tier": 4,
        "status": "candidate",
        "note": "Big quality jump over SDXL Turbo for stills, "
                "especially hands/text. 12B — the fp16 weights do "
                "not fit a 16 GB T4 alongside anything else; "
                "adoption needs a quantized-load smoke test.",
    },
    {
        "id": "sesame/csm-1b",
        "name": "Sesame CSM 1B",
        "kind": "audio_tts",
        "task": "tts",
        "license": "Apache-2.0",
        "size_gb": 3.0,
        "vram_gb": 4.0,
        "quality_tier": 3,
        "status": "candidate",
        "note": "Conversational speech model — more natural "
                "prosody than Kokoro for dialogue-style audio. "
                "Needs a GPU test for voice consistency with the "
                "site's 6 character voices before adoption.",
    },
    # ------------------------------------------------------------------
    # WATCH — known, not yet evaluated. Sizes/licenses UNVERIFIED.
    # ------------------------------------------------------------------
    {
        "id": "THUDM/CogVideoX-5b",
        "name": "CogVideoX 5B",
        "kind": "video",
        "task": "t2v",
        "license": "CogVideoX model license (custom — verify "
                   "commercial terms before any use)",
        "size_gb": 11.0,
        "vram_gb": 16.0,
        "quality_tier": 3,
        "status": "watch",
        "note": "Alternative open video model family. Not "
                "evaluated: license terms and T4 offload fit both "
                "need checking first.",
    },
    {
        "id": "Lightricks/LTX-Video",
        "name": "LTX-Video",
        "kind": "video",
        "task": "t2v",
        "license": "LTX-Video Open Weights License (verify)",
        "size_gb": 5.0,
        "vram_gb": 12.0,
        "quality_tier": 3,
        "status": "watch",
        "note": "Known for very fast generation. Not evaluated: "
                "which checkpoint/license applies and real output "
                "quality at our sizes are open questions.",
    },
    {
        "id": "stabilityai/stable-diffusion-3.5-medium",
        "name": "Stable Diffusion 3.5 Medium",
        "kind": "image",
        "task": "t2i",
        "license": "Stability AI Community License (verify "
                   "current terms)",
        "size_gb": 5.0,
        "vram_gb": 10.0,
        "quality_tier": 4,
        "status": "watch",
        "note": "Possible SDXL successor for stills with better "
                "prompt following. Not evaluated against FLUX "
                "Schnell on our hardware yet.",
    },
    {
        "id": "Qwen/Qwen3-14B",
        "name": "Qwen 3 14B",
        "kind": "chat",
        "task": "chat",
        "license": "Apache-2.0",
        "size_gb": 28.0,
        "vram_gb": 16.0,
        "quality_tier": 4,
        "status": "watch",
        "note": "Stronger chat brain, but at 8-bit it leaves no "
                "KV-cache headroom on a 16 GB T4 (already rejected "
                "once as OOM-prone). Revisit only with a bigger "
                "GPU or a proven 4-bit recipe.",
    },
]

_BY_ID = {m["id"]: m for m in MODELS}


def get(model_id: str) -> dict | None:
    """One zoo entry by HF id (a copy), or None."""
    entry = _BY_ID.get(model_id)
    return dict(entry) if entry else None


def entries(kind: str | None = None,
            status: str | None = None) -> list[dict]:
    """Registry entries (copies), optionally filtered."""
    out = []
    for m in MODELS:
        if kind is not None and m["kind"] != kind:
            continue
        if status is not None and m["status"] != status:
            continue
        out.append(dict(m))
    return out


def pick(kind: str, heavy: bool = False) -> dict | None:
    """The ACTIVE zoo entry serving ``kind`` — what the fleet runs.

    For video, only text-to-video entries route plain video jobs
    (the i2v variant never hijacks them). ``heavy`` (a 10s+ video)
    prefers the highest-tier active when more than one is active;
    today exactly one model per kind is active, so heavy changes
    nothing yet — it exists so the day a bigger video model goes
    active, heavy jobs route to it without code changes elsewhere.
    Returns None when a kind has no active entry (unknown kind
    raises ValueError instead — a typo must not silently route).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown zoo kind: {kind}")
    actives = [m for m in MODELS
               if m["kind"] == kind and m["status"] == "active"]
    if kind == "video":
        actives = [m for m in actives if m.get("task") == "t2v"]
    if not actives:
        return None
    actives.sort(key=lambda m: (-int(m["quality_tier"]), m["id"]))
    return dict(actives[0])


def active_models() -> dict:
    """{zoo kind: {id, name, quality_tier}} for every served kind —
    the public face of the zoo (used by GET /api/zoo)."""
    out = {}
    for kind in KINDS:
        entry = pick(kind)
        if entry:
            out[kind] = {
                "id": entry["id"],
                "name": entry["name"],
                "quality_tier": entry["quality_tier"],
            }
    heavy = pick("video", heavy=True)
    if heavy:
        out["video_heavy"] = {
            "id": heavy["id"],
            "name": heavy["name"],
            "quality_tier": heavy["quality_tier"],
        }
    return out


def zoo_summary() -> dict:
    """Counts by status and kind, for status endpoints/reports."""
    by_status = {s: 0 for s in STATUSES}
    by_kind = {k: 0 for k in KINDS}
    for m in MODELS:
        by_status[m["status"]] = by_status.get(m["status"], 0) + 1
        by_kind[m["kind"]] = by_kind.get(m["kind"], 0) + 1
    return {
        "total": len(MODELS),
        "by_status": by_status,
        "by_kind": by_kind,
    }
