#!/usr/bin/env bash
# Drift check: confronta la config live dell'istanza con la copia canonica nel
# repo. Segnala, non ripristina. Uso: ./drift-check.sh [ssh-alias]
set -u
cd "$(dirname "$0")"

HOST="${1:-ha-steve-dev}"
drift=0

echo "== config.yaml (live vs repo) =="
if ssh "$HOST" 'cat ~/.hermes/config.yaml' | diff -u config.yaml - ; then
  echo "OK: config.yaml allineato"
else
  drift=1
fi

echo
echo "== SOUL.md (live vs repo) =="
if ssh "$HOST" 'cat ~/.hermes/SOUL.md 2>/dev/null' | diff -u SOUL.md - ; then
  echo "OK: SOUL.md allineato"
else
  drift=1
fi

echo
echo "== .env: chiavi valorizzate (nomi, non valori) =="
live_keys=$(ssh "$HOST" 'grep -oE "^[A-Z_]+=" ~/.hermes/.env | sort -u' | tr -d =)
tmpl_keys=$(grep -oE '^[A-Z_]+=' env.template | tr -d = | sort -u)
missing=$(comm -23 <(echo "$tmpl_keys") <(echo "$live_keys"))
extra=$(comm -13 <(echo "$tmpl_keys") <(echo "$live_keys"))
[ -n "$missing" ] && { echo "MANCANTI sull'istanza:"; echo "$missing"; drift=1; }
[ -n "$extra" ]   && { echo "PRESENTI live ma non nel template (valutare se aggiungerle):"; echo "$extra"; drift=1; }
[ -z "$missing$extra" ] && echo "OK: chiavi allineate"

echo "----"
if [ "$drift" -eq 0 ]; then echo "drift-check: nessuna deriva"; else echo "drift-check: DERIVA RILEVATA (aggiorna repo o istanza, e traccia nel journal)"; fi
exit $drift
