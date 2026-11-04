# Email delivery with n8n

Import `deploy/n8n/interview-email.json` into your existing n8n instance. This workflow handles both invitations and booking confirmations. It does not authenticate application users.

1. On **Authenticated email webhook**, create/select a Header Auth credential. Its header name must be `X-Interview-Token`; its value must be a unique random secret, for example generated with `openssl rand -hex 32`.
2. On **Send email**, select your SMTP credential. The email service credentials remain inside n8n. Use TLS as required by your provider.
3. Publish/activate the workflow and copy its **Production URL** (not `/webhook-test/`). Serve n8n over HTTPS.
4. Set these values in the server's existing `.env` without replacing its database or bootstrap values:

```dotenv
EMAIL_PROVIDER=n8n
N8N_EMAIL_WEBHOOK_URL=https://YOUR-N8N-HOST/webhook/interview-email
N8N_EMAIL_WEBHOOK_TOKEN=YOUR_HEADER_AUTH_SECRET
SMTP_FROM=YOUR_VERIFIED_SENDER_ADDRESS
```

5. Recreate the application to load the environment:

```bash
docker compose up -d --build api
```

6. Log in, upload a test candidate whose mailbox you control, create a job and send an invitation. Verify the invitation email, its private candidate link, time selection and confirmation email.

The backend sends `event`, `from`, `to`, `subject`, and `text` as JSON. n8n must return HTTP 200 with `{"status":"sent"}` **after** the mail server accepts the email. An immediate webhook acknowledgement does not count as sent. This confirms acceptance by the mail server, not inbox delivery. Do not enable “Continue on Fail” on the mail node. Timeouts and invalid acknowledgements are marked as failures; requests are not retried automatically because a timeout can occur after delivery.

Workflow execution payload retention is disabled because messages contain private invitation links. Do not pin real payloads or enable proxy body logging. Deleting or troubleshooting previous n8n execution data is an operator action.

Existing deployments without `EMAIL_PROVIDER` continue using SMTP unless an n8n URL is configured. To opt back into direct delivery, explicitly set `EMAIL_PROVIDER=smtp` and the SMTP settings from `.env.example`. There is no silent fallback after an n8n failure.

References:
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/
- https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.sendemail/
