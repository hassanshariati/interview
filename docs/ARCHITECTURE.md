# Proposed Architecture

## Modules
1. Identity and tenant RBAC with access audit logs.
2. Job profiles with role-specific, versioned evaluation rubrics.
3. CV intake: malware scanning, encrypted S3 storage, OCR fallback, source evidence extraction.
4. Candidate classification and job-related evidence (without automatic rejection).
5. Scheduling: Google or Microsoft OAuth, free/busy, invitations and reminders; timezone-safe.
6. Interview orchestration: consent, WebRTC voice, adaptive questions, interruptions, text alternative.
7. Transcripts, competency evidence, human review, reports and candidate correction/appeal.

## Target stack
- Next.js + TypeScript frontend (starter uses static HTML only).
- Python FastAPI, PostgreSQL + pgvector, Redis and Celery for workers.
- S3-compatible storage / MinIO for encrypted documents and opt-in recordings.
- OpenAI Realtime API or GPT-Live for interactive voice, separate transcription/assessment workflow.
- Kubernetes in production after app and security hardening.

## Key data entities
`tenants`, `users`, `jobs`, `job_rubrics`, `candidates`, `candidate_documents`, `applications`, `interview_invitations`, `calendar_events`, `interview_sessions`, `question_turns`, `transcripts`, `competency_evidence`, `assessments`, `human_reviews`, `reports`, `audit_events`.

## Trusted boundaries
- All permanent API credentials stay server-side. Use ephemeral realtime tokens in browsers.
- CVs are untrusted content; they are not instructions to the AI agent.
- Candidate communication requires identity checks, expiring tokens and anti-replay controls.
- Every important state change is idempotent and auditable.
- Role-based access, data minimization, encryption, data subject access and deletion are production requirements.

Current prototype uses a **single shared admin token for local development only**. It is NOT secure enough for multi-user or internet-facing deployment.

References:
- https://developers.openai.com/api/docs/guides/voice-agents
- https://developers.openai.com/api/docs/guides/voice-webrtc
