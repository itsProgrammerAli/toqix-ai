# TOQIX AI

**Socho. Bolo. Ban Gaya.** — Think it. Say it. It's made.

TOQIX AI is the web studio front desk of a self-owned, any-prompt video
generation system. Type an idea — in English or Roman Urdu — and TOQIX turns
it into a director-grade generation prompt, packages it as a job for the
owner's GPU runner, and publishes finished videos in the studio gallery.

What this web app does:

- **Prompt engine** — understands Roman Urdu as well as English, detects the
  content domain (15-domain curriculum), and expands a rough idea into a
  detailed cinematic prompt with style presets.
- **Job packages** — every prompt becomes a job that is exported for the
  owner's Colab GPU runner (Wan 2.1 open-weights model).
- **Gallery** — finished MP4s are imported back, normalized by ffmpeg to
  delivery spec (faststart, limited-range yuv420p BT.709) with JPG
  thumbnails, and shown with ratings and training-consent controls.
- **Data flywheel** — consented, highly rated results are curated into
  versioned datasets that feed the owner's own LoRA fine-tunes.

Honest note on where rendering happens: the heavy video generation runs on
GPU via the project's Colab notebooks — not on this web host. This service
is the studio (interface, prompt engine, job store, gallery); the GPU
runner does the rendering, and finished videos come back here.

**Zero external APIs at runtime.** No generation service, no API keys —
every moving part is open source or written for TOQIX.

## Deploy

Docker. The image is based on `python:3.12-slim` with `ffmpeg` installed,
runs as a non-root user, and starts with:

```
uvicorn toqix.server:app --host 0.0.0.0 --port ${PORT:-7860}
```

The app listens on `$PORT` when the host provides one (e.g. Render), and
falls back to port 7860 otherwise.
