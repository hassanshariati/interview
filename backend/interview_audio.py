"""Optional Persian question audio and full-recording transcription services.

No audio is retained in the database or filesystem. TTS uses the remote
Microsoft Edge neural-voice service; STT uses the configured GapGPT account
and may incur extra provider costs. Both require candidate consent.
"""
import asyncio
import os
import re

import httpx
from fastapi import HTTPException

from .gapgpt import gapgpt_config

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
    """Request a final transcript of the COMPLETE recorded clip, not interim ASR."""
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
    # whisper-1 and most OpenAI-compatible gateways accept the Persian hint.
    payload = {"model": model, "response_format": "json"}
    if model == "whisper-1":
        payload["language"] = "fa"
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(70.0, connect=10.0),
            follow_redirects=False,
        ) as client:
            response = await client.post(
                base + "/audio/transcriptions",
                headers={"Authorization": "Bearer " + key},
                files={"file": (filename, audio, media)},
                data=payload,
            )
        if response.status_code in (401, 403):
            raise HTTPException(503, "کلید API برای تبدیل صوت پذیرفته نشد.")
        if response.status_code == 404:
            raise HTTPException(503, "مدل یا مسیر تبدیل صوت در حساب GapGPT فعال نیست.")
        if response.status_code in (402, 429):
            raise HTTPException(503, "سقف مصرف یا موجودی API صوتی کافی نیست.")
        if response.status_code >= 400:
            raise HTTPException(502, "GapGPT نتوانست فایل صوتی را پردازش کند.")
        result = response.json()
        text = result.get("text", "") if isinstance(result, dict) else ""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty transcript")
        return text.strip()[:6500]
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "تبدیل صدای طولانی بیش از حد زمان برد.") from exc
    except httpx.RequestError as exc:
        raise HTTPException(502, "اتصال به سرویس تبدیل صدا برقرار نشد.") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(502, "خروجی تبدیل گفتار به متن معتبر نبود.") from exc
