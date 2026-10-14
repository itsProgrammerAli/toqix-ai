"""TOQIX post-processing — ffmpeg helpers.

Delivery spec for everything TOQIX ships (the user's client needs it):
H.264 video, faststart (moov atom at the front), yuv420p pixel format,
limited (TV) range, BT.709 primaries/transfer/matrix.

All local ffmpeg calls — no external services.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Force even dims, then stamp full BT.709 + limited-range tags into the
# frames themselves (setparams) — encoder flags alone leave primaries/
# transfer untagged on some inputs.
_SETPARAMS = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
_DELIVERY_VFILTER = f"scale=trunc(iw/2)*2:trunc(ih/2)*2,{_SETPARAMS}"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
    return proc


def probe(path: str | Path) -> dict:
    """ffprobe a media file, return parsed JSON."""
    proc = _run([
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ])
    return json.loads(proc.stdout)


def video_stream(path: str | Path) -> dict:
    for stream in probe(path).get("streams", []):
        if stream.get("codec_type") == "video":
            return stream
    raise ValueError(f"no video stream in {path}")


def has_audio(path: str | Path) -> bool:
    return any(
        s.get("codec_type") == "audio" for s in probe(path).get("streams", [])
    )


def is_faststart(path: str | Path) -> bool:
    """True when the moov atom sits before the first mdat atom."""
    data = Path(path).read_bytes()[: 64 * 1024 * 1024]
    moov = data.find(b"moov")
    mdat = data.find(b"mdat")
    return moov != -1 and (mdat == -1 or moov < mdat)


def _delivery_args() -> list[str]:
    return [
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-color_primaries", "bt709", "-color_trc", "bt709",
        "-colorspace", "bt709", "-color_range", "tv",
        "-movflags", "+faststart",
    ]


def normalize(src: str | Path, dst: str | Path) -> Path:
    """Re-encode any MP4 to the TOQIX delivery spec."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", _DELIVERY_VFILTER, *_delivery_args(), "-c:a", "aac",
           "-b:a", "128k", str(dst)]
    _run(cmd)
    return dst


def upscale(src: str | Path, dst: str | Path, scale: float = 2.0,
            target_height: int | None = None) -> Path:
    """Lanczos upscale + gentle sharpening, delivered in TOQIX spec."""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if target_height:
        vf = (f"scale=-2:{int(target_height)}:flags=lanczos,"
              f"unsharp=5:5:0.8:5:5:0.0,{_SETPARAMS}")
    else:
        vf = (f"scale=iw*{scale}:ih*{scale}:flags=lanczos,"
              f"unsharp=5:5:0.8:5:5:0.0,{_SETPARAMS}")
    cmd = ["ffmpeg", "-y", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?",
           "-vf", vf, *_delivery_args(), "-c:a", "aac", "-b:a", "128k",
           str(dst)]
    _run(cmd)
    return dst


def mux_audio(video: str | Path, audio: str | Path, dst: str | Path,
              shortest: bool = True) -> Path:
    """Replace (or add) the audio track of a video. Video is copied
    untouched; container is rewritten with faststart."""
    video, audio, dst = Path(video), Path(audio), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-i", str(video), "-i", str(audio),
           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]
    if shortest:
        cmd.append("-shortest")
    cmd.append(str(dst))
    _run(cmd)
    return dst


def thumbnail(video: str | Path, dst: str | Path, at_seconds: float = 0.5) -> Path:
    """Extract a single JPG frame for the gallery."""
    video, dst = Path(video), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run([
        "ffmpeg", "-y", "-ss", str(at_seconds), "-i", str(video),
        "-frames:v", "1", "-q:v", "3", str(dst),
    ])
    return dst
