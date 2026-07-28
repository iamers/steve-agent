#!/usr/bin/env python3
"""Steve e2e — MTProto user-account injector/reader.

MTProto injector/reader for e2e tests: posts messages as a real user in
Steve's dev group, supports forum topics via `--thread`, and exposes a
structural `read` subcommand (instead of raw log output) so spike scenarios
can assert the bot's responses without a separate observer.

Posts messages into the Steve dev Telegram group as a REAL user account
("test-human"): messages arrive with is_bot=false, exercising allowlists and
mention-gating exactly like a human. Credentials (api_id, api_hash, session
string) load from a gitignored secrets file (.local/e2e-secrets.env by
default); this module NEVER contains a secret or an instance literal.

Telethon is imported lazily; run under an isolated uv env:

  uv run --with telethon python tools/e2e/injector.py whoami
  uv run --with telethon python tools/e2e/injector.py send --chat <id> \\
      --thread <topic_id> --text "ping" --marker-prefix t2
  uv run --with telethon python tools/e2e/injector.py read --chat <id> --limit 10
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import uuid

DEFAULT_SECRETS = ".local/e2e-secrets.env"


def load_secrets(path=DEFAULT_SECRETS):
    if not os.path.exists(path):
        raise FileNotFoundError(f"secrets file not found: {path}")
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for req in ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_SESSION_STRING"):
        if not env.get(req):
            raise KeyError(f"{req} missing/empty in {path}")
    return env


def make_marker(prefix="rt"):
    """Short, whole-word-anchorable marker: <prefix>-<12 hex>. No shell metacharacters."""
    if not re.fullmatch(r"[0-9A-Za-z._-]+", prefix or ""):
        raise ValueError("marker prefix must match [0-9A-Za-z._-]+")
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def mention_text(body, marker, mention=None):
    """Optional leading @mention, the body, the trailing marker (if any)."""
    parts = []
    if mention:
        parts.append("@" + mention.lstrip("@"))
    if body:
        parts.append(body)
    if marker:
        parts.append(marker)
    return " ".join(parts)


def make_client(secrets):
    from telethon.sync import TelegramClient          # lazy: helpers stay stdlib-only
    from telethon.sessions import StringSession
    return TelegramClient(StringSession(secrets["TELEGRAM_SESSION_STRING"]),
                          int(secrets["TELEGRAM_API_ID"]), secrets["TELEGRAM_API_HASH"])


def require_live(client):
    """get_me() liveness pre-check; exits 4 on an unauthorized session."""
    client.connect()
    if not client.is_user_authorized():
        print("SESSION_INVALID: re-auth needed", file=sys.stderr)
        client.disconnect()
        sys.exit(4)
    return client.get_me()


def cmd_whoami(args):
    secrets = load_secrets(args.secrets)
    client = make_client(secrets)
    me = require_live(client)
    client.disconnect()
    print(f"LIVE account_id={me.id} is_bot={bool(me.bot)} username={me.username or '-'}")
    return 0


def cmd_send(args):
    secrets = load_secrets(args.secrets)
    if not args.self_target and args.chat is None:
        print("ERROR: pass --chat <id> or --self", file=sys.stderr)
        return 2
    marker = None if args.no_marker else (args.marker or make_marker(args.marker_prefix))
    text = mention_text(args.text, marker, args.mention)
    target = "me" if args.self_target else args.chat
    client = make_client(secrets)
    require_live(client)
    if not args.self_target:
        client.get_dialogs()  # warm entity cache so send-by-id resolves
    kwargs = {"silent": True}
    if args.thread:
        kwargs["reply_to"] = args.thread  # Telethon: reply_to a topic id posts into that forum topic
    sent = client.send_message(target, text, **kwargs)
    client.disconnect()
    print(f"SENT marker={marker or '-'} message_id={sent.id}")
    return 0


def cmd_read(args):
    """Structural read-back of the last N messages (optionally one topic only).

    Output line per message, oldest first:
      id=<mid> thread=<tid|-> sender=<uid|-> bot=<0|1> text=<first 160 chars, newlines flattened>
    """
    secrets = load_secrets(args.secrets)
    client = make_client(secrets)
    require_live(client)
    client.get_dialogs()
    kwargs = {"limit": args.limit}
    if args.thread:
        kwargs["reply_to"] = args.thread  # iter within a forum topic
    msgs = list(client.iter_messages(args.chat, **kwargs))
    client.disconnect()
    for m in reversed(msgs):
        sender = getattr(m, "sender_id", None)
        is_bot = 0
        if getattr(m, "sender", None) is not None and getattr(m.sender, "bot", False):
            is_bot = 1
        tid = "-"
        if getattr(m, "reply_to", None) is not None:
            tid = getattr(m.reply_to, "reply_to_top_id", None) or getattr(m.reply_to, "reply_to_msg_id", None) or "-"
        text = (m.message or "").replace("\n", " ")[:160]
        rich = ""
        if not text:
            # Rich messages (structured/styled payloads) carry their content
            # outside the legacy text field: clients render them, but
            # m.message is empty. Flatten every "text" leaf so assertions on
            # bot replies do not mistake a rich message for an empty one.
            text = _flatten_rich_text(m)
            rich = " rich=1" if text else ""
        print(f"id={m.id} thread={tid} sender={sender or '-'} bot={is_bot}{rich} text={text}")
    return 0


def _flatten_rich_text(m):
    """Best-effort extraction of text leaves from a rich_message payload."""
    try:
        payload = m.to_dict().get("rich_message")
    except Exception:
        payload = None
    if not payload:
        return ""
    pieces = []

    def walk(node):
        if isinstance(node, dict):
            val = node.get("text")
            if isinstance(val, str) and val.strip():
                pieces.append(val.strip())
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(payload)
    return " ".join(pieces).replace("\n", " ")[:160]


def main(argv=None):
    p = argparse.ArgumentParser(description="Steve e2e MTProto injector/reader")
    p.add_argument("--secrets", default=DEFAULT_SECRETS, help="path to the gitignored secrets env")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("whoami", help="liveness pre-check (get_me)")

    s = sub.add_parser("send", help="send a message / @mention carrying a marker")
    s.add_argument("--chat", type=int, help="target chat id")
    s.add_argument("--self", dest="self_target", action="store_true",
                   help="send to Saved Messages (write-path smoke)")
    s.add_argument("--thread", type=int, help="forum topic id (message_thread_id)")
    s.add_argument("--mention", help="bot username to @mention (without @)")
    s.add_argument("--text", default="", help="message body (marker appended unless --no-marker)")
    s.add_argument("--marker", help="explicit marker (else auto from --marker-prefix)")
    s.add_argument("--marker-prefix", default="rt", help="prefix for the auto marker")
    s.add_argument("--no-marker", action="store_true", help="send the body verbatim, no marker")

    r = sub.add_parser("read", help="structural read-back of recent messages")
    r.add_argument("--chat", type=int, required=True, help="chat id")
    r.add_argument("--thread", type=int, help="forum topic id filter")
    r.add_argument("--limit", type=int, default=10, help="messages to fetch (default 10)")

    args = p.parse_args(argv)
    if args.cmd == "whoami":
        return cmd_whoami(args)
    if args.cmd == "send":
        return cmd_send(args)
    if args.cmd == "read":
        return cmd_read(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
