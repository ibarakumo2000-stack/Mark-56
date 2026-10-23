"""
Shared library for the JARVIS mail plugins (the mail_*.py files in this
folder). Leading underscore keeps JARVIS's loader from treating this as a
tool itself — it has no PLUGIN dict / run() function.

Persistent settings (account/tokens) and runtime state (seen messages,
drafts, send log, pending digest) are both stored via JARVIS's own
memory.config_manager — the same mechanism plane_radar.py uses for its
saved home location — rather than a separate hand-rolled file, so this
plugin family fits the rest of the install instead of reinventing storage.
"""

from __future__ import annotations

import base64
import re
import threading
import uuid
from typing import Callable, Optional

from memory.config_manager import get_plugin_config, save_plugin_config

_CONFIG_NS = "mail_account"  # provider, tokens, behavior settings
_STATE_NS = "mail_state"  # seen ids, drafts, sent log, pending digest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "provider": "",  # "gmail" or "outlook" — empty means not set up yet
    "account_email": "",
    "gmail": {"client_id": "", "client_secret": "", "refresh_token": ""},
    "outlook": {
        "client_id": "",
        "client_secret": "",
        "tenant_id": "common",
        "refresh_token": "",
    },
    "auto_send_enabled": False,
    "poll_interval_seconds": 90,
    "vip_senders": [],
    "urgent_keywords": [
        "urgent",
        "asap",
        "action required",
        "deadline",
        "immediately",
        "final notice",
        "security alert",
        "payment failed",
    ],
    "promo_sender_patterns": [
        r"no-?reply@",
        r"newsletter@",
        r"marketing@",
        r"notifications@",
    ],
}


class ConfigError(Exception):
    pass


def load_config() -> dict:
    cfg = get_plugin_config(_CONFIG_NS) or {}
    if not cfg.get("provider"):
        raise ConfigError(
            "No mail account is set up yet. Run _mail_oauth_setup.py once "
            "(see README.md) to connect Gmail or Outlook."
        )
    merged = {**DEFAULT_CONFIG, **cfg}
    for key in ("gmail", "outlook"):
        merged[key] = {**DEFAULT_CONFIG[key], **cfg.get(key, {})}
    return merged


def save_config(cfg: dict) -> None:
    save_plugin_config(_CONFIG_NS, cfg)


# ---------------------------------------------------------------------------
# Runtime state: seen message ids, drafts, send log, pending digest entries.
# Guarded by a lock since the monitor thread and tool calls can both touch it.
# ---------------------------------------------------------------------------

_state_lock = threading.Lock()

_EMPTY_STATE = {
    "seen_message_ids": [],
    "drafts": {},  # draft_id -> {message_id, body, provider_draft_id, status}
    "sent_log": [],  # [{draft_id, sent_at, method}]
    "pending_digest": [],  # [{message_id, urgency, category, summary, from, subject}]
}


def read_state() -> dict:
    with _state_lock:
        state = get_plugin_config(_STATE_NS) or {}
        return {**_EMPTY_STATE, **state}


def update_state(mutator: Callable[[dict], object]):
    """Run `mutator(state)` under lock, persist via save_plugin_config, return
    whatever the mutator returns."""
    with _state_lock:
        state = {**_EMPTY_STATE, **(get_plugin_config(_STATE_NS) or {})}
        result = mutator(state)
        save_plugin_config(_STATE_NS, state)
        return result


# ---------------------------------------------------------------------------
# Classification (heuristic only — no LLM call, so it's cheap enough to run
# on every poll from the background monitor thread).
# ---------------------------------------------------------------------------


def classify(message: dict, cfg: dict) -> dict:
    """message: {id, from, subject, snippet}. Returns urgency/category/summary."""
    subject_lower = (message.get("subject") or "").lower()
    from_lower = (message.get("from") or "").lower()

    vip = {v.lower() for v in cfg.get("vip_senders", [])}
    if any(v in from_lower for v in vip):
        return {
            "urgency": "high",
            "category": "action_needed",
            "summary": f"From a VIP contact: {message.get('subject', '(no subject)')}",
        }

    if any(k in subject_lower for k in cfg.get("urgent_keywords", [])):
        return {
            "urgency": "emergency",
            "category": "action_needed",
            "summary": message.get("subject", "(no subject)"),
        }

    if any(re.search(p, from_lower) for p in cfg.get("promo_sender_patterns", [])):
        return {
            "urgency": "noise",
            "category": "promotional",
            "summary": message.get("subject", "(no subject)"),
        }

    return {
        "urgency": "normal",
        "category": "fyi",
        "summary": message.get("subject", "(no subject)"),
    }


# ---------------------------------------------------------------------------
# Provider connectors — a tiny common interface so plugin files never
# branch on provider. Only Gmail and Outlook are implemented.
# ---------------------------------------------------------------------------


class GmailConnector:
    def __init__(self, cfg: dict):
        # Imported lazily so this folder doesn't hard-fail to import if
        # google-api-python-client isn't installed and the user is only
        # using Outlook.
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build

        g = cfg["gmail"]
        creds = Credentials(
            token=None,
            refresh_token=g["refresh_token"],
            client_id=g["client_id"],
            client_secret=g["client_secret"],
            token_uri="https://oauth2.googleapis.com/token",
            scopes=[
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.modify",
                "https://www.googleapis.com/auth/gmail.compose",
                "https://www.googleapis.com/auth/gmail.send",
            ],
        )
        creds.refresh(Request())
        self.service = build("gmail", "v1", credentials=creds)

    def _to_simple(self, m: dict) -> dict:
        headers = m.get("payload", {}).get("headers", [])

        def h(name):
            return next(
                (x["value"] for x in headers if x["name"].lower() == name.lower()), ""
            )

        return {
            "id": m["id"],
            "thread_id": m.get("threadId", ""),
            "from": h("From"),
            "subject": h("Subject"),
            "snippet": m.get("snippet", ""),
            "body": self._extract_body(m.get("payload", {})) or m.get("snippet", ""),
            "received_at": m.get("internalDate", ""),
        }

    def _extract_body(self, part: dict) -> Optional[str]:
        if not part:
            return None
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            data = part["body"]["data"]
            return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
        for child in part.get("parts", []) or []:
            found = self._extract_body(child)
            if found:
                return found
        return None

    def list_recent(self, limit=20):
        resp = (
            self.service.users()
            .messages()
            .list(userId="me", maxResults=limit, labelIds=["INBOX"])
            .execute()
        )
        ids = [m["id"] for m in resp.get("messages", [])]
        out = []
        for mid in ids:
            full = (
                self.service.users()
                .messages()
                .get(userId="me", id=mid, format="full")
                .execute()
            )
            out.append(self._to_simple(full))
        return out

    def get_message(self, message_id: str):
        full = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return self._to_simple(full)

    def get_thread(self, thread_id: str):
        full = (
            self.service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        return [self._to_simple(m) for m in full.get("messages", [])]

    def create_draft(self, message_id: str, body_text: str) -> str:
        original = self.get_message(message_id)
        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        raw_lines = [
            f"To: {original['from']}",
            f"Subject: {subject}",
            "Content-Type: text/plain; charset=utf-8",
            "",
            body_text,
        ]
        raw = base64.urlsafe_b64encode("\r\n".join(raw_lines).encode("utf-8")).decode()
        draft = (
            self.service.users()
            .drafts()
            .create(
                userId="me",
                body={"message": {"raw": raw, "threadId": original["thread_id"]}},
            )
            .execute()
        )
        return draft["id"]

    def send_draft(self, provider_draft_id: str):
        self.service.users().drafts().send(
            userId="me", body={"id": provider_draft_id}
        ).execute()

    def archive_message(self, message_id: str):
        self.service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()

    def flag_message(self, message_id: str):
        self.service.users().messages().modify(
            userId="me", id=message_id, body={"addLabelIds": ["STARRED"]}
        ).execute()

    def delete_message(self, message_id: str):
        self.service.users().messages().trash(userId="me", id=message_id).execute()


class OutlookConnector:
    GRAPH = "https://graph.microsoft.com/v1.0"

    def __init__(self, cfg: dict):
        import requests

        self._requests = requests
        o = cfg["outlook"]
        token_resp = requests.post(
            f"https://login.microsoftonline.com/{o['tenant_id']}/oauth2/v2.0/token",
            data={
                "client_id": o["client_id"],
                "client_secret": o["client_secret"],
                "refresh_token": o["refresh_token"],
                "grant_type": "refresh_token",
                "scope": "Mail.Read Mail.ReadWrite Mail.Send offline_access",
            },
            timeout=20,
        )
        token_resp.raise_for_status()
        self._access_token = token_resp.json()["access_token"]

    def _headers(self):
        return {"Authorization": f"Bearer {self._access_token}"}

    def _to_simple(self, m: dict) -> dict:
        return {
            "id": m["id"],
            "thread_id": m.get("conversationId", ""),
            "from": (m.get("from") or {}).get("emailAddress", {}).get("address", ""),
            "subject": m.get("subject", ""),
            "snippet": m.get("bodyPreview", ""),
            "body": (m.get("body") or {}).get("content", m.get("bodyPreview", "")),
            "received_at": m.get("receivedDateTime", ""),
        }

    def list_recent(self, limit=20):
        r = self._requests.get(
            f"{self.GRAPH}/me/mailFolders/inbox/messages",
            headers=self._headers(),
            params={"$top": limit, "$orderby": "receivedDateTime DESC"},
            timeout=20,
        )
        r.raise_for_status()
        return [self._to_simple(m) for m in r.json().get("value", [])]

    def get_message(self, message_id: str):
        r = self._requests.get(
            f"{self.GRAPH}/me/messages/{message_id}", headers=self._headers(), timeout=20
        )
        r.raise_for_status()
        return self._to_simple(r.json())

    def get_thread(self, thread_id: str):
        r = self._requests.get(
            f"{self.GRAPH}/me/messages",
            headers=self._headers(),
            params={
                "$filter": f"conversationId eq '{thread_id}'",
                "$orderby": "receivedDateTime ASC",
            },
            timeout=20,
        )
        r.raise_for_status()
        return [self._to_simple(m) for m in r.json().get("value", [])]

    def create_draft(self, message_id: str, body_text: str) -> str:
        r = self._requests.post(
            f"{self.GRAPH}/me/messages/{message_id}/createReply",
            headers=self._headers(),
            json={},
            timeout=20,
        )
        r.raise_for_status()
        draft_id = r.json()["id"]
        r2 = self._requests.patch(
            f"{self.GRAPH}/me/messages/{draft_id}",
            headers=self._headers(),
            json={"body": {"contentType": "text", "content": body_text}},
            timeout=20,
        )
        r2.raise_for_status()
        return draft_id

    def send_draft(self, provider_draft_id: str):
        r = self._requests.post(
            f"{self.GRAPH}/me/messages/{provider_draft_id}/send",
            headers=self._headers(),
            timeout=20,
        )
        r.raise_for_status()

    def archive_message(self, message_id: str):
        r = self._requests.post(
            f"{self.GRAPH}/me/messages/{message_id}/move",
            headers=self._headers(),
            json={"destinationId": "archive"},
            timeout=20,
        )
        r.raise_for_status()

    def flag_message(self, message_id: str):
        r = self._requests.patch(
            f"{self.GRAPH}/me/messages/{message_id}",
            headers=self._headers(),
            json={"flag": {"flagStatus": "flagged"}},
            timeout=20,
        )
        r.raise_for_status()

    def delete_message(self, message_id: str):
        r = self._requests.delete(
            f"{self.GRAPH}/me/messages/{message_id}", headers=self._headers(), timeout=20
        )
        r.raise_for_status()


def get_connector(cfg: dict):
    if cfg["provider"] == "gmail":
        return GmailConnector(cfg)
    if cfg["provider"] == "outlook":
        return OutlookConnector(cfg)
    raise ConfigError(f"Unknown provider '{cfg['provider']}' in mail account config")


# ---------------------------------------------------------------------------
# Background monitor thread — polls for new mail, classifies, and speaks up
# immediately for anything 'emergency'. Everything else waits for the next
# digest pull.
# ---------------------------------------------------------------------------

_monitor_thread: Optional[threading.Thread] = None
_monitor_stop = threading.Event()


def is_monitoring() -> bool:
    return _monitor_thread is not None and _monitor_thread.is_alive()


def _monitor_loop(player, stop_event: threading.Event):
    interval = 90  # fallback until config loads successfully at least once

    while not stop_event.is_set():
        try:
            cfg = load_config()
            interval = cfg.get("poll_interval_seconds", 90)
            connector = get_connector(cfg)

            recent = connector.list_recent(limit=15)
            state = read_state()
            seen = set(state["seen_message_ids"])
            new_messages = [m for m in recent if m["id"] not in seen]

            for m in new_messages:
                c = classify(m, cfg)

                def _record(state, m=m, c=c):
                    state["seen_message_ids"].append(m["id"])
                    state["seen_message_ids"] = state["seen_message_ids"][-500:]
                    if c["urgency"] in ("emergency", "high"):
                        state["pending_digest"].append(
                            {
                                "message_id": m["id"],
                                "urgency": c["urgency"],
                                "category": c["category"],
                                "summary": c["summary"],
                                "from": m["from"],
                                "subject": m["subject"],
                            }
                        )

                update_state(_record)

                if c["urgency"] == "emergency" and player is not None:
                    try:
                        player.write_log(
                            f"JARVIS: Urgent email from {m['from']} — {c['summary']}"
                        )
                    except Exception:
                        pass
        except Exception as e:
            # Never let the background thread die — a mailbox not yet
            # configured, a transient network error, or an expired token
            # should just get retried next cycle, logged quietly instead of
            # crashing with an unhandled traceback.
            if player is not None:
                try:
                    player.write_log(f"JARVIS: mail monitoring hit an error: {e}")
                except Exception:
                    pass

        stop_event.wait(interval)


def start_monitoring(player) -> str:
    global _monitor_thread
    if is_monitoring():
        return "already_running"
    # Validate up front so the caller gets an honest error immediately
    # instead of a background thread that silently loops on failure.
    load_config()
    _monitor_stop.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop, args=(player, _monitor_stop), daemon=True
    )
    _monitor_thread.start()
    return "started"


def stop_monitoring() -> str:
    if not is_monitoring():
        return "not_running"
    _monitor_stop.set()
    return "stopping"


def new_draft_id() -> str:
    return uuid.uuid4().hex[:12]
