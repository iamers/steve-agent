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

# Path coinvolti nel gate D4 (vincoli senza test).
REVIEW_POLICY_PATH = ".steve/review-policy.yaml"
PR_BRIEF_PATH = "tools/pr-brief.py"


# ---------------------------------------------------------------------------
# Task id di origine + gate D4 (deterministici, basati su path/pattern)
# ---------------------------------------------------------------------------

def parse_task_id(branch):
    """Estrae l'id del task di origine dal branch name.

    Matcha il pattern ``steve-agent/t_<id>-...`` dove ``<id>`` e' [a-f0-9]+.
    Restituisce ``t_<id>`` oppure None se il branch non matcha il prefisso
    atteso (es. feat/xxx, main, branch senza steve-agent/).
    """
    if not branch:
        return None
    m = re.match(r"steve-agent/(t_[a-f0-9]+)-", branch)
    return m.group(1) if m else None


def check_d4_gate(files):
    """Gate D4: True se il diff tocca review-policy MA NON pr-brief.py.

    Modificare la policy di review senza toccare il compilatore che la
    testesta e' un vincolo non testato: richiede firma umana esplicita.
    Confronto di set di path, zero euristiche.
    """
    fileset = set(files)
    touches_policy = REVIEW_POLICY_PATH in fileset
    touches_compiler = PR_BRIEF_PATH in fileset
    return touches_policy and not touches_compiler


def escalate_tier_for_d4(pr_tier_name, d4_active):
    """Se il gate D4 e' attivo, il tier effettivo sale almeno a propagazione.

    Se era sicuro diventa propagazione; se era gia' propagazione o blast
    resta tale.
    """
    if not d4_active:
        return pr_tier_name
    if TIER_ORDER.get(pr_tier_name, 1) < TIER_ORDER["propagazione"]:
        return "propagazione"
    return pr_tier_name


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
                 critical_files, summary_text, task_id=None, d4_active=False):
    """Compila il template riempiendo i campi dinamici, lasciando intatte
    le sezioni statiche (footer, placeholder Scelte non banali, checklist).

    critical_files: lista di (path, tier_lowercase, matched_pattern_or_None).
    task_id: id del task di origine (``t_<id>``) o None.
    d4_active: se True, inserisce il marcatore D4 (vincolo senza test).
    """
    lines = template_text.split("\n")
    output = []
    leggi_prima_emitted = False
    i = 0
    while i < len(lines):
        line = lines[i]
        # Riga header: PR #<N> — <title>
        if "<N>" in line and "<title>" in line:
            output.append("PR #{} — {}".format(number, title))
        # Riga branch: Branch: <branch> -> main (+ eventuale riga Origine)
        elif "<branch>" in line:
            output.append("Branch: {} -> main".format(branch))
            if task_id:
                output.append("Origine: task {}".format(task_id))
        # Sezione fissa "Leggi prima": iniettata una sola volta, subito prima
        # del blocco ## Triage (dopo le info della PR, prima dei file critici).
        elif not leggi_prima_emitted and line.strip() == "## Triage":
            output.append("Leggi prima (nel worktree): README.md, CLAUDE.md, .steve/review-policy.yaml")
            output.append("")
            output.append(line)
            leggi_prima_emitted = True
        # Riga tier (sostituisce l'intera riga) + eventuale marcatore D4
        elif line.startswith("Tier:"):
            output.append("Tier: {}".format(tier_upper))
            if d4_active:
                output.append("D4: vincolo senza test - firma umana obbligatoria")
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
        ("tools/x.py", "propagazione"),
        ("scripts/foo.sh", "propagazione"),
        (".github/workflows/ci.yml", "propagazione"),
        ("README.md", "sicuro"),
        ("CLAUDE.md", "sicuro"),
        (".gitignore", "sicuro"),
        ("percorso-ignoto.xyz", "propagazione"),
    ]
    for path, expected in cases:
        got, _ = file_tier(path, tiers)
        assert got == expected, "{}: aspettato {}, ottenuto {}".format(
            path, expected, got)

    # --- Estensione 1: task id di origine dal branch name -----------------
    tid_cases = [
        ("steve-agent/t_4806977c-ci-workflow-fix-4-finding-shellcheck-ste",
         "t_4806977c"),
    ]
    for branch, expected in tid_cases:
        got = parse_task_id(branch)
        assert got == expected, "parse_task_id({!r}): aspettato {}, ottenuto {}".format(
            branch, expected, got)
    # Branch non matching devono dare None
    for branch in ("feat/random", "main", "t_solo_id"):
        got = parse_task_id(branch)
        assert got is None, "parse_task_id({!r}): aspettato None, ottenuto {}".format(
            branch, got)

    # --- Estensione 2: sezione fissa "Leggi prima" ------------------------
    # Rendering con input fittizio (senza rete): la stringa deve essere presente.
    template_path = policy_path.parent / "review-brief-template.md"
    template_text = template_path.read_text()
    sample_brief = render_brief(
        template_text, number=1, title="sample", branch="feat/sample",
        tier_upper="SICURO", critical_files=[], summary_text="x",
        task_id=None, d4_active=False)
    assert "Leggi prima (nel worktree): README.md, CLAUDE.md, .steve/review-policy.yaml" in sample_brief, \
        "sezione 'Leggi prima' mancante nel brief renderizzato"

    # --- Estensione 3: gate D4 -------------------------------------------
    # Solo review-policy (senza pr-brief.py) -> D4 attivo + tier sale
    files_policy_only = [REVIEW_POLICY_PATH]
    assert check_d4_gate(files_policy_only) is True, \
        "D4 dovrebbe attivarsi con solo review-policy.yaml"
    escalated = escalate_tier_for_d4("sicuro", True)
    assert escalated == "propagazione", \
        "D4 attivo: tier sicuro dovrebbe salire a propagazione, ottenuto {}".format(
            escalated)
    # Entrambi i file -> D4 NON attivo (il compilatore e' stato toccato)
    files_both = [REVIEW_POLICY_PATH, PR_BRIEF_PATH]
    assert check_d4_gate(files_both) is False, \
        "D4 NON dovrebbe attivarsi quando pr-brief.py e' nel diff"
    assert escalate_tier_for_d4("sicuro", False) == "sicuro", \
        "D4 inattivo: tier non deve cambiare"

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

    # Task id di origine dal branch name (deterministico)
    task_id = parse_task_id(branch)

    # Gate D4: vincolo su review-policy senza test -> tier sale + firma umana
    d4_active = check_d4_gate(files)
    pr_tier_name = escalate_tier_for_d4(pr_tier_name, d4_active)

    # File critici: solo blast e propagazione (con il pattern che ha fatto match)
    critical = [
        (path, ftier, pattern)
        for path, ftier, pattern in file_results
        if ftier in ("blast", "propagazione")
    ]

    summary = extract_summary(body, args.summary)

    brief = render_brief(template_text, number, title, branch,
                         pr_tier_name.upper(), critical, summary,
                         task_id=task_id, d4_active=d4_active)
    # Normalizza: una sola riga vuota finale
    brief = brief.rstrip("\n") + "\n"
    sys.stdout.write(brief)


if __name__ == "__main__":
    main()
