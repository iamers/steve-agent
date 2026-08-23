#!/usr/bin/env python3
"""Block reviewer tools when the task omitted the required review skill."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile


REQUIRED_ASSIGNEE = "steve-reviewer"
REQUIRED_SKILL = "github/github-code-review"
BLOCK_MESSAGE = (
    "Review task contract check failed: the created event must assign the card "
    f"to {REQUIRED_ASSIGNEE} with skill {REQUIRED_SKILL}. "
    "Call kanban_block with kind=capability and stop; do not bypass this guard."
)


class ContractError(Exception):
    """The current task cannot prove the required review contract."""


def read_created_payload(database: str, task_id: str) -> dict:
    """Read the immutable created-event payload from the pinned board."""
    if not database or not task_id:
        raise ContractError("missing dispatcher task context")

    try:
        database_uri = Path(database).expanduser().resolve().as_uri() + "?mode=ro"
        # Never let SQLite's default five-second busy wait race the five-second
        # hook timeout. A locked board is a validation failure and must block.
        connection = sqlite3.connect(database_uri, uri=True, timeout=0)
        try:
            row = connection.execute(
                "SELECT payload FROM task_events "
                "WHERE task_id = ? AND kind = 'created' "
                "ORDER BY id ASC LIMIT 1",
                (task_id,),
            ).fetchone()
        finally:
            connection.close()
    except (OSError, sqlite3.Error) as exc:
        raise ContractError("board event log is unavailable") from exc

    if row is None:
        raise ContractError("created event is missing")
    try:
        payload = json.loads(row[0])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ContractError("created event payload is malformed") from exc
    if not isinstance(payload, dict):
        raise ContractError("created event payload is not an object")
    return payload


def require_review_contract(payload: dict) -> None:
    """Require the exact assignee and bundled skill recorded at creation."""
    if payload.get("assignee") != REQUIRED_ASSIGNEE:
        raise ContractError("created event has the wrong assignee")
    skills = payload.get("skills")
    if not isinstance(skills, list) or REQUIRED_SKILL not in skills:
        raise ContractError("created event omits the required review skill")


def emit_block() -> None:
    print(json.dumps({"action": "block", "message": BLOCK_MESSAGE}))


def run_hook() -> int:
    try:
        # Consume Hermes' hook payload so the parent never writes into a closed
        # pipe. Input failures must block too: hook process errors fail open.
        sys.stdin.read()
        payload = read_created_payload(
            os.environ.get("HERMES_KANBAN_DB", ""),
            os.environ.get("HERMES_KANBAN_TASK", ""),
        )
        require_review_contract(payload)
    except Exception:
        # Hermes shell hooks are fail-open on non-zero exits and malformed output.
        # Always return a valid block directive for every validation failure.
        emit_block()
    return 0


def create_fixture(path: Path, payload: dict | None) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE task_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "task_id TEXT NOT NULL, run_id INTEGER, kind TEXT NOT NULL, "
            "payload TEXT, created_at INTEGER NOT NULL)"
        )
        if payload is not None:
            connection.execute(
                "INSERT INTO task_events "
                "(task_id, run_id, kind, payload, created_at) "
                "VALUES (?, NULL, 'created', ?, 1)",
                ("t_review", json.dumps(payload)),
            )
        connection.commit()
    finally:
        connection.close()


def invoke_fixture(database: Path | None) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["HERMES_KANBAN_TASK"] = "t_review"
    if database is None:
        environment["HERMES_KANBAN_DB"] = "/does/not/exist/kanban.db"
    else:
        environment["HERMES_KANBAN_DB"] = str(database)
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input='{"hook_event_name":"pre_tool_call","tool_name":"terminal"}',
        text=True,
        capture_output=True,
        env=environment,
        timeout=10,
        check=False,
    )


def run_self_test_in(fixture_root: Path) -> int:
    valid_database = fixture_root / "valid.db"
    missing_skill_database = fixture_root / "missing-skill.db"
    missing_event_database = fixture_root / "missing-event.db"

    create_fixture(
        valid_database,
        {"assignee": REQUIRED_ASSIGNEE, "skills": [REQUIRED_SKILL]},
    )
    create_fixture(
        missing_skill_database,
        {"assignee": REQUIRED_ASSIGNEE, "skills": None},
    )
    create_fixture(missing_event_database, None)

    failures = 0

    def check(label: str, condition: bool) -> None:
        nonlocal failures
        if condition:
            print(f"ok: {label}")
        else:
            print(f"not ok: {label}")
            failures += 1

    try:
        import yaml

        config = yaml.safe_load(Path(__file__).with_name("config.yaml").read_text())
        hook = config["hooks"]["pre_tool_call"][0]
        matcher = re.compile(hook["matcher"])
        config_connected = (
            hook["command"]
            == "~/.hermes/profiles/steve-reviewer/review-task-guard.py"
            and hook["timeout"] == 5
            and os.access(Path(__file__), os.X_OK)
        )
        matcher_scoped = (
            matcher.fullmatch("kanban_show") is None
            and matcher.fullmatch("kanban_block") is None
            and matcher.fullmatch("kanban_complete") is not None
            and matcher.fullmatch("terminal") is not None
        )
    except Exception:
        config_connected = False
        matcher_scoped = False

    check("reviewer config registers the executable guard", config_connected)
    check("matcher permits only inspection and blocking", matcher_scoped)
    worker_soul = Path(__file__).parent.parent / "steve-worker" / "SOUL.md"
    try:
        worker_contract = (
            f'skills: ["{REQUIRED_SKILL}"]' in worker_soul.read_text()
        )
    except OSError:
        worker_contract = False
    check("worker directive sets the structured review skill", worker_contract)

    valid = invoke_fixture(valid_database)
    check(
        "required skill allows reviewer tools",
        valid.returncode == 0 and valid.stdout == "" and valid.stderr == "",
    )

    lock_connection = sqlite3.connect(valid_database, isolation_level=None)
    try:
        lock_connection.execute("BEGIN EXCLUSIVE")
        locked = invoke_fixture(valid_database)
    finally:
        lock_connection.rollback()
        lock_connection.close()
    check(
        "locked board fails closed before the hook timeout",
        locked.returncode == 0
        and json.loads(locked.stdout).get("action") == "block",
    )

    missing_skill = invoke_fixture(missing_skill_database)
    try:
        missing_skill_output = json.loads(missing_skill.stdout)
    except json.JSONDecodeError:
        missing_skill_output = {}
    check(
        "missing skill blocks reviewer tools",
        missing_skill.returncode == 0
        and missing_skill_output.get("action") == "block",
    )
    check(
        "missing skill names the required contract",
        REQUIRED_SKILL in missing_skill_output.get("message", ""),
    )

    missing_event = invoke_fixture(missing_event_database)
    check(
        "missing created event fails closed",
        missing_event.returncode == 0
        and json.loads(missing_event.stdout).get("action") == "block",
    )

    unavailable = invoke_fixture(None)
    check(
        "unavailable board fails closed",
        unavailable.returncode == 0
        and json.loads(unavailable.stdout).get("action") == "block",
    )

    if failures:
        print(f"self-test FAILED: {failures} assertion(s) failed")
        return 1
    print("self-test ok")
    return 0


def run_self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="steve-review-task-guard-") as root:
        return run_self_test_in(Path(root))


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return run_self_test()
    if sys.argv[1:]:
        print("Usage: review-task-guard.py [--self-test]", file=sys.stderr)
        return 2
    return run_hook()


if __name__ == "__main__":
    raise SystemExit(main())
