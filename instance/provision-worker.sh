#!/usr/bin/env bash
# Provisiona un profilo worker Hermes con i symlink necessari per git e gh CLI.
# I worker Kanban girano con HOME isolato (~/.hermes/profiles/<worker>/home) e
# senza i symlink giusti non vedono ~/.gitconfig né ~/.config/gh dell'utente unix.
# Uso: ./provision-worker.sh <profile-name>
set -u

PROFILE_NAME="${1:-}"

# Verifica argomento
if [ -z "$PROFILE_NAME" ]; then
  echo "Error: specify the profile name" >&2
  echo "Usage: $0 <profile-name>" >&2
  exit 1
fi

PROFILE_DIR="$HOME/.hermes/profiles/$PROFILE_NAME"

# Verifica che il profilo esista
if [ ! -d "$PROFILE_DIR" ]; then
  echo "Error: profile '$PROFILE_NAME' does not exist" >&2
  echo "Create it with: hermes profile create $PROFILE_NAME --clone" >&2
  exit 1
fi

PROFILE_HOME="$PROFILE_DIR/home"
USER_GITCONFIG="$HOME/.gitconfig"
USER_GH_CONFIG="$HOME/.config/gh"

# Crea home/.config se manca
if [ ! -d "$PROFILE_HOME/.config" ]; then
  mkdir -p "$PROFILE_HOME/.config"
fi

# Funzione per creare un symlink idempotente
create_symlink() {
  local target="$1"
  local link="$2"
  local desc="$3"

  # Se il link esiste già ed è un symlink
  if [ -L "$link" ]; then
    local current_target
    current_target=$(readlink "$link")
    if [ "$current_target" = "$target" ]; then
      echo "OK: $desc already configured ($link -> $target)"
      return 0
    else
      # Link punta altrove, sovrascrivi
      ln -sfn "$target" "$link"
      echo "FIX: $desc updated ($link -> $target)"
      return 0
    fi
  fi

  # Se è una directory reale (non symlink perché sopra -L era false)
  if [ -d "$link" ]; then
    if [ -z "$(ls -A "$link")" ]; then
      # Directory vuota, rimuovila e crea il symlink
      rmdir "$link"
      ln -s "$target" "$link"
      echo "FIX: empty directory removed, $desc created ($link -> $target)"
      return 0
    else
      # Directory non vuota, errore
      echo "Error: $link exists and is a non-empty directory" >&2
      echo "Cannot overwrite automatically. Remove it manually or empty it." >&2
      return 1
    fi
  fi

  # Se è un file regolare, errore
  if [ -f "$link" ]; then
    echo "Error: $link exists and is a regular file" >&2
    echo "Cannot overwrite automatically. Remove it manually." >&2
    return 1
  fi

  # Non esiste, crea il symlink
  ln -s "$target" "$link"
  echo "OK: $desc created ($link -> $target)"
  return 0
}

# Crea i symlink
already_provisioned=true

create_symlink "$USER_GITCONFIG" "$PROFILE_HOME/.gitconfig" ".gitconfig" || already_provisioned=false
create_symlink "$USER_GH_CONFIG" "$PROFILE_HOME/.config/gh" ".config/gh" || already_provisioned=false

# Riepilogo
echo
echo "=== Symlink verification ==="
echo -n ".gitconfig: "
if [ -L "$PROFILE_HOME/.gitconfig" ]; then
  readlink "$PROFILE_HOME/.gitconfig"
else
  echo "NOT LINK"
fi
echo -n ".config/gh: "
if [ -L "$PROFILE_HOME/.config/gh" ]; then
  readlink "$PROFILE_HOME/.config/gh"
else
  echo "NOT LINK"
fi

if $already_provisioned; then
  echo
  echo "already provisioned"
fi

exit 0
