"""Optional Persian question audio and full-recording transcription services.

No audio is retained in the database or filesystem. TTS uses the remote
Microsoft Edge neural-voice service; STT uses the configured GapGPT account
and may incur extra provider costs. Both require candidate consent.
"""
import asyncio
import logging
import os
import re

import httpx
from fastapi import HTTPException

from .gapgpt import gapgpt_config

logger = logging.getLogger("interview.stt")

_AUDIO_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,95}$")
_VOICES = frozenset({"fa-IR-DilaraNeural", "fa-IR-FaridNeural"})
_AUDIO_LIMIT = 4 * 1024 * 1024


async def persian_question_mp3(question: str) -> bytes:
    """Generate speech for the last server-authored Persian question only."""
    if os.getenv("PERSIAN_TTS_ENABLED", "true").lower() != "true":
        raise HTTPException(503, "تولید صدای فارسی روی سرور فعال نیست.")
    voice = os.getenv("PERSIAN_TTS_VOICE", "fa-IR-DilaraNeural")
    if voice not in _VOICES:
        raise HTTPException(503, "صدای فارسی انتخاب‌شده معتبر نیست.")
    # Imported lazily so unit tests can patch this function without network.
    try:
        import edge_tts
    except ImportError as exc:
        raise HTTPException(503, "خدمات صدای فارسی نصب نشده‌اند.") from exc

    async def produce():
        fragments = []
        size = 0
        communicator = edge_tts.Communicate(question[:1500], voice, rate="-6%")
        async for part in communicator.stream():
            if part.get("type") != "audio":
                continue
            chunk = part.get("data", b"")
            size += len(chunk)
            if size > _AUDIO_LIMIT:
                raise HTTPException(502, "حجم خروجی صدای فارسی بیش از حد مجاز است.")
            fragments.append(chunk)
        return b"".join(fragments)

    try:
        audio = await asyncio.wait_for(produce(), timeout=22.0)
    except (TimeoutError, OSError, ValueError) as exc:
        raise HTTPException(502, "تولید صدای فارسی در سرویس گفتار ممکن نشد.") from exc
    except HTTPException:
        raise
    except Exception as exc:
        # edge_tts currently raises a mixture of connector/protocol errors.
        raise HTTPException(502, "سرویس صدای فارسی در دسترس نیست.") from exc
    if len(audio) < 256:
        raise HTTPException(502, "فایل صوتی فارسی معتبری دریافت نشد.")
    return audio


_STT_INPUT_LIMIT = 8 * 1024 * 1024
_STT_OUTPUT_LIMIT = 8 * 1024 * 1024
_STT_FORMATS = frozenset({"audio/webm", "audio/ogg", "audio/mp4", "audio/wav",
                          "audio/mpeg", "audio/mp3"})


async def normalize_browser_audio(audio: bytes, mime: str) -> bytes:
    """Decode untrusted browser audio and encode canonical mono 16-kHz MP3 in pipes.

    GapGPT is known to accept MP3, but some gateways reject MediaRecorder
    WebM/Opus clips. No applicant recordings are written to the filesystem.
    FFmpeg runs inside the unprivileged, read-only, resource-limited API container.
    """
    media = mime.split(";", 1)[0].lower().strip()
    if media not in _STT_FORMATS:
        raise HTTPException(422, "قالب فایل صوتی مرورگر پشتیبانی نمی‌شود.")
    if not (1024 <= len(audio) <= _STT_INPUT_LIMIT):
        raise HTTPException(413 if len(audio) > _STT_INPUT_LIMIT else 422,
                            "فایل صوتی ضبط‌شده خالی یا بیش از حد بزرگ است.")
    cmd = (
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
        "-protocol_whitelist", "pipe", "-threads", "1", "-i", "pipe:0",
        "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", "190",
        "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame",
        "-b:a", "48k", "-f", "mp3", "pipe:1",
    )
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except (OSError, FileNotFoundError) as exc:
        logger.error("STT audio converter unavailable")
        raise HTTPException(503, "ابزار تبدیل فایل صوتی روی سرور آماده نیست.") from exc
    try:
        converted, _stderr = await asyncio.wait_for(process.communicate(audio), timeout=24)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise HTTPException(504, "تبدیل فرمت صوتی بیش از حد زمان برد؛ فایل را کوتاه‌تر ضبط کن.") from exc
    if process.returncode != 0 or len(converted) < 1024 or len(converted) > _STT_OUTPUT_LIMIT:
        logger.warning("STT audio conversion failed media=%s code=%s bytes=%d",
                       media, process.returncode, len(audio))
        raise HTTPException(422, "فایل صوتی ضبط‌شده قابل رمزگشایی نبود؛ لطفاً با مرورگر دیگری ضبط کن.")
    logger.info("STT audio normalized media=%s input_bytes=%d mp3_bytes=%d",
                media, len(audio), len(converted))
    return converted


async def gapgpt_transcribe_audio(audio: bytes, mime: str) -> str:
    """Transcribe the full recorded clip with bounded retries for transient failures.

    Do not log audio, API tokens, provider response bodies, or candidate data.
    Retries can incur additional provider costs, so never retry authorization,
    invalid-file or quota failures.
    """
    if os.getenv("GAPGPT_STT_ENABLED", "true").lower() != "true":
        raise HTTPException(503, "تبدیل صوت به متن در این سامانه فعال نیست.")
    key, _, base = gapgpt_config()
    model = os.getenv("GAPGPT_STT_MODEL", "whisper-1").strip()
    if not _AUDIO_MODEL.fullmatch(model):
        raise HTTPException(503, "مدل تبدیل گفتار به متن معتبر نیست.")
    # Standard MP3 uploads work with GapGPT while browser WebM/Opus may not.
    # Re-encode the complete recording rather than relabeling its MIME type.
    mp3_audio = await normalize_browser_audio(audio, mime)
    payload = {"model": model, "response_format": "json"}
    if model == "whisper-1":
        payload["language"] = "fa"

    attempts = max(1, min(2, int(os.getenv("GAPGPT_STT_MAX_ATTEMPTS", "2"))))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(44.0, connect=8.0), follow_redirects=False
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(
                        base + "/audio/transcriptions",
                        headers={"Authorization": "Bearer " + key},
                        files={"file": ("answer.mp3", mp3_audio, "audio/mpeg")},
                        data=payload,
                    )
                except (httpx.TimeoutException, httpx.RequestError) as exc:
                    kind = "timeout" if isinstance(exc, httpx.TimeoutException) else "connection"
                    logger.warning("STT upstream %s at attempt %d of %d", kind, attempt+1, attempts)
                    if attempt + 1 < attempts:
                        await asyncio.sleep(0.5)
                        continue
                    status = 504 if kind == "timeout" else 502
                    message = ("مهلت پردازش صدا در سرویس به پایان رسید." if status == 504 else
                               "اتصال به سرویس تبدیل صدا برقرار نشد.")
                    raise HTTPException(status, message) from exc

                status = response.status_code
                if status in (500, 502, 503, 504):
                    logger.warning("STT upstream returned HTTP %d at attempt %d of %d",
                                   status, attempt+1, attempts)
                    if attempt + 1 < attempts:
                        await asyncio.sleep(0.5)
                        continue
                    raise HTTPException(502, "سرویس تبدیل گفتار خطای موقت "
                                        + str(status) + " داد؛ از گزینه تلاش مجدد استفاده کن.")
                if status in (401, 403):
                    raise HTTPException(503, "کلید API برای تبدیل صوت پذیرفته نشد.")
                if status == 404:
                    raise HTTPException(503, "مدل یا مسیر تبدیل صوت در حساب GapGPT فعال نیست.")
                if status in (402, 429):
                    raise HTTPException(503, "سقف مصرف یا موجودی API صوتی کافی نیست.")
                if status == 413:
                    raise HTTPException(413, "حجم فایل صوتی برای سرویس تبدیل گفتار زیاد است.")
                if status in (400, 415, 422):
                    raise HTTPException(422, "سرویس GapGPT فایل MP3 تبدیل‌شده را نپذیرفت "
                                        + "(کد " + str(status) + "). مدل تبدیل گفتار یا محدودیت حساب را بررسی کن.")
                if status >= 400:
                    logger.warning("STT upstream rejected request status=%d", status)
                    raise HTTPException(502, "سرویس تبدیل صوت پاسخ ناموفق داد (کد "
                                        + str(status) + ").")
                try:
                    data = response.json()
                    transcript = data.get("text", "") if isinstance(data, dict) else ""
                    if not isinstance(transcript, str) or not transcript.strip():
                        raise ValueError("empty transcript")
                except (ValueError, TypeError) as exc:
                    logger.warning("STT upstream response could not be parsed, status=%d", status)
                    raise HTTPException(502, "متن قابل‌استفاده‌ای از سرویس تبدیل گفتار دریافت نشد.") from exc
                return transcript.strip()[:6500]
    except HTTPException:
        raise
