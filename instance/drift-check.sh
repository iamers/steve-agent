#!/usr/bin/env bash
# Drift check: confronta la config live dell'istanza con la copia canonica nel
# repo. Segnala, non ripristina. Uso: ./drift-check.sh [ssh-alias]
set -u
cd "$(dirname "$0")" || exit 1

HOST="${1:-ha-steve-dev}"
drift=0

echo "== config.yaml (live vs repo) =="
# Due blocchi top-level vivono solo sull'istanza live e non devono mai
# entrare nel repo, quindi li escludiamo dal confronto applicando lo stesso
# filtro awk a entrambi i lati (il canonico resta senza questi blocchi e il
# drift-check li ignora, senza falsi positivi):
#  - "dashboard:": credenziali basic-auth (password_hash e secret)
#  - "onboarding:": flag first-run (onboarding.seen.*) scritti a runtime dal
#    gateway, non configurazione
strip_blocks='/^(dashboard|onboarding):/{skip=1; next} /^[A-Za-z_]/{skip=0} !skip'
if diff -u <(awk "$strip_blocks" config.yaml) <(ssh "$HOST" 'cat ~/.hermes/config.yaml' | awk "$strip_blocks") ; then
  echo "OK: config.yaml allineato (blocchi dashboard e onboarding esclusi)"
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
echo "== SOUL profili (live vs repo) =="
# Confronta il SOUL.md canonico di ogni profilo worker con la copia live.
for profile in steve-worker steve-reviewer; do
  canonical="profiles/$profile/SOUL.md"
  if [ ! -f "$canonical" ]; then
    echo "DRIFT: $profile — copia canonica mancante ($canonical)"
    drift=1
    continue
  fi
  if ssh "$HOST" "cat ~/.hermes/profiles/$profile/SOUL.md 2>/dev/null" | diff -u "$canonical" - ; then
    echo "OK: $profile SOUL.md allineato"
  else
    drift=1
  fi
done

echo
echo "== .env: chiavi valorizzate (nomi, non valori) =="
live_keys=$(ssh "$HOST" 'grep -oE "^[A-Z_]+=" ~/.hermes/.env | sort -u' | tr -d =)
tmpl_keys=$(grep -oE '^[A-Z_]+=' env.template | tr -d = | sort -u)
missing=$(comm -23 <(echo "$tmpl_keys") <(echo "$live_keys"))
extra=$(comm -13 <(echo "$tmpl_keys") <(echo "$live_keys"))
[ -n "$missing" ] && { echo "MANCANTI sull'istanza:"; echo "$missing"; drift=1; }
[ -n "$extra" ]   && { echo "PRESENTI live ma non nel template (valutare se aggiungerle):"; echo "$extra"; drift=1; }
[ -z "$missing$extra" ] && echo "OK: chiavi allineate"

echo
echo "== worker profiles =="
# Ottieni la lista dei profili dall'istanza
profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')

if [ -z "$profiles" ]; then
  echo "OK: nessun profilo presente"
else
  profiles_ok=true
  for profile in $profiles; do
    # Leggi il mode dalla copia canonica nel repo (default: shared)
    mode_file="profiles/$profile/credentials.mode"
    if [ -f "$mode_file" ]; then
      mode=$(cat "$mode_file")
    else
      mode="shared"
    fi

    if [ "$mode" = "shared" ]; then
      # mode shared: verifica i symlink come prima
      gitconfig_check=$(ssh "$HOST" "[ -L ~/.hermes/profiles/$profile/home/.gitconfig ] && [ \"\$(readlink ~/.hermes/profiles/$profile/home/.gitconfig)\" = ~/.gitconfig ] && echo OK || echo FAIL")
      ghconfig_check=$(ssh "$HOST" "[ -L ~/.hermes/profiles/$profile/home/.config/gh ] && [ \"\$(readlink ~/.hermes/profiles/$profile/home/.config/gh)\" = ~/.config/gh ] && echo OK || echo FAIL")

      if [ "$gitconfig_check" = "OK" ] && [ "$ghconfig_check" = "OK" ]; then
        echo "OK: $profile (shared, symlink corretti)"
      else
        echo "DRIFT: $profile (shared, symlink mancanti o errati)"
        echo "  - .gitconfig: $gitconfig_check"
        echo "  - .config/gh: $ghconfig_check"
        echo "  Esegui sull'istanza: cd ~/repos/steve-agent && ./instance/provision-worker.sh $profile"
        drift=1
        profiles_ok=false
      fi
    elif [ "$mode" = "isolated" ]; then
      # mode isolated: verifica che le credenziali siano isolate
      # 1) home/.config/gh deve essere una directory reale (non symlink) e contenere hosts.yml
      ghconfig_check=$(ssh "$HOST" "[ -d ~/.hermes/profiles/$profile/home/.config/gh ] && [ ! -L ~/.hermes/profiles/$profile/home/.config/gh ] && [ -f ~/.hermes/profiles/$profile/home/.config/gh/hosts.yml ] && echo OK || echo FAIL")
      # 2) home/.gitconfig NON deve essere un symlink (assente o file regolare = ok)
      gitconfig_check=$(ssh "$HOST" "[ ! -L ~/.hermes/profiles/$profile/home/.gitconfig ] && echo OK || echo FAIL")

      if [ "$gitconfig_check" = "OK" ] && [ "$ghconfig_check" = "OK" ]; then
        echo "OK: $profile (isolated, credenziali isolate)"
      else
        echo "DRIFT: $profile (isolated, credenziali non conformi)"
        echo "  - .gitconfig: $gitconfig_check (deve essere assente o file regolare, NON un symlink)"
        echo "  - .config/gh: $ghconfig_check (deve essere una directory reale contenente hosts.yml)"
        echo "  Per profili isolated usa: HOME=~/.hermes/profiles/$profile/home gh auth login"
        echo "  NON eseguire provision-worker.sh per profili isolated"
        drift=1
        profiles_ok=false
      fi
    else
      echo "DRIFT: $profile (mode non valido: $mode, deve essere 'shared' o 'isolated')"
      drift=1
      profiles_ok=false
    fi
  done

  if $profiles_ok; then
    echo "OK: tutti i profili conformi"
  fi
fi

echo
echo "== profili: config.yaml (live vs repo) =="

# Profili live sull'istanza
live_profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')
# Copie canoniche nel repo (profiles/<nome>/config.yaml)
canonical_profiles=$(find profiles -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort -u)

# Nessun profilo live e nessuna copia canonica = OK
if [ -z "$live_profiles" ] && [ -z "$canonical_profiles" ]; then
  echo "OK: nessun profilo live e nessuna copia canonica"
else
  # 1) Per ogni profilo live: verifica copia canonica e confronta config.yaml
  for profile in $live_profiles; do
    canonical="profiles/$profile/config.yaml"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/profiles/$profile/config.yaml" | diff -u "$canonical" - ; then
        echo "OK: $profile config.yaml allineato"
      else
        drift=1
      fi
    else
      echo "DRIFT: profilo $profile live senza copia canonica nel repo"
      drift=1
    fi
  done

  # 2) Per ogni copia canonica senza profilo live corrispondente
  for profile in $canonical_profiles; do
    if ! echo "$live_profiles" | grep -qx "$profile"; then
      echo "DRIFT: canonico $profile senza profilo live"
      drift=1
    fi
  done
fi

echo
echo "== skill: SKILL.md (live vs repo) =="

# Skill bundled stock di Hermes, installate di default e NON gestite da
# steve-agent: escluse dal drift-check (sono legittime sull'istanza senza
# avere un canonico nel repo). La lista corrisponde alle directory top-level
# di skill presenti sotto ~/.hermes/skills/. Da mantenere aggiornata quando
# Hermes aggiunge skill bundled: per ricalcolarla, elenca le directory
# top-level live con `ls -d ~/.hermes/skills/*/` e tieni tutto tranne le
# skill gestite da steve-agent (es. steve-factory).
stock_skills='apple|autonomous-ai-agents|computer-use|creative|data-science|dogfood|email|github|media|mlops|note-taking|productivity|research|smart-home|social-media|software-development|yuanbao'

# Skill live sull'istanza (escluse le stock)
live_skills=$(ssh "$HOST" 'ls -d ~/.hermes/skills/*/ 2>/dev/null | xargs -n1 basename | sort -u' | grep -Ev "^($stock_skills)$")
# Copie canoniche nel repo (skills/<nome>/SKILL.md)
canonical_skills=$(find skills -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort -u)

# Nessuna skill live e nessuna canonica = OK
if [ -z "$live_skills" ] && [ -z "$canonical_skills" ]; then
  echo "OK: nessuna skill presente"
else
  # 1) Per ogni skill live: verifica copia canonica e confronta SKILL.md
  for skill in $live_skills; do
    canonical="skills/$skill/SKILL.md"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/skills/$skill/SKILL.md" | diff -u "$canonical" - ; then
        echo "OK: $skill SKILL.md allineato"
      else
        drift=1
      fi
    else
      echo "DRIFT: skill $skill live senza copia canonica nel repo"
      drift=1
    fi
  done

  # 2) Per ogni copia canonica senza skill live corrispondente
  for skill in $canonical_skills; do
    if ! echo "$live_skills" | grep -qx "$skill"; then
      echo "DRIFT: canonico $skill senza skill live"
      drift=1
    fi
  done
fi

echo "----"
if [ "$drift" -eq 0 ]; then echo "drift-check: nessuna deriva"; else echo "drift-check: DERIVA RILEVATA (aggiorna repo o istanza, e traccia nel journal)"; fi
exit $drift
