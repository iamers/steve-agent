#!/usr/bin/env bash
# Backup sicuro di ~/.hermes/kanban.db usando SQLite online backup API.
# Progettato per girare sotto cron watchdog (--no-agent): silenzioso su successo.
# Uso: ./backup-kanban.sh
set -u

KANBAN_DB="$HOME/.hermes/kanban.db"
BACKUP_DIR="$HOME/.hermes/backups"
RETENTION=7

# If the DB does not exist, exit 0 silently (an instance without a board is not an error)
if [ ! -f "$KANBAN_DB" ]; then
  exit 0
fi

# Crea la directory backup se manca
if [ ! -d "$BACKUP_DIR" ]; then
  mkdir -p "$BACKUP_DIR"
  chmod 700 "$BACKUP_DIR"
fi

# Timestamp per il nome del backup
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/kanban-$TIMESTAMP.db"

# Esegui il backup usando Python sqlite3 online backup API
KANBAN_DB="$KANBAN_DB" BACKUP_FILE="$BACKUP_FILE" python3 -c "
import sqlite3
import sys
import os

kanban_db = os.environ['KANBAN_DB']
backup_file = os.environ['BACKUP_FILE']

try:
    # Connessione al DB sorgente (in uso, permesso solo lettura)
    src = sqlite3.connect(f'file:{kanban_db}?mode=ro', uri=True)
    # Connessione al DB destinazione (crea il file)
    dst = sqlite3.connect(backup_file)
    # Online backup
    src.backup(dst)
    src.close()
    dst.close()
    sys.exit(0)
except Exception as e:
    print(f'Backup error: {e}', file=sys.stderr)
    sys.exit(1)
" || exit 1

# Imposta permessi restrictivi sul backup
chmod 600 "$BACKUP_FILE"

# Cleanup: keep the latest 7 backups, delete the oldest ones (database file
# plus any WAL/SHM sidecar files SQLite may have left next to it -- a plain
# "*.db" glob does not match "*.db-wal" or "*.db-shm").
cd "$BACKUP_DIR" || exit 1
ls -t kanban-*.db 2>/dev/null | tail -n +$((RETENTION + 1)) | while IFS= read -r old; do
  rm -f -- "$old" "${old}-wal" "${old}-shm"
done

# Silenzioso su successo (stdout vuoto)
exit 0
