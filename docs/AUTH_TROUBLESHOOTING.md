# Browser authentication

Use the exact HTTPS origin configured in `APP_ORIGIN`, without a path or trailing slash. `COOKIE_SECURE=true` is required in production. Preserve the host and original HTTPS scheme through both reverse proxies. Do not disable origin or CSRF checks to fix login errors.

For a local HTTP-only test, explicitly set both `APP_ORIGIN=http://localhost:8000` and `COOKIE_SECURE=false`; keep this limited to local development.

Login verifies that the browser retained its HttpOnly session cookie before displaying the dashboard. The UI shows readable messages for invalid credentials, lockouts, validation errors, mismatched origins and network errors. A 401 returns to login. A CSRF failure refreshes the session token for the next user action without replaying a write. Logout only clears the dashboard after the server confirms logout.

An account locks for 15 minutes after five incorrect passwords. A successful emergency reset clears the account lock and revokes existing sessions:

```bash
docker compose exec -it api python -m backend.admin_cli reset-password --email YOUR_ADMIN_EMAIL
```

Enter the same password twice (at least 14 characters). `BOOTSTRAP_ADMIN_PASSWORD` only creates the first user on an empty database; changing it later does not change an existing user's password. Never delete the database volume to fix authentication.

The source fixes and automated tests do not diagnose the deployed server's specific error. If a problem remains, inspect the failed request's status and response in browser developer tools, plus `docker compose logs --tail=100 api`, without sharing passwords, cookies or tokens.
