"""
Run this ONCE manually, from JARVIS's project root, to connect a mailbox:

    python _mail_oauth_setup.py

It opens a browser for you to sign in and grant access (Gmail) or prints a
device code (Outlook), then saves the finished config — including the
refresh token — into JARVIS's own settings via memory.config_manager, the
same store plane_radar.py uses for its saved home location. Nothing is
left behind in a plaintext runtime file.

Not a JARVIS plugin (no PLUGIN dict), hence the leading underscore so the
loader skips it.

Before running:
1. Copy mail_account_config.example.json to mail_account_config.local.json
   in this folder.
2. Fill in "provider", "account_email", and the client_id/client_secret for
   that provider (from Google Cloud Console for Gmail, or an Azure AD app
   registration for Outlook).
3. Run this script. You can delete mail_account_config.local.json
   afterwards — it's only a staging file for this one-time step.
"""
import json
from pathlib import Path

from memory.config_manager import save_plugin_config

_STAGING_PATH = Path(__file__).resolve().parent / "mail_account_config.local.json"
_CONFIG_NS = "mail_account"


def _load_staging() -> dict:
    if not _STAGING_PATH.exists():
        raise SystemExit(
            f"Copy mail_account_config.example.json to {_STAGING_PATH.name} in this "
            "folder and fill in provider/account_email/client_id/client_secret first."
        )
    return json.loads(_STAGING_PATH.read_text())


def setup_gmail(cfg: dict) -> dict:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": cfg["gmail"]["client_id"],
                "client_secret": cfg["gmail"]["client_secret"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.send",
        ],
    )
    creds = flow.run_local_server(port=0)
    cfg["gmail"]["refresh_token"] = creds.refresh_token
    print("Got Gmail refresh token.")
    return cfg


def setup_outlook(cfg: dict) -> dict:
    import msal

    app = msal.PublicClientApplication(
        cfg["outlook"]["client_id"],
        authority=f"https://login.microsoftonline.com/{cfg['outlook']['tenant_id']}",
    )
    scopes = ["Mail.Read", "Mail.ReadWrite", "Mail.Send", "offline_access"]
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        raise SystemExit(f"Failed to start device flow: {flow}")
    print(flow["message"])  # tells the user to open a URL and enter a code
    result = app.acquire_token_by_device_flow(flow)
    if "refresh_token" not in result:
        raise SystemExit(f"Auth failed: {result.get('error_description', result)}")
    cfg["outlook"]["refresh_token"] = result["refresh_token"]
    print("Got Outlook refresh token.")
    return cfg


def main():
    cfg = _load_staging()
    provider = cfg.get("provider", "")
    if provider == "gmail":
        cfg = setup_gmail(cfg)
    elif provider == "outlook":
        cfg = setup_outlook(cfg)
    else:
        raise SystemExit(
            f"Set \"provider\" to 'gmail' or 'outlook' in {_STAGING_PATH.name} first."
        )

    save_plugin_config(_CONFIG_NS, cfg)
    print(
        f"Saved to JARVIS's config store under '{_CONFIG_NS}'. The mail_*.py "
        f"plugins are ready to use — you can delete {_STAGING_PATH.name} now."
    )


if __name__ == "__main__":
    main()
