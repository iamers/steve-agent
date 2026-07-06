#!/usr/bin/env bash
# Backup sicuro di ~/.hermes/kanban.db usando SQLite online backup API.
# Progettato per girare sotto cron watchdog (--no-agent): silenzioso su successo.
# Uso: ./backup-kanban.sh
set -u

KANBAN_DB="$HOME/.hermes/kanban.db"
BACKUP_DIR="$HOME/.hermes/backups"
RETENTION=7

# Se il DB non esiste, exit 0 silenzioso (istanza senza board non è errore)
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
python3 -c "
import sqlite3
import sys

try:
    # Connessione al DB sorgente (in uso, permesso solo lettura)
    src = sqlite3.connect('$KANBAN_DB', uri=True, readonly=True)
    # Connessione al DB destinazione (crea il file)
    dst = sqlite3.connect('$BACKUP_FILE')
    # Online backup
    src.backup(dst)
    src.close()
    dst.close()
    sys.exit(0)
except Exception as e:
    print(f'Errore backup: {e}', file=sys.stderr)
    sys.exit(1)
" || exit 1

# Imposta permessi restrictivi sul backup
chmod 600 "$BACKUP_FILE"

# Cleanup: mantieni gli ultimi 7 backup, elimina i più vecchi
cd "$BACKUP_DIR" || exit 1
ls -t kanban-*.db 2>/dev/null | tail -n +$((RETENTION + 1)) | xargs -r rm -f

# Silenzioso su successo (stdout vuoto)
exit 0