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
    accepted = {
        "audio/webm": "answer.webm",
        "audio/ogg": "answer.ogg",
        "audio/mp4": "answer.mp4",
        "audio/wav": "answer.wav",
    }
    media = mime.split(";", 1)[0].lower().strip()
    filename = accepted.get(media)
    if not filename:
        raise HTTPException(422, "قالب فایل صدا پشتیبانی نمی‌شود.")
    payload = {"model": model, "response_format": "json"}
    if model == "whisper-1":
        payload["language"] = "fa"

    attempts = max(1, min(2, int(os.getenv("GAPGPT_STT_MAX_ATTEMPTS", "2"))))
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(55.0, connect=10.0), follow_redirects=False
        ) as client:
            for attempt in range(attempts):
                try:
                    response = await client.post(
                        base + "/audio/transcriptions",
                        headers={"Authorization": "Bearer " + key},
                        files={"file": (filename, audio, media)},
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
                    raise HTTPException(422, "سرویس تبدیل گفتار فایل صوتی را نپذیرفت "
                                        + "(کد " + str(status) + "). فایل را دوباره ضبط کن.")
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
