#!/usr/bin/env python3
"""workflow-check: asserts that both Open Table entry points serialise together.

The reduction's first adapter obligation is that runs for one session never
execute concurrently. On GitHub that holds because concurrency group names are
repository-scoped rather than workflow-scoped, so the event-driven entry point
and the periodic sweep enter the same serialisation domain when they resolve to
the same group name for the same session.

What this checks is the **resolved** key for representative values, never the
source expressions. The two expressions necessarily differ: a scheduled event
carries no `github.event.issue`, so the sweep reads a matrix value instead, and
a sweep that copied the event-driven expression verbatim would resolve its issue
component to empty. An earlier version of this obligation asked for the two
expressions to be byte-identical, which would have enforced exactly that defect
while passing, because two identical strings agree whether or not either is
correct.

It also refuses a second construction site: no workflow outside the reusable one
may declare an `open-table-` group. The moment there are two, this is back to
comparing strings that can agree while both are wrong.

Three further things a wrong deployment would pass are checked here, because
each one looks deployed from the outside:

- the sweep's matrix is the enumeration's output rather than a hand-written
  list, which is what "the enumerated issue number is what the reduction
  receives" means;
- the reduction's ISSUE_NUMBER comes from the same input as the group;
- the scheduled entry point asks for the periodic timeline read. Without it the
  sweep runs, finds every loss the manifest already identifies, and walks past
  the erased-memory case it exists to catch.

Usage:
  python3 tools/workflow-check.py --self-test
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

WORKFLOWS_PATH = ".github/workflows"
REUSABLE_CALL = "./.github/workflows/open-table-reduce.yml"
GROUP_PREFIX = "open-table-"
ENUMERATION_FLAG = "--list-sessions"

# Representative values. They are arbitrary but must be distinguishable from an
# empty resolution, which is the defect this check exists to catch.
REPOSITORY_ID = "777"
SESSION_ISSUE = "143"

EXPRESSION_RE = re.compile(r"\$\{\{\s*(.+?)\s*\}\}")
MATRIX_SOURCE_RE = re.compile(
    r"\A\$\{\{\s*fromJSON\(\s*needs\.([A-Za-z0-9_-]+)\.outputs\.([A-Za-z0-9_-]+)\s*\)\s*\}\}\Z"
)
STEP_OUTPUT_RE = re.compile(
    r"\A\$\{\{\s*steps\.([A-Za-z0-9_-]+)\.outputs\.[A-Za-z0-9_-]+\s*\}\}\Z"
)


def triggers_of(workflow):
    """Return the workflow's trigger names.

    YAML 1.1 resolves a bare `on` to the boolean true, so PyYAML keys the
    trigger block under True rather than under "on". A check that looks up "on"
    alone sees no triggers in any real workflow file and then agrees with
    everything, which is the failure mode this function exists to avoid.
    """
    if not isinstance(workflow, dict):
        return set()
    block = workflow.get("on", workflow.get(True))
    if isinstance(block, dict):
        return set(block)
    if isinstance(block, list):
        return set(block)
    return {block} if block else set()


def jobs_of(workflow):
    if not isinstance(workflow, dict):
        return []
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        return []
    return [(name, job) for name, job in sorted(jobs.items()) if isinstance(job, dict)]


def resolve(expression, bindings):
    """Substitute `${{ }}` the way a runner would: an unavailable context is empty."""
    return EXPRESSION_RE.sub(
        lambda match: str(bindings.get(match.group(1), "")), str(expression)
    )


def concurrency_sites(workflows):
    """Every place that builds a group name carrying the Open Table prefix."""
    sites = []
    for name, workflow in sorted(workflows.items()):
        blocks = [("workflow level", workflow.get("concurrency"))]
        blocks.extend(
            ("job {}".format(job_name), job.get("concurrency"))
            for job_name, job in jobs_of(workflow)
        )
        for where, block in blocks:
            group = block.get("group") if isinstance(block, dict) else block
            if isinstance(group, str) and GROUP_PREFIX in group:
                sites.append((name, where, group))
    return sites


def reusable_workflow(workflows):
    """The reduction's reusable workflow, found by the path its callers name.

    Deliberately not "the first workflow declaring workflow_call": any other
    reusable workflow the repository grows would displace it depending on where
    its name sorts, and the check would then measure the wrong file while still
    passing.
    """
    name = REUSABLE_CALL.rsplit("/", 1)[-1]
    workflow = workflows.get(name)
    if not isinstance(workflow, dict) or "workflow_call" not in triggers_of(workflow):
        return None, None
    return name, workflow


def entry_points(workflows):
    """Every job that calls the reusable reduction."""
    found = []
    for name, workflow in sorted(workflows.items()):
        for job_name, job in jobs_of(workflow):
            if job.get("uses") == REUSABLE_CALL:
                found.append((name, workflow, job_name, job))
    return found


def issue_number_env(reusable):
    """Where the reduction's ISSUE_NUMBER is built, and from what."""
    for job_name, job in jobs_of(reusable):
        env = job.get("env")
        if isinstance(env, dict) and "ISSUE_NUMBER" in env:
            return job_name, str(env["ISSUE_NUMBER"])
    return None, None


def matrix_comes_from_enumeration(workflow, value):
    """Whether this matrix value is the output of a job that ran the enumeration.

    A hand-written list of issue numbers resolves to a perfectly good key and is
    still wrong: it is a copy of a list GitHub already answers, so it goes stale
    the moment a session opens or closes, and it does so silently.
    """
    match = MATRIX_SOURCE_RE.match(str(value).strip())
    if not match:
        return False
    producer, output = match.group(1), match.group(2)
    job = dict(jobs_of(workflow)).get(producer)
    if job is None:
        return False
    declared = (job.get("outputs") or {}).get(output)
    step_match = STEP_OUTPUT_RE.match(str(declared).strip()) if declared else None
    if not step_match:
        return False
    for step in job.get("steps") or []:
        if isinstance(step, dict) and step.get("id") == step_match.group(1):
            return ENUMERATION_FLAG in str(step.get("run") or "")
    return False


def entry_point_bindings(workflow, job, complaints, label):
    """The contexts a runner would actually have for this entry point."""
    bindings = {"github.repository_id": REPOSITORY_ID}
    triggers = triggers_of(workflow)
    if triggers & {"issue_comment", "issues"}:
        bindings["github.event.issue.number"] = SESSION_ISSUE
    matrix = (job.get("strategy") or {}).get("matrix")
    if isinstance(matrix, dict):
        for key, value in matrix.items():
            bindings["matrix.{}".format(key)] = SESSION_ISSUE
            if not matrix_comes_from_enumeration(workflow, value):
                complaints.append(
                    "{}: matrix.{} is not the output of a job running {}, so the "
                    "number the reduction receives is not the enumerated one".format(
                        label, key, ENUMERATION_FLAG
                    )
                )
    return bindings


def check_workflows(workflows):
    """Return the complaints. An empty list means the invariant holds."""
    complaints = []
    # A file here that is not a mapping is empty or broken. Skipping it quietly
    # is how a deployment half of which failed to parse still reads as checked.
    malformed = sorted(
        name for name, workflow in workflows.items() if not isinstance(workflow, dict)
    )
    if malformed:
        return [
            "not a YAML mapping, so nothing in it can be checked: {}".format(
                ", ".join(malformed)
            )
        ]

    reusable_name, reusable = reusable_workflow(workflows)
    if reusable is None:
        return [
            "{} is missing or does not declare on.workflow_call, so nothing "
            "builds the group".format(REUSABLE_CALL)
        ]

    sites = concurrency_sites(workflows)
    if len(sites) != 1:
        return complaints + [
            "{} sites build an {} group; exactly one is allowed, in {}: {}".format(
                len(sites), GROUP_PREFIX, reusable_name,
                ", ".join("{} ({})".format(site[0], site[1]) for site in sites) or "none",
            )
        ]
    site_file, site_where, group_expression = sites[0]
    if site_file != reusable_name:
        return complaints + [
            "the {} group is built in {} ({}) rather than in the reusable "
            "workflow {}".format(GROUP_PREFIX, site_file, site_where, reusable_name)
        ]

    env_job, env_expression = issue_number_env(reusable)
    if env_expression is None:
        return complaints + [
            "{} builds no ISSUE_NUMBER, so the reduction reads no session".format(
                reusable_name
            )
        ]

    points = entry_points(workflows)
    if not points:
        return complaints + ["no workflow calls {}".format(REUSABLE_CALL)]
    # Without this, a sweep whose job stops being an entry point at all -- a
    # renamed path, a malformed jobs block -- leaves the event-driven caller
    # passing every assertion below, and the check agrees that a deployment
    # with no clock in it is correct.
    if not any("schedule" in triggers_of(workflow) for _, workflow, _, _ in points):
        complaints.append(
            "no entry point is on a clock, so nothing calls the reduction "
            "periodically and detection latency is bounded by traffic again"
        )

    expected = "{}{}-{}".format(GROUP_PREFIX, REPOSITORY_ID, SESSION_ISSUE)
    resolved = {}
    for name, workflow, job_name, job in points:
        label = "{} (job {})".format(name, job_name)
        bindings = entry_point_bindings(workflow, job, complaints, label)
        passed = (job.get("with") or {}).get("issue_number")
        if passed is None:
            complaints.append("{}: passes no issue_number".format(label))
            continue
        issue_value = resolve(passed, bindings)
        inputs = {
            "github.repository_id": REPOSITORY_ID,
            "inputs.issue_number": issue_value,
        }
        key = resolve(group_expression, inputs)
        number = resolve(env_expression, inputs)
        resolved[label] = key
        if key != expected:
            complaints.append(
                "{}: resolves the group to {!r}, expected {!r}".format(
                    label, key, expected
                )
            )
        if number != SESSION_ISSUE:
            complaints.append(
                "{}: the reduction's ISSUE_NUMBER resolves to {!r} rather than the "
                "session it was called for, {!r} (built in {} job {})".format(
                    label, number, SESSION_ISSUE, reusable_name, env_job
                )
            )
        periodic = (job.get("with") or {}).get("periodic") is True
        scheduled = "schedule" in triggers_of(workflow)
        if scheduled and not periodic:
            complaints.append(
                "{}: is scheduled but does not ask for the periodic timeline "
                "read, so the sweep would run without reading it".format(label)
            )
        if periodic and not scheduled:
            complaints.append(
                "{}: asks for the periodic read without being on a clock".format(label)
            )

    if len(set(resolved.values())) > 1:
        complaints.append(
            "the entry points resolve to different groups and do not serialise "
            "against each other: {}".format(
                ", ".join(
                    "{} -> {!r}".format(label, key)
                    for label, key in sorted(resolved.items())
                )
            )
        )
    return complaints


def parse_workflows(texts):
    return {name: yaml.safe_load(text) for name, text in texts.items()}


def load_repository_workflows():
    root = Path(__file__).resolve().parent.parent
    directory = root / WORKFLOWS_PATH
    paths = sorted(directory.glob("*.yml")) + sorted(directory.glob("*.yaml"))
    if not paths:
        raise SystemExit("error: no workflow files under {}".format(directory))
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8")) for path in paths
    }


REUSABLE_FIXTURE = """
name: reduction
on:
  workflow_call:
    inputs:
      issue_number:
        required: true
        type: number
      periodic:
        required: false
        default: false
        type: boolean
concurrency:
  group: open-table-${{ github.repository_id }}-${{ inputs.issue_number }}
  cancel-in-progress: false
jobs:
  reduce:
    runs-on: ubuntu-latest
    env:
      ISSUE_NUMBER: ${{ inputs.issue_number }}
    steps:
      - run: python3 reduce.py --issue "$ISSUE_NUMBER"
"""

EVENT_FIXTURE = """
name: event driven
on:
  issue_comment:
    types: [created, edited, deleted]
jobs:
  reduce:
    if: contains(github.event.issue.labels.*.name, 'open-table/session')
    uses: ./.github/workflows/open-table-reduce.yml
    with:
      issue_number: ${{ github.event.issue.number }}
"""

SWEEP_FIXTURE = """
name: sweep
on:
  schedule:
    - cron: "17 * * * *"
jobs:
  enumerate:
    runs-on: ubuntu-latest
    outputs:
      sessions: ${{ steps.list.outputs.sessions }}
    steps:
      - id: list
        run: |
          sessions="$(python3 reduce.py --list-sessions)"
          printf 'sessions=%s\\n' "$sessions" >> "$GITHUB_OUTPUT"
  sweep:
    needs: enumerate
    strategy:
      matrix:
        issue_number: ${{ fromJSON(needs.enumerate.outputs.sessions) }}
    uses: ./.github/workflows/open-table-reduce.yml
    with:
      issue_number: ${{ matrix.issue_number }}
      periodic: true
"""


def fixture(**replacements):
    """The three-file deployment, with one file swapped for a planted defect."""
    texts = {
        "open-table-reduce.yml": REUSABLE_FIXTURE,
        "open-table.yml": EVENT_FIXTURE,
        "open-table-sweep.yml": SWEEP_FIXTURE,
    }
    texts.update(replacements)
    return parse_workflows(texts)


def run_self_test():
    failures = []

    def expect_ok(name, workflows):
        complaints = check_workflows(workflows)
        if complaints:
            failures.append("FAIL {}: expected no complaint, got {}".format(name, complaints))
        else:
            print("ok: {}".format(name))

    def expect_refused(name, workflows, fragment):
        complaints = check_workflows(workflows)
        if not complaints:
            failures.append("FAIL {}: the defect passed".format(name))
        elif not any(fragment in complaint for complaint in complaints):
            failures.append(
                "FAIL {}: refused for the wrong reason: {}".format(name, complaints)
            )
        else:
            print("ok: {} is refused".format(name))

    expect_ok("a deployment with one construction site and two entry points", fixture())

    # The defect the previous version of this check would have guaranteed: the
    # sweep copies the event-driven expression, which a scheduled event does not
    # populate, and the issue component resolves to empty.
    expect_refused(
        "a sweep copying the event-driven expression",
        fixture(**{"open-table-sweep.yml": SWEEP_FIXTURE.replace(
            "issue_number: ${{ matrix.issue_number }}",
            "issue_number: ${{ github.event.issue.number }}",
        )}),
        "resolves the group to 'open-table-777-'",
    )

    expect_refused(
        "a second site building the group",
        fixture(**{"open-table-sweep.yml": SWEEP_FIXTURE.replace(
            "  sweep:\n    needs: enumerate",
            "  sweep:\n    needs: enumerate\n    concurrency:\n"
            "      group: open-table-${{ github.repository_id }}-${{ matrix.issue_number }}",
        )}),
        "2 sites build an open-table- group",
    )

    expect_refused(
        "a reduction whose ISSUE_NUMBER is not the input the group used",
        fixture(**{"open-table-reduce.yml": REUSABLE_FIXTURE.replace(
            "ISSUE_NUMBER: ${{ inputs.issue_number }}",
            "ISSUE_NUMBER: ${{ github.event.issue.number }}",
        )}),
        "ISSUE_NUMBER resolves to",
    )

    expect_refused(
        "a sweep whose matrix is a hand-written list",
        fixture(**{"open-table-sweep.yml": SWEEP_FIXTURE.replace(
            "issue_number: ${{ fromJSON(needs.enumerate.outputs.sessions) }}",
            "issue_number: [143]",
        )}),
        "is not the output of a job running --list-sessions",
    )

    expect_refused(
        "a sweep that never asks for the periodic read",
        fixture(**{"open-table-sweep.yml": SWEEP_FIXTURE.replace(
            "      periodic: true\n", "",
        )}),
        "does not ask for the periodic timeline read",
    )

    expect_refused(
        "a deployment with no entry point at all",
        parse_workflows({"open-table-reduce.yml": REUSABLE_FIXTURE}),
        "no workflow calls",
    )

    # Another reusable workflow must not be mistaken for the reduction's, and a
    # name sorting before it is how that would happen.
    expect_ok(
        "an unrelated reusable workflow sorting before the reduction's",
        fixture(**{"aardvark.yml": REUSABLE_FIXTURE.replace(
            "open-table-", "unrelated-",
        )}),
    )
    expect_refused(
        "a deployment whose only entry point is the event-driven one",
        parse_workflows({
            "open-table-reduce.yml": REUSABLE_FIXTURE, "open-table.yml": EVENT_FIXTURE,
        }),
        "no entry point is on a clock",
    )
    expect_refused(
        "a workflow file that is empty",
        dict(fixture(), **{"empty.yml": None}),
        "not a YAML mapping",
    )
    expect_refused(
        "the reduction's reusable workflow missing entirely",
        parse_workflows({
            "open-table.yml": EVENT_FIXTURE, "open-table-sweep.yml": SWEEP_FIXTURE,
        }),
        "is missing or does not declare on.workflow_call",
    )

    complaints = check_workflows(load_repository_workflows())
    if complaints:
        failures.extend("FAIL real repository: {}".format(c) for c in complaints)
    else:
        print(
            "ok: this repository's entry points both resolve to {}{}-{}".format(
                GROUP_PREFIX, REPOSITORY_ID, SESSION_ISSUE
            )
        )

    if failures:
        for failure in failures:
            print(failure)
        print("self-test FAILED: {} assertion(s) failed".format(len(failures)))
        return 1
    print("self-test ok")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Asserts that both Open Table entry points serialise together.")
    parser.add_argument("--self-test", action="store_true",
                        help="Run fixture assertions plus the real check against this repo")
    args = parser.parse_args()
    if not args.self_test:
        parser.error("--self-test is the only supported mode")
    return run_self_test()


if __name__ == "__main__":
    sys.exit(main())
