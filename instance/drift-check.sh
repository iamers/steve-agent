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
# Il confine di fine-blocco è QUALSIASI costrutto in colonna 0, non solo una
# chiave che inizia per lettera: una chiave YAML top-level può essere quotata
# ("chiave": valore) e del contenuto malformato può iniziare con un altro
# carattere. Con il vecchio confine /^[A-Za-z_]/ quelle righe restavano dentro
# il blocco e venivano INGHIOTTITE, e la guardia dichiarava "no drift" su un
# file che aveva contenuto top-level in più: un falso negativo.
# I commenti in colonna 0 NON chiudono il blocco (un commento dentro dashboard
# non deve far riemergere le righe successive del blocco stesso).
strip_blocks='/^(dashboard|onboarding):/{skip=1; next} /^[^[:space:]#]/{skip=0} !skip'
live_cfg=$(mktemp); trap 'rm -f "$live_cfg"' EXIT
ssh "$HOST" 'cat ~/.hermes/config.yaml' > "$live_cfg"

if python3 -c 'import yaml' 2>/dev/null; then
  sem=$(mktemp); trap 'rm -f "$live_cfg" "$sem"' EXIT
  cat > "$sem" <<'PY'
import sys, json, difflib, re, yaml

INSTANCE_ONLY = ("dashboard", "onboarding")
ENV_MATERIALIZED = (
    "platforms.telegram.extra.allow_admin_from",
    "platforms.telegram.extra.group_allow_admin_from",
)
MISSING = object()


class StrictLoader(yaml.SafeLoader):
    """SafeLoader che RIFIUTA le chiavi duplicate.

    yaml.safe_load, di suo, tiene silenziosamente l'ultima occorrenza di una
    chiave ripetuta. Su un confronto semantico questo aprirebbe un buco: un file
    live con una chiave duplicata il cui ULTIMO valore coincide col canonico
    verrebbe dichiarato allineato, mentre il file è realmente diverso e
    malformato. Il confronto testuale lo intercettava; questo lo intercetta
    fallendo CHIUSO, cioè segnalando drift invece di tacere.
    """


class DuplicateKey(Exception):
    """Chiave duplicata. Porta con sé SOLO la posizione, mai il nome.

    Il nome NON viene conservato di proposito. Sembrava "struttura e non
    contenuto", ma una chiave dentro un blocco instance-only può essere essa
    stessa sensibile, e gli errori vengono emessi PRIMA che pop() rimuova quel
    blocco. Un'eccezione alla regola "mai testo preso dal documento" è bastata a
    riaprire il buco che la regola chiudeva: qui non ci sono eccezioni.
    """

    def __init__(self, mark):
        self.line = None if mark is None else mark.line + 1
        self.column = None if mark is None else mark.column + 1


def _no_duplicate_keys(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DuplicateKey(key_node.start_mark)
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_duplicate_keys
)


def load(path, label):
    # I blocchi instance-only sono già stati rimossi A MONTE, prima di arrivare
    # qui: vedi il filtro awk applicato a entrambi i lati. È deliberato e non
    # ridondante. Se li rimuovessimo dopo il parsing, un errore del parser
    # DENTRO un blocco escluso verrebbe formattato e stampato prima
    # dell'esclusione, portandosi dietro il token incriminato: un hash o un
    # secret della dashboard finirebbe nell'output del check. Rimuovendoli
    # prima, quel contenuto non raggiunge mai il parser.
    # Un errore del parser NON deve mai riportare testo preso dal documento: il
    # messaggio di PyYAML cita il token incriminato, e quel token può trovarsi
    # dentro un blocco instance-only (una password_hash, un secret). Stampiamo
    # quindi solo TIPO e POSIZIONE. Così la riservatezza non dipende più dal
    # riuscire a riconoscere lessicalmente i blocchi da escludere prima del
    # parsing, che con le molte grafie equivalenti di YAML è una partita persa.
    try:
        data = yaml.load(open(path), Loader=StrictLoader) or {}
    except DuplicateKey as exc:
        where = "" if exc.line is None else f" at line {exc.line}, column {exc.column}"
        print(f"{label}: duplicate key{where}")
        sys.exit(1)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        where = "" if mark is None else f" at line {mark.line + 1}, column {mark.column + 1}"
        print(f"{label}: invalid YAML{where}")
        sys.exit(1)
    for key in INSTANCE_ONLY:
        data.pop(key, None)  # dopo il parsing ogni grafia collassa qui
    return data


def get_path(data, path):
    current = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return MISSING
        current = current[part]
    return current


def drop_path(data, path):
    parts = path.split(".")
    current = data
    parents = []
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        parents.append((current, part))
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    for parent, part in reversed(parents):
        if parent.get(part) == {}:
            parent.pop(part)
        else:
            break


def leaves(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from leaves(item)
    else:
        yield value


def contains_env_reference(value):
    return any(
        isinstance(item, str) and re.search(r"\$\{[^{}]+\}", item)
        for item in leaves(value)
    )


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (dict, list)):
        return not value
    return False


def contains_unexpanded_reference(value):
    return any(
        isinstance(item, str) and re.fullmatch(r"\$\{.*\}", item)
        for item in leaves(value)
    )


repo_data, live_data = load(sys.argv[1], "repo"), load(sys.argv[2], "live")
shape_drift = False
for path in ENV_MATERIALIZED:
    repo_value = get_path(repo_data, path)
    live_value = get_path(live_data, path)

    # Questi valori hanno proprietari diversi: nel repo resta il riferimento
    # alla variabile, mentre sull'istanza deve esserci il valore risolto. Le
    # forme sono verificabili senza mai stampare il contenuto.
    if repo_value is MISSING and live_value is MISSING:
        continue
    if repo_value is MISSING:
        print(f"DRIFT: env-materialized path {path} is missing from the repository")
        shape_drift = True
    elif live_value is MISSING:
        print(f"DRIFT: env-materialized path {path} is missing from the live config")
        shape_drift = True
    else:
        if not contains_env_reference(repo_value):
            print(
                f"DRIFT: repository holds a materialized value for {path}; "
                "the repository is public"
            )
            shape_drift = True
        if is_empty(live_value) or contains_unexpanded_reference(live_value):
            print(
                f"DRIFT: live value for {path} was never expanded; access control "
                "keys in this state disable the administrator"
            )
            shape_drift = True

    # Anche in errore i valori non devono raggiungere il diff semantico: il
    # diagnostico sopra nomina solo il path e la condizione.
    drop_path(repo_data, path)
    drop_path(live_data, path)

repo = json.dumps(repo_data, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
live = json.dumps(live_data, sort_keys=True, indent=2, ensure_ascii=False).splitlines()
semantic_drift = repo != live
if semantic_drift:
    sys.stdout.write("\n".join(difflib.unified_diff(repo, live, "repo", "live", lineterm="")) + "\n")
sys.exit(1 if shape_drift or semantic_drift else 0)
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
  # NESSUNA degradazione: senza pyyaml il confronto non si fa.
  # Il ramo testuale che c'era prima riconosceva i blocchi da escludere con un
  # filtro a righe, e YAML ammette molte grafie equivalenti della stessa chiave
  # ("dashboard":, 'dashboard':, dashboard :, forme con tag o esplicite). Con
  # una grafia non riconosciuta il blocco restava nel diff CON I SUOI VALORI,
  # cioè password_hash e secret finivano nell'output del check. Non è un
  # confronto più rumoroso: è più debole, e su una guardia che tratta segreti
  # non è un compromesso accettabile.
  # Quindi si fallisce CHIUSO e in modo azionabile: non poter verificare non è
  # "nessun drift", è un controllo non eseguito, e va contato come tale.
  echo "ERROR: pyyaml is required to compare config.yaml safely."
  echo "       Install it (e.g. 'pip install --user pyyaml') and re-run."
  echo "       Refusing to fall back to a textual compare: it cannot exclude"
  echo "       instance-only blocks reliably and would print their values."
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
