#!/usr/bin/env python3
"""pr-brief: compila il brief di review approvabile per una PR.

Triage deterministico basato sui path (non LLM): per ogni file modificato
trova il tier tramite i pattern della policy .steve/review-policy.yaml; il
tier della PR e' il max tra tutti i file (blast > propagazione > sicuro).
Stampa il brief compilato su stdout seguendo .steve/review-brief-template.md.

L'invio del brief e la decisione di merge NON sono compito di questo tool:
il merge resta sempre umano. Questo tool concentra solo la decisione.

Uso:
  python3 tools/pr-brief.py --repo <owner/name> --pr <N> [--summary "testo"]
  python3 tools/pr-brief.py --self-test
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

# Ordine di gravita: blast (outage) > propagazione (bug replicato) > sicuro.
TIER_ORDER = {"sicuro": 0, "propagazione": 1, "blast": 2}
# Tier di default quando nessun pattern matcha: fail-safe, non fast.
DEFAULT_TIER = "propagazione"


# ---------------------------------------------------------------------------
# Matcher: traduzione glob -> regex
# ---------------------------------------------------------------------------

def glob_to_regex(pattern):
    """Traduce un pattern glob (con * e **) in regex anchorata.

    **  matcha qualsiasi sequenza di caratteri, separatori di directory inclusi
    *   matcha qualsiasi sequenza eccetto il separatore '/'
    ?   matcha un singolo carattere eccetto il separatore '/'
    gli altri caratteri sono letterali (con escape dei metacaratteri regex)

    fnmatch da solo non basta: tratta '*' come match-all incluso '/',
    per cui 'tools/*' matcherebbe anche 'tools/sub/dir/file.py'.
    """
    out = []
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # ** attraverso i confini di directory
                out.append(".*")
                i += 2
            else:
                # * entro un singolo segmento di path
                out.append("[^/]*")
                i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c in ".^$+(){}[]|\\":

            out.append("\\" + c)
            i += 1
        else:
            out.append(c)
            i += 1
    return "^" + "".join(out) + "$"


def file_tier(path, tiers):
    """Trova il tier di un file via pattern matching.

    Itera i tier dal piu' grave al meno grave: il primo tier con un pattern
    che matcha vince (corrisponde al max). Se nessun pattern matcha,
    restituisce (DEFAULT_TIER, None).

    Restituisce (tier_name, matched_pattern).
    """
    for tier_name in sorted(tiers, key=lambda t: TIER_ORDER.get(t, 0), reverse=True):
        for pat in tiers[tier_name].get("paths", []):
            if re.match(glob_to_regex(pat), path):
                return tier_name, pat
    return DEFAULT_TIER, None


def compute_pr_tier(paths, tiers):
    """Tier della PR = max(tier di tutti i file modificati).

    Restituisce (pr_tier_name, [(path, file_tier, matched_pattern), ...]).
    """
    file_results = []
    for path in paths:
        ftier, pattern = file_tier(path, tiers)
        file_results.append((path, ftier, pattern))
    if not file_results:
        return DEFAULT_TIER, []
    pr_tier_name = max(
        (ftier for _, ftier, _ in file_results),
        key=lambda t: TIER_ORDER.get(t, 1),
    )
    return pr_tier_name, file_results


# ---------------------------------------------------------------------------
# Caricamento policy e template
# ---------------------------------------------------------------------------

def find_policy_path():
    """Trova .steve/review-policy.yaml: dalla cwd verso l'alto, poi dallo script."""
    cwd = Path.cwd()
    for p in [cwd] + list(cwd.parents):
        candidate = p / ".steve" / "review-policy.yaml"
        if candidate.is_file():
            return candidate
    # Fallback: tools/pr-brief.py -> la root del repo e' due livelli sopra
    script_root = Path(__file__).resolve().parent.parent
    candidate = script_root / ".steve" / "review-policy.yaml"
    if candidate.is_file():
        return candidate
    return None


def load_policy(policy_path):
    """Carica i tiers dalla policy YAML."""
    with open(policy_path) as f:
        data = yaml.safe_load(f)
    return data.get("tiers", {})


# ---------------------------------------------------------------------------
# Compilazione del brief
# ---------------------------------------------------------------------------

def extract_summary(body, override):
    """Sintesi per 'Cosa cambia': --summary, prime 3 righe non vuote del body, o fallback."""
    if override:
        return override
    if body:
        non_empty = [ln for ln in body.split("\n") if ln.strip()]
        if non_empty:
            return "\n".join(non_empty[:3])
    return "(sintesi non disponibile)"


def render_brief(template_text, number, title, branch, tier_upper,
                 critical_files, summary_text):
    """Compila il template riempiendo i campi dinamici, lasciando intatte
    le sezioni statiche (footer, placeholder Scelte non banali, checklist).

    critical_files: lista di (path, tier_lowercase, matched_pattern_or_None).
    """
    lines = template_text.split("\n")
    output = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Riga header: PR #<N> — <title>
        if "<N>" in line and "<title>" in line:
            output.append("PR #{} — {}".format(number, title))
        # Riga branch: Branch: <branch> -> main
        elif "<branch>" in line:
            output.append("Branch: {} -> main".format(branch))
        # Riga tier (sostituisce l'intera riga)
        elif line.startswith("Tier:"):
            output.append("Tier: {}".format(tier_upper))
        # Sezione Files critici: sostituisce i placeholder con i file reali
        elif line.strip() == "Files critici:":
            output.append(line)
            # Salta le righe placeholder (- <path> ...)
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("- <path>"):
                i += 1
            # Inserisci i file critici reali (blast e propagazione)
            for path, ftier, pattern in critical_files:
                perche = pattern if pattern else "default (nessun match)"
                output.append("- {}  ({}, {})".format(path, ftier, perche))
            continue  # i e' gia' posizionato sulla riga successiva
        # Sezione Cosa cambia: sostituisce il placeholder con la sintesi
        elif "<2-3 righe" in line:
            output.append(summary_text)
        else:
            # Tutte le altre righe restano cosi' come nel template
            output.append(line)
        i += 1
    return "\n".join(output)


# ---------------------------------------------------------------------------
# Fetch PR via gh
# ---------------------------------------------------------------------------

def fetch_pr(repo, pr_number):
    """Legge i dati della PR via gh CLI. Restituisce il dict JSON."""
    cmd = [
        "gh", "pr", "view", str(pr_number),
        "--repo", repo,
        "--json", "number,title,headRefName,body,files",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        print("errore: gh CLI non trovata nel PATH", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print("errore: gh pr view fallito (exit {})".format(e.returncode), file=sys.stderr)
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def run_self_test():
    """Asserzioni sul matcher usando la policy reale del repo (senza rete)."""
    policy_path = find_policy_path()
    if not policy_path:
        print("errore: .steve/review-policy.yaml non trovato", file=sys.stderr)
        sys.exit(1)
    tiers = load_policy(policy_path)

    cases = [
        ("instance/config.yaml", "blast"),
        (".steve/qualcosa/file.md", "propagazione"),
        ("tools/x.py", "sicuro"),
        ("percorso-ignoto.xyz", "propagazione"),
    ]
    for path, expected in cases:
        got, _ = file_tier(path, tiers)
        assert got == expected, "{}: aspettato {}, ottenuto {}".format(
            path, expected, got)

    print("self-test ok")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Compila il brief di review per una PR (triage deterministico).")
    parser.add_argument("--repo", help="Repository owner/name (es. iamers/steve-agent)")
    parser.add_argument("--pr", type=int, help="Numero della PR")
    parser.add_argument("--summary", help="Sintesi override per 'Cosa cambia'")
    parser.add_argument("--self-test", action="store_true",
                        help="Esegui asserzioni sul matcher senza rete")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return

    if not args.repo or args.pr is None:
        parser.error("--repo e --pr sono obbligatori (a meno di --self-test)")

    # Carica policy e template dalla root del repo
    policy_path = find_policy_path()
    if not policy_path:
        print("errore: .steve/review-policy.yaml non trovato", file=sys.stderr)
        sys.exit(1)
    tiers = load_policy(policy_path)

    template_path = policy_path.parent / "review-brief-template.md"
    if not template_path.is_file():
        print("errore: .steve/review-brief-template.md non trovato", file=sys.stderr)
        sys.exit(1)
    template_text = template_path.read_text()

    # Legge la PR via gh
    pr_data = fetch_pr(args.repo, args.pr)

    number = pr_data.get("number", args.pr)
    title = pr_data.get("title", "(senza titolo)")
    branch = pr_data.get("headRefName", "(sconosciuto)")
    body = pr_data.get("body") or ""
    files = [f["path"] for f in pr_data.get("files", [])]

    # Triage deterministico
    pr_tier_name, file_results = compute_pr_tier(files, tiers)

    # File critici: solo blast e propagazione (con il pattern che ha fatto match)
    critical = [
        (path, ftier, pattern)
        for path, ftier, pattern in file_results
        if ftier in ("blast", "propagazione")
    ]

    summary = extract_summary(body, args.summary)

    brief = render_brief(template_text, number, title, branch,
                         pr_tier_name.upper(), critical, summary)
    # Normalizza: una sola riga vuota finale
    brief = brief.rstrip("\n") + "\n"
    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
