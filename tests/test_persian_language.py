"""Regression tests for Persian-only AI interviews."""
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "admin@example.com")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "sufficiently-long-test-admin-password")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("APP_ORIGIN", "http://testserver")

from backend.interview_context import build_interview_instructions
from backend.main import app
from backend.persian import is_persian_question


def test_persian_question_check():
    english = ("Hello! Thank you for joining this interview. Can you tell me about "
               "a microservices architecture project and your responsibilities?")
    persian = ("سلام! درباره پروژه‌ای که در آن معماری microservices را "
               "پیاده‌سازی کردی و مسئولیت خودت در آن توضیح بده.")
    assert not is_persian_question(english)
    assert is_persian_question(persian)
    prompt = build_interview_instructions(
        SimpleNamespace(title="Backend Engineer", required_skills=["microservices"]),
        SimpleNamespace(cv_text="Project: built Kubernetes microservices in production."))
    assert "ONLY in Persian" in prompt


def test_english_draft_is_retried_and_only_persian_is_saved():
    with patch.dict(os.environ, {
        "LLM_PROVIDER": "gapgpt", "GAPGPT_API_KEY": "synthetic-key",
    }):
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={
                "email": "admin@example.com",
                "password": "sufficiently-long-test-admin-password"})
            assert login.status_code == 200
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            job = client.post("/api/v1/jobs", headers=headers, json={
                "title": "Microservices Developer", "required_skills": ["Kubernetes"]}).json()
            application = client.post("/api/v1/public/applications", data={
                "job_id": str(job["id"]), "full_name": "Persian Interview Candidate",
                "email": "fa-language-test@example.com"})
            assert application.status_code == 200, application.text
            token = application.json()["interview_path"].split("#")[1]
            assert client.post("/api/v1/public/invitation/consent",
                json={"token": token, "accepted": True}).status_code == 200
            english = "Hello, describe a project where you implemented microservices."
            persian = "سلام! لطفاً یک پروژه معماری microservices را توضیح بده و بگو چه مسئولیت‌هایی داشتی."
            with patch("backend.main.generate_question", new_callable=AsyncMock) as mocked:
                mocked.side_effect = [english, persian]
                first = client.post("/api/v1/public/invitation/ai-turn",
                                    json={"token": token})
                assert first.status_code == 200, first.text
                assert first.json()["question"] == persian
                assert mocked.await_count == 2
            history = client.post("/api/v1/public/invitation/lookup",
                json={"token": token}).json()["ai_messages"]
            assert len(history) == 1
            assert history[0]["text"] == persian


def test_old_english_question_can_be_rewritten_without_new_turn():
    from sqlalchemy import select
    from backend.auth import digest
    from backend.db import SessionLocal
    from backend import models

    with patch.dict(os.environ, {"LLM_PROVIDER": "gapgpt",
                                 "GAPGPT_API_KEY": "synthetic-key"}):
        with TestClient(app) as client:
            login = client.post("/api/v1/auth/login", json={
                "email": "admin@example.com",
                "password": "sufficiently-long-test-admin-password"})
            headers = {"X-CSRF-Token": login.json()["csrf_token"]}
            job = client.post("/api/v1/jobs", headers=headers, json={
                "title": "Systems Architect", "required_skills": ["Linux"]}).json()
            application = client.post("/api/v1/public/applications", data={
                "job_id": str(job["id"]), "full_name": "Legacy Interview Candidate",
                "email": "fa-old-question@example.com"})
            assert application.status_code == 200
            token = application.json()["interview_path"].split("#")[1]
            assert client.post("/api/v1/public/invitation/consent",
                json={"token": token, "accepted": True}).status_code == 200
            with SessionLocal() as db:
                inv = db.scalar(select(models.Invitation).where(
                    models.Invitation.token_digest == digest(token)))
                inv.transcript = [{"role": "interviewer", "source": "server_llm",
                                   "text": "Hello! What microservices did you design?",
                                   "saved_at": 1}]
                db.commit()
            persian = "سلام! درباره معماری microservices که طراحی کردی و چالش‌های پروژه توضیح بده."
            with patch("backend.main.generate_question", new_callable=AsyncMock) as mocked:
                mocked.return_value = persian
                fixed = client.post("/api/v1/public/invitation/ai-turn",
                                    json={"token": token})
                assert fixed.status_code == 200, fixed.text
                assert fixed.json()["was_corrected"] is True
                assert fixed.json()["turn_count"] == 1
                assert mocked.await_count == 1
            again = client.post("/api/v1/public/invitation/ai-turn",
                                json={"token": token})
            assert again.json()["was_corrected"] is False
            history = client.post("/api/v1/public/invitation/lookup",
                json={"token": token}).json()["ai_messages"]
            assert len(history) == 1
            assert history[0]["text"] == persian
