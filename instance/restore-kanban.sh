#!/usr/bin/env bash
# Restore un backup di kanban.db (prodotto da backup-kanban.sh) in una
# destinazione a scelta, usando la SQLite online backup API (lo stesso
# meccanismo di backup-kanban.sh, in direzione opposta).
#
# La destinazione e' SEMPRE un argomento esplicito: lo script non ha un target
# di default, quindi non puo' mai scrivere sopra un database live per omissione.
# Si rifiuta con un messaggio chiaro ed exit non-zero su sorgente mancante,
# sorgente corrotta, o destinazione gia' esistente; non produce mai un file
# vuoto lasciato li' a sembrare un successo.
#
# Uso: ./restore-kanban.sh <backup-file> <destination-file>
set -u

BACKUP_FILE="${1:-}"
DEST_FILE="${2:-}"

if [ -z "$BACKUP_FILE" ] || [ -z "$DEST_FILE" ]; then
  echo "usage: $0 <backup-file> <destination-file>" >&2
  exit 2
fi

if [ ! -f "$BACKUP_FILE" ]; then
  echo "error: backup file not found: $BACKUP_FILE" >&2
  exit 1
fi

if [ -e "$DEST_FILE" ]; then
  echo "error: destination already exists, refusing to overwrite: $DEST_FILE" >&2
  exit 1
fi

DEST_DIR=$(dirname -- "$DEST_FILE")
if [ ! -d "$DEST_DIR" ]; then
  mkdir -p "$DEST_DIR" || { echo "error: could not create destination directory: $DEST_DIR" >&2; exit 1; }
fi

# Verifica l'integrita' della sorgente PRIMA di scrivere qualsiasi byte sulla
# destinazione, poi esegue il restore con la SQLite online backup API. Un
# fallimento qui non deve lasciare un file di destinazione vuoto o parziale.
BACKUP_FILE="$BACKUP_FILE" DEST_FILE="$DEST_FILE" python3 -c "
import sqlite3
import sys
import os

backup_file = os.environ['BACKUP_FILE']
dest_file = os.environ['DEST_FILE']

try:
    src = sqlite3.connect(f'file:{backup_file}?mode=ro', uri=True)
    check = src.execute('PRAGMA integrity_check').fetchone()[0]
    if check != 'ok':
        print(f'Restore error: backup failed integrity check: {check}', file=sys.stderr)
        sys.exit(1)
    dst = sqlite3.connect(dest_file)
    src.backup(dst)
    src.close()
    dst.close()
    sys.exit(0)
except sqlite3.Error as e:
    print(f'Restore error: {e}', file=sys.stderr)
    sys.exit(1)
"
RC=$?
if [ "$RC" -ne 0 ]; then
  # Rimuove un eventuale file di destinazione vuoto/parziale creato prima del
  # fallimento, cosi' un refuse non lascia un artefatto che sembra un successo.
  rm -f "$DEST_FILE"
  exit 1
fi

chmod 600 "$DEST_FILE"
echo "restored: $BACKUP_FILE -> $DEST_FILE"
exit 0
