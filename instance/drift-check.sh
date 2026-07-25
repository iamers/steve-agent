#!/usr/bin/env bash
# Drift check: confronta la config live dell'istanza con la copia canonica nel
# repo. Segnala, non ripristina. Uso: ./drift-check.sh [ssh-alias]
set -u
cd "$(dirname "$0")" || exit 1

HOST="${1:-${STEVE_HOST:?pass host as arg1 or set STEVE_HOST}}"
drift=0

echo "== config.yaml (live vs repo) =="
# Due blocchi top-level vivono solo sull'istanza live e non devono mai
# entrare nel repo, quindi li escludiamo dal confronto su entrambi i lati:
#  - "dashboard:": credenziali basic-auth (password_hash e secret)
#  - "onboarding:": flag first-run (onboarding.seen.*) scritti a runtime dal
#    gateway, non configurazione
# Escluderli PRIMA di stampare qualsiasi diff è anche una garanzia di
# sicurezza: nessun hash o secret può finire nell'output del check.
#
# Il confronto è SEMANTICO (YAML parsato, chiavi ordinate), non testuale.
# Motivo: il file live è scritto da Hermes, che quando riscrive il config
# rimuove TUTTI i commenti e normalizza le virgolette (misurato il 2026-07-25:
# live 0 righe di commento, canonico 24, contenuto funzionale identico).
# Confrontare a testo pretenderebbe che due artefatti con proprietari diversi
# coincidano byte per byte, e costringerebbe a spogliare il canonico della
# documentazione che serve a chi lo legge. Il confronto semantico cattura ogni
# differenza che conta (chiavi, valori, struttura) e ignora solo la
# formattazione che non controlliamo.
strip_blocks='/^(dashboard|onboarding):/{skip=1; next} /^[A-Za-z_]/{skip=0} !skip'
live_cfg=$(mktemp); trap 'rm -f "$live_cfg"' EXIT
ssh "$HOST" 'cat ~/.hermes/config.yaml' > "$live_cfg"

if python3 -c 'import yaml' 2>/dev/null; then
  sem=$(mktemp); trap 'rm -f "$live_cfg" "$sem"' EXIT
  cat > "$sem" <<'PY'
import sys, json, difflib, yaml

INSTANCE_ONLY = ("dashboard", "onboarding")


class StrictLoader(yaml.SafeLoader):
    """SafeLoader che RIFIUTA le chiavi duplicate.

    yaml.safe_load, di suo, tiene silenziosamente l'ultima occorrenza di una
    chiave ripetuta. Su un confronto semantico questo aprirebbe un buco: un file
    live con una chiave duplicata il cui ULTIMO valore coincide col canonico
    verrebbe dichiarato allineato, mentre il file è realmente diverso e
    malformato. Il confronto testuale lo intercettava; questo lo intercetta
    fallendo CHIUSO, cioè segnalando drift invece di tacere.
    """


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key: {key!r}", key_node.start_mark
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def norm(path, label):
    # I blocchi instance-only sono già stati rimossi A MONTE, prima di arrivare
    # qui: vedi il filtro awk applicato a entrambi i lati. È deliberato e non
    # ridondante. Se li rimuovessimo dopo il parsing, un errore del parser
    # DENTRO un blocco escluso verrebbe formattato e stampato prima
    # dell'esclusione, portandosi dietro il token incriminato: un hash o un
    # secret della dashboard finirebbe nell'output del check. Rimuovendoli
    # prima, quel contenuto non raggiunge mai il parser.
    try:
        data = yaml.load(open(path), Loader=StrictLoader) or {}
    except yaml.YAMLError as exc:
        print(f"{label}: invalid YAML or duplicate keys: {exc}")
        sys.exit(1)
    for key in INSTANCE_ONLY:
        data.pop(key, None)  # difesa in profondità: già rimossi a monte
    return json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False).splitlines()


repo, live = norm(sys.argv[1], "repo"), norm(sys.argv[2], "live")
if repo == live:
    sys.exit(0)
sys.stdout.write("\n".join(difflib.unified_diff(repo, live, "repo", "live", lineterm="")) + "\n")
sys.exit(1)
PY
  # Filtra i blocchi instance-only PRIMA del parsing: così il loro contenuto
  # non raggiunge mai il parser e non può finire nel messaggio di un errore.
  repo_s=$(mktemp); live_s=$(mktemp)
  trap 'rm -f "$live_cfg" "$sem" "$repo_s" "$live_s"' EXIT
  awk "$strip_blocks" config.yaml  > "$repo_s"
  awk "$strip_blocks" "$live_cfg"  > "$live_s"
  if python3 "$sem" "$repo_s" "$live_s"; then
    echo "OK: config.yaml aligned (semantic compare; dashboard/onboarding excluded)"
  else
    drift=1
  fi
else
  # Degradazione: senza pyyaml si torna al confronto testuale storico. È più
  # rumoroso (segnala commenti e virgolette che Hermes normalizza) ma non più
  # debole: meglio un falso positivo che un buco nella guardia.
  echo "NOTE: pyyaml unavailable, falling back to textual compare (noisier)"
  if diff -u <(awk "$strip_blocks" config.yaml) <(awk "$strip_blocks" "$live_cfg") ; then
    echo "OK: config.yaml aligned (textual compare; dashboard/onboarding excluded)"
  else
    drift=1
  fi
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
