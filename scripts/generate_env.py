"""Generate a strong local .env; passwords are never committed or printed in logs."""
import argparse
import getpass
import os
import secrets
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--admin-email", required=True, help="initial admin email")
args = parser.parse_args()
base = Path(__file__).resolve().parents[1]
dest = base / ".env"
if dest.exists():
    raise SystemExit(".env already exists; not overwriting it")
postgres = secrets.token_urlsafe(32)
password = secrets.token_urlsafe(25)
example = (base / ".env.example").read_text()
example = example.replace("BOOTSTRAP_ADMIN_EMAIL=", "BOOTSTRAP_ADMIN_EMAIL=" + args.admin_email)
example = example.replace("BOOTSTRAP_ADMIN_PASSWORD=", "BOOTSTRAP_ADMIN_PASSWORD=" + password)
example = example.replace("POSTGRES_PASSWORD=", "POSTGRES_PASSWORD=" + postgres)
fd = os.open(dest, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(example)
print("Created .env with permissions 0600")
print("Initial admin email:", args.admin_email)
print("Initial admin password (store securely; only shown once):", password)
