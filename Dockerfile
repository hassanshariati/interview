FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
# Keep these two layers in the same order as previously released builds, so
# production can reuse its existing pip cache even if PyPI is temporarily slow.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Decode MediaRecorder WebM/Opus and normalize to MP3 through in-memory pipes.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY backend ./backend
COPY web ./web
RUN useradd -m app && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
