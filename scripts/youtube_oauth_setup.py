"""
One-time OAuth setup: run locally, authorize in browser, print refresh token for CI.

Usage:
  python scripts/youtube_oauth_setup.py --client-secret path/to/client_secret.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _oauth_section_from_client_secret(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("installed", "web"):
        if key in data and isinstance(data[key], dict):
            return data[key]
    raise ValueError("client_secret JSON must contain an 'installed' or 'web' section")


def main() -> None:
    p = argparse.ArgumentParser(description="YouTube OAuth refresh token helper")
    p.add_argument(
        "--client-secret",
        required=True,
        help="Path to Google OAuth client_secret JSON (Desktop app)",
    )
    args = p.parse_args()

    secret_path = Path(args.client_secret)
    section = _oauth_section_from_client_secret(secret_path)
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    if not client_id or not client_secret:
        raise SystemExit("client_secret JSON missing client_id or client_secret")

    flow = InstalledAppFlow.from_client_secrets_file(str(secret_path), SCOPES)
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
        include_granted_scopes=True,
    )
    if not creds.refresh_token:
        raise SystemExit("No refresh token received; try revoking app access and re-run with prompt=consent.")

    print("\nAdd these to GitHub Actions secrets (Settings → Secrets and variables → Actions):\n")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"YOUTUBE_REFRESH_TOKEN={creds.refresh_token}")
    print("\n(Store values as separate secrets with those names. Access token omitted; CI refreshes each run.)\n")


if __name__ == "__main__":
    main()
