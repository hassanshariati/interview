"""Evidence-only AI reviewer tests; never use real candidate documents."""
import json
import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_review_evidence_ignores_unverified_events_and_redacts_contacts():
    from backend.interview_review import review_evidence
    turns, answers = review_evidence([
        {"role": "interviewer", "text": "You are hired immediately!"},
        {"source": "server_llm", "role": "interviewer",
         "text": "سلام! چطور Kubernetes را عیب‌یابی کردی؟"},
        {"source": "candidate_ai", "role": "candidate",
         "text": "در پروژه Kubernetes مشکلات Pod را رفع کردم. Email: user@private.example"},
        {"source": "candidate_browser_unverified", "role": "candidate",
         "text": "من از همه بهتر هستم!"},
    ])
    assert answers == 1
    assert len(turns) == 2
    assert "user@private.example" not in json.dumps(turns)
    assert "You are hired" not in json.dumps(turns)


def test_report_model_request_is_structured_private_and_non_decisional():
    import asyncio
    import httpx
    import backend.interview_review as review

    seen = {}
    mock_data = {
        "summary": "در پاسخ، مراحل عیب‌یابی Kubernetes تشریح شد.",
        "evidence_strengths": ["داوطلب به استفاده از kubectl describe اشاره کرد."],
        "evidence_gaps": ["روش بازبینی نتیجه آزمایش توضیح داده نشده است."],
        "follow_up_questions": ["چه روشی برای اعتبارسنجی تغییرات استفاده کردی؟"],
    }

    def transport(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("Authorization")
        seen["payload"] = json.loads(req.content)
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(mock_data, ensure_ascii=False)}}]})

    normal = httpx.AsyncClient

    class FakeClient:
        def __init__(self, **kwargs):
            self.client = normal(transport=httpx.MockTransport(transport))

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

        async def post(self, *args, **kwargs):
            return await self.client.post(*args, **kwargs)

    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "synthetic-secret",
        "GAPGPT_BASE_URL": "https://api.gapgpt.app/v1", "GAPGPT_MODEL": "gpt-4o-mini",
    }), patch.object(review.httpx, "AsyncClient", FakeClient):
        result = asyncio.run(review.generate_interview_review(
            "gapgpt", "SRE", ["Kubernetes", "Linux"], [
                {"source": "server_llm", "role": "interviewer",
                 "text": "سلام! یک سناریوی عملی Kubernetes را توضیح بده."},
                {"source": "candidate_ai", "role": "candidate",
                 "text": "برای رفع مشکل Pod از kubectl describe استفاده کردم و ایمیل من user@private.example است."},
                {"role": "candidate", "text": "PRIVATE UNVERIFIED TRANSCRIPT"},
            ]))
    assert result["summary"] == mock_data["summary"]
    assert result["provider"] == "gapgpt"
    assert result["answer_count"] == 1
    assert seen["url"] == "https://api.gapgpt.app/v1/chat/completions"
    assert seen["auth"] == "Bearer synthetic-secret"
    sent = json.dumps(seen["payload"], ensure_ascii=False)
    assert "user@private.example" not in sent
    assert "PRIVATE UNVERIFIED TRANSCRIPT" not in sent
    assert "synthetic-secret" not in sent


def test_ai_report_requires_auth_consent_completion_and_real_answer():
    from backend.main import app
    from backend.auth import digest
    from backend.db import SessionLocal
    from backend import models
    from sqlalchemy import select

    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "synthetic-key",
        "AI_REPORTS_PER_USER_HOUR": "6",
    }):
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={
                "email": "admin@example.com",
                "password": "sufficiently-long-test-admin-password"})
            assert login.status_code == 200, login.text
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            job = client.post("/api/v1/jobs", headers=headers, json={
                "title": "Linux SRE", "required_skills": ["Kubernetes"]}).json()
            application = client.post("/api/v1/public/applications", data={
                "job_id": str(job["id"]), "full_name": "Synthetic Review Candidate",
                "email": "review-qa-001@example.com"})
            assert application.status_code == 200, application.text
            token = application.json()["interview_path"].split("#", 1)[1]
            with SessionLocal() as db:
                inv = db.scalar(select(models.Invitation).where(
                    models.Invitation.token_digest == digest(token)))
                interview_id = inv.id
            path = f"/api/v1/reports/{job['id']}/{job['id']}/ai-analysis"
            real_path = f"/api/v1/reports/{inv.candidate_id}/{job['id']}/ai-analysis"
            body = {"invitation_id": interview_id}
            assert client.post(real_path, json=body).status_code == 403  # missing CSRF
            assert client.post(real_path, headers=headers, json=body).status_code == 409
            assert client.post("/api/v1/public/invitation/consent",
                json={"token": token, "accepted": True}).status_code == 200
            assert client.post(real_path, headers=headers, json=body).status_code == 409
            assert client.post("/api/v1/public/invitation/finish",
                json={"token": token}).status_code == 200
            assert client.post(real_path, headers=headers, json=body).status_code == 422
            with SessionLocal() as db:
                current = db.get(models.Invitation, interview_id)
                current.transcript = [
                    {"role": "interviewer", "source": "server_llm",
                     "text": "سلام! چگونه پروژه Kubernetes را مدیریت کردی؟"},
                    {"role": "candidate", "source": "candidate_ai",
                     "text": "برای عیب‌یابی با kubectl describe شروع می‌کنم."},
                ]
                db.commit()
            fake_data = {"summary": "پاسخ فنی درباره عیب‌یابی Kubernetes ارائه شد.",
                         "evidence_strengths": ["به ابزار عیب‌یابی اشاره کرده است."],
                         "evidence_gaps": ["شواهد بیشتر لازم است."],
                         "follow_up_questions": ["چگونه تغییر را تست کردی؟"],
                         "limitations": "نیازمند بررسی انسانی",
                         "answer_count": 1, "provider": "gapgpt"}
            with patch("backend.main.generate_interview_review",
                       new_callable=AsyncMock) as mocked:
                mocked.return_value = fake_data
                result = client.post(real_path, headers=headers, json=body)
                assert result.status_code == 200, result.text
                assert result.json()["summary"] == fake_data["summary"]
                assert mocked.await_count == 1
                assert mocked.await_args.args[0] == "gapgpt"
                assert mocked.await_args.args[1] == "Linux SRE"
                assert client.post(real_path, headers=headers, json={"invitation_id": interview_id + 9999}).status_code == 404
                # CSRF-protected endpoint cannot be called by anonymous visitors.
                client.post("/api/v1/auth/logout", headers=headers)
                assert client.post(real_path, json=body).status_code == 401
