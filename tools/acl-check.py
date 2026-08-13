#!/usr/bin/env python3
"""acl-check: asserts the publishable half of the ACL configuration.

Covers command names, which configuration keys must exist, and structural
relationships between keys: whether the Telegram command tiers still match
.steve/acl-policy.yaml (which commands stay open to a non-admin user; every
other command is reserved to whoever the admin key resolves to), whether the
worker profile still carries no Telegram surface, whether the access-control
env keys are still mandatory in instance/env.template, and whether the
worker/reviewer credentials.mode files still encode separate identities.

Nothing here reads or asserts an account, chat id or user id. Those are
identity-bearing and are covered on the deployment side, against a baseline
that never enters this repository: see .steve/acl-identity-keys.txt and
instance/drift-check.sh.

Usage:
  python3 tools/acl-check.py --self-test
"""
import argparse
import subprocess
import sys
from pathlib import Path

import yaml

POLICY_PATH = ".steve/acl-policy.yaml"
IDENTITY_KEYS_PATH = ".steve/acl-identity-keys.txt"
ENV_TEMPLATE_PATH = "instance/env.template"

MISSING = object()


def find_repo_root():
    """Finds the repo root by locating .steve/acl-policy.yaml upward from cwd."""
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        if (p / POLICY_PATH).is_file():
            return p
    # Fallback: tools/acl-check.py -> the repo root is one level up.
    script_root = Path(__file__).resolve().parent.parent
    if (script_root / POLICY_PATH).is_file():
        return script_root
    return None


def get_path(data, dotted):
    """Walks a dotted path through nested dicts. Returns MISSING if absent."""
    current = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


# ---------------------------------------------------------------------------
# Pure assertion functions: operate on already-parsed data, no file I/O.
# Each returns a list of problem strings; an empty list means compliant.
# ---------------------------------------------------------------------------

def check_command_tiers(config_data, tiers, label):
    """Each scope's admin key must be present and non-empty, and its open-
    command list must match the policy exactly (as a set: order is not
    load-bearing for a permission list)."""
    problems = []
    for scope, spec in tiers.items():
        admin_value = get_path(config_data, spec["admin_key"])
        if admin_value is MISSING or not admin_value:
            problems.append(
                "{}: {} scope's admin key {} is missing or empty "
                "(that scope's command tiering is not gated by anyone)".format(
                    label, scope, spec["admin_key"]))
        elif not isinstance(admin_value, list):
            # Truthiness is not a shape: `true` is truthy and gates nobody.
            problems.append(
                "{}: {} scope's admin key {} is {}, expected a list".format(
                    label, scope, spec["admin_key"], type(admin_value).__name__))
        open_value = get_path(config_data, spec["open_commands_key"])
        if open_value is MISSING:
            problems.append("{}: {} scope's open-commands key {} is missing".format(
                label, scope, spec["open_commands_key"]))
        elif not isinstance(open_value, list) or not all(
                isinstance(c, str) for c in open_value):
            # The container must be checked before its contents: a mapping with
            # the same keys, or a bare string, compares equal as a set and would
            # pass while meaning something else entirely to the runtime.
            problems.append(
                "{}: {} scope's open-commands key {} is {}, expected a list of "
                "strings".format(label, scope, spec["open_commands_key"],
                                 type(open_value).__name__))
        elif set(open_value) != set(spec["open_commands"]):
            problems.append(
                "{}: {} scope's open commands are {}, expected {}".format(
                    label, scope, sorted(open_value), sorted(spec["open_commands"])))
    return problems


def check_no_telegram_surface(config_data, label):
    """The profile must carry no platforms.telegram block at all."""
    if get_path(config_data, "platforms.telegram") is not MISSING:
        return ["{}: carries a platforms.telegram block (must have none)".format(label)]
    return []


def check_required_env_keys(template_text, required_keys):
    """A key is mandatory unless its KEY= line carries the @optional marker
    (the same convention instance/drift-check.sh already reads)."""
    problems = []
    lines = template_text.splitlines()
    for key in required_keys:
        line = next((ln for ln in lines if ln.startswith(key + "=")), None)
        if line is None:
            problems.append("{}: required key {} is not declared".format(
                ENV_TEMPLATE_PATH, key))
        elif "@optional" in line:
            problems.append(
                "{}: required key {} is marked @optional (its absence would "
                "no longer count as drift)".format(ENV_TEMPLATE_PATH, key))
    return problems


def check_credentials_mode(modes, valid_values, required):
    """modes: {profile_relpath: mode_string_or_None}."""
    problems = []
    for profile, mode in modes.items():
        if mode not in valid_values:
            problems.append(
                "{}/credentials.mode: {!r} is not one of {}".format(
                    profile, mode, valid_values))
    for profile, expected in required.items():
        actual = modes.get(profile)
        if actual != expected:
            problems.append(
                "{}/credentials.mode: is {!r}, must be {!r}".format(
                    profile, actual, expected))
    return problems


def check_conversation_prerequisites(config_data, spec, label):
    """Configuration cannot prove an ordinary message gets a coherent reply --
    that is runtime. It can prove the prerequisites are still declared: a
    primary model, a provider for it, and a non-empty fallback chain. Remove
    any of them and an ordinary reply stops arriving."""
    problems = []
    for dotted in spec.get("required_paths", []):
        value = get_path(config_data, dotted)
        if value is MISSING or value in (None, ""):
            problems.append(
                "{}: {} is missing or empty (an ordinary message would have no "
                "model to answer it)".format(label, dotted))
    for dotted in spec.get("non_empty_list_paths", []):
        value = get_path(config_data, dotted)
        if value is MISSING or not isinstance(value, list) or not value:
            problems.append(
                "{}: {} must be a non-empty list (no fallback chain left)".format(
                    label, dotted))
    return problems


def tracked_files(root):
    """What the repository ships is `git ls-files`, not a directory walk with
    exclusions: the second is right on the day it is written and quietly wrong
    afterwards."""
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def check_baseline_not_tracked(tracked_paths, baseline_name):
    """The identity baseline holds UNSALTED hashes of identity values. A numeric
    account id has a small enough space that an unsalted hash is recoverable in
    seconds, so the whole design rests on that file never leaving the deployment.
    The privacy guard cannot enforce it: the guard matches values, and a hash is
    not its value. So the assertion lives here, where it can fail."""
    problems = []
    for path in tracked_paths:
        if Path(path).name == baseline_name:
            problems.append(
                "{}: the identity baseline must never be tracked -- it holds "
                "unsalted hashes of identity values".format(path))
    return problems


def check_identity_keys_declared(identity_keys, template_text):
    """Every identity-bearing key tracked on the deployment side must also be
    a real key in env.template: otherwise the deployment could baseline a key
    that no installation guide ever tells anyone to set."""
    problems = []
    lines = template_text.splitlines()
    declared = {
        ln.split("=", 1)[0] for ln in lines
        if "=" in ln and not ln.lstrip().startswith("#")
    }
    for key in identity_keys:
        if key not in declared:
            problems.append(
                "{}: {} is tracked as identity-bearing but not declared in {}".format(
                    IDENTITY_KEYS_PATH, key, ENV_TEMPLATE_PATH))
    return problems


# ---------------------------------------------------------------------------
# File loading
# ---------------------------------------------------------------------------

def load_policy(root):
    with open(root / POLICY_PATH) as f:
        return yaml.safe_load(f)


def load_identity_keys(root):
    keys = []
    with open(root / IDENTITY_KEYS_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                keys.append(line)
    return keys


def load_config(root, rel_path):
    with open(root / rel_path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# Self-test: fixture assertions (prove each check can fail on data the real
# repo never supplies) plus the real check against this repository's files.
# ---------------------------------------------------------------------------

def run_self_test():
    failures = []

    def expect(label, problems, want_clean):
        if want_clean and problems:
            failures.append("FAIL {}: expected no problems, got {}".format(label, problems))
        elif not want_clean and not problems:
            failures.append(
                "FAIL {}: expected a problem, got none (the check examined nothing, "
                "or approved a bad input)".format(label))
        else:
            print("ok: {} -> {}".format(label, problems if problems else "clean"))

    # --- Fixture-based: independent dummy data, unrelated to the real
    # policy/config below, so a mutation of the real files cannot
    # coincidentally make both sides of these assertions agree.
    tiers = {
        "dm": {"admin_key": "a.b", "open_commands_key": "a.c", "open_commands": ["x", "y"]},
    }
    good = {"a": {"b": ["${ADMIN}"], "c": ["x", "y"]}}
    expect("command tiers: matching fixture is clean",
           check_command_tiers(good, tiers, "fixture"), want_clean=True)

    bad_extra_command = {"a": {"b": ["${ADMIN}"], "c": ["x", "y", "eval"]}}
    expect("command tiers: an extra open command is flagged",
           check_command_tiers(bad_extra_command, tiers, "fixture"), want_clean=False)

    bad_empty_admin = {"a": {"b": [], "c": ["x", "y"]}}
    expect("command tiers: an emptied admin key is flagged",
           check_command_tiers(bad_empty_admin, tiers, "fixture"), want_clean=False)

    bad_missing_admin = {"a": {"c": ["x", "y"]}}
    expect("command tiers: a removed admin key is flagged",
           check_command_tiers(bad_missing_admin, tiers, "fixture"), want_clean=False)

    expect("no-telegram: a clean profile passes",
           check_no_telegram_surface({"agent": {}}, "fixture"), want_clean=True)
    expect("no-telegram: a profile with the surface is flagged",
           check_no_telegram_surface({"platforms": {"telegram": {}}}, "fixture"), want_clean=False)

    template_ok = "TELEGRAM_ALLOWED_USERS=\nTELEGRAM_GROUP_ALLOWED_CHATS=\n"
    expect("required env keys: both present and mandatory is clean",
           check_required_env_keys(
               template_ok, ["TELEGRAM_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_CHATS"]),
           want_clean=True)
    template_optional = "TELEGRAM_ALLOWED_USERS=            # @optional\nTELEGRAM_GROUP_ALLOWED_CHATS=\n"
    expect("required env keys: one silently marked @optional is flagged",
           check_required_env_keys(
               template_optional, ["TELEGRAM_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_CHATS"]),
           want_clean=False)
    template_missing = "TELEGRAM_GROUP_ALLOWED_CHATS=\n"
    expect("required env keys: one removed entirely is flagged",
           check_required_env_keys(
               template_missing, ["TELEGRAM_ALLOWED_USERS", "TELEGRAM_GROUP_ALLOWED_CHATS"]),
           want_clean=False)

    expect("credentials mode: reviewer isolated is clean",
           check_credentials_mode(
               {"w": "shared", "r": "isolated"}, ["shared", "isolated"], {"r": "isolated"}),
           want_clean=True)
    expect("credentials mode: reviewer reverted to shared is flagged",
           check_credentials_mode(
               {"w": "shared", "r": "shared"}, ["shared", "isolated"], {"r": "isolated"}),
           want_clean=False)
    expect("credentials mode: a malformed value is flagged",
           check_credentials_mode(
               {"w": "shared", "r": "public"}, ["shared", "isolated"], {"r": "isolated"}),
           want_clean=False)

    expect("identity keys: a declared key is clean",
           check_identity_keys_declared(["TELEGRAM_ADMIN_ID"], "TELEGRAM_ADMIN_ID=\n"),
           want_clean=True)
    expect("identity keys: an undeclared key is flagged",
           check_identity_keys_declared(["TELEGRAM_ADMIN_ID"], "OTHER_KEY=\n"),
           want_clean=False)

    expect("tiers: a mapping with the right keys is not a list",
           check_command_tiers(
               {"a": {"k": ["x"], "o": {"status": 1, "whoami": 2}}},
               {"g": {"admin_key": "a.k", "open_commands_key": "a.o",
                      "open_commands": ["status", "whoami"]}}, "x"),
           want_clean=False)
    expect("tiers: a truthy non-list admin gate is flagged",
           check_command_tiers(
               {"a": {"k": True, "o": ["status", "whoami"]}},
               {"g": {"admin_key": "a.k", "open_commands_key": "a.o",
                      "open_commands": ["status", "whoami"]}}, "x"),
           want_clean=False)

    expect("conversation: declared prerequisites are clean",
           check_conversation_prerequisites(
               {"model": {"default": "m", "provider": "p"}, "fallback_model": [{"model": "f"}]},
               {"required_paths": ["model.default", "model.provider"],
                "non_empty_list_paths": ["fallback_model"]}, "x"),
           want_clean=True)
    expect("conversation: an empty fallback chain is flagged",
           check_conversation_prerequisites(
               {"model": {"default": "m", "provider": "p"}, "fallback_model": []},
               {"required_paths": ["model.default", "model.provider"],
                "non_empty_list_paths": ["fallback_model"]}, "x"),
           want_clean=False)

    expect("baseline: a tree without the baseline is clean",
           check_baseline_not_tracked(
               ["instance/drift-check.sh", ".steve/acl-policy.yaml"], "b.sha256"),
           want_clean=True)
    expect("baseline: a tracked baseline is flagged wherever it sits",
           check_baseline_not_tracked(
               ["docs/notes/b.sha256"], "b.sha256"),
           want_clean=False)

    # --- Real repo: the actual files must be clean right now.
    root = find_repo_root()
    if root is None:
        print("error: {} not found".format(POLICY_PATH), file=sys.stderr)
        sys.exit(1)
    policy = load_policy(root)
    identity_keys = load_identity_keys(root)
    template_text = (root / ENV_TEMPLATE_PATH).read_text()

    real_problems = []
    for rel_path in policy["tiered_config_files"]:
        data = load_config(root, rel_path)
        real_problems += check_command_tiers(data, policy["telegram_command_tiers"], rel_path)
    for rel_path in policy["untiered_config_files"]:
        data = load_config(root, rel_path)
        real_problems += check_no_telegram_surface(data, rel_path)
    real_problems += check_required_env_keys(template_text, policy["required_env_keys"])
    real_problems += check_identity_keys_declared(identity_keys, template_text)
    real_problems += check_baseline_not_tracked(
        tracked_files(root), policy["identity_baseline_filename"])
    conv = policy["conversation_prerequisites"]
    real_problems += check_conversation_prerequisites(
        load_config(root, conv["config_file"]), conv, conv["config_file"])

    modes = {}
    for profile_dir in sorted((root / "instance" / "profiles").iterdir()):
        mode_file = profile_dir / "credentials.mode"
        if mode_file.is_file():
            rel = str(profile_dir.relative_to(root))
            modes[rel] = mode_file.read_text().strip()
    cred_policy = policy["credentials_mode"]
    real_problems += check_credentials_mode(
        modes, cred_policy["valid_values"], cred_policy["required"])

    if real_problems:
        for p in real_problems:
            print("PROBLEM: {}".format(p))
        failures.append("FAIL: the real repository does not match .steve/acl-policy.yaml")
    else:
        print(
            "ok: real repository matches .steve/acl-policy.yaml "
            "({} tiered config file(s), {} untiered, {} required env key(s), "
            "{} identity key(s), {} profile(s))".format(
                len(policy["tiered_config_files"]), len(policy["untiered_config_files"]),
                len(policy["required_env_keys"]), len(identity_keys), len(modes)))

    if failures:
        for f in failures:
            print(f)
        print("self-test FAILED: {} assertion(s) failed".format(len(failures)))
        sys.exit(1)
    print("self-test ok")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(
        description="Asserts the publishable half of the ACL configuration.")
    parser.add_argument("--self-test", action="store_true",
                        help="Run fixture assertions plus the real check against this repo")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is the only supported mode")
    run_self_test()


if __name__ == "__main__":
    main()
