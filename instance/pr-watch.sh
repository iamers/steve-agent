#!/usr/bin/env bash
# pr-watch: watchdog per PR aperte nuove. Progettato per girare sotto cron
# --no-agent: per ogni PR aperta NON ancora vista stampa il brief completo;
# nessuna PR nuova = stdout vuoto (silenzio).
#
# Mantiene lo stato delle PR gia' viste in ~/.hermes/state/pr-seen.txt.
# Il brief viene generato invocando tools/pr-brief.py dal clone in cui questo
# script risiede (usa il path dello script per trovare la root del repo).
#
# Uso: ./pr-watch.sh [owner/name]   (default: iamers/steve-agent)
set -u

REPO="${1:-iamers/steve-agent}"

# Trova la root del repo dal path dello script: instance/pr-watch.sh -> root.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PR_BRIEF="$REPO_ROOT/tools/pr-brief.py"

# File di stato: una PR per riga nel formato <repo>#<numero>
STATE_DIR="$HOME/.hermes/state"
STATE_FILE="$STATE_DIR/pr-seen.txt"
mkdir -p "$STATE_DIR"
touch "$STATE_FILE"

# Legge la lista delle PR aperte: una per riga, solo il numero.
OPEN_PRS_JSON=$(gh pr list --repo "$REPO" --state open --json number 2>/dev/null) || {
    # gh non disponibile o errore di rete: silenzioso (non e' un'errore fatale
    # per un watchdog, ci riprovera' al prossimo tick).
    exit 0
}

# Estrae i numeri delle PR aperte dal JSON.
OPEN_PRS=$(printf '%s\n' "$OPEN_PRS_JSON" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for item in data:
    print(item.get('number', ''))
")

# Nessuna PR aperta = silenzio.
[ -z "$OPEN_PRS" ] && exit 0

NEW_FOUND=0
while IFS= read -r num; do
    [ -z "$num" ] && continue
    key="$REPO#$num"
    # Salta le PR gia' viste.
    if grep -qxF "$key" "$STATE_FILE" 2>/dev/null; then
        continue
    fi
    # PR nuova: genera e stampa il brief.
    python3 "$PR_BRIEF" --repo "$REPO" --pr "$num" || continue
    echo
    # Registra la PR come vista.
    echo "$key" >> "$STATE_FILE"
    NEW_FOUND=1
done <<< "$OPEN_PRS"

# Silenzioso: nessun output se non ci sono PR nuove.
exit 0
