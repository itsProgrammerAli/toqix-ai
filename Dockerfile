# TOQIX AI Studio — Hugging Face Spaces (Docker SDK)
# Runs the FastAPI studio (prompt engine + gallery). Video rendering itself
# happens on the owner's GPU (Colab notebooks); this Space is the studio.
FROM python:3.12-slim

# ffmpeg is required at runtime: toqix/postprocess.py shells out to ffmpeg
# for delivery-spec normalization (faststart, yuv420p BT.709) and thumbnails.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces runs containers as uid 1000.
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    TOQIX_PORT=7860

WORKDIR /home/user/app

# Dependencies first (layer caching). Installed system-wide as root so the
# uvicorn entrypoint is on PATH for the non-root user.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (toqix package, static web studio, curriculum data).
COPY --chown=user:user toqix ./toqix
COPY --chown=user:user web ./web
COPY --chown=user:user data ./data

# The app creates its working dirs (data/exports, outputs, thumbs, imports,
# uploads, datasets, logs) at import time — they must be writable by uid 1000.
RUN mkdir -p /home/user/app/data /home/user/app/logs \
    && chown -R user:user /home/user/app

USER user
EXPOSE 7860

CMD ["sh", "-c", "uvicorn toqix.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
