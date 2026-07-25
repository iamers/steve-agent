#!/usr/bin/env bash
# Drift check: confronta la config live dell'istanza con la copia canonica nel
# repo. Segnala, non ripristina. Uso: ./drift-check.sh [ssh-alias]
set -u
cd "$(dirname "$0")" || exit 1

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"
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
  echo "OK: config.yaml aligned (dashboard and onboarding blocks excluded)"
else
  drift=1
fi

echo
echo "== SOUL.md (live vs repo) =="
if ssh "$HOST" 'cat ~/.hermes/SOUL.md 2>/dev/null' | diff -u SOUL.md - ; then
  echo "OK: SOUL.md aligned"
else
  drift=1
fi

echo
echo "== SOUL profiles (live vs repo) =="
# Confronta il SOUL.md canonico di ogni profilo worker con la copia live.
for profile in steve-worker steve-reviewer; do
  canonical="profiles/$profile/SOUL.md"
  if [ ! -f "$canonical" ]; then
    echo "DRIFT: $profile — missing canonical copy ($canonical)"
    drift=1
    continue
  fi
  if ssh "$HOST" "cat ~/.hermes/profiles/$profile/SOUL.md 2>/dev/null" | diff -u "$canonical" - ; then
    echo "OK: $profile SOUL.md aligned"
  else
    drift=1
  fi
done

echo
echo "== .env: keys set (names, not values) =="
# Chiavi opzionali (marcate "@optional" nel commento di riga di env.template):
# sono facoltative (es. tutto il blocco del merge gate). La loro assenza o
# presenza sull'istanza è legittima, quindi NON generano drift: vengono escluse
# dal confronto missing/extra e riportate solo come riga informativa.
optional_keys=$(grep -E '^[A-Z_]+=.*@optional' env.template | grep -oE '^[A-Z_]+' | sort -u)
# filter_optional: rimuove le chiavi opzionali da un set (già ordinato). Se la
# lista è vuota restituisce l'input invariato: grep -f su un file vuoto non ha
# pattern, ma `echo "$vuota"` produrrebbe una riga vuota che con -v escluderebbe
# tutto — da qui la guardia esplicita.
filter_optional() {
  if [ -n "$optional_keys" ]; then
    grep -vxF -f <(printf '%s\n' "$optional_keys")
  else
    cat
  fi
}
live_keys=$(ssh "$HOST" 'grep -oE "^[A-Z_]+=" ~/.hermes/.env | sort -u' | tr -d =)
tmpl_keys=$(grep -oE '^[A-Z_]+=' env.template | tr -d = | sort -u | filter_optional)
live_filtered=$(echo "$live_keys" | filter_optional)
missing=$(comm -23 <(echo "$tmpl_keys") <(echo "$live_filtered"))
extra=$(comm -13 <(echo "$tmpl_keys") <(echo "$live_filtered"))
[ -n "$missing" ] && { echo "MISSING on instance:"; echo "$missing"; drift=1; }
[ -n "$extra" ]   && { echo "PRESENT live but not in template (consider whether to add them):"; echo "$extra"; drift=1; }
[ -z "$missing$extra" ] && echo "OK: keys aligned"

# Chiavi opzionali: solo informativo, MAI drift.
if [ -n "$optional_keys" ]; then
  opt_set=$(comm -12 <(echo "$optional_keys") <(echo "$live_keys"))
  opt_unset=$(comm -23 <(echo "$optional_keys") <(echo "$live_keys"))
  [ -n "$opt_set" ]   && echo "optional keys set on instance: $(echo "$opt_set" | paste -sd, -)"
  [ -n "$opt_unset" ] && echo "optional keys not set on instance: $(echo "$opt_unset" | paste -sd, -)"
fi

echo
echo "== worker profiles =="
# Ottieni la lista dei profili dall'istanza
profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')

if [ -z "$profiles" ]; then
  echo "OK: no profiles present"
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
        echo "OK: $profile (shared, symlinks correct)"
      else
        echo "DRIFT: $profile (shared, symlinks missing or wrong)"
        echo "  - .gitconfig: $gitconfig_check"
        echo "  - .config/gh: $ghconfig_check"
        echo "  Run on the instance: cd ~/repos/steve-agent && ./instance/provision-worker.sh $profile"
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
        echo "OK: $profile (isolated, credentials isolated)"
      else
        echo "DRIFT: $profile (isolated, credentials non-compliant)"
        echo "  - .gitconfig: $gitconfig_check (must be absent or a regular file, NOT a symlink)"
        echo "  - .config/gh: $ghconfig_check (must be a real directory containing hosts.yml)"
        echo "  For isolated profiles use: HOME=~/.hermes/profiles/$profile/home gh auth login"
        echo "  Do NOT run provision-worker.sh for isolated profiles"
        drift=1
        profiles_ok=false
      fi
    else
      echo "DRIFT: $profile (invalid mode: $mode, must be 'shared' or 'isolated')"
      drift=1
      profiles_ok=false
    fi
  done

  if $profiles_ok; then
    echo "OK: all profiles compliant"
  fi
fi

echo
echo "== profiles: config.yaml (live vs repo) =="

# Profili live sull'istanza
live_profiles=$(ssh "$HOST" 'ls -d ~/.hermes/profiles/*/ 2>/dev/null | xargs -n1 basename | sort -u')
# Copie canoniche nel repo (profiles/<nome>/config.yaml)
canonical_profiles=$(find profiles -maxdepth 1 -mindepth 1 -type d -exec basename {} \; 2>/dev/null | sort -u)

# Nessun profilo live e nessuna copia canonica = OK
if [ -z "$live_profiles" ] && [ -z "$canonical_profiles" ]; then
  echo "OK: no live profiles and no canonical copy"
else
  # 1) Per ogni profilo live: verifica copia canonica e confronta config.yaml
  for profile in $live_profiles; do
    canonical="profiles/$profile/config.yaml"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/profiles/$profile/config.yaml" | diff -u "$canonical" - ; then
        echo "OK: $profile config.yaml aligned"
      else
        drift=1
      fi
    else
      echo "DRIFT: profile $profile live without canonical copy in repo"
      drift=1
    fi
  done

  # 2) Per ogni copia canonica senza profilo live corrispondente
  for profile in $canonical_profiles; do
    if ! echo "$live_profiles" | grep -qx "$profile"; then
      echo "DRIFT: canonical $profile without live profile"
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
  echo "OK: no skills present"
else
  # 1) Per ogni skill live: verifica copia canonica e confronta SKILL.md
  for skill in $live_skills; do
    canonical="skills/$skill/SKILL.md"
    if [ -f "$canonical" ]; then
      if ssh "$HOST" "cat ~/.hermes/skills/$skill/SKILL.md" | diff -u "$canonical" - ; then
        echo "OK: $skill SKILL.md aligned"
      else
        drift=1
      fi
    else
      echo "DRIFT: skill $skill live without canonical copy in repo"
      drift=1
    fi
  done

  # 2) Per ogni copia canonica senza skill live corrispondente
  for skill in $canonical_skills; do
    if ! echo "$live_skills" | grep -qx "$skill"; then
      echo "DRIFT: canonical $skill without live skill"
      drift=1
    fi
  done
fi

echo "----"
if [ "$drift" -eq 0 ]; then echo "drift-check: no drift"; else echo "drift-check: DRIFT DETECTED (update repo or instance, and log it in the journal)"; fi
exit $drift
