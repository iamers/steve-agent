#!/usr/bin/env bash
# Drift check: compare the instance's live config with the canonical copy in
# the repository. Report differences; do not restore them.
# Usage: ./drift-check.sh [ssh-alias]
#        ./drift-check.sh --compare-config <repo-yaml> <live-yaml>
set -u

usage() {
  echo "Usage: $0 [ssh-alias]" >&2
  echo "       $0 --compare-config <repo-yaml> <live-yaml>" >&2
}

compare_only=false
if [ "${1:-}" = "--compare-config" ]; then
  if [ "$#" -ne 3 ]; then
    usage
    exit 2
  fi
  compare_only=true
  compare_repo=$2
  compare_live=$3
elif [ "$#" -gt 1 ]; then
  usage
  exit 2
fi

cd "$(dirname "$0")" || exit 1

drift=0
live_cfg=""
sem=""
repo_s=""
live_s=""
# Two top-level blocks exist only on the live instance and must never enter the
# repository, so exclude them from both sides of the comparison:
#  - "dashboard:": basic-auth credentials (password_hash and secret)
#  - "onboarding:": first-run flags (onboarding.seen.*) written at runtime by
#    the gateway, not configuration
# Excluding them BEFORE printing any diff is also a security guarantee: no hash
# or secret can appear in the check output.
#
# The comparison is SEMANTIC (parsed YAML, sorted keys), not textual.
# Reason: Hermes writes the live file and removes ALL comments and normalizes
# quotation marks whenever it rewrites the config (measured on 2026-07-25: live
# file with 0 comment lines, canonical file with 24, identical functional
# content). A textual comparison would require two artifacts with different
# owners to match byte for byte and would force us to strip useful reader
# documentation from the canonical file. The semantic comparison catches every
# meaningful difference (keys, values, structure) and ignores only formatting
# we do not control.
# The end-of-block boundary is ANY construct in column 0, not only a key that
# starts with a letter: a top-level YAML key may be quoted ("key": value), and
# malformed content may start with another character. With the old
# /^[A-Za-z_]/ boundary, those lines remained inside the block and were
# SWALLOWED, so the guard reported "no drift" for a file with extra top-level
# content: a false negative.
# Comments in column 0 DO NOT close the block (a comment inside dashboard must
# not make the block's subsequent lines reappear).
strip_blocks='/^(dashboard|onboarding):/{skip=1; next} /^[^[:space:]#]/{skip=0} !skip'

compare_config() {
  repo_cfg=$1
  live_cfg_to_compare=$2

  if python3 -c 'import yaml' 2>/dev/null; then
    sem=$(mktemp)
    trap 'rm -f "$live_cfg" "$sem" "$repo_s" "$live_s"' EXIT
    cat > "$sem" <<'PY'
import sys, json, difflib, re, yaml

INSTANCE_ONLY = ("dashboard", "onboarding")
ENV_MATERIALIZED = (
    "platforms.telegram.extra.allow_admin_from",
    "platforms.telegram.extra.group_allow_admin_from",
)
INSTANCE_LOCAL_PREFERENCES = (
    "approvals.destructive_slash_confirm",
)
MISSING = object()


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that REJECTS duplicate keys.

    By itself, yaml.safe_load silently keeps the last occurrence of a repeated
    key. In a semantic comparison this would create a gap: a live file with a
    duplicate key whose LAST value matches the canonical one would be reported
    as aligned even though the file is actually different and malformed. The
    textual comparison detected this; this loader detects it by failing CLOSED,
    reporting drift instead of remaining silent.
    """


class DuplicateKey(Exception):
    """Duplicate key. Carries ONLY its position, never its name.

    The name is deliberately NOT retained. It seemed like "structure rather
    than content", but a key inside an instance-only block may itself be
    sensitive, and errors are emitted BEFORE pop() removes that block. One
    exception to the "never include text taken from the document" rule was
    enough to reopen the gap that the rule closed: there are no exceptions here.
    """

    def __init__(self, mark):
        self.line = None if mark is None else mark.line + 1
        self.column = None if mark is None else mark.column + 1


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKey(key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def load(path, label):
    # The instance-only blocks have already been removed UPSTREAM, before this
    # point: see the awk filter applied to both sides. This is deliberate, not
    # redundant. If we removed them after parsing, a parser error INSIDE an
    # excluded block would be formatted and printed before the exclusion,
    # carrying the offending token with it: a dashboard hash or secret would
    # appear in the check output. Removing the blocks first ensures that their
    # content never reaches the parser.
    # A parser error must NEVER report text taken from the document: the PyYAML
    # message quotes the offending token, which may be inside an instance-only
    # block (a password_hash or secret). Therefore print only TYPE and POSITION.
    # This ensures confidentiality no longer depends on lexically recognizing
    # the blocks to exclude before parsing, a losing battle given YAML's many
    # equivalent spellings.
    try:
        data = yaml.load(open(path), Loader=StrictLoader) or {}
    except DuplicateKey as exc:
        where = "" if exc.line is None else f" at line {exc.line}, column {exc.column}"
        print(f"{label}: duplicate key{where}")
        sys.exit(1)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        where = "" if mark is None else f" at line {mark.line + 1}, column {mark.column + 1}"
        print(f"{label}: invalid YAML{where}")
        sys.exit(1)
    for key in INSTANCE_ONLY:
        data.pop(key, None)  # after parsing, every spelling collapses here
    return data


def get_path(data, path):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def drop_path(data, path):
    parts = path.split(".")
    current = data
    parents = []
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        parents.append((current, part))
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    for parent, part in reversed(parents):
        if parent.get(part) == {}:
            parent.pop(part)
        else:
            break


def leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)
    else:
        yield value


def contains_env_reference(value):
    return any(
        isinstance(item, str) and re.fullmatch(r"\$\{[^}]+\}", item)
        for item in leaves(value)
    )


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list)):
        return not value
    return False


def contains_unexpanded_reference(value):
    return any(
        isinstance(item, str) and re.search(r"\$\{[^}]+\}", item)
        for item in leaves(value)
    )


repo_data, live_data = load(sys.argv[1], "repo"), load(sys.argv[2], "live")
shape_drift = False
for path in ENV_MATERIALIZED:
    repo_value = get_path(repo_data, path)
    live_value = get_path(live_data, path)

    # These values have different owners: the variable reference remains in the
    # repository, while the resolved value must be present on the instance. The
    # forms can be verified without ever printing the content.
    if repo_value is MISSING and live_value is MISSING:
        continue
    if repo_value is MISSING:
        print(f"DRIFT: env-materialized path {path} is missing from the repository")
        shape_drift = True
    elif live_value is MISSING:
        print(f"DRIFT: env-materialized path {path} is missing from the live config")
        shape_drift = True
    else:
        if not contains_env_reference(repo_value):
            print(
                f"DRIFT: repository holds a materialized value for {path}; "
                "the repository is public"
            )
            shape_drift = True
        if is_empty(live_value) or contains_unexpanded_reference(live_value):
            print(
                f"DRIFT: live value for {path} was never expanded; access control "
                "keys in this state disable the administrator"
            )
            shape_drift = True

    # Even on error, values must not reach the semantic diff: the diagnostic
    # above names only the path and the condition.
    drop_path(repo_data, path)
    drop_path(live_data, path)

for path in INSTANCE_LOCAL_PREFERENCES:
    repo_value = get_path(repo_data, path)
    if repo_value is not MISSING:
        print(
            f"DRIFT: instance-local preference {path} is present in the repository; "
            "the blueprint must keep the product default"
        )
        shape_drift = True

    # A live value is a legitimate per-instance choice. Neither value may reach
    # the semantic diff or its output.
    drop_path(repo_data, path)
    drop_path(live_data, path)

repo = json.dumps(repo_data, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
live = json.dumps(live_data, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
semantic_drift = repo != live
if semantic_drift:
    sys.stdout.write("\n".join(difflib.unified_diff(repo, live, "repo", "live", lineterm="")) + "\n")
sys.exit(1 if shape_drift or semantic_drift else 0)
PY
    # Filter instance-only blocks BEFORE parsing so their content never reaches
    # the parser and cannot appear in an error message.
    repo_s=$(mktemp); live_s=$(mktemp)
    trap 'rm -f "$live_cfg" "$sem" "$repo_s" "$live_s"' EXIT
    awk "$strip_blocks" "$repo_cfg" > "$repo_s"
    awk "$strip_blocks" "$live_cfg_to_compare" > "$live_s"
    python3 "$sem" "$repo_s" "$live_s"
    comparator_status=$?
    return "$comparator_status"
  else
    # NO degradation: without pyyaml, do not perform the comparison.
    # The previous textual branch recognized blocks to exclude with a line
    # filter, but YAML allows many equivalent spellings of the same key
    # ("dashboard":, 'dashboard':, dashboard :, tagged or explicit forms). With
    # an unrecognized spelling, the block remained in the diff WITH ITS VALUES,
    # so password_hash and secret appeared in the check output. This is not a
    # noisier comparison: it is a weaker one, and that is not an acceptable
    # compromise for a guard that handles secrets.
    # Therefore fail CLOSED and provide an actionable error: being unable to
    # verify is not "no drift"; it is a check that did not run and must count as
    # such.
    echo "ERROR: pyyaml is required to compare config.yaml safely."
    echo "       Install it (e.g. 'pip install --user pyyaml') and re-run."
    echo "       Refusing to fall back to a textual compare: it cannot exclude"
    echo "       instance-only blocks reliably and would print their values."
    return 1
  fi
}

if "$compare_only"; then
  compare_config "$compare_repo" "$compare_live"
  exit $?
fi

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"

echo "== config.yaml (live vs repo) =="
live_cfg=$(mktemp)
trap 'rm -f "$live_cfg" "$sem" "$repo_s" "$live_s"' EXIT
ssh "$HOST" 'cat ~/.hermes/config.yaml' > "$live_cfg"

if compare_config config.yaml "$live_cfg"; then
  echo "OK: config.yaml aligned (semantic compare; dashboard/onboarding excluded)"
else
  drift=1
fi

echo
echo "== SOUL.md (live vs repo) =="
if ssh "$HOST" 'cat ~/.hermes/SOUL.md 2>/dev/null' | diff -u SOUL.md - ; then
  echo "OK: SOUL.md aligned"
else
  drift=1
fi

echo
echo "== SOUL profiles (live vs repo) =="
# Compare each worker profile's canonical SOUL.md with its live copy.
for profile in steve-worker steve-reviewer; do
  canonical="profiles/$profile/SOUL.md"
  if [ ! -f "$canonical" ]; then
    echo "DRIFT: $profile — missing canonical copy ($canonical)"
    drift=1
    continue
  fi
  if ssh "$HOST" "cat ~/.hermes/profiles/$profile/SOUL.md 2>/dev/null" | diff -u "$canonical" - ; then
    echo "OK: $profile SOUL.md aligned"
  else
    drift=1
  fi
done

echo
echo "== .env: keys set (names, not values) =="
# Optional keys (marked "@optional" in the env.template line comment) are not
# required (for example, the entire merge-gate block). Their absence or presence
# on the instance is legitimate, so they do NOT create drift: they are excluded
# from the missing/extra comparison and reported only as an informational line.
optional_keys=$(grep -E '^[A-Z_]+=.*@optional' env.template | grep -oE '^[A-Z_]+' | sort -u)
# filter_optional: remove optional keys from an already sorted set. If the list
# is empty, return the input unchanged: grep -f with an empty file has no
# patterns, but `echo "$empty"` would produce an empty line that, with -v, would
# exclude everything—hence the explicit guard.
filter_optional() {
  if [ -n "$optional_keys" ]; then
    grep -vxF -f <(printf '%s\n' "$optional_keys")
  else
    cat
  fi
}
live_keys=$(ssh "$HOST" 'grep -oE "^[A-Z_]+=" ~/.hermes/.env | sort -u' | tr -d =)
tmpl_keys=$(grep -oE '^[A-Z_]+=' env.template | tr -d = | sort -u | filter_optional)
live_filtered=$(echo "$live_keys" | filter_optional)
missing=$(comm -23 <(echo "$tmpl_keys") <(echo "$live_filtered"))
extra=$(comm -13 <(echo "$tmpl_keys") <(echo "$live_filtered"))
[ -n "$missing" ] && { echo "MISSING on instance:"; echo "$missing"; drift=1; }
[ -n "$extra" ]   && { echo "PRESENT live but not in template (consider whether to add them):"; echo "$extra"; drift=1; }
[ -z "$missing$extra" ] && echo "OK: keys aligned"

# Optional keys: informational only, NEVER drift.
if [ -n "$optional_keys" ]; then
  opt_set=$(comm -12 <(echo "$optional_keys") <(echo "$live_keys"))
  opt_unset=$(comm -23 <(echo "$optional_keys") <(echo "$live_keys"))
  [ -n "$opt_set" ]   && echo "optional keys set on instance: $(echo "$opt_set" | paste -sd, -)"
  [ -n "$opt_unset" ] && echo "optional keys not set on instance: $(echo "$opt_unset" | paste -sd, -)"
fi

echo
echo "== worker profiles =="
# Get the profile list from the instance.
profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')

if [ -z "$profiles" ]; then
  echo "OK: no profiles present"
else
  profiles_ok=true
  for profile in $profiles; do
    # Read the mode from the canonical repository copy (default: shared).
    mode_file="profiles/$profile/credentials.mode"
    if [ -f "$mode_file" ]; then
      mode=$(cat "$mode_file")
    else
      mode="shared"
    fi

    if [ "$mode" = "shared" ]; then
      # shared mode: verify symlinks as before.
      gitconfig_check=$(ssh "$HOST" "[ -L ~/.hermes/profiles/$profile/home/.gitconfig ] && [ \"\$(readlink ~/.hermes/profiles/$profile/home/.gitconfig)\" = ~/.gitconfig ] && echo OK || echo FAIL")
      ghconfig_check=$(ssh "$HOST" "[ -L ~/.hermes/profiles/$profile/home/.config/gh ] && [ \"\$(readlink ~/.hermes/profiles/$profile/home/.config/gh)\" = ~/.config/gh ] && echo OK || echo FAIL")

      if [ "$gitconfig_check" = "OK" ] && [ "$ghconfig_check" = "OK" ]; then
        echo "OK: $profile (shared, symlinks correct)"
      else
        echo "DRIFT: $profile (shared, symlinks missing or wrong)"
        echo "  - .gitconfig: $gitconfig_check"
        echo "  - .config/gh: $ghconfig_check"
        echo "  Run on the instance: cd ~/repos/steve-agent && ./instance/provision-worker.sh $profile"
        drift=1
        profiles_ok=false
      fi
    elif [ "$mode" = "isolated" ]; then
      # isolated mode: verify that credentials are isolated.
      # 1) home/.config/gh must be a real directory (not a symlink) containing hosts.yml.
      ghconfig_check=$(ssh "$HOST" "[ -d ~/.hermes/profiles/$profile/home/.config/gh ] && [ ! -L ~/.hermes/profiles/$profile/home/.config/gh ] && [ -f ~/.hermes/profiles/$profile/home/.config/gh/hosts.yml ] && echo OK || echo FAIL")
      # 2) home/.gitconfig must NOT be a symlink (absent or a regular file = OK).
      gitconfig_check=$(ssh "$HOST" "[ ! -L ~/.hermes/profiles/$profile/home/.gitconfig ] && echo OK || echo FAIL")

      if [ "$gitconfig_check" = "OK" ] && [ "$ghconfig_check" = "OK" ]; then
        echo "OK: $profile (isolated, credentials isolated)"
      else
        echo "DRIFT: $profile (isolated, credentials non-compliant)"
        echo "  - .gitconfig: $gitconfig_check (must be absent or a regular file, NOT a symlink)"
        echo "  - .config/gh: $ghconfig_check (must be a real directory containing hosts.yml)"
        echo "  For isolated profiles use: HOME=~/.hermes/profiles/$profile/home gh auth login"
        echo "  Do NOT run provision-worker.sh for isolated profiles"
        drift=1
        profiles_ok=false
      fi
    else
      echo "DRIFT: $profile (invalid mode: $mode, must be 'shared' or 'isolated')"
      drift=1
      profiles_ok=false
    fi
  done

  if $profiles_ok; then
    echo "OK: all profiles compliant"
  fi
fi

echo
echo "== profiles: config.yaml (live vs repo) =="

# Live profiles on the instance.
live_profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')
# Canonical repository copies (profiles/<name>/config.yaml).
canonical_profiles=$(find profiles -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort -u)

# No live profiles and no canonical copies = OK.
if [ -z "$live_profiles" ] && [ -z "$canonical_profiles" ]; then
  echo "OK: no live profiles and no canonical copy"
else
  # 1) For each live profile, verify its canonical copy and compare config.yaml.
  for profile in $live_profiles; do
    canonical="profiles/$profile/config.yaml"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/profiles/$profile/config.yaml" | diff -u "$canonical" - ; then
        echo "OK: $profile config.yaml aligned"
      else
        drift=1
      fi
    else
      echo "DRIFT: profile $profile live without canonical copy in repo"
      drift=1
    fi
  done

  # 2) Check each canonical copy without a corresponding live profile.
  for profile in $canonical_profiles; do
    if ! echo "$live_profiles" | grep -qx "$profile"; then
      echo "DRIFT: canonical $profile without live profile"
      drift=1
    fi
  done
fi

echo
echo "== skill: SKILL.md (live vs repo) =="

# Stock skills bundled with Hermes, installed by default and NOT managed by
# steve-agent: excluded from the drift check (they are legitimate on the
# instance without a canonical repository copy). The list corresponds to the
# top-level skill directories under ~/.hermes/skills/. Keep it updated when
# Hermes adds bundled skills: to recalculate it, list the live top-level
# directories with `ls -d ~/.hermes/skills/*/` and keep everything except the
# skills managed by steve-agent (for example, steve-factory).
stock_skills='apple|autonomous-ai-agents|computer-use|creative|data-science|dogfood|email|github|hermes-desktop-plugins|media|mlops|note-taking|productivity|research|smart-home|social-media|software-development|yuanbao'

# Live skills on the instance (excluding stock skills).
live_skills=$(ssh "$HOST" 'ls -d ~/.hermes/skills/*/ 2>/dev/null | xargs -n1 basename | sort -u' | grep -Ev "^($stock_skills)$")
# Canonical repository copies (skills/<name>/SKILL.md).
canonical_skills=$(find skills -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort -u)

# No live skills and no canonical copies = OK.
if [ -z "$live_skills" ] && [ -z "$canonical_skills" ]; then
  echo "OK: no skills present"
else
  # 1) For each live skill, verify its canonical copy and compare SKILL.md.
  for skill in $live_skills; do
    canonical="skills/$skill/SKILL.md"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/skills/$skill/SKILL.md" | diff -u "$canonical" - ; then
        echo "OK: $skill SKILL.md aligned"
      else
        drift=1
      fi
    else
      echo "DRIFT: skill $skill live without canonical copy in repo"
      drift=1
    fi
  done

  # 2) Check each canonical copy without a corresponding live skill.
  for skill in $canonical_skills; do
    if ! echo "$live_skills" | grep -qx "$skill"; then
      echo "DRIFT: canonical $skill without live skill"
      drift=1
    fi
  done
fi

echo "----"
if [ "$drift" -eq 0 ]; then echo "drift-check: no drift"; else echo "drift-check: DRIFT DETECTED (update repo or instance, and log it in the journal)"; fi
exit $drift
