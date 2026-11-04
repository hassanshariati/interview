"""Interview MVP HTTP API. Do not infer stress or emotions in hiring."""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter, defaultdict
from urllib.parse import urlparse
import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from . import models
from .auth import SESSION_COOKIE, bootstrap_admin, check_credentials, digest, login_rate_limit, new_session, now, ph, require_admin, session_for_request
from .cv_parser import MAX_BYTES, parse_cv
from .db import Base, engine, get_db
from .emailer import send_email
from .matching import classify, match_job

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
APP_ORIGIN = os.getenv("APP_ORIGIN", "https://interview.armember.ir").rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)  # MVP only. Use Alembic before schema upgrades.
    bootstrap_admin()
    yield


app = FastAPI(title="Interview AI", version="0.3.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")


@app.middleware("http")
async def protect_requests(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != APP_ORIGIN:
            return Response("Origin not allowed", status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


class UserIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=14, max_length=256)
    role: str = Field(pattern="^(admin|recruiter)$")


class JobIn(BaseModel):
    title: str = Field(min_length=3, max_length=180)
    description: str = Field(default="", max_length=20000)
    required_skills: list[str] = Field(min_length=1, max_length=60)


class AssessmentIn(BaseModel):
    candidate_id: int
    job_id: int
    competency: str = Field(min_length=2, max_length=180)
    score: int = Field(ge=0, le=4)
    observed_answer: str = Field(min_length=5, max_length=10000)
    reviewer_notes: str = Field(default="", max_length=5000)


class InvitationIn(BaseModel):
    candidate_id: int
    job_id: int
    slots: list[datetime] = Field(min_length=1, max_length=5)


class TokenIn(BaseModel):
    token: str = Field(min_length=30, max_length=200)


class ConfirmIn(TokenIn):
    selected_slot: str = Field(min_length=15, max_length=64)


class ConsentIn(TokenIn):
    accepted: bool


class TranscriptIn(TokenIn):
    role: str
    text: str = Field(min_length=1, max_length=2000)


def audit(db, user_id, action, resource):
    db.add(models.AuditEvent(user_id=user_id, action=action, resource=resource, created_at=now()))


def get_invitation(db: Session, raw_token: str):
    invitation = db.scalar(select(models.Invitation).where(models.Invitation.token_digest == digest(raw_token)))
    if not invitation or invitation.expires_at < now():
        raise HTTPException(404, "Invitation not found or expired")
    return invitation


@app.get("/")
def home():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/admin/")
@app.get("/admin")
def admin_page():
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/candidate/")
@app.get("/candidate")
def candidate_page():
    return FileResponse(WEB_DIR / "candidate.html")


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": "0.3.0"}


@app.post("/api/v1/auth/login")
def login(payload: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    login_rate_limit((request.client.host if request.client else "unknown") + ":" + str(payload.email).lower())
    user = check_credentials(db, str(payload.email), payload.password)
    if not user:
        raise HTTPException(401, "Invalid credentials or account temporarily locked")
    token, csrf = new_session(db, user)
    response.set_cookie(SESSION_COOKIE, token, max_age=8 * 60 * 60, path="/", httponly=True,
                        secure=os.getenv("COOKIE_SECURE", "true").lower() == "true", samesite="strict")
    audit(db, user.id, "auth.login", "web")
    db.commit()
    return {"email": user.email, "role": user.role, "csrf_token": csrf}


@app.get("/api/v1/auth/me")
def whoami(request: Request, db: Session = Depends(get_db)):
    result = session_for_request(db, request)
    if not result:
        raise HTTPException(401, "Login required")
    user, session = result
    return {"email": user.email, "role": user.role, "csrf_token": session.csrf_token}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    result = session_for_request(db, request)
    if result:
        user, session = result
        if request.headers.get("x-csrf-token") != session.csrf_token:
            raise HTTPException(403, "CSRF verification failed")
        audit(db, user.id, "auth.logout", "web")
        db.delete(session)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"logged_out": True}


@app.post("/api/v1/admin/users")
def create_user(payload: UserIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    if user.role != "admin":
        raise HTTPException(403, "Admin role required")
    person = models.User(email=str(payload.email).lower(), password_hash=ph.hash(payload.password), role=payload.role)
    db.add(person)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "Account already exists") from exc
    audit(db, user.id, "user.create", str(person.id))
    db.commit()
    return {"id": person.id, "email": person.email, "role": person.role}


@app.get("/api/v1/admin/users")
def list_users(db: Session = Depends(get_db), user=Depends(require_admin)):
    if user.role != "admin":
        raise HTTPException(403, "Admin role required")
    people = db.scalars(select(models.User).order_by(models.User.id)).all()
    return [{"id": x.id, "email": x.email, "role": x.role, "is_active": x.is_active} for x in people]


@app.post("/api/v1/jobs")
def create_job(payload: JobIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    skills = list(dict.fromkeys(s.strip()[:100] for s in payload.required_skills if s.strip()))
    if not skills:
        raise HTTPException(422, "At least one required skill")
    job = models.Job(title=payload.title, description=payload.description, required_skills=skills)
    db.add(job)
    db.flush()
    audit(db, user.id, "job.create", str(job.id))
    db.commit()
    db.refresh(job)
    return {"id": job.id, "title": job.title, "required_skills": job.required_skills}


JOB_CATEGORIES = (
    ("فناوری اطلاعات", ("devops", "developer", "software", "linux", "python", "java", "cloud", "kubernetes",
                       "docker", "network", "برنامه", "شبکه", "نرم‌افزار", "امنیت", "it", "backend", "frontend")),
    ("داده و هوش مصنوعی", ("data", "ai", "machine learning", "database", "analytics", "sql", "هوش مصنوعی", "داده")),
    ("مالی و حسابداری", ("finance", "account", "bank", "financial", "حسابدار", "مالی", "بانک")),
    ("طراحی و محصول", ("design", "ui", "ux", "product", "graphic", "طراحی", "محصول")),
    ("بازاریابی و فروش", ("marketing", "sales", "growth", "بازاریاب", "فروش")),
    ("منابع انسانی و مدیریت", ("hr", "recruit", "management", "human resources", "مدیر", "منابع انسانی")),
)


def job_category(job):
    description = " ".join([job.title, *(job.required_skills or [])]).casefold()
    for label, terms in JOB_CATEGORIES:
        if any(term in description for term in terms):
            return label
    return "سایر حوزه‌ها"


def job_payload(job):
    return {"id": job.id, "title": job.title, "description": job.description or "",
            "required_skills": job.required_skills or [], "category": job_category(job)}


@app.get("/api/v1/public/jobs")
def public_jobs(q: str = Query(default="", max_length=100),
                category: str = Query(default="", max_length=100),
                db: Session = Depends(get_db)):
    """Public, non-sensitive job catalogue. No admin authentication required."""
    items = db.scalars(select(models.Job).order_by(models.Job.id.desc()).limit(200)).all()
    query = q.strip().casefold()
    return [job_payload(j) for j in items
            if (not category or job_category(j) == category)
            and (not query or query in " ".join([j.title, j.description or "", *(j.required_skills or [])]).casefold())]


@app.post("/api/v1/public/applications")
async def self_apply(job_id: int = Form(gt=0), full_name: str = Form(min_length=2, max_length=180),
                     email: EmailStr = Form(), file: UploadFile | None = File(default=None),
                     db: Session = Depends(get_db)):
    """Create a short-lived, applicant-owned interview entry. Never expose admin data."""
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    normalized_email = str(email).strip().lower()
    last_day = datetime.now(timezone.utc) - timedelta(hours=24)
    # Database-backed hourly ceiling: protects paid Realtime provisioning even if
    # a hostile client rotates email addresses (proxy-level limits are also advised).
    hourly_cap = max(1, min(200, int(os.getenv("PUBLIC_APPLICATIONS_PER_HOUR", "20"))))
    attempts = db.scalars(select(models.AuditEvent.id).where(
        models.AuditEvent.action == "application.self_start",
        models.AuditEvent.created_at >= now() - 3600).limit(hourly_cap)).all()
    if len(attempts) >= hourly_cap:
        raise HTTPException(429, "Public interview capacity reached; please retry later")
    recent = db.scalars(select(models.Candidate.id).where(
        models.Candidate.email == normalized_email, models.Candidate.created_at >= last_day).limit(3)).all()
    if len(recent) >= 3:
        raise HTTPException(429, "Too many applications for this email in the past 24 hours")
    cv_text, filename = "", ""
    if file and file.filename:
        data = await file.read(MAX_BYTES + 1)
        try:
            cv_text = parse_cv(file.filename, data)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(422, "Cannot parse document") from exc
        filename = Path(file.filename).name[:255]
    candidate = models.Candidate(full_name=full_name.strip(), email=normalized_email, source_filename=filename,
                                 cv_text=cv_text, job_families=classify(cv_text) if cv_text else [])
    db.add(candidate)
    db.flush()
    token = secrets.token_urlsafe(48)
    current = datetime.now(timezone.utc).isoformat()
    inv = models.Invitation(candidate_id=candidate.id, job_id=job.id, token_digest=digest(token),
                            slots=[current], selected_slot=current, status="confirmed",
                            expires_at=now() + 2 * 60 * 60, created_at=now())
    db.add(inv)
    db.flush()
    audit(db, None, "application.self_start", str(inv.id))
    db.commit()
    # Token is in a fragment, never the HTTP path or query; it grants access to this interview only.
    return {"interview_path": "/candidate/#" + token, "job_title": job.title,
            "expires_in_seconds": 7200, "note": "This link is private; your email has not been verified."}


@app.get("/api/v1/jobs")
def list_jobs(db: Session = Depends(get_db), user=Depends(require_admin)):
    items = db.scalars(select(models.Job).order_by(models.Job.id.desc())).all()
    return [job_payload(j) for j in items]


@app.post("/api/v1/candidates/upload")
async def upload_cv(full_name: str = Form(min_length=2, max_length=180), email: EmailStr = Form(),
                    file: UploadFile = File(), db: Session = Depends(get_db), user=Depends(require_admin)):
    data = await file.read(MAX_BYTES + 1)
    try:
        text = parse_cv(file.filename or "", data)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(422, "Cannot parse document") from exc
    families = classify(text)
    candidate = models.Candidate(full_name=full_name, email=str(email), source_filename=Path(file.filename or "cv").name[:255],
                                 cv_text=text, job_families=families)
    db.add(candidate)
    db.flush()
    audit(db, user.id, "candidate.upload", str(candidate.id))
    db.commit()
    db.refresh(candidate)
    return {"id": candidate.id, "full_name": candidate.full_name, "job_families": families, "extracted_characters": len(text)}


@app.get("/api/v1/candidates")
def list_candidates(db: Session = Depends(get_db), user=Depends(require_admin)):
    items = db.scalars(select(models.Candidate).order_by(models.Candidate.id.desc())).all()
    return [{"id": c.id, "full_name": c.full_name, "email": c.email, "job_families": c.job_families} for c in items]


@app.get("/api/v1/matches/{candidate_id}/{job_id}")
def candidate_match(candidate_id: int, job_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    c, j = db.get(models.Candidate, candidate_id), db.get(models.Job, job_id)
    if not c or not j:
        raise HTTPException(404, "Candidate or job not found")
    return {"candidate_id": c.id, "job_id": j.id, **match_job(c.cv_text, j.required_skills)}


@app.post("/api/v1/assessments")
def add_review(payload: AssessmentIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    if not db.get(models.Candidate, payload.candidate_id) or not db.get(models.Job, payload.job_id):
        raise HTTPException(404, "Candidate or job not found")
    item = models.Assessment(**payload.model_dump())
    db.add(item)
    db.flush()
    audit(db, user.id, "assessment.add", str(item.id))
    db.commit()
    return {"id": item.id, "saved": True}


@app.get("/api/v1/admin/analytics")
def analytics(db: Session = Depends(get_db), user=Depends(require_admin)):
    """Management charts contain only actual submissions and human rubric ratings."""
    jobs = db.scalars(select(models.Job).order_by(models.Job.id.desc())).all()
    candidates = db.scalars(select(models.Candidate).order_by(models.Candidate.id.desc())).all()
    meetings = db.scalars(select(models.Invitation).order_by(models.Invitation.id.desc())).all()
    assessments = db.scalars(select(models.Assessment).order_by(models.Assessment.id.desc())).all()
    by_job = Counter(m.job_id for m in meetings)
    statuses = Counter(m.status for m in meetings)
    activity = Counter(datetime.fromtimestamp(m.created_at, tz=timezone.utc).date().isoformat() for m in meetings)
    scored = defaultdict(list)
    ratings_by_pair = Counter()
    for a in assessments:
        scored[a.competency].append(a.score)
        ratings_by_pair[(a.candidate_id, a.job_id)] += 1
    names = {c.id: c.full_name for c in candidates}
    titles = {j.id: j.title for j in jobs}
    today = datetime.now(timezone.utc).date()
    trend = [(today - timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
    return {
        "counts": {"jobs": len(jobs), "candidates": len(candidates),
                   "interviews": len(meetings), "finished": statuses["finished"],
                   "assessments": len(assessments)},
        "statuses": [{"name": key, "value": statuses[key]} for key in ("pending", "confirmed", "finished")],
        "by_job": [{"job_id": j.id, "name": j.title, "count": by_job[j.id]} for j in jobs],
        "activity": [{"day": day, "count": activity[day]} for day in trend],
        "competencies": [{"name": key, "average": round(sum(values) / len(values), 2),
                           "count": len(values)} for key, values in sorted(scored.items())],
        "recent": [{"id": m.id, "candidate_id": m.candidate_id, "job_id": m.job_id,
                    "candidate": names.get(m.candidate_id, "—"), "job": titles.get(m.job_id, "—"),
                    "status": m.status, "created_at": m.created_at,
                    "human_ratings": ratings_by_pair[(m.candidate_id, m.job_id)]}
                   for m in meetings[:50]],
        "rating_note": "Scores (0-4) are entered by human reviewers. Missing evaluations are unscored."
    }


@app.get("/api/v1/reports/{candidate_id}/{job_id}")
def report(candidate_id: int, job_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    c, j = db.get(models.Candidate, candidate_id), db.get(models.Job, job_id)
    if not c or not j:
        raise HTTPException(404, "Candidate or job not found")
    reviews = db.scalars(select(models.Assessment).where(models.Assessment.candidate_id == candidate_id,
                           models.Assessment.job_id == job_id).order_by(models.Assessment.id)).all()
    meetings = db.scalars(select(models.Invitation).where(models.Invitation.candidate_id == candidate_id,
                            models.Invitation.job_id == job_id).order_by(models.Invitation.id.desc())).all()
    return {
        "candidate": c.full_name, "job": j.title, "cv_evidence": match_job(c.cv_text, j.required_skills),
        "human_assessments": [{"competency": a.competency, "score": a.score, "observed_answer": a.observed_answer,
                                "reviewer_notes": a.reviewer_notes} for a in reviews],
        "interviews": [{"id": m.id, "status": m.status, "slot": m.selected_slot,
                        "transcript": m.transcript, "transcript_source": "candidate_browser_unverified"} for m in meetings],
        "decision": "Human review required", "automated_rejection": False,
        "note": "Client-submitted transcripts are not independently verified; no automatic hiring assessment is performed."
    }


@app.post("/api/v1/invitations")
def create_invitation(payload: InvitationIn, db: Session = Depends(get_db), user=Depends(require_admin)):
    candidate = db.get(models.Candidate, payload.candidate_id)
    job = db.get(models.Job, payload.job_id)
    if not candidate or not job:
        raise HTTPException(404, "Candidate or job not found")
    future = datetime.now(timezone.utc) + timedelta(minutes=30)
    if any(s.tzinfo is None or s.utcoffset() is None or s.astimezone(timezone.utc) <= future for s in payload.slots):
        raise HTTPException(422, "All slots must include timezone offsets and be at least 30 minutes in the future")
    slots = list(dict.fromkeys(s.astimezone(timezone.utc).isoformat() for s in payload.slots))
    token = secrets.token_urlsafe(48)
    ttl = max(1, min(60, int(os.getenv("INVITATION_TTL_DAYS", "30"))))
    inv = models.Invitation(candidate_id=candidate.id, job_id=job.id, token_digest=digest(token), slots=slots,
                            status="pending", expires_at=now() + ttl * 86400, created_at=now())
    db.add(inv)
    db.flush()
    audit(db, user.id, "invite.create", str(inv.id))
    db.commit()
    link = APP_ORIGIN + "/candidate/#" + token  # hash fragment never reaches HTTP server logs / referrer
    message = (f"Hello {candidate.full_name},\n\nYou are invited to an interview for {job.title}.\n"
               "Please open the private link to choose one of the proposed times (shown in your local timezone):\n"
               f"{link}\n\nDo not share this link. It expires after {ttl} days.\n")
    try:
        send_email(candidate.email, f"Interview invitation — {job.title}", message)
        inv.email_status = "sent"
    except Exception:
        inv.email_status = "failed"
    db.commit()
    return {"id": inv.id, "status": inv.status, "email_status": inv.email_status,
            "note": "No invitation link is returned by the API. Configure SMTP before inviting candidates."}


@app.get("/api/v1/invitations")
def list_invitations(db: Session = Depends(get_db), user=Depends(require_admin)):
    items = db.scalars(select(models.Invitation).order_by(models.Invitation.id.desc()).limit(100)).all()
    return [{"id": i.id, "candidate_id": i.candidate_id, "job_id": i.job_id, "status": i.status,
             "email_status": i.email_status, "selected_slot": i.selected_slot, "created_at": i.created_at} for i in items]


@app.post("/api/v1/public/invitation/lookup")
def public_lookup(payload: TokenIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    c, job = db.get(models.Candidate, inv.candidate_id), db.get(models.Job, inv.job_id)
    return {"job": job.title, "candidate": c.full_name, "slots": inv.slots, "selected_slot": inv.selected_slot,
            "status": inv.status, "consent": bool(inv.consent_at), "voice_enabled": os.getenv("ENABLE_REALTIME", "false") == "true"}


@app.post("/api/v1/public/invitation/confirm")
def public_confirm(payload: ConfirmIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    if inv.status not in ("pending", "confirmed"):
        raise HTTPException(409, "Interview cannot be rescheduled")
    if payload.selected_slot not in inv.slots:
        raise HTTPException(422, "The selected slot was not offered")
    if datetime.fromisoformat(payload.selected_slot) < datetime.now(timezone.utc):
        raise HTTPException(422, "Selected slot has passed")
    inv.selected_slot = payload.selected_slot
    inv.status = "confirmed"
    db.commit()
    candidate = db.get(models.Candidate, inv.candidate_id)
    job = db.get(models.Job, inv.job_id)
    local_time = datetime.fromisoformat(inv.selected_slot).strftime("%Y-%m-%d %H:%M UTC")
    try:
        send_email(candidate.email, "Interview time confirmed — " + job.title,
                   f"Hello {candidate.full_name}, your interview for {job.title} is confirmed for {local_time}. "
                   "Use your private invitation link at the scheduled time.")
    except Exception:
        pass  # Booking remains confirmed even if the email provider is temporarily unavailable.
    return {"confirmed": True, "selected_slot": inv.selected_slot}


@app.post("/api/v1/public/invitation/consent")
def public_consent(payload: ConsentIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    if not payload.accepted:
        raise HTTPException(422, "Explicit consent is required for voice processing")
    if inv.status != "confirmed":
        raise HTTPException(409, "Choose a time first")
    inv.consent_at = now()
    db.commit()
    return {"consent": True}


async def realtime_secret(instructions: str):
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or os.getenv("ENABLE_REALTIME", "false").lower() != "true":
        raise HTTPException(503, "Realtime voice service is not enabled")
    config = {"expires_after": {"anchor": "created_at", "seconds": 90},
              "session": {"type": "realtime", "model": os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime"),
                          "instructions": instructions,
                          "audio": {"input": {"transcription": {"model": "gpt-transcribe"}}}}}
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post("https://api.openai.com/v1/realtime/client_secrets", json=config,
                                     headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            result = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Realtime provider could not create a session") from exc
    if not result.get("value"):
        raise HTTPException(502, "Voice session initialization failed")
    return {"value": result["value"], "expires_at": result.get("expires_at")}


@app.post("/api/v1/public/invitation/voice-secret")
async def candidate_voice(payload: TokenIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    if inv.status != "confirmed" or not inv.consent_at:
        raise HTTPException(403, "Select a time and accept voice processing first")
    if inv.voice_sessions >= 3:
        raise HTTPException(429, "Voice session limit reached; contact the recruiter")
    if not inv.selected_slot:
        raise HTTPException(403, "Interview time not confirmed")
    selected = datetime.fromisoformat(inv.selected_slot).astimezone(timezone.utc)
    current = datetime.now(timezone.utc)
    if not (selected - timedelta(minutes=30) <= current <= selected + timedelta(hours=2)):
        raise HTTPException(403, "Voice interview is available from 30 minutes before until 2 hours after the booked time")
    job = db.get(models.Job, inv.job_id)
    skills = ", ".join(s[:100] for s in job.required_skills[:20])
    instructions = (
        "You are an interviewer in a voluntary PRACTICE hiring interview. Speak Persian if the candidate speaks Persian, otherwise English. "
        "Ask one technical question at a time and follow up on the candidate's content; cover applied troubleshooting and scenario reasoning. "
        f"The recruiter-selected competencies are: {skills}. "
        "Do not ask about protected attributes or infer stress, emotions, honesty, health, personality or disability from voice. "
        "Do not make a hiring decision or assign a score. Kindly allow the candidate to pause or request a repeat. "
        "Aim for 10-15 minutes. Start by greeting and asking a relevant technical question."
    )
    secret = await realtime_secret(instructions)
    inv.voice_sessions += 1
    db.commit()
    return secret


@app.post("/api/v1/public/invitation/transcript")
def candidate_transcript(payload: TranscriptIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    if not inv.consent_at or inv.status != "confirmed":
        raise HTTPException(403, "Interview is not authorized")
    if payload.role not in ("candidate", "interviewer"):
        raise HTTPException(422, "Invalid role")
    existing = list(inv.transcript or [])
    if len(existing) >= 150:
        raise HTTPException(413, "Transcript event limit reached")
    existing.append({"role": payload.role, "text": payload.text, "saved_at": now()})
    inv.transcript = existing
    db.commit()
    return {"saved": True, "count": len(existing), "provenance": "candidate_browser_unverified"}



def report_ready_notification(candidate, job, invitation):
    """Best-effort manager alert without sending CV or browser-supplied transcript."""
    payload = {
        "event": "interview.finished",
        "invitation_id": invitation.id,
        "candidate_id": candidate.id,
        "candidate_name": candidate.full_name,
        "job_id": job.id,
        "job_title": job.title,
        "report_url": APP_ORIGIN + "/admin",
        "review_required": True,
    }
    webhook = os.getenv("N8N_REPORT_WEBHOOK_URL", "").strip()
    secret = os.getenv("N8N_REPORT_WEBHOOK_SECRET", "").strip()
    if webhook:
        # n8n should use header authentication and HTTPS with a private token.
        if not webhook.startswith("https://") or len(secret) < 16:
            return "not_configured"
        try:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                result = client.post(webhook, json=payload,
                                     headers={"Authorization": "Bearer " + secret})
                result.raise_for_status()
            return "sent"
        except httpx.HTTPError:
            return "failed"
    manager_email = os.getenv("MANAGER_REPORT_EMAIL", "").strip()
    if not manager_email:
        return "not_configured"
    try:
        send_email(manager_email, "Interview awaiting human review — " + job.title,
                   f"Interview completed: {candidate.full_name}\n"
                   f"Job: {job.title}\n"
                   f"Interview record: {invitation.id}\n"
                   f"Review the evidence after signing in: {APP_ORIGIN}/admin\n"
                   "This notice contains only report metadata. The interview is unscored until reviewed.")
        return "sent"
    except Exception:
        return "failed"


@app.post("/api/v1/public/invitation/finish")
def candidate_finish(payload: TokenIn, db: Session = Depends(get_db)):
    inv = get_invitation(db, payload.token)
    if inv.status != "confirmed":
        raise HTTPException(409, "Interview is not active")
    inv.status = "finished"
    inv.finished_at = now()
    db.commit()
    candidate = db.get(models.Candidate, inv.candidate_id)
    job = db.get(models.Job, inv.job_id)
    delivery = report_ready_notification(candidate, job, inv)
    return {"finished": True, "notification_status": delivery,
            "note": "The interview is subject to human evaluation."}


@app.post("/api/v1/realtime/client-secret")
async def admin_voice_demo(user=Depends(require_admin)):
    return await realtime_secret(
        "Conduct a short professional practice interview in Persian or English. Ask technical questions "
        "one at a time and do not infer emotions, honesty, stress, health, or make hiring decisions."
    )
