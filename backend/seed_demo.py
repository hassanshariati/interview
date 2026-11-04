"""Explicit, idempotent demo-data initializer.

Run only on request: docker compose exec -T api python -m backend.seed_demo.
Never emails people, creates login accounts, or touches existing non-demo records.
All records are deliberately marked synthetic in API/UI.
"""
import json
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from . import models
from .auth import digest, now
from .db import SessionLocal
from .main import DEMO_SOURCE_FILENAME

# Demo jobs are publicly selectable, but only applicants using the public form
# create a real, private interview link.
JOBS = [
    ("[نمونه] مهندس DevOps و Kubernetes",
     "مدیریت کلاستر Kubernetes، استقرار Docker، پایش سرویس‌ها و رفع رخدادهای عملیاتی.",
     ["Kubernetes", "Docker", "Linux", "Helm", "Prometheus"]),
    ("[نمونه] توسعه‌دهنده ارشد Python / Backend",
     "طراحی API، عیب‌یابی سرویس‌های FastAPI، توسعه امن و بهینه‌سازی پایگاه داده.",
     ["Python", "FastAPI", "PostgreSQL", "Redis", "Testing"]),
    ("[نمونه] تحلیلگر داده و SQL",
     "تحلیل داده‌های سازمانی، ساخت داشبورد و استخراج بینش قابل استناد.",
     ["SQL", "Python", "Power BI", "ETL", "Data Analysis"]),
    ("[نمونه] کارشناس امنیت شبکه",
     "تحلیل رویدادهای امنیتی، مدیریت فایروال و رسیدگی به رخدادهای زیرساخت.",
     ["Network Security", "Linux", "SIEM", "Firewall", "Incident Response"]),
    ("[نمونه] مهندس هوش مصنوعی",
     "طراحی سامانه‌های هوش مصنوعی، ارزیابی خروجی مدل و پیاده‌سازی RAG.",
     ["AI", "LLM", "Python", "RAG", "Evaluation"]),
    ("[نمونه] طراح محصول و UI/UX",
     "طراحی تجربه کاربری، نمونه‌سازی و اعتبارسنجی راهکارها با کاربر.",
     ["UI", "UX", "Figma", "Design Systems", "Accessibility"]),
    ("[نمونه] کارشناس مالی و حسابداری",
     "تهیه گزارش مالی، کنترل اسناد و تطبیق حساب‌ها با رویه‌های سازمانی.",
     ["Accounting", "Excel", "Finance", "Budgeting", "Reporting"]),
    ("[نمونه] کارشناس منابع انسانی",
     "برنامه‌ریزی جذب، طراحی مصاحبه ساختاریافته و هماهنگی ارتباط با داوطلبان.",
     ["HR", "Recruitment", "Interview Design", "Communication"]),
    ("[نمونه] مدیر محصول نرم‌افزار",
     "اولویت‌بندی نیازمندی‌ها، طراحی نقشه راه و ارتباط با ذی‌نفعان فنی.",
     ["Product Management", "Agile", "Roadmap", "Stakeholders"]),
    ("[نمونه] کارشناس فروش و بازاریابی دیجیتال",
     "تحلیل کانال‌های جذب، اجرای کمپین و پیگیری شاخص‌های فروش.",
     ["Marketing", "Sales", "SEO", "CRM", "Analytics"]),
]

# All names and email addresses are fictitious. .invalid is not a real mail domain.
PEOPLE = [
    ("داوطلب آزمایشی شماره ۱", "demo-candidate-01@example.invalid", 0, "finished",
     ["بررسی رخدادهای Kubernetes", "عیب‌یابی سرویس لینوکس"], [3, 2]),
    ("داوطلب آزمایشی شماره ۲", "demo-candidate-02@example.invalid", 1, "finished",
     ["طراحی API امن", "مدیریت تراکنش دیتابیس"], [4, 3]),
    ("داوطلب آزمایشی شماره ۳", "demo-candidate-03@example.invalid", 2, "finished",
     ["تحلیل SQL", "طراحی داشبورد"], [3, 3]),
    ("داوطلب آزمایشی شماره ۴", "demo-candidate-04@example.invalid", 3, "confirmed",
     [], []),
    ("داوطلب آزمایشی شماره ۵", "demo-candidate-05@example.invalid", 5, "pending",
     [], []),
]


def seed(db):
    """Insert missing demo records only. Safe to call repeatedly."""
    created = {"jobs": 0, "candidates": 0, "interviews": 0, "mock_ratings": 0}
    job_rows = []
    for title, description, skills in JOBS:
        job = db.scalar(select(models.Job).where(models.Job.title == title))
        if job is None:
            job = models.Job(title=title, description="آزمایشی — " + description, required_skills=skills)
            db.add(job)
            db.flush()
            created["jobs"] += 1
        job_rows.append(job)

    # Distinct synthetic applicant identities cannot clash with real emails.
    for i, (name, email, job_index, status, competencies, scores) in enumerate(PEOPLE):
        candidate = db.scalar(select(models.Candidate).where(
            models.Candidate.email == email, models.Candidate.source_filename == DEMO_SOURCE_FILENAME))
        if candidate is None:
            candidate = models.Candidate(
                full_name="[نمونه] " + name, email=email,
                source_filename=DEMO_SOURCE_FILENAME,
                cv_text="نمونه مصنوعی رزومه برای نمایش داشبورد؛ فاقد اطلاعات واقعی شخص.",
                job_families=[])
            db.add(candidate)
            db.flush()
            created["candidates"] += 1

        job_id = job_rows[job_index].id
        invitation = db.scalar(select(models.Invitation).where(
            models.Invitation.candidate_id == candidate.id,
            models.Invitation.job_id == job_id,
            models.Invitation.email_status == "demo"))
        if invitation is None:
            age_days = 9 - i * 2
            started = now() - age_days * 86400
            slot = (datetime.now(timezone.utc) +
                    (timedelta(days=1) if status != "finished" else -timedelta(days=age_days))).isoformat()
            lines = (
                [{"role": "interviewer",
                  "text": "[گفت‌وگوی مصنوعی] برای رفع مشکل Pod در Kubernetes چه می‌کنید؟",
                  "saved_at": started},
                 {"role": "candidate",
                  "text": "[پاسخ ساختگی] ابتدا لاگ، رویدادهای Pod و منابع مصرفی را بررسی می‌کنم.",
                  "saved_at": started}] if status == "finished" else []
            )
            invitation = models.Invitation(
                candidate_id=candidate.id, job_id=job_id,
                token_digest=digest(secrets.token_urlsafe(48)),
                slots=[slot], selected_slot=slot if status != "pending" else None,
                status=status, created_at=started, expires_at=now() + 30 * 86400,
                email_status="demo", consent_at=None, voice_sessions=0,
                transcript=lines, finished_at=started if status == "finished" else None)
            db.add(invitation)
            db.flush()
            created["interviews"] += 1

        # Sample rubric scores are not real reviewer judgments. API keeps these
        # outside "human_assessments" analytics, in "demo_competencies".
        for competency, score in zip(competencies, scores):
            has_score = db.scalar(select(models.Assessment.id).where(
                models.Assessment.candidate_id == candidate.id,
                models.Assessment.job_id == job_id,
                models.Assessment.competency == competency))
            if has_score is None:
                db.add(models.Assessment(
                    candidate_id=candidate.id, job_id=job_id,
                    competency=competency, score=score,
                    observed_answer="[متن ساختگی] پاسخ صرفاً برای تست نمودارها تولید شده است.",
                    reviewer_notes="[نمونه مصنوعی] این امتیاز توسط کارشناس ثبت نشده است."))
                created["mock_ratings"] += 1

    db.commit()
    return created


def main():
    with SessionLocal() as db:
        result = seed(db)
    print("DEMO_SEED_RESULT=" + json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
