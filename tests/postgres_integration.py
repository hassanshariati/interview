"""Run against a disposable PostgreSQL 17 CI service (not SQLite)."""
import os

os.environ.setdefault("BOOTSTRAP_ADMIN_EMAIL", "qa-admin@example.com")
os.environ.setdefault("BOOTSTRAP_ADMIN_PASSWORD", "test-password-strong-enough")
os.environ.setdefault("APP_ORIGIN", "http://testserver")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ENABLE_REALTIME", "false")

from fastapi.testclient import TestClient
from sqlalchemy import select
from backend import models
from backend.db import SessionLocal
from backend.main import app

with TestClient(app) as client:
    job = models.Job(
        title="Test PostgreSQL CV storage",
        description="CI-only",
        required_skills=["Kubernetes", "PostgreSQL"],
    )
    with SessionLocal() as db:
        db.add(job)
        db.commit()
        job_id = job.id

    for i, resume in enumerate((
        b"Project: PostgreSQL migration and Kubernetes autoscaling.\x00",
        "تجربه Kubernetes و پروژه PostgreSQL\x00".encode("utf-8"),
    )):
        response = client.post(
            "/api/v1/public/applications",
            data={
                "job_id": str(job_id),
                "full_name": "Test\x00 Applicant",
                "email": f"pgcv-test-{i}@example.com",
            },
            files={"file": ("resume.txt", resume, "text/plain")},
        )
        assert response.status_code == 200, response.text
        token = response.json()["interview_path"].split("#")[1]
        lookup = client.post("/api/v1/public/invitation/lookup", json={"token": token})
        assert lookup.status_code == 200, lookup.text
        assert lookup.json()["cv_received"] is True

    with SessionLocal() as db:
        candidates = db.scalars(select(models.Candidate).where(
            models.Candidate.email.like("pgcv-test-%@example.com")
        )).all()
        assert len(candidates) == 2
        assert all("\x00" not in c.cv_text and "\x00" not in c.full_name for c in candidates)

print("PostgreSQL CV registration with NUL-containing resumes: PASS")
