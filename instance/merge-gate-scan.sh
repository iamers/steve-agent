#!/usr/bin/env bash
# merge-gate-scan: scanner davanti al gate. Trova le PR aperte con label
# `steve-approved` (configurabile via STEVE_APPROVAL_LABEL) e invoca
# instance/merge-gate.sh su ciascuna. Niente LLM, niente logica di merge
# propria: delega totalmente al gate (già provato sul canary #46, NON
# modificarlo).
#
# Progettato per girare sotto cron --no-agent: stdout VUOTO = silenzio.
# - Feature non configurata       -> stdout vuoto (STEVE_MERGE_APP_ID o
#                                   STEVE_MERGE_KEY_PATH assenti/vuote: il
#                                   merge gate è OPZIONALE, non è un guasto).
# - Nessuna PR etichettata        -> stdout vuoto (silenzio totale, come
#                                   pr-watch.sh).
# - Stesso reject già riportato  -> stdout vuoto (anti-rumore via state file).
# - Reject con reason NUOVA       -> stampa (una sola volta per la coppia
#                                   <pr, reason>).
# - Merge riuscito                -> stampa SEMPRE un annuncio leggibile con
#                                   link e pulisce lo stato per quella PR
#                                   (evento one-shot).
#
# Anti-concorrenza: flock su un lockfile in ~/.hermes/state. Se un'istanza
# è già in corso, esci silenzioso (exit 0).
#
# Uso:
#   ./merge-gate-scan.sh            scanner runtime (mergia se il gate approva)
#   ./merge-gate-scan.sh --dry-run  elenca candidati + decisioni del gate,
#                                   NON mergia, NON scrive stato (esplorazione
#                                   manuale: qui il rumore è accettabile).
#   ./merge-gate-scan.sh --self-test
#                                   verifica il formatter senza side effect
#
# Env vars (ereditate dall'ambiente del cron, NON passate in argv; le credenziali
# vivono nel .env dell'istanza e NON vanno mai hardcodate qui):
#   STEVE_REPO            owner/name (default: iamers/steve-agent)
#   STEVE_APPROVAL_LABEL  label che marca una PR approvata
#                         (default: steve-approved, NON "approved" del gate)
#   STEVE_MERGE_APP_ID, STEVE_MERGE_KEY_PATH, STEVE_REVIEWER_LOGIN
#                         credenziali/identità del gate (lette da merge-gate.sh)
set -u

# format_merge_announcement <repository> <pr>
# Costruisce l'annuncio di merge. Funzione pura: nessuna rete, stato o lettura.
format_merge_announcement() {
    local repository="$1" pr="$2"
    printf 'merged: PR #%s was merged by the gate.\n' "$pr"
    printf 'https://github.com/%s/pull/%s\n' "$repository" "$pr"
    printf 'Tier safe, and the label, the approved review, green CI and an unchanged head were all\n'
    printf 'verified before merging. Nothing for you to do.\n'
}

run_self_test() {
    local expected actual
    expected=$(printf '%s\n' \
        'merged: PR #123 was merged by the gate.' \
        'https://github.com/octo/example/pull/123' \
        'Tier safe, and the label, the approved review, green CI and an unchanged head were all' \
        'verified before merging. Nothing for you to do.')
    actual=$(format_merge_announcement "octo/example" "123")

    if [ "$actual" != "$expected" ]; then
        echo "FAIL: format_merge_announcement returned unexpected text"
        return 1
    fi
    echo "ok: format_merge_announcement -> https://github.com/octo/example/pull/123"
    echo "self-test ok"
    return 0
}

# Valida la modalità prima di qualunque side effect. Il runtime non accetta
# argomenti; --dry-run e --self-test sono le modalità esplicite.
MODE="runtime"
case "$#:${1:-}" in
    0:) ;;
    1:--dry-run) MODE="dry-run" ;;
    1:--self-test) MODE="self-test" ;;
    *)
        echo "usage: $0 [--dry-run|--self-test]" >&2
        exit 2
        ;;
esac

if [ "$MODE" = "self-test" ]; then
    run_self_test
    exit $?
fi

# Trova la root del repo dal path dello script: instance/merge-gate-scan.sh -> root.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MERGE_GATE="$REPO_ROOT/instance/merge-gate.sh"

# Defaults dell'istanza. La label canonica è `steve-approved`, non il default
# "approved" interno del gate (il gate legge la label dall'ambiente).
# Ogni fallback risolto qui va riesportato a ogni invocazione del gate.
REPO="${STEVE_REPO:-iamers/steve-agent}"
APPROVAL_LABEL="${STEVE_APPROVAL_LABEL:-steve-approved}"

# ---------------------------------------------------------------------------
# Feature OPZIONALE. Il merge gate (e la sua GitHub App) è facoltativo: un
# adopter può non volerlo. Se le credenziali non sono configurate, il prodotto
# deve funzionare IDENTICO. In modalità runtime esci 0 in SILENZIO (non è un
# guasto, è un'istanza che non usa il gate). Solo con --dry-run stampi una
# riga esplicativa (esplorazione manuale: il rumore è accettabile).
# ---------------------------------------------------------------------------
if [ -z "${STEVE_MERGE_APP_ID:-}" ] || [ -z "${STEVE_MERGE_KEY_PATH:-}" ]; then
    if [ "$MODE" = "dry-run" ]; then
        echo "merge gate feature not configured: STEVE_MERGE_APP_ID/STEVE_MERGE_KEY_PATH not set"
    fi
    exit 0
fi

# Modalità --dry-run: esplorazione manuale senza lock né stato. Elenca i
# candidati e chiama merge-gate.sh --dry-run per ciascuno.
if [ "$MODE" = "dry-run" ]; then
    CANDIDATES=$(gh pr list --repo "$REPO" --state open \
        --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || exit 0
    [ -z "$CANDIDATES" ] && exit 0
    while IFS= read -r pr; do
        [ -z "$pr" ] && continue
        echo "=== PR #${pr} (${REPO}, label ${APPROVAL_LABEL}) ==="
        STEVE_REPO="$REPO" \
            STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
            "$MERGE_GATE" --dry-run "$pr" || true
    done <<< "$CANDIDATES"
    exit 0
fi

# Da qui in poi esiste solo la modalità runtime. Stato e lock vengono creati
# dopo guard opzionale, query candidati e uscita dry-run.
STATE_DIR="$HOME/.hermes/state"
STATE_FILE="$STATE_DIR/merge-gate-seen.txt"
LOCKFILE="$STATE_DIR/merge-gate-scan.lock"
mkdir -p "$STATE_DIR"
touch "$STATE_FILE"

# LOCK anti-concorrenza: se un'istanza è già in corso, esci silenzioso. Il fd 9
# resta aperto per tutta la vita del processo; flock lo rilascia all'uscita.
exec 9>"$LOCKFILE"
flock -n 9 || exit 0

# La query runtime resta sotto lock: due tick concorrenti non devono valutare
# o mutare la stessa PR in parallelo. Errori di gh restano silenziosi.
CANDIDATES=$(gh pr list --repo "$REPO" --state open \
    --label "$APPROVAL_LABEL" --json number --jq '.[].number' 2>/dev/null) || exit 0
[ -z "$CANDIDATES" ] && exit 0

# ---------------------------------------------------------------------------
# Helper per lo stato anti-rumore. Una riga per evento già riportato, nel
# formato `<pr>\t<reason>`.
# ---------------------------------------------------------------------------

# report_reject <pr> <reason> <gate_stdout>
# Stampa l'output del gate SOLO se la coppia (pr, reason) è nuova; altrimenti
# resta in silenzio (reject identico al giro precedente). Quando è nuova,
# registra la chiave nello state file.
report_reject() {
    local pr="$1" reason="$2" gate_out="$3"
    local key
    key=$(printf '%s\t%s' "$pr" "$reason")
    if grep -qxF "$key" "$STATE_FILE" 2>/dev/null; then
        return 0
    fi
    printf '%s\n' "$gate_out"
    printf '%s\n' "$key" >> "$STATE_FILE"
}

# clear_state <pr>
# Rimuove tutte le righe di stato per questa PR. Chiamato sui merge riusciti:
# un merge è un evento one-shot che resetta il rumore per la PR.
clear_state() {
    local pr="$1" tmp
    tmp=$(mktemp "${TMPDIR:-/tmp}/merge-gate-seen.XXXXXX")
    # awk su campo tab: tiene tutto ciò la cui prima colonna non è questa PR.
    awk -F'\t' -v p="$pr" '$1 != p' "$STATE_FILE" > "$tmp" 2>/dev/null || true
    mv "$tmp" "$STATE_FILE"
}

# ---------------------------------------------------------------------------
# Esecuzione di una singola PR.
# ---------------------------------------------------------------------------

# run_one <pr>: invoca merge-gate.sh <pr>, applicando l'anti-rumore. Stampa su
# stdout solo ciò che va consegnato questo tick. Ritorna sempre 0 (un reject
# del gate non è un errore di scanner).
run_one() {
    local pr="$1"
    local out rc verdict_line reason

    # Cattura stdout+stderr del gate. Il token e la chiave privata NON appaiono
    # mai nell'output del gate (garanzia di merge-gate.sh): qui li passiamo solo
    # attraverso, non li logghiamo noi.
    out=$(STEVE_REPO="$REPO" \
        STEVE_APPROVAL_LABEL="$APPROVAL_LABEL" \
        "$MERGE_GATE" "$pr" 2>&1); rc=$?

    # La riga di verdetto è l'ultima che inizia con MERGE: o REJECT:.
    verdict_line=$(printf '%s\n' "$out" | grep -E '^(MERGE|REJECT):' | tail -1)

    case "$verdict_line" in
        MERGE:*)
            if [ "$rc" -eq 0 ]; then
                # Merge riuscito: riporta SEMPRE e resetta il rumore per la PR.
                clear_state "$pr"
                format_merge_announcement "$REPO" "$pr"
            else
                # Verdetto MERGE ma do_merge fallito: anomalia one-shot, chiave
                # su "merge-failed" così ripetizioni identiche restano quiete.
                report_reject "$pr" "merge-failed" "$out"
            fi
            ;;
        REJECT:*)
            # reason = testo dopo "REJECT: " (es. "(c) CI is not green ...").
            reason="${verdict_line#REJECT: }"
            report_reject "$pr" "$reason" "$out"
            ;;
        *)
            # Nessuna riga di verdetto (es. STEVE_REPO mancante, usage error).
            # Chiave su "eval-error": ripetizioni identiche restano quiete.
            report_reject "$pr" "eval-error" "$out"
            ;;
    esac
    return 0
}

# ---------------------------------------------------------------------------
# Modalità runtime: una run_one per candidata. L'anti-rumore decide cosa stampare.
# ---------------------------------------------------------------------------
while IFS= read -r pr; do
    [ -z "$pr" ] && continue
    run_one "$pr" || true
done <<< "$CANDIDATES"

# Silenzioso di default: nessun output se non ci sono eventi nuovi.
exit 0
