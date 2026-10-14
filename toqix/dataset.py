"""TOQIX data flywheel — versioned training-dataset builder.

TOQIX improves in *rounds*, not by magic: finished generations the user
rated highly AND consented to share, plus the user's own uploaded videos,
are curated here into a versioned dataset:

    data/datasets/v{N}/  videos + caption .txt files + manifest.json

Notebook 04 then fine-tunes a new LoRA (toqix_lora_v{N}) on the latest
version on the owner's GPU.

Hard rules (never violated by this module):
  * Nothing is included without recorded consent — a job's consent flag
    must be ON; uploads require data/uploads/consent.json with
    {"training_consent": true}.
  * Finished jobs qualify automatically only at rating >= 4. Lower-rated
    jobs are excluded unless explicitly included (manual_job_ids or
    include_low_rated=True) — and even then, only with consent.
  * Every skip is recorded in the manifest with its reason.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from . import config, jobs

MIN_AUTO_RATING = 4
_VIDEO_SUFFIXES = (".mp4", ".mov", ".mkv", ".webm")


def uploads_consent() -> bool:
    """Uploads count as consented only with an explicit consent file."""
    marker = config.UPLOADS_DIR / "consent.json"
    if not marker.exists():
        return False
    try:
        return bool(json.loads(marker.read_text(encoding="utf-8")).get("training_consent"))
    except Exception:
        return False


def dataset_versions() -> list[int]:
    versions = []
    for path in config.DATASETS_DIR.glob("v*"):
        if path.is_dir() and path.name[1:].isdigit():
            versions.append(int(path.name[1:]))
    return sorted(versions)


def next_version() -> int:
    versions = dataset_versions()
    return (versions[-1] + 1) if versions else 1


def latest_manifest() -> dict | None:
    versions = dataset_versions()
    if not versions:
        return None
    path = config.DATASETS_DIR / f"v{versions[-1]}" / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_dataset(
    include_low_rated: bool = False,
    manual_job_ids: list[str] | None = None,
) -> dict:
    """Curate the next dataset version and return its manifest."""
    manual = set(manual_job_ids or [])
    version = next_version()
    vdir = config.DATASETS_DIR / f"v{version}"
    vdir.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    skipped: list[dict] = []

    # (a) Finished generations — consent first, then the rating bar.
    for job in jobs.list_jobs(limit=100000):
        if job["status"] != "done":
            continue
        if not job["consent"]:
            skipped.append({
                "source": "job", "id": job["id"],
                "reason": "no training consent recorded",
            })
            continue
        qualifies = (
            job["rating"] >= MIN_AUTO_RATING
            or include_low_rated
            or job["id"] in manual
        )
        if not qualifies:
            skipped.append({
                "source": "job", "id": job["id"],
                "reason": f"rating {job['rating']} below {MIN_AUTO_RATING} "
                          "(not manually included)",
            })
            continue
        src = config.OUTPUTS_DIR / f"{job['id']}.mp4"
        if not src.exists():
            skipped.append({
                "source": "job", "id": job["id"],
                "reason": "output file missing",
            })
            continue
        name = f"job_{job['id']}"
        shutil.copy2(src, vdir / f"{name}.mp4")
        caption = job["enhanced_prompt"]
        (vdir / f"{name}.txt").write_text(caption, encoding="utf-8")
        items.append({
            "file": f"{name}.mp4",
            "caption_file": f"{name}.txt",
            "source": "job",
            "job_id": job["id"],
            "prompt": job["prompt"],
            "caption": caption,
            "rating": job["rating"],
            "domain": job.get("domain", ""),
            "consent": True,
        })

    # (b) User uploads — folder-level explicit consent + a caption per video.
    consented = uploads_consent()
    for video in sorted(config.UPLOADS_DIR.iterdir()):
        if video.suffix.lower() not in _VIDEO_SUFFIXES or not video.is_file():
            continue
        if not consented:
            skipped.append({
                "source": "upload", "file": video.name,
                "reason": "no data/uploads/consent.json with "
                          "{\"training_consent\": true}",
            })
            continue
        caption_path = video.with_suffix(".txt")
        if not caption_path.exists():
            skipped.append({
                "source": "upload", "file": video.name,
                "reason": "no caption .txt file",
            })
            continue
        caption = caption_path.read_text(encoding="utf-8").strip()
        dest_name = f"upload_{video.name}"
        shutil.copy2(video, vdir / dest_name)
        (vdir / f"upload_{video.stem}.txt").write_text(caption, encoding="utf-8")
        items.append({
            "file": dest_name,
            "caption_file": f"upload_{video.stem}.txt",
            "source": "upload",
            "filename": video.name,
            "prompt": caption,
            "caption": caption,
            "rating": None,
            "domain": "",
            "consent": True,
        })

    n_jobs = sum(1 for i in items if i["source"] == "job")
    n_uploads = sum(1 for i in items if i["source"] == "upload")
    manifest = {
        "version": version,
        "created_at": time.time(),
        "min_auto_rating": MIN_AUTO_RATING,
        "include_low_rated": bool(include_low_rated),
        "items": items,
        "skipped": skipped,
        "counts": {"included": len(items), "skipped": len(skipped)},
        "totals": {
            "items": len(items),
            "jobs": n_jobs,
            "uploads": n_uploads,
            "skipped": len(skipped),
        },
    }
    (vdir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="toqix.dataset")
    sub = parser.add_subparsers(dest="command")
    build_parser = sub.add_parser(
        "build", help="curate the next versioned dataset")
    build_parser.add_argument(
        "--include-low-rated", action="store_true",
        help="also include consented jobs rated below "
             f"{MIN_AUTO_RATING} (consent is still mandatory)")
    args = parser.parse_args()
    if args.command not in (None, "build"):
        parser.error(f"unknown command: {args.command}")

    m = build_dataset(include_low_rated=bool(
        getattr(args, "include_low_rated", False)))
    print(f"dataset v{m['version']}: {m['counts']['included']} clips included, "
          f"{m['counts']['skipped']} skipped")
    for item in m["items"]:
        print("  +", item["file"], f"({item['source']})")
    for skip in m["skipped"]:
        print("  -", skip.get("id") or skip.get("file"), "->", skip["reason"])
