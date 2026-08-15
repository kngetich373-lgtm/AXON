"""Shared local OAuth2 support for Google Workspace integrations."""
from __future__ import annotations
from pathlib import Path
from typing import Iterable
import os

class GoogleOAuthError(RuntimeError):
    pass

class GoogleOAuth:
    def __init__(self, credentials_file: str | Path | None = None, token_file: str | Path | None = None):
        self.credentials_file = Path(credentials_file or os.getenv("AXON_GOOGLE_CREDENTIALS", "credentials.json")).expanduser()
        self.token_file = Path(token_file or os.getenv("AXON_GOOGLE_TOKEN", str(Path.home() / ".config" / "axon" / "google_token.json"))).expanduser()

    def configure(self, credentials_file: str | Path | None = None, token_file: str | Path | None = None):
        if credentials_file:
            self.credentials_file = Path(credentials_file).expanduser()
        if token_file:
            self.token_file = Path(token_file).expanduser()
        self._cached = None

    def credentials(self, scopes: Iterable[str]):
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise GoogleOAuthError("Install Google dependencies: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2") from exc

        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        creds = None
        if self.token_file.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_file), list(scopes))
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        if not creds or not creds.valid:
            if not self.credentials_file.exists():
                raise GoogleOAuthError(
                    f"Google OAuth credentials not found at {self.credentials_file}. "
                    "Create a Desktop OAuth client in Google Cloud and set AXON_GOOGLE_CREDENTIALS."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), list(scopes))
            creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        self.token_file.write_text(creds.to_json(), encoding="utf-8")
        try:
            os.chmod(self.token_file, 0o600)
        except OSError:
            pass
        return creds

    def revoke(self) -> None:
        if self.token_file.exists():
            self.token_file.unlink()
