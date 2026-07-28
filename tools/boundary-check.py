#!/usr/bin/env python3
"""Reject task boundaries that overlap with parallel work.

Usage:
  python3 tools/boundary-check.py --batch <file.json>
  python3 tools/boundary-check.py --repo <owner/name> --paths <path>...
  python3 tools/boundary-check.py --self-test
"""

import argparse
import json
import re
import subprocess
import sys
from itertools import combinations
from pathlib import Path

TRUST_FAILURE = 2


def natural_sort_key(value):
    """Return a deterministic, human-friendly key for labels such as #97."""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def validate_boundaries(boundaries):
    """Validate and normalize a task-to-paths mapping."""
    if not isinstance(boundaries, dict):
        raise ValueError("the batch must be a JSON object")

    normalized = {}
    for label, paths in boundaries.items():
        if not isinstance(label, str) or not label:
            raise ValueError("every task label must be a non-empty string")
        if not isinstance(paths, list):
            raise ValueError("boundaries for {!r} must be a list".format(label))
        if any(not isinstance(path, str) or not path for path in paths):
            raise ValueError(
                "every boundary for {!r} must be a non-empty string".format(label)
            )
        normalized[label] = set(paths)
    return normalized


def find_collisions(boundaries):
    """Return all intersecting task pairs and their shared paths."""
    normalized = validate_boundaries(boundaries)
    labels = sorted(normalized, key=natural_sort_key)
    collisions = []
    for left, right in combinations(labels, 2):
        shared = sorted(normalized[left] & normalized[right])
        if shared:
            collisions.append((left, right, shared))
    return collisions


def format_collision(left, right, shared):
    """Render one collision as one chat-readable line."""
    return "{} <> {}: {}".format(left, right, ", ".join(shared))


def report_collisions(collisions):
    """Print collisions and return the guard's conflict/no-conflict exit code."""
    for left, right, shared in collisions:
        print(format_collision(left, right, shared))
    return 1 if collisions else 0


def load_batch(path):
    """Load a batch JSON file, failing closed when it cannot be trusted."""
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("cannot read batch file: {}".format(error)) from error
    validate_boundaries(data)
    return data


def fetch_open_pull_requests(repo):
    """Read every open pull request and its files with one gh invocation."""
    command = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--limit",
        "1000",
        "--json",
        "number,files",
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=True
        )
    except FileNotFoundError as error:
        raise ValueError("gh CLI not found in PATH") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() if error.stderr else "no error output"
        raise ValueError(
            "gh pr list failed with exit {}: {}".format(error.returncode, detail)
        ) from error

    try:
        pull_requests = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError("gh returned malformed JSON") from error
    if not isinstance(pull_requests, list):
        raise ValueError("gh returned an unexpected JSON shape")
    return pull_requests


def pull_request_boundaries(pull_requests):
    """Convert gh pull-request data to a label-to-paths mapping."""
    boundaries = {}
    for pull_request in pull_requests:
        if not isinstance(pull_request, dict):
            raise ValueError("gh returned an invalid pull request entry")
        number = pull_request.get("number")
        files = pull_request.get("files")
        if not isinstance(number, int) or not isinstance(files, list):
            raise ValueError("gh returned an invalid pull request entry")
        paths = []
        for file_entry in files:
            if not isinstance(file_entry, dict):
                raise ValueError("gh returned an invalid file entry for #{}".format(number))
            path = file_entry.get("path")
            if not isinstance(path, str) or not path:
                raise ValueError("gh returned an invalid file path for #{}".format(number))
            paths.append(path)
        boundaries["#{}".format(number)] = paths
    return boundaries


def find_repo_collisions(candidate_paths, pull_requests):
    """Return open pull requests whose files intersect candidate paths."""
    validate_boundaries({"candidate": candidate_paths})
    candidate = set(candidate_paths)
    open_boundaries = validate_boundaries(pull_request_boundaries(pull_requests))
    collisions = []
    for label in sorted(open_boundaries, key=natural_sort_key):
        shared = sorted(candidate & open_boundaries[label])
        if shared:
            collisions.append(("candidate", label, shared))
    return collisions


def run_self_test():
    """Drive the production comparison over real and disjoint fixtures."""
    real_boundaries = {
        "#93": [
            "docs/decisions/adr-20260727-expected-listeners-are-instance-local.md",
            "instance/INSTALL.md",
            "instance/smoke.sh",
        ],
        "#106": ["instance/pr-watch.sh", "instance/smoke.sh"],
        "#97": ["instance/pr-watch.sh"],
        "#107": ["instance/INSTALL.md", "instance/smoke.sh"],
    }
    expected = {
        ("#93", "#106", ("instance/smoke.sh",)),
        ("#93", "#107", ("instance/INSTALL.md", "instance/smoke.sh")),
        ("#106", "#107", ("instance/smoke.sh",)),
        ("#97", "#106", ("instance/pr-watch.sh",)),
    }

    print("real collision fixture:")
    actual_collisions = find_collisions(real_boundaries)
    actual = {
        (left, right, tuple(shared))
        for left, right, shared in actual_collisions
    }
    assert actual == expected, "real collision fixture did not match the four expected pairs"
    actual_exit = report_collisions(actual_collisions)
    assert actual_exit == 1, "real collision fixture must exit 1"
    print("real collision fixture: exit 1 as expected")

    disjoint_boundaries = {
        "task-a": ["tools/alpha.py"],
        "task-b": ["docs/beta.md"],
    }
    print("disjoint fixture:")
    disjoint_collisions = find_collisions(disjoint_boundaries)
    assert disjoint_collisions == [], "disjoint fixture must report no collisions"
    disjoint_exit = report_collisions(disjoint_collisions)
    assert disjoint_exit == 0, "disjoint fixture must exit 0"
    print("(no conflicts)")
    print("disjoint fixture: exit 0 as expected")
    print("self-test ok")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(
        description="Reject intersecting task boundaries before parallel dispatch."
    )
    parser.add_argument("--batch", help="JSON task-to-boundaries mapping")
    parser.add_argument("--repo", help="Repository owner/name")
    parser.add_argument("--paths", nargs="+", help="Candidate repository paths")
    parser.add_argument(
        "--self-test", action="store_true", help="Run deterministic assertions"
    )
    args = parser.parse_args()

    if args.self_test:
        if args.batch or args.repo or args.paths:
            parser.error("--self-test cannot be combined with another mode")
        return args
    if args.batch:
        if args.repo or args.paths:
            parser.error("--batch cannot be combined with --repo or --paths")
        return args
    if args.repo and args.paths:
        return args
    parser.error("use --batch, or use --repo together with --paths")


def main():
    args = parse_args()
    if args.self_test:
        return run_self_test()

    try:
        if args.batch:
            collisions = find_collisions(load_batch(args.batch))
        else:
            pull_requests = fetch_open_pull_requests(args.repo)
            collisions = find_repo_collisions(args.paths, pull_requests)
    except ValueError as error:
        print("error: {}".format(error), file=sys.stderr)
        return TRUST_FAILURE
    return report_collisions(collisions)


if __name__ == "__main__":
    sys.exit(main())
