"""
JARVIS plugin: unified mail assistant (Gmail/Outlook) — read, triage, draft,
send, organize, and watch the inbox, all through one tool with an `action`
parameter, the same pattern plane_radar.py uses for scan/set_home.

Requires _mail_core.py (shared library, not a plugin itself) alongside this
file, and a connected account — see README.md / _mail_oauth_setup.py.
"""
from plugins import _mail_core as core

PLUGIN = {
    "name": "mail_manager",
    "description": (
        "Manages the user's connected email inbox (Gmail/Outlook): checking what's "
        "urgent, reading messages, drafting and sending replies, cleaning up the "
        "inbox, and watching it in the background. Pick `action` based on what the "
        "user actually wants:\n"
        "  - 'digest': quick urgent-only check — 'check my email', 'anything urgent', "
        "'what needs my attention'.\n"
        "  - 'read': full read-out of recent mail or one thread — 'read my email', "
        "'summarize my inbox', 'what did they say in that thread'.\n"
        "  - 'draft_reply': save a reply as a draft (never sends) — use once you and "
        "the user have composed what to say; always read it back and get explicit "
        "confirmation before using 'send_reply'.\n"
        "  - 'send_reply': send a previously drafted reply — ONLY with confirm=true, "
        "ONLY right after the user explicitly says to send it.\n"
        "  - 'manage_message': archive/delete/flag ONE specific message — 'archive "
        "that email', 'delete that one'.\n"
        "  - 'organize_inbox': bulk-clean the whole inbox — 'clean up my inbox', "
        "'organize my email'.\n"
        "  - 'watch_start' / 'watch_stop': start or stop continuous background "
        "monitoring — 'start watching my email', 'stop monitoring my inbox'.\n"
        "Do NOT use this for flight/plane tracking or aircraft identification — "
        "that's plane_radar/aircraft_identifier."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "One of: digest, read, draft_reply, send_reply, manage_message, "
                    "organize_inbox, watch_start, watch_stop."
                ),
            },
            "limit": {
                "type": "INTEGER",
                "description": "[read] How many recent messages to read (default 5, max 20). Ignored if thread_id is given.",
            },
            "thread_id": {
                "type": "STRING",
                "description": "[read] A specific thread/conversation id, if the user means one already surfaced.",
            },
            "message_id": {
                "type": "STRING",
                "description": "[draft_reply, manage_message] The email's id, from an earlier 'digest' or 'read' call.",
            },
            "reply_body": {
                "type": "STRING",
                "description": "[draft_reply] The full reply text, composed with the user.",
            },
            "draft_id": {
                "type": "STRING",
                "description": "[send_reply] The draft id returned by a prior 'draft_reply' call.",
            },
            "confirm": {
                "type": "BOOLEAN",
                "description": "[send_reply] True ONLY if the user just explicitly confirmed sending this exact draft.",
            },
            "message_action": {
                "type": "STRING",
                "description": "[manage_message] One of: archive, delete, flag.",
            },
        },
        "required": ["action"],
    },
    "behavior": "NON_BLOCKING",
    "scheduling": "WHEN_IDLE",
}


# ── per-action handlers ─────────────────────────────────────────────────────
# Each returns the spoken string. Kept as separate functions (rather than one
# giant run()) so this reads the same as having 8 files, just without the
# separate PLUGIN/run() boilerplate each needed.

def _do_digest(params: dict, player) -> str:
    state = core.read_state()
    pending = state.get("pending_digest", [])

    if not pending:
        monitoring_note = (
            ""
            if core.is_monitoring()
            else " (mail watching is currently off, so this only reflects what's "
            "been checked manually — say 'start watching my email' to turn it on)"
        )
        return f"Nothing urgent right now, sir.{monitoring_note}"

    emergency = [p for p in pending if p["urgency"] == "emergency"]
    high = [p for p in pending if p["urgency"] == "high"]

    lines = []
    if emergency:
        lines.append(f"{len(emergency)} urgent:")
        lines += [f"  - {p['from']}: {p['summary']}" for p in emergency]
    if high:
        lines.append(f"{len(high)} high priority:")
        lines += [f"  - {p['from']}: {p['summary']}" for p in high]

    core.update_state(lambda s: s.update(pending_digest=[]))

    spoken = []
    if emergency:
        spoken.append(f"{len(emergency)} urgent — " + "; ".join(f"{p['from']}: {p['summary']}" for p in emergency))
    if high:
        spoken.append(f"{len(high)} high priority — " + "; ".join(f"{p['from']}: {p['summary']}" for p in high))
    result_text = "Here's what needs your attention, sir: " + ". ".join(spoken) + "."

    if player:
        try:
            if hasattr(player, "show_content"):
                player.show_content("EMAIL DIGEST", "\n".join(lines))
        except Exception:
            pass
    return result_text


def _do_read(params: dict, player) -> str:
    try:
        limit = min(int(params.get("limit") or 5), 20)
    except (TypeError, ValueError):
        limit = 5
    thread_id = (params.get("thread_id") or "").strip()

    cfg = core.load_config()
    connector = core.get_connector(cfg)
    messages = connector.get_thread(thread_id) if thread_id else connector.list_recent(limit=limit)

    if not messages:
        return "There's nothing there to read, sir."

    summaries = []
    for m in messages:
        body = (m.get("body") or "").strip().replace("\n", " ")
        if len(body) > 600:
            body = body[:600] + "..."
        summaries.append(f"[id:{m['id']}] From {m['from']} — Subject: {m['subject']}. {body}")

    if player:
        try:
            if hasattr(player, "show_content"):
                player.show_content("INBOX", "\n\n".join(summaries))
        except Exception:
            pass
    return " || ".join(summaries)


def _do_draft_reply(params: dict, player) -> str:
    message_id = (params.get("message_id") or "").strip()
    reply_body = params.get("reply_body") or ""
    if not message_id or not reply_body:
        return "Sir, I need both the email and the reply text to save a draft."

    cfg = core.load_config()
    connector = core.get_connector(cfg)
    provider_draft_id = connector.create_draft(message_id, reply_body)
    draft_id = core.new_draft_id()

    def _save(state, draft_id=draft_id):
        state["drafts"][draft_id] = {
            "message_id": message_id,
            "body": reply_body,
            "provider_draft_id": provider_draft_id,
            "status": "pending_review",
        }

    core.update_state(_save)

    if player:
        try:
            if hasattr(player, "show_content"):
                player.show_content("DRAFT REPLY", reply_body)
        except Exception:
            pass
    return f"Draft saved, sir — draft id {draft_id}. Say the word and I'll send it."


def _do_send_reply(params: dict, player) -> str:
    draft_id = (params.get("draft_id") or "").strip()
    confirm = bool(params.get("confirm", False))
    if not draft_id:
        return "Sir, I don't have a draft id to send."

    state = core.read_state()
    draft = state.get("drafts", {}).get(draft_id)
    if not draft:
        return f"Sir, I don't have a draft on file with id {draft_id}."
    if draft["status"] == "sent":
        return "That draft has already been sent, sir."
    if not confirm:
        return f"I haven't sent it — please confirm first. Here's the draft: {draft['body'][:200]}"

    cfg = core.load_config()
    connector = core.get_connector(cfg)
    connector.send_draft(draft["provider_draft_id"])

    def _mark_sent(state):
        import time
        state["drafts"][draft_id]["status"] = "sent"
        state["sent_log"].append(
            {"draft_id": draft_id, "sent_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "method": "confirmed"}
        )

    core.update_state(_mark_sent)
    return "Sent, sir."


def _do_manage_message(params: dict, player) -> str:
    message_id = (params.get("message_id") or "").strip()
    message_action = (params.get("message_action") or "").lower().strip()
    if message_action not in ("archive", "delete", "flag"):
        return "Sir, that should be archive, delete, or flag."
    if not message_id:
        return "Sir, I need to know which email."

    cfg = core.load_config()
    connector = core.get_connector(cfg)
    if message_action == "archive":
        connector.archive_message(message_id)
        return "Archived, sir."
    if message_action == "delete":
        connector.delete_message(message_id)
        return "Deleted, sir."
    connector.flag_message(message_id)
    return "Flagged, sir."


def _do_organize_inbox(params: dict, player) -> str:
    cfg = core.load_config()
    connector = core.get_connector(cfg)
    recent = connector.list_recent(limit=100)

    archived = 0
    flagged = 0
    for m in recent:
        c = core.classify(m, cfg)
        if c["urgency"] == "noise":
            connector.archive_message(m["id"])
            archived += 1
        elif c["category"] == "action_needed":
            connector.flag_message(m["id"])
            flagged += 1

    return f"Done, sir — archived {archived} message(s) and flagged {flagged} that need your attention."


def _do_watch_start(params: dict, player) -> str:
    status = core.start_monitoring(player)
    if status == "already_running":
        return "Already watching your inbox, sir."
    cfg = core.load_config()
    interval = cfg.get("poll_interval_seconds", 90)
    return f"Now watching your inbox, sir — I'll check every {interval} seconds and flag anything urgent right away."


def _do_watch_stop(params: dict, player) -> str:
    status = core.stop_monitoring()
    return "Stopped watching your inbox, sir." if status != "not_running" else "I wasn't watching your inbox, sir."


_HANDLERS = {
    "digest": _do_digest,
    "read": _do_read,
    "draft_reply": _do_draft_reply,
    "send_reply": _do_send_reply,
    "manage_message": _do_manage_message,
    "organize_inbox": _do_organize_inbox,
    "watch_start": _do_watch_start,
    "watch_stop": _do_watch_stop,
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    params = parameters or {}
    action = (params.get("action") or "").strip().lower()
    handler = _HANDLERS.get(action)

    if handler is None:
        return (
            f"Sir, I don't recognize the mail action '{action}'. Valid ones are: "
            + ", ".join(_HANDLERS.keys()) + "."
        )

    try:
        result_text = handler(params, player)
    except Exception as e:
        return f"Sir, that mail request failed: {e}"

    if player:
        try:
            player.write_log(f"JARVIS: [{action}] {result_text}")
        except Exception:
            pass
    return result_text
