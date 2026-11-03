"""Exercise authentication and the complete browser invitation workflow."""
import base64
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

_TMP = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(_TMP.name) / "test.sqlite3")
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.com"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "sufficiently-long-test-admin-password"
os.environ["COOKIE_SECURE"] = "false"
os.environ["APP_ORIGIN"] = "http://testserver"
os.environ["ENABLE_REALTIME"] = "false"

from backend.main import app  # noqa: E402


def test_auth_cv_invite_report_end_to_end():
    with TestClient(app) as client:
        assert client.get("/api/v1/jobs").status_code == 401
        login = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "sufficiently-long-test-admin-password"})
        assert login.status_code == 200, login.text
        assert "httponly" in login.headers["set-cookie"].lower()
        assert "samesite=strict" in login.headers["set-cookie"].lower()
        csrf = login.json()["csrf_token"]
        assert client.get("/api/v1/auth/me").json()["email"] == "admin@example.com"
        created_user = client.post("/api/v1/admin/users", headers={"X-CSRF-Token": csrf}, json={
            "email": "recruiter@example.com", "password": "another-long-recruiter-password", "role": "recruiter"})
        assert created_user.status_code == 200, created_user.text
        assert len(client.get("/api/v1/admin/users").json()) == 2
        url = "/api/v1/jobs"
        job = {"title": "Senior DevOps", "required_skills": ["Linux", "Kubernetes", "Terraform"]}
        assert client.post(url, json=job).status_code == 403  # CSRF must be enforced
        headers = {"X-CSRF-Token": csrf}
        jr = client.post(url, json=job, headers=headers)
        assert jr.status_code == 200, jr.text
        job_id = jr.json()["id"]
        upload = client.post("/api/v1/candidates/upload", data={"full_name": "Sample Candidate", "email": "candidate@example.com"},
                             files={"file": ("cv.txt", b"Linux, Kubernetes and Ansible experience", "text/plain")}, headers=headers)
        assert upload.status_code == 200, upload.text
        candidate_id = upload.json()["id"]
        match = client.get(f"/api/v1/matches/{candidate_id}/{job_id}").json()
        assert len(match["mentioned_skills"]) == 2
        received = {}

        def fake_send(destination, subject, body):
            received["to"], received["subject"], received["body"] = destination, subject, body

        with patch("backend.main.send_email", side_effect=fake_send):
            times = [(datetime.now(timezone.utc) + timedelta(days=x)).isoformat() for x in (1, 2)]
            invite = client.post("/api/v1/invitations", headers=headers,
                                 json={"candidate_id": candidate_id, "job_id": job_id, "slots": times})
        assert invite.status_code == 200, invite.text
        assert invite.json()["email_status"] == "sent"
        assert "token" not in invite.json()
        token = re.search(r"/candidate/#([^\s]+)", received["body"]).group(1)
        candidate = client.post("/api/v1/public/invitation/lookup", json={"token": token})
        assert candidate.status_code == 200
        slot = candidate.json()["slots"][0]
        assert client.post("/api/v1/public/invitation/confirm", json={"token": token, "selected_slot": "2040-01-01T00:00:00+00:00"}).status_code == 422
        confirm = client.post("/api/v1/public/invitation/confirm", json={"token": token, "selected_slot": slot})
        assert confirm.status_code == 200, confirm.text
        consent = client.post("/api/v1/public/invitation/consent", json={"token": token, "accepted": True})
        assert consent.status_code == 200
        disabled = client.post("/api/v1/public/invitation/voice-secret", json={"token": token})
        assert disabled.status_code == 403  # session is not yet inside scheduled interview window
        transcript = client.post("/api/v1/public/invitation/transcript", json={"token": token, "role": "candidate", "text": "To inspect pod issues I run kubectl describe pod."})
        assert transcript.status_code == 200
        assert client.post("/api/v1/public/invitation/finish", json={"token": token}).status_code == 200
        report = client.get(f"/api/v1/reports/{candidate_id}/{job_id}").json()
        assert report["interviews"][0]["transcript_source"] == "candidate_browser_unverified"
        assert report["decision"] == "Human review required"
        logout = client.post("/api/v1/auth/logout", headers=headers)
        assert logout.status_code == 200
        assert client.get("/api/v1/jobs").status_code == 401
        basic = base64.b64encode(b"admin@example.com:sufficiently-long-test-admin-password").decode()
        assert client.get("/api/v1/jobs", headers={"Authorization": "Basic " + basic}).status_code == 200


def test_bad_origin_blocked():
    with TestClient(app) as client:
        result = client.post("/api/v1/auth/login", json={"email": "admin@example.com", "password": "x"}, headers={"Origin": "https://evil.example"})
        assert result.status_code == 403
