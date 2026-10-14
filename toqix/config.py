"""Central configuration for TOQIX AI.

Everything is local. No API keys, no external services.
Generation happens on the owner's GPU via the Colab notebooks,
which read these same defaults from the exported job packages.
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
EXPORTS_DIR = DATA_DIR / "exports"      # job package JSONs for the Colab runner
OUTPUTS_DIR = DATA_DIR / "outputs"      # finished, delivery-spec MP4s
THUMBS_DIR = DATA_DIR / "thumbs"        # JPG thumbnails for the gallery
IMPORTS_DIR = DATA_DIR / "imports"      # raw MP4s arriving from the GPU runner
UPLOADS_DIR = DATA_DIR / "uploads"      # user videos (+ caption .txt) for the flywheel
DATASETS_DIR = DATA_DIR / "datasets"    # versioned training datasets v1, v2, ...
CURRICULUM_DIR = DATA_DIR / "curriculum"
DOMAINS_PATH = CURRICULUM_DIR / "domains.json"
LOGS_DIR = BASE_DIR / "logs"
DB_PATH = DATA_DIR / "toqix.db"

for _d in (DATA_DIR, EXPORTS_DIR, OUTPUTS_DIR, THUMBS_DIR, IMPORTS_DIR,
           UPLOADS_DIR, DATASETS_DIR, CURRICULUM_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
HOST = os.environ.get("TOQIX_HOST", "0.0.0.0")
PORT = int(os.environ.get("TOQIX_PORT", "8960"))

# ---------------------------------------------------------------------------
# Models (open weights on Hugging Face — downloaded by the Colab notebooks,
# never called through any hosted inference API)
# ---------------------------------------------------------------------------
MODELS = {
    # Default engine: small enough for a free-tier T4, still real Wan quality.
    "wan2.1-t2v-1.3b": {
        "label": "Wan 2.1 Text-to-Video 1.3B (fast, T4-friendly)",
        "hf_id": "Wan-AI/Wan2.1-T2V-1.3B-Diffusers",
        "pipeline": "WanPipeline",
        "task": "t2v",
    },
    # Heavier text-to-video for A100 / paid Colab runtimes.
    "wan2.1-t2v-14b": {
        "label": "Wan 2.1 Text-to-Video 14B (max quality, A100)",
        "hf_id": "Wan-AI/Wan2.1-T2V-14B-Diffusers",
        "pipeline": "WanPipeline",
        "task": "t2v",
    },
    # Image-to-video: animate a still image.
    "wan2.1-i2v-14b-480p": {
        "label": "Wan 2.1 Image-to-Video 14B 480P",
        "hf_id": "Wan-AI/Wan2.1-I2V-14B-480P-Diffusers",
        "pipeline": "WanImageToVideoPipeline",
        "task": "i2v",
    },
}
DEFAULT_MODEL = "wan2.1-t2v-1.3b"

# The owner's own fine-tuned checkpoint (produced by notebook 02).
# On Drive it lives at MyDrive/TOQIX/checkpoints/toqix_lora — the runner
# notebook picks it up automatically when present.
LORA_DRIVE_PATH = "TOQIX/checkpoints/toqix_lora"
LORA_NAME = "toqix"

# ---------------------------------------------------------------------------
# Generation defaults (Wan-native: 16 fps, frame count must be 4k+1)
# ---------------------------------------------------------------------------
DEFAULT_STEPS = 30
DEFAULT_GUIDANCE = 5.0
DEFAULT_FPS = 16
DEFAULT_DURATION = 3          # seconds
DEFAULT_SEED = 42

# Aspect -> (width, height). All dimensions are multiples of 16, as the
# Wan VAE requires.
ASPECT_SIZES = {
    "16:9": (832, 480),
    "9:16": (480, 832),
    "1:1": (640, 640),
}
DEFAULT_ASPECT = "16:9"


def frames_for_duration(duration_seconds: float, fps: int = DEFAULT_FPS) -> int:
    """Wan generates 4k+1 frames. Round the requested duration to the
    nearest valid frame count at the given fps."""
    n = float(duration_seconds) * int(fps)
    frames = 4 * round(n / 4) + 1
    return max(17, int(frames))


def size_for_aspect(aspect: str) -> tuple[int, int]:
    return ASPECT_SIZES.get(aspect, ASPECT_SIZES[DEFAULT_ASPECT])
