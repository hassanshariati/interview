# Public job portal + management dashboard

The two experiences share the existing FastAPI service and PostgreSQL database, but have separate routes, interfaces and access controls:

- \`/\` — public, searchable jobs, category filters and optional CV intake
- \`/candidate/#<private-token>\` — dedicated AI voice / accessible text interview
- \`/admin\` — separate sign-in, jobs, candidates, interview overview, human scoring and reports

No second host or additional container is required. The existing Docker Compose and nginx reverse proxy route all three pages to FastAPI. The admin API requires cookie authentication, a valid session and CSRF protection for writes.

## How it works

An administrator creates a job under \`/admin\`. It is shown in \`GET /api/v1/public/jobs\`, where the field/category is inferred from the title and required skills. Self-service applications POST multipart fields (\`job_id\`, \`full_name\`, \`email\`, optional \`file\`) to \`/api/v1/public/applications\`. The API creates a candidate and a short-lived (two-hour), already-confirmed interview and returns a fragment-only link. The applicant is redirected to the separate interview page; microphone access and transcript storage require explicit consent.

Existing invitation-based, scheduled interviews continue to function. The API provides \`/api/v1/admin/analytics\` using actual database counts, interview status and **human-entered** assessment scores only. It does not infer competence, stress, honesty or emotional state from speech. Transcripts received from the applicant browser are unverified and need human review.

## Production readiness

1. Run \`docker compose up -d --build\` after merging, or use the existing manual GitHub Action once the branch is merged into main. Health check: \`/api/v1/health\`.
2. Set \`APP_ORIGIN=https://interview.armember.ir\` and \`COOKIE_SECURE=true\` in \`.env\` when hosted behind HTTPS. Never expose the container's internal API directly without TLS / reverse proxy.
3. Configure \`OPENAI_API_KEY\` and \`ENABLE_REALTIME=true\` only after controls for spending, identity validation and abuse are ready. Voice remains unavailable when disabled; text answers can still be submitted by an applicant.
4. Set \`PUBLIC_APPLICATIONS_PER_HOUR\` (default 20). There is also a per-email limit of three self-service applications per 24 hours. These are **not** a substitute for trusted proxy-level rate limits, CAPTCHA, email verification, bot controls and cost monitoring; self-service currently does **not verify email ownership**.
5. If externally publishing, implement email confirmation before issuing paid AI session tokens, retention/deletion controls, privacy notice, and staff review workflows. Do not use an automated hiring rejection based on this MVP.
6. The UI prioritizes the locally installed licensed \`B Yekan\` font, with Google-hosted Vazirmatn and Tahoma as fallbacks. Supply a properly licensed self-hosted font if offline / exact B-Yekan rendering is required.
7. Job categories are inferred for now; if staff need editable categories or vacancy state, add explicit model fields through an Alembic migration rather than calling SQLAlchemy \`create_all()\` on an already populated database.

The design is an original Jobpply-inspired implementation, not a direct copy of Colorlib template assets. 

## Manager notifications

After the applicant finishes, the interview remains stored even if notification delivery fails. The server sends an alert containing IDs, applicant name, job title and the authenticated \`/admin\` page; it does **not** send transcripts or audio to the webhook or via email.

- For n8n: set \`N8N_REPORT_WEBHOOK_URL\` to an HTTPS webhook endpoint and \`N8N_REPORT_WEBHOOK_SECRET\` to a strong, random 16+ character bearer token, and configure the n8n Webhook node to check the matching \`Authorization: Bearer ...\` header. Handle the alert in n8n and forward it to your management distribution list.
- For basic SMTP fallback: leave the n8n URL unset and set \`MANAGER_REPORT_EMAIL\` plus the existing \`SMTP_*\` settings.
- Both are optional: the finish endpoint's \`notification_status\` can be \`sent\`, \`failed\` or \`not_configured\`. Failure doesn't undo an interview. Reliable delivery with retries/outbox is future production work.

The charted competency scores remain human-entered, not automatically inferred from voice.