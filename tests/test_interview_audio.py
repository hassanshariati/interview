"""Speech regression tests: only whole recordings, no private audio saved."""
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend.main import app
from backend import models
from backend.auth import digest
from backend.db import SessionLocal
from sqlalchemy import select


def _candidate(client, suffix="audio-long"):
    login = client.post("/api/v1/auth/login", json={
        "email": "admin@example.com", "password": "sufficiently-long-test-admin-password"})
    assert login.status_code == 200, login.text
    headers = {"X-CSRF-Token": login.json()["csrf_token"]}
    job = client.post("/api/v1/jobs", headers=headers, json={
        "title": "Infrastructure Specialist", "required_skills": ["Kubernetes"]}).json()
    response = client.post("/api/v1/public/applications", data={
        "job_id": str(job["id"]), "full_name": "Synthetic Audio Test Candidate",
        "email": suffix+"@example.com"})
    assert response.status_code == 200, response.text
    token = response.json()["interview_path"].split("#")[1]
    return token


def test_audio_routes_restricted_to_consented_interviews_and_server_questions():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "synthetic-test-only",
        "GAPGPT_STT_ENABLED": "true", "PERSIAN_TTS_ENABLED": "true",
    }):
        with TestClient(app) as client:
            token = _candidate(client, "full-audio-test")
            blob = b"x" * 3500
            path = "/api/v1/public/invitation/transcribe-audio"
            def upload(data):
                return client.post(path, data={"token": token},
                    files={"file": ("answer.webm", data, "audio/webm")})
            assert upload(blob).status_code == 403
            assert client.post("/api/v1/public/invitation/persian-speech",
                json={"token": token}).status_code == 403
            assert client.post("/api/v1/public/invitation/consent",
                json={"token": token, "accepted": True}).status_code == 200
            assert upload(blob).status_code == 409
            assert client.post("/api/v1/public/invitation/persian-speech",
                json={"token": token}).status_code == 409

            question = "سلام! در پروژه Kubernetes چطور مشکل سرویس را مرحله‌به‌مرحله عیب‌یابی کردی؟"
            with SessionLocal() as db:
                inv = db.scalar(select(models.Invitation).where(
                    models.Invitation.token_digest == digest(token)))
                inv.transcript = [{"role": "interviewer", "source": "server_llm", "text": question}]
                db.commit()
            with patch("backend.main.persian_question_mp3",
                       new_callable=AsyncMock) as voice:
                voice.return_value = b"mp3" * 120
                speech = client.post("/api/v1/public/invitation/persian-speech",
                                     json={"token": token})
                assert speech.status_code == 200, speech.text
                assert speech.headers["content-type"].startswith("audio/mpeg")
                assert voice.await_args.args[0] == question
            answer = "من برای بررسی خطا، لاگ‌ها و وضعیت Pod را کنترل کردم. " * 85
            with patch("backend.main.gapgpt_transcribe_audio",
                       new_callable=AsyncMock) as stt:
                stt.return_value = answer
                text = upload(blob)
                assert text.status_code == 200, text.text
                assert text.json()["text"] == answer
                assert stt.await_args.args[0] == blob
                assert stt.await_args.args[1] == "audio/webm"
            with SessionLocal() as db:
                inv = db.scalar(select(models.Invitation).where(
                    models.Invitation.token_digest == digest(token)))
                assert len(inv.transcript) == 1
                assert answer not in str(inv.transcript)
            assert upload(b"x" * 50).status_code == 422
            oversized = upload(b"x" * (8*1024*1024 + 200))
            assert oversized.status_code == 413


def test_gapgpt_audio_adapter_receives_full_file_without_leaking_credentials():
    import backend.interview_audio as audio
    import json

    seen = {}
    def transport(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = request.content
        seen["content_type"] = request.headers.get("content-type")
        return httpx.Response(200, json={"text": "من یک پاسخ کامل درباره Kubernetes ارائه کردم."})
    original = httpx.AsyncClient
    class FakeClient:
        def __init__(self, **kwargs):
            self.client = original(transport=httpx.MockTransport(transport))
        async def __aenter__(self):
            return await self.client.__aenter__()
        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)
        async def post(self, *args, **kwargs):
            return await self.client.post(*args, **kwargs)
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "test-private-secret",
        "GAPGPT_BASE_URL": "https://api.gapgpt.app/v1",
        "GAPGPT_STT_MODEL": "whisper-1"
    }), patch.object(audio.httpx, "AsyncClient", FakeClient):
        clip=b"x" * 6000
        result=asyncio.run(audio.gapgpt_transcribe_audio(clip,"audio/webm;codecs=opus"))
    assert "Kubernetes" in result
    assert seen["url"] == "https://api.gapgpt.app/v1/audio/transcriptions"
    assert seen["authorization"] == "Bearer test-private-secret"
    assert b"whisper-1" in seen["body"]
    assert b"answer.webm" in seen["body"]
    assert clip in seen["body"]
    assert b"test-private-secret" not in seen["body"]


def test_persian_voice_produces_audio_without_browser_voice_installation():
    import backend.interview_audio as audio
    called = {}
    class Speaker:
        def __init__(self,text,voice,rate):
            called.update({"text":text,"voice":voice,"rate":rate})
        async def stream(self):
            yield {"type":"WordBoundary","text":"سلام"}
            yield {"type":"audio","data":b"x"*500}
            yield {"type":"audio","data":b"y"*400}
    with patch.dict(sys.modules, {"edge_tts":SimpleNamespace(Communicate=Speaker)}), patch.dict(
        os.environ, {"PERSIAN_TTS_ENABLED":"true", "PERSIAN_TTS_VOICE":"fa-IR-DilaraNeural"}
    ):
        data=asyncio.run(audio.persian_question_mp3("سلام! درباره تجربه خودت توضیح بده."))
    assert data == b"x"*500+b"y"*400
    assert called["voice"] == "fa-IR-DilaraNeural"
    assert called["rate"] == "-6%"
    assert called["text"].startswith("سلام!")


def test_candidate_can_submit_untruncated_long_transcript_after_review():
    """A reviewed Persian answer above 2000 characters reaches the LLM and DB intact."""
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "synthetic-test-only",
    }):
        with TestClient(app) as client:
            token = _candidate(client, "long-verified-voice")
            assert client.post("/api/v1/public/invitation/consent",
                json={"token": token, "accepted": True}).status_code == 200
            with SessionLocal() as db:
                inv = db.scalar(select(models.Invitation).where(
                    models.Invitation.token_digest == digest(token)))
                inv.transcript = [{
                    "role": "interviewer", "source": "server_llm",
                    "text": "سلام! در پروژه Kubernetes چه وظایفی داشتی؟"
                }]
                inv_id = inv.id
                db.commit()
            answer = ("برای عیب‌یابی کلاستر ابتدا وضعیت نودها و لاگ‌ها را بررسی کردم. " * 55).strip()
            assert 2000 < len(answer) <= 6500
            with patch("backend.main.generate_persian_question",
                       new_callable=AsyncMock) as mock:
                mock.return_value = "سلام! پس از رفع خطا چطور نتیجه را آزمایش کردی؟"
                result = client.post("/api/v1/public/invitation/ai-turn",
                                     json={"token": token, "text": answer})
                assert result.status_code == 200, result.text
                assert mock.await_args.args[2] == answer
            with SessionLocal() as db:
                inv = db.get(models.Invitation, inv_id)
                recorded = [event for event in inv.transcript
                            if event.get("source") == "candidate_ai"]
                assert len(recorded) == 1
                assert recorded[0]["text"] == answer
