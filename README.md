# Interview AI — Secure-Login Recruiting MVP

**Target host:** `94.184.27.131`  
**Domain:** `https://interview.armember.ir`  
**Status:** runnable MVP, **not production-certified hiring software**.

## Implemented

- Single-organization recruiter dashboard (Persian/RTL).
- **Baseline authentication**: Argon2id password hashes, admin/recruiter roles, initial admin bootstrap, signed-in `HttpOnly` browser session (8 hours), `Secure` + `SameSite=Strict` cookies, CSRF checks, per-account login lockout and per-process/IP throttling, password reset CLI. Optional HTTP **Basic Auth** for CLI requests over **HTTPS only**.
- Admin user creation endpoint and audit records for critical recruiter actions.
- Job creation, PDF/DOCX/TXT CV extraction and skill-keyword evidence (not automated candidate ranking/rejection).
- SMTP STARTTLS candidate invitations with 1–5 proposed times, private tokenized booking page and confirmation email; times are stored in UTC and displayed in candidate's browser timezone.
- Role-specific browser voice interviewing via OpenAI Realtime WebRTC **when configured**. Short-lived voice secrets are minted server-side and candidate must explicitly consent. Session restricted to booked time window.
- Optional browser-collected transcript snippets for **human review only** (unverified client provenance). Human-entered competency scores and JSON report; no automatic hiring decision.
- Single Docker Compose stack: PostgreSQL, FastAPI and container Nginx, with only container Nginx exposed at `127.0.0.1:18080`. Optional Caddy profile for standalone HTTPS.
- Nginx HTTP validation and HTTPS reverse proxy configuration for the target domain.

## NOT yet implemented / critical limitations

- Browser transcript events can be tampered with and may be missing or inaccurate; **do not** use them as independently verified assessment evidence. A server-side Realtime sideband and review workflow are necessary for a hiring-grade transcript.
- No automatic AI scoring, voice-based stress/emotion/honesty detection, PDF report generator, OAuth calendar sync, automated reminders, bulk uploads, malware scanning or retention/deletion portal.
- Startup creates database tables but does **not** migrate schemas. Use Alembic before future migrations.
- No security audit, dedicated production monitoring, rate limiting for all public invitation endpoints, independent accessibility/fairness testing, or legal/privacy review.
- Do not upload real applicant data until those requirements are addressed and appropriate permission, retention policies and data protection measures are in place.

## Server prerequisites

- Ubuntu Linux with Docker Engine and Docker Compose plugin.
- Nginx installed **on the host**, port 80 and 443 accessible.
- `interview.armember.ir` DNS A record points to `94.184.27.131`.
- Certbot installed, reachable outbound SMTP and OpenAI API as required.
- Sufficient disk space for PostgreSQL backup/restore. Allow SSH only to trusted administrators.

## 1. Deploy with one Docker Compose stack

SSH into the target server and clone the repository (do not overwrite an existing `.env` or PostgreSQL volume):

```bash
ssh root@94.184.27.131
mkdir -p /opt/interview-ai
cd /opt
# On a new installation only:
git clone https://github.com/hassanshariati/interview.git interview-ai
cd /opt/interview-ai
python3 scripts/generate_env.py --admin-email admin@your-organization.example
chmod 600 .env
```

The default Compose file starts **three services**: `db` (private PostgreSQL), `api` (private FastAPI), and `proxy` (container Nginx on loopback port `18080`). An optional `edge` service uses Caddy for HTTPS, but is deliberately disabled by default so it cannot take over port 80/443 on a host already running Nginx.

If you are updating an existing checkout, run `git pull --ff-only` in `/opt/interview-ai` and preserve `.env` and Docker volumes.

The generator prints the **initial admin password one time**. Save it in a password manager. The `.env` contains sensitive values and must never be added to Git.

Edit `.env` to set `SMTP_HOST`, `SMTP_FROM`, `SMTP_USER`, `SMTP_PASSWORD` (the provider must support STARTTLS); to enable voice, also set `OPENAI_API_KEY` and `ENABLE_REALTIME=true`. The voice key always stays on the backend.

```bash
./scripts/deploy.sh
curl -fsS http://127.0.0.1:18080/api/v1/health
```

After the initial account has been created, **remove** the bootstrap password from `.env` and restart the API. Accounts already in the database are not reset by bootstrap values.

```bash
sudo sed -i 's/^BOOTSTRAP_ADMIN_PASSWORD=.*/BOOTSTRAP_ADMIN_PASSWORD=/' .env
sudo docker compose up -d --force-recreate api
```

If you need to reset the password without command-line exposure:

```bash
docker compose exec -it api python -m backend.admin_cli reset-password --email admin@your-organization.example
```

## 2. Configure HTTPS for interview.armember.ir

### Recommended on your multi-site server: existing host Nginx

Continue to use the host's Nginx for HTTPS, proxying to the `proxy` service on `127.0.0.1:18080`. The Docker Compose file does **not** bind ports 80/443 in this default mode. Do not install a second host Nginx or overwrite other virtual hosts.

### Alternative on an otherwise empty server: HTTPS inside Compose

**Use only if nothing else listens on 80/443** and the DNS A record is configured. This activates the optional Caddy container with automated TLS:

```bash
docker compose --profile standalone-https up -d --build --wait
```

In this mode you do not need a separate host Nginx or Certbot. To stop only the extra Caddy service, run `docker compose --profile standalone-https stop edge`. Do not enable this profile on the current host without checking `ss -lntp` for conflicts.

### Existing host Nginx / Certbot setup

**Before touching Nginx:** check for duplicate domain stanzas in `/etc/nginx/sites-enabled/` and `/etc/nginx/conf.d/`; do not replace existing site configs for other domains.

```bash
getent ahostsv4 interview.armember.ir
sudo install -d -m 755 /var/www/certbot
sudo cp deploy/nginx/00-interview-http.conf /etc/nginx/sites-available/interview.armember.ir
sudo ln -sfn /etc/nginx/sites-available/interview.armember.ir /etc/nginx/sites-enabled/interview.armember.ir
sudo nginx -t && sudo systemctl reload nginx
sudo certbot certonly --webroot -w /var/www/certbot -d interview.armember.ir
```

Once the certificate exists:

```bash
sudo cp deploy/nginx/interview.armember.ir.conf /etc/nginx/sites-available/interview.armember.ir
sudo nginx -t && sudo systemctl reload nginx
curl -I https://interview.armember.ir
```

If Nginx fails its config test, do not reload it. Inspect existing listeners and server-name conflicts first. Certificate renewal should be managed by the installed Certbot timer.

## 3. Authentication and API

Open `https://interview.armember.ir` and sign in using the initial admin email/password.

To create another account, log in as admin and use the protected API endpoint:

```text
POST /api/v1/admin/users
{"email":"recruiter@example.com","password":"choose-a-long-random-password","role":"recruiter"}
```

Browser API uses a cookie and `X-CSRF-Token` returned by `/api/v1/auth/login` or `/api/v1/auth/me` for modifying requests.

For a command-line smoke test using HTTP Basic Auth (HTTPS only):

```bash
curl -u 'admin@your-organization.example' https://interview.armember.ir/api/v1/jobs
```

This command prompts for the password rather than placing it in shell history. Do not use Basic Auth over HTTP, or log Authorization headers.

## 4. Candidate workflow

1. Admin uploads a synthetic CV, defines job competencies and selects the corresponding candidate/job.
2. Admin proposes 1–5 times and creates an invite. When SMTP is correctly configured, a private link is sent to the candidate's email address.
3. Candidate opens the link, confirms a time, reads consent information and starts voice interview within 30 minutes before to 2 hours after the selected time.
4. The browser can upload transcript snippets; the report tags them as `candidate_browser_unverified` and requires human evaluation.
5. Admin adds documented technical evaluation notes and reviews `/api/v1/reports/{candidate_id}/{job_id}`.

**Important:** ownership of an email invitation link grants candidate-level access. There is no additional identity verification. Limit exposure and add candidate auth if required by your organization.

## 5. Operational checks

```bash
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 db
docker compose logs --tail=100 proxy
sudo nginx -t
curl -fsS https://interview.armember.ir/api/v1/health
```

Example database backup (protect file permissions):

```bash
mkdir -p backups && chmod 700 backups
docker compose exec -T db pg_dump -U interview -Fc interview > "backups/interview-$(date +%F).dump"
chmod 600 backups/*.dump
```

Keep encrypted backups off-host and test restore procedures. Never commit backups or CVs.

## Tests

```bash
python3 -m pip install -r requirements.txt
pytest -q
```

Tests cover password/cookie session, CSRF, role/user creation, CV upload/matching, invitation, candidate flow, report and HTTP Basic access. End-to-end SMTP, live OpenAI, Nginx and Docker deploy must be smoke-tested with configured services.

## Important policy

Evaluate job-related knowledge from questions and answers; **do not** derive hiring outcomes from vocal tremor, stress, accent, gender, disability or inferred emotion. Human reviewer controls consequential decisions. See `docs/ASSESSMENT_AND_PRIVACY.md`.

## GitHub repository

Committed source: <https://github.com/hassanshariati/interview>. If GitHub app write access is unavailable, install this ZIP and push the source via authenticated Git on your trusted workstation (not by exposing passwords in chat). Check the connected GitHub app's **Contents: Read and write** permission.


## DeepSeek CV-grounded interview (v0.4.0)

The server-side DeepSeek integration uses the official Chat Completions endpoint.
In the server-only `.env` file, set:

```dotenv
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=your-actual-key
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
AI_QUESTIONS_PER_INTERVIEW=10
AI_QUESTIONS_PER_HOUR=80
```

Restart the API container so it receives updated environment variables:

```bash
docker compose up -d --force-recreate api
```

Select a job on the public portal, optionally submit a CV, confirm consent, and
press **Start interview with DeepSeek**. DeepSeek receives only bounded,
heuristically redacted professional CV excerpts and technical competencies,
not the entire CV. It creates the first practical question and follow-up questions
after each answer; the AI conversation is saved with server-side provenance and
is available to the authorized human reviewer.

**Browser voice:** Web Speech Recognition and SpeechSynthesis provide optional
speech recognition and spoken questions. Availability and Persian quality vary by
browser, OS, and installed voices. The browser's speech recognition provider MAY
process raw audio externally; it is not necessarily local speech-to-text.
DeepSeek itself receives text, not raw audio. The textarea fallback works even
without browser speech APIs. Use HTTPS, and allow the microphone permission.
The OpenAI Realtime path remains available separately when chosen and configured.

**Controls:** A private interview token, explicit consent, scheduled/TTL window,
per-interview question count and global hourly call limit apply. The API key is
never sent to the browser. Public applicant identity is NOT email-verified.
Avoid real private resumes while evaluating third-party provider privacy.
No automated hiring decision or inferred emotion/stress rating is performed.

If the page reports **DeepSeek not configured**, verify the API container has
received the server-only environment variables (print only booleans; do NOT
print the key). If a provider call returns an error, verify DeepSeek account
credit, key validity, DNS egress and the account's permitted API models.


## GapGPT provider (v0.4.1)

GapGPT can be selected **instead of** DeepSeek for the existing CV-grounded
interview pipeline. The configured endpoint must be exactly
`https://api.gapgpt.app/v1` and the server sends standard, non-streaming
`POST /chat/completions` requests. Configure on the production host:

```dotenv
LLM_PROVIDER=gapgpt
GAPGPT_API_KEY=your-private-API-key
GAPGPT_BASE_URL=https://api.gapgpt.app/v1
GAPGPT_MODEL=gpt-4o-mini
```

The model above is an example: use the exact model ID enabled for **your**
GapGPT account. API usage, costs and model availability depend on the provider;
free chat on a website does not imply free API credits. Never publish the key
or copy it into `DEEPSEEK_API_KEY`.

```bash
cd /opt/interview-ai
docker compose up -d --force-recreate api
docker compose exec -T api python -c 'from backend.gapgpt import configured; print("GAPGPT_READY="+str(configured()))'
```

`GAPGPT_READY=True` checks that environment variables are present; it does
**not** prove the API key is valid or the account has credits. If the selected
model is rejected, check the provider's dashboard and change
`GAPGPT_MODEL`; errors are returned without leaking the token to candidates.

The candidate interview still requires an unexpired private link and consent.
Only professional excerpts from the CV (not the full document) are sent to
the selected model for practical interview follow-ups. The optional audio
experience is provided by browser speech recognition / speech synthesis, **not**
native low-latency realtime audio through GapGPT. Some browsers use remote
speech-to-text providers; test with fictitious CVs and review the privacy terms
of both services before allowing real candidates.


## Press-to-talk and post-interview technical analysis (v0.5.0)

For GapGPT/DeepSeek text interviews, the candidate starts a session and hears
one question (using browser speech synthesis where available). The interviewer
**waits** for an answer. The candidate can type and send, or hold the
**press-to-talk** button while speaking and release it to finalize recognition.
A new AI follow-up is requested **only after the button is released** and
speech recognition yields final text. Brief silence during a press should
not automatically submit a partial answer; if ASR does not return final text,
the candidate can type or edit an answer instead.

Browser speech recognition is best-effort, including for Persian: browser
support, microphone permissions, privacy and audio accuracy vary. Speech
may be processed by the browser's external provider. Press-to-talk does not
stream raw audio to GapGPT. Users must still explicitly consent.

Authorized admin/recruiter users may open **گزارش و ارزیابی**, select a
candidate and job, and after completion click **تحلیل شواهد فنی با AI** for
a completed interview with at least one valid AI-flow answer. The model
provides an evidence-based Persian synopsis, cited skill observations,
uncertainties and follow-up questions. There are **no automatic interview
scores or hire/reject recommendations**. The report is generated on demand
and is not permanently stored; repeated requests consume provider tokens.
Rate limit via `AI_REPORTS_PER_USER_HOUR` (default 6).

Only server-associated interview turns are summarized, not arbitrary
browser-submitted transcript messages. Email, phone and URL patterns are
redacted from limited text excerpts before model transfer. This is a
heuristic minimization, **not a guarantee** of removing every private
detail. Reports and interview content require authorized management access;
human reviewers must verify any asserted skill evidence and make
employment decisions themselves.
