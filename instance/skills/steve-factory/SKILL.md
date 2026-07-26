---
name: steve-factory
description: "Runbook per il profilo main: orchestrare il ciclo factory (task, review, merge) dalla chat senza coordinatore esterno."
version: 1.0.0
author: Steve Agent
license: MIT
metadata:
  hermes:
    tags: [orchestration, kanban, factory, review, steve]
    related_skills: []
---

# Steve Factory — runbook del profilo main

## Overview

Questa skill insegna al profilo main (Steve, l'orchestratore in chat) a gestire
l'intero ciclo factory senza un coordinatore esterno: creare task di sviluppo,
farli revieware, portarli alla decisione di merge. La board kanban e' la verita';
la chat e' dove si decide, non dove si sviluppa.

Steve NON sviluppa in chat (vedi SOUL.md), NON tocca il runtime dell'istanza,
NON mergia: finche' la fase 2 non e' attiva il merge resta umano.

## Quando si usa

- Un membro propone un lavoro che finira' in un repo tracked.
- Arriva la notifica di una PR aperta e serve avviare la review.
- Serve redirigere un task dopo una review con request-changes.

Non si usa per: discussioni di solo prodotto, brainstorming, o cio' che non
produce file committati.

## 1. Ruolo e confini

- Steve orchestra dalla chat. Lo sviluppo avviene nei task dispatchati, mai in
  conversazione diretta (la regola vive in SOUL.md, qui la si onora).
- Mai modificare il runtime dell'istanza (config live, profili, credenziali):
  quelle sono operazioni di ops, non di orchestrazione.
- Mai mergiare direttamente. La fase 2 e' **attiva**: il merge gate
  (`instance/merge-gate.sh`) e' deployato, testato con canary reale (#46,
  HTTP 200). Il gate automatizza il lavoro meccanico, NON la decisione: quando
  il coordinatore (owner) da' l'approve in chat, Steve applica la label
  `steve-approved` sulla PR e l'owner (o un cron) esegue il gate. Il gate
  verifica le 5 condizioni (label, review, CI, tier safe, SHA match) e solo
  se tutte vere esegue il merge commit. Steve NON esegue il gate lui stesso:
  applica la label, l'esecuzione e' dell'owner o del cron (vedi
  .steve/pr-lifecycle.md).
- La board e' la verita': se un lavoro non e' un task sulla board, non esiste.

## 2. Creare un task di sviluppo

Prima di creare e dispatchare task, aggiorna `main` nel clone, così i nuovi
worktree partono dalla base corrente:

    git -C <clone> fetch --quiet origin main && git -C <clone> merge --ff-only origin/main

I worktree sono creati da `HEAD` con `git worktree add`, senza fetch: un clone
stale produce branch stale e lavoro di rebase successivo. Se il merge non è
fast-forward, fermati e segnalalo: il clone è divergente, è una situazione
ops e non va forzata.
Per un batch di task indipendenti esegui l'aggiornamento una sola volta, prima
di crearli, non una volta per task.

Usa il tool `kanban_create` (o il CLI `hermes kanban create`). Il brief DEVE
contenere, in modo che il worker possa verificarlo da solo:

- **Goal** in una frase.
- **Vincoli** (convenzioni, dipendenze, vincoli di linguaggio).
- **Boundaries**: elenco esplicito dei file/cartelle toccabili. Tutto cio' che
  non e' in lista e' fuori limite.
- **Verify eseguibili**: comandi con exit 0 atteso che il worker deve mostrare
  eseguiti nel proprio result.
- **Stop-when**: condizione che dice al worker quando fermarsi e riportare.

Campi del task:

- `assignee: steve-worker`
- `--project steve-agent` (worktree e branch li deriva il sistema)
- `--goal` per i task sostanziali (goal loop)
- `--skill` per forzare le skill bundled pertinenti; in particolare
  `github/github-pr-workflow` per i task che aprono PR
- `--parent` per le dipendenze: la promozione a ready quando i parent sono done
  e' automatica, non va gestita a mano

**Task che aprono PR e coinvolgono CI:** nel brief scrivi esplicito che il
worker NON deve fare polling attivo sullo stato CI (vedi Pitfall #6): una
sola chiamata con timeout generoso, poi completa con il numero PR anche se la
CI e' ancora pending. Il coordinatore verifica a posteriori. Comando per lo
stato CI: `gh run list --commit <sha>` (NON `gh pr checks`, che richiede lo
scope separato "Checks: read" non disponibile sui PAT correnti).

Dopo la creazione: notify-subscribe del task al topic Telegram della story (o al
topic Backlog di default), cosi' gli esiti arrivano in push invece di dover
essere interrogati.

**Batch di task indipendenti (dispatch parallelo):** quando un membro propone
N task indipendenti (es. batch pre-publish: scrub, license, narrative), creali
tutti con `kanban_create` (senza `parents` reciproci: vanno dritti a `ready`),
poi esegui un solo `hermes kanban dispatch`. Il dispatcher spawna i worker in
parallelo, ciascuno nel proprio worktree su branch indipendente. Nessun
conflitto tra PR: ogni worker lavora su file diversi. Crea le review man mano
che i worker chiudono.

## 3. Sanitizzazione

OBBLIGATORIO per ogni task che produce file committati. La lista delle stringhe
vietate ha UNA SORGENTE LOGICA (un seed condiviso) con copie per-macchina:

- Sull'istanza vive in `~/.hermes/private/forbidden-strings.txt` ed e' quella
  che Steve legge per costruire i brief.
- Sulla stessa macchina, il clone del repo la aggancia come
  `.local/privacy-denylist.txt` tramite un symlink gitignorato, cosi' la guardia
  `scripts/check_privacy.sh` consuma la STESSA lista (il path e'
  `.local/privacy-denylist.txt`, overridabile via `PRIVACY_DENYLIST`).
- Tenere sincronizzate le copie tra macchine e' un compito ops dichiarato, non
  di Steve: se le copie divergono fa fede il seed della guardia dev-privacy.

Nei worktree `--project` il symlink `.local/privacy-denylist.txt` NON esiste
(vive nel clone del repo): colma il gap `PRIVACY_DENYLIST` dall'ambiente — il
gateway la esporta ai worker dispatchati dal `.env` dell'istanza. Se punta al
file denylist (path assoluto, es. `~/.hermes/private/forbidden-strings.txt`),
`scripts/check_privacy.sh` lo usa direttamente: il worker esegue i check del
brief anche senza il `.local/`.

Per ogni stringa della lista, includi nel verify del brief un check negativo:

    ! grep -qi <stringa> <file>

REGOLA FONDAMENTALE: mai copiare i valori della lista in file committabili, nei
body delle PR o nei messaggi pubblici. Nel brief si citano come check, non si
commentano e non si trascrivono. Il path e' il riferimento; il contenuto resta
locale e privato.

## 4. Ciclo di review

Alla notifica di PR aperta, crea un task di review:

- `assignee: steve-reviewer`
- `--skill github/github-code-review`
- Review formale della PR via `gh`: `approve` oppure `request-changes` motivato.

Il brief del task di review DEVE imporre la **riesecuzione** dei verify, non la
sola rilettura del diff: il reviewer non si fida delle claim di esecuzione del
worker, le **riesegue**. Per **ogni** task di review:

- **(a)** Riporta **testuali** nel body del task i comandi verify del brief
  originario del worker: copiali, non parafrasarli (il reviewer deve eseguire
  esattamente cio' che il worker ha dichiarato).
- **(b)** Il reviewer **riesegue** i verify nel worktree del task e **incolla**
  nel result di review il loro esito (stdout + exit code) per ciascuno.
- **(c)** Se anche un solo verify fallisce, la review e' **REQUEST_CHANGES** a
  prescindere dal diff: un codice che sembra corretto ma non passa i verify non e'
  approvabile. La review verifica, non rilegge soltanto.

L'autore non revisiona mai se stesso: se il worker che ha aperto la PR coincide
con il reviewer, assegna la review a un altro profilo.

Se la review e' REQUEST_CHANGES, il task del worker originale risulta gia' `done`
(un task done non si ri-dispatcha nel nostro flusso). Crea invece un NUOVO task
di fix:

1. `kanban_create` con `assignee: steve-worker`, `--parent` il task originario,
   e `workspace dir:<path del worktree del task originario>` (cosi' lavora sullo
   stesso branch e la PR si aggiorna).
2. Il body del task di fix riporta i finding del reviewer **testuali** piu'
   l'istruzione di pushare sul branch corrente **senza aprire nuove PR**.
3. Dopo il fix, crea un nuovo task di re-review per `steve-reviewer`.

Il thread di commenti del task originario resta il posto dove tracciare la
catena: un `kanban_comment` sul task padre registra l'esito di ogni giro
(fix applicato, re-review richiesta, esito della re-review).

## 5. Brief approvabile e decisione umana

Il compilatore (`tools/pr-brief.py`) e' un GATE su ogni PR aperta, come da
.steve/pr-lifecycle.md: calcola il tier di ogni file modificato contro
.steve/review-policy.yaml e produce il brief (il tier della PR e' il massimo tra
i file: blast > propagation > safe).

**Titoli e descrizioni delle PR in inglese.** Il titolo e il corpo della PR
si scrivono in inglese: coerenza con la convention "identifiers in inglese"
di AGENTS.md, e perche' il diff e' pubblico. Lo scrivi esplicito nel brief di
ogni task che apre una PR, cosi' il worker onora la regola.

La decisione resta umana:

- `approve` nel topic -> merge (oggi manuale; fase 2 sara' tracciato).
- `reject: <motivo>` -> l'autore riceve il motivo del reject nel topic e itera
  da quello. Il redesign draft generato dal compilatore e' il comportamento
  TARGET (vedi la tabella di stato in .steve/pr-lifecycle.md), non cio' che il
  tool fa oggi: non promettere cio' che il tool non fa.

Il brief concentra la decisione: non sostituire il giudizio informato dal tier
con una opinione libera non motivata.

## 6. Approve-in-chat: la label attiva il gate

Questa e' la regola operativa che attiva il gate deterministico. La decisione
di merge resta umana (§5); questa sezione dice **cosa fa Steve** quando
l'admin approva in chat: applica la label e si ferma.

1. **Quando l'ADMIN approva in chat una PR** (es. "approva #NN", "approve
   #NN"), tu applichi sulla PR la label di approvazione `steve-approved` PIU'
   un commento sulla PR che cita la decisione: chi ha approvato, quando, e il
   tier della PR. Esempio di commento:
   `Approved by @<admin-handle> in chat (<data>). Tier: safe. Merge gate eligible.`
2. **NON mergi MAI.** Il merge lo esegue il gate deterministico
   `instance/merge-gate.sh` (solo per tier safe, dopo che la label e' applicata
   e le altre 4 condizioni sono soddisfatte) oppure l'umano su GitHub (per
   propagation/blast, dove il gate rifiuta). La regola "mai mergiare" del §1
   resta invariata: la label e' autorizzazione, non esecuzione.
3. **Solo l'admin puo' autorizzare.** Verifica l'identita' di chi scrive come
   fai gia' per i comandi tiered (lo stereotipo dell'admin e' configurato
   nell'istanza). Un approve da un non-admin va ignorato.
4. **Se il tier della PR NON e' safe: dillo all'admin e NON applicare la
   label.** Il gate rifiuterebbe comunque (condizione d: tier deve essere
   safe), ma non applicare la label evita rumore inutile e un reject del cron
   ogni 5 minuti. Spiega all'admin: "tier propagation/blast, il gate non
   copre questo tier — il merge e' manuale su GitHub." Per i tier non-safe,
   l'admin fa il merge a mano sulla UI GitHub.
5. **La label e' la marcatura dell'autorizzazione; la fonte di verita' che il
   gate legge resta sulla PR** (label + review APPROVED + CI verde + SHA
   match). La label da sola non basta: il gate verifica tutte le 5
   condizioni. Applicare la label e' necessario ma non sufficiente.
6. **Istanza senza merge gate.** Il gate e la GitHub App sono OPZIONALI:
   l'adopter sceglie in fase di installazione se attivarli. Prima di concludere
   che il merge gate NON e' configurato, esegui questo probe e incolla il suo
   risultato nel tuo reasoning:
   ```bash
   [ -n "${STEVE_MERGE_APP_ID:-}" ] && [ -n "${STEVE_MERGE_KEY_PATH:-}" ] \
     && [ -f "${STEVE_MERGE_KEY_PATH}" ] \
     && echo "merge gate: CONFIGURED" || echo "merge gate: NOT CONFIGURED"
   ```
   Il probe non stampa segreti e non legge il contenuto della chiave: verifica
   solo che App id e key path non siano vuoti e che il file indicato esista.
   Un "not configured" non verificato non e' una conclusione accettabile. Se
   non puoi eseguire il probe, dichiaralo, chiedi all'admin e non scegliere per
   default il ramo senza gate: quel ramo riporta silenziosamente la catena
   approve-in-chat al merge manuale e il sistema non lo segnala. Solo se il
   probe restituisce `merge gate: NOT CONFIGURED`, **NON applicare la label
   `steve-approved`**: nessuno la legge, sarebbe una marcatura morta. In
   quel caso un approve in chat significa solo che il merge lo fa l'umano su
   GitHub. Dillo esplicitamente all'admin: \"approve registrato, merge
   manuale su GitHub (nessun gate configurato su questa istanza).\" Il
   flusso e' identico a quello pre-gate: review approvata -> merge umano,
   nulla cambia per l'adopter. La label serve SOLO quando esiste un gate
   che la consuma.

**Scanner cron.** L'orchestratore non esegue il gate direttamente, ne' esegue
lo scanner. Deve pero' sapere che `instance/merge-gate-scan.sh` esiste: e' il
cron scanner che trova le PR etichettate `steve-approved` e invoca il gate su
ciascuna. La label che tu applichi e' esattamente cio' che lo scanner cerca.
Dopo aver applicato la label + commento, il tuo lavoro e' finito: e' lo
scanner (cron) o l'umano (UI GitHub) a portare la PR al merge.

## 7. Convenzione topic per story

Se la story ha un topic Telegram dedicato, TUTTI i suoi task vanno iscritti a
quel topic (notify-subscribe). Il topic Backlog resta l'indice trasversale:
mantiene la vista d'insieme ma non e' il posto dove discutere il singolo task.

## Common Pitfalls

1. **Sviluppare in chat.** Se stai scrivendo codice nella conversazione invece
   di creare un task, stai violando la SOUL. Ferma e metti sulla board.

2. **Brief senza verify eseguibili.** "funziona" non e' un verify. Il verify e'
   un comando con exit 0 atteso che il worker esegue e mostra nel result.

3. **Sanitizzazione mancante.** Un task che produce file senza i check negativi
   sulle stringhe vietate e' un task non spedito.

4. **Tener traccia della catena di review.** Su REQUEST_CHANGES il task del
   worker originale e' gia' `done`: crea un nuovo task di fix con `--parent`
   (vedi §4) e registra l'esito di ogni giro con `kanban_comment` sul task padre.

5. **L'approve in chat non esegue il merge.** L'approve autorizza. Il merge
   e' eseguito dal gate (`instance/merge-gate.sh`) dopo che Steve ha applicato
   la label `steve-approved`. Il gate e' deployato e attivo (canary #46
   riuscito). Steve NON esegue il gate lui stesso.

6. **Worker in loop su attesa CI (budget esaurito).** Nei task che aprono una
   PR, il worker puo' bruciare tutto il budget iterazioni (60/60) aspettando
   che la CI diventi verde interrogando lo stato in loop. Due trappole:
   - **Circularita':** lo stato CI non torna mai verde finche' la PR non e'
     aperta; se il worker fa polling prima di aprire la PR, e' un loop vuoto.
   - **Costo iterazioni:** ogni interrogazione e' un'iterazione; GitHub CI
     impiega minuti, il budget si esaurisce prima.
   Comando corretto per lo stato CI: `gh run list --commit <sha>` (NON
   `gh pr checks`, che richiede lo scope "Checks: read" non disponibile sui
   PAT correnti). Nei brief di task che aprono PR, scrivi esplicito: "dopo il
   push, apri la PR; chiama `gh run list --commit <sha>` **una sola volta**
   con timeout generoso; se la CI e' ancora pending, completa il task con il
   numero PR — il coordinatore verifica a posteriori". Mai polling attivo.

7. **Diagnosi dei timeout via worktree.** Quando un worker va in timeout
   (`Iteration budget exhausted`), prima di rilanciare o bloccare, ispeziona il
   suo worktree: `git -C <workspace_path> log --oneline -3`, `git status`, e
   verifica se il branch e' pushato sul remote (`git fetch origin <branch>` +
   `gh pr list --head <branch> --state all`). Il lavoro e' spesso gia' commit
   e pushato, ma la PR non e' mai stata aperta (collegato al pitfall #6). In
   quel caso un `kanban_comment` sul task con istruzione "non ripartire da
   zero, apri la PR dal branch esistente" basta a sbloccare il retry.
   Questo pattern si e' confermato valido anche per crash di natura runtime
   (pid not alive, protocol violation): il codice scritto prima del crash
   sopravvive nel worktree, il retry lo riutilizza.

8. **Sanitizzazione nei worktree del project.** I worktree creati con
   `--project steve-agent` NON hanno il symlink `.local/privacy-denylist.txt`
   (vive nel clone del repo, non nei worktree derivati): il gap originale era
   reale. **E' ora chiuso** quando `PRIVACY_DENYLIST` e' nell'ambiente del
   worker — il gateway esporta le chiavi del `.env` dell'istanza ai worker
   dispatchati, e se la variabile punta al file denylist dell'istanza,
   `scripts/check_privacy.sh` lo usa direttamente anche senza il symlink
   `.local/`. Il reviewer che la riesegue e' **cintura di sicurezza**, non
   workaround per un gap. Se invece `PRIVACY_DENYLIST` non e' nell'ambiente
   (deploy non ancora fatto), il worker skippa e lo dichiara; il reviewer
   colma il gap leggendo la denylist da
   `~/.hermes/private/forbidden-strings.txt`. Transitorio, non strutturale.

9. **Verify grep `-A<N>` fragili su policy YAML.** Nei brief, i check
   `grep -A20 'propagation' <policy> | grep <path>` producono falsi positivi
   quando i blocchi YAML sono vicini: `-A20` sfora dal blocco target in quello
   adiacente. Per i verify di classificazione tier su `.steve/review-policy.yaml`,
   **usa un parser YAML** invece di grep contestuale:
   `python3 -c "import yaml; t=yaml.safe_load(open('.steve/review-policy.yaml')); assert '<path>' not in t['tiers'].get('propagation',{}).get('paths',[])"`.
   Vale anche per i verify nei brief di review.

10. **Profile down dopo deploy di config (model swap).** Quando un profilo
    worker o reviewer riceve un nuovo config deployato (in particolare un cambio
    di `model.default` o `model.provider`), puo' diventare instabile: crash
    ripetuti con `protocol violation` (exit rc=0 senza chiamare
    `kanban_complete`) o `pid not alive`. I worktree conservano il lavoro
    pre-crash (vedi pitfall #7), ma il profilo resta down finche' il config non
    viene corretto o roll-back-ato.
    - **Sintomi:** 2+ crash consecutivi con la stessa `protocol_violation` sullo
      stesso task, heartbeat regolari fino all'uscita pulita senza complete.
    - **Diagnosi:** se il crash segue a meno di 1h dal deploy di un config con
      model swap, sospetta correlazione. Chiedi al coordinatore (ops) di
      verificare il config attivo del profilo.
    - **Non bruciare retry** oltre il secondo crash consecutivo identico: il
      problema e' sistemico, non transiente.

11. **Self-review GitHub constraint blocca il fallback.** I profili `main` e
    `steve-worker` condividono lo stesso account GitHub (`scrat-ai-dev`):
    GitHub vieta a un account di approvare la propria PR. Quando
    `steve-reviewer` (account separato `scrat-ai-rev`) e' down, l'orchestratore
    **non puo' sostituirsi** registrando l'approve su GitHub — anche se esegue
    i verify e documenta tutto in un `kanban_comment`.
    - **Fallback quando il reviewer e' down:** esegui i verify dal profilo main
      nel worktree di review, registra esito e verdetto in un `kanban_comment`
      sul task, e **segnala al coordinatore** che serve un approve manuale
      (dalla UI GitHub con l'account `scrat-ai-rev`, se accessibile) o il
      ripristino del reviewer.
    - **Non tentare `gh pr review --approve` dal profilo main** su PR aperte da
      steve-worker: restituisce `Review can not approve your own pull request`.

12. **Deadlock `respawn_guarded` con `active_pr` e figli bloccati.** Quando un
    worker ha aperto la PR e si e' bloccato con `review-required`, il dispatcher
    puo' iniziare a respawnerlo in loop con `respawn_guarded` reason
    `active_pr`. Il worker non fa progresso (la PR e' gia' aperta) ma non
    raggiunge mai `done`, quindi eventuali task figli (es. review con
    `parents=[worker_task]`) restano in `todo` indefinitamente. La factory si
    ferma per ore senza che nessuno se ne accorga.
    - **Sintomi:** `hermes kanban diagnostics` mostra `stranded_in_ready` sul
      task padre; gli eventi sono una coda di `respawn_guarded` ogni 60s; il
      task figlio e' in `todo` con zero run.
    - **Fix:** completa manualmente il padre con `hermes kanban complete
      <task_id> --summary "..."` o `kanban_complete(task_id=..., summary=...)`.
      Il padre passa a `done`, il figlio si promuove a `ready`, il prossimo
      `hermes kanban dispatch` lo pick up.
    - **Prevenzione:** quando un worker blocca con `review-required` e ha figli
      in `todo`/`ready`, completa il padre subito invece di aspettare che il
      dispatcher lo risolva da solo. Il dispatcher non completa task
      `blocked`/`respawn_guarded` automaticamente.

13. **Provider rate-limit (429) causa crash review transienti.** Non solo i
    model swap (pitfall #10): anche un rate-limit 429 del provider LLM
    causa crash `pid not alive` e `protocol_violation` sui profili worker e
    reviewer. Diversamente dal pitfall #10 (sistemico), questo e' **transiente**:
    la quota si libera, e al retry il profilo completa pulito.
    - **Sintomi:** 1-2 crash consecutivi, poi un unblock manuale e retry
      che completa in pochi minuti.
    - **Diagnosi:** se il crash avviene in finestra di carico e il retry
      post-unblock chiude pulito, era rate-limit. Controlla gli eventi del task
      per `gave_up` seguito da `unblocked` e `completed`.
    - **Azione:** non bruciare retry. Se il dispatcher ha gia' fatto `gave_up`,
      un `kanban_comment` con "retry" + `kanban_unblock` fa ripartire il task al
      prossimo dispatch.

14. **Accoppiamento assert/stringa in pr-brief.py: la dipendenza e' interna al tool.** Nei brief che toccano pr-brief.py, l'accoppiamento critico tra `run_self_test()` e il template NON e' template→tool (come si potrebbe pensare): la stringa emessa nel brief la inietta pr-brief.py stesso, non il template. Quindi la dipendenza da cercare e' tutta interna al tool — se traduci una stringa emessa da render_brief(), l'assert in run_self_test() che la controlla va aggiornato nello stesso file, nello stesso commit.

15. **Testo canonico da fonti esterne: verify con diff, non con grep marker.**
    Quando un worker deve riprodurre un testo canonico verbatim (licenze,
    standard, specifiche), i verify basati su grep marker (`grep -c
    'Covenants'`, `grep -c 'Notice'`) **non sono sufficienti**: confermano che
    le sezioni ci sono, non che il contenuto e' corretto. Una singola parola
    sbagliata nel testo legale (es. `EXPRESS, IMPLIED` invece di `EXPRESS OR
    IMPLIED` in una disclaimer BUSL-1.1) passa tutti i grep marker.
    - **Nel brief del task di review**, per testo canonico, includi un verify
      che **scarica la fonte ufficiale** (con `curl`) e **confronta** il
      contenuto del file nel worktree riga per riga, con tolleranza solo su
      whitespace/wrapping.
    - **Differenziare dal diff review normale:** il reviewer legge il diff come
      racconto; per testo canonico, deve confrontare carattere per carattera
      contro la fonte. Sono due check diversi con due tecniche diverse.
    - **Pattern di brief:** "scarica `https://spdx.org/licenses/BUSL-1.1.html`,
      estrai il testo dalla sezione 'Terms' in poi, confronta col file LICENSE
      nel worktree. Tolleranza solo su whitespace/wrapping. Se trovi
      discrepanze materiali nel testo legale -> REQUEST_CHANGES."

16. **Race condition sui commenti di review ai task running.** Quando il coordinatore posta un `kanban_comment` con findings aggiuntivi su un task di review gia' in stato `running`, il reviewer puo' completare e approvare PRIMA di leggere il commento. La finestra e' di decine di secondi: il commento arriva dopo che il reviewer ha gia' passato la fase di lettura del brief, o addirittura dopo che ha gia' chiamato `gh pr review --approve`.
    - **Sintomi:** il reviewer completa con APPROVED, e il coordinatore vede il proprio commento marcato "just now" accanto a un task gia' done. I difetti segnalati non sono nella review su GitHub.
    - **Causa:** il dispatcher spawna il reviewer al `dispatch`; il commento arriva dopo, ma il reviewer non rilegge i commenti durante l'esecuzione.
    - **Gestione (approccio adottato):** se il reviewer salta il commento, scatena comunque il fix sul branch esistente (come si fa per qualsiasi REQUEST_CHANGES post-approve). L'approve su GitHub resta valido; il fix commit aggiorna la PR e richiede re-review.
    - **Prevenzione (protocollo operativo):** quando il coordinatore (o il repo owner) manda rilievi su review in corso, **sempre opzione (a) prima**: `kanban_block` il task di review **prima** di commentare, poi `kanban_unblock` dopo aver postato il commento. Questo garantisce che il reviewer rilegga i commenti quando riprende. Solo se il reviewer ha gia' chiuso (task `done`), ricorrere all'opzione (b): fix task sul branch + re-review. Non commentare MAI un task `running` senza averlo prima bloccato: e' il bug che questa sessione ha confermato (reviewer ha approvato #38 e #39 senza incorporare i rilievi, #37 e #40 hanno richiesto fix post-approve).

17. **Redazione del display layer su pattern `Authorization:` (falsi positivi nei review).** Il terminal layer di Hermes maschera qualsiasi pattern `Authorization: *** come `Authorization: ***`. Questo vale per `cat`, `sed -n <N>p`, `grep`, `git show :file | cat`: tutti mostrano `***` anche quando i byte reali sono `${auth}` o `token xyz`. Un reviewer che legge il diff o il file via terminal vede un bug che non esiste.
    - **Sintomi:** il reviewer flagga `Authorization: ***` come literal placeholder, REQUEST_CHANGES. Il worker giustamente dice "il fix e' gia' presente". Si crea un deadlock di review basato su un fantasma.
    - **Diagnosi:** verifica con hex dump (`xxd`, `od -An -tx1`) o Python byte-level (`b"${auth}" in line`). L'hex bypassa il display layer.
    - **Prevenzione:** quando un worker o un reviewer flagga un pattern `Authorization: ***`, prima di dispatchare un fix, verifica i byte reali con `xxd`. Non fidarti di `cat`, `sed`, `grep` per linee che contengono header di autenticazione.
    - **Nel brief di review:** quando si chiede al reviewer di tracciare il flusso auth nel codice, specificare esplicitamente di usare `xxd` o `od` per verificare i byte delle righe con `Authorization:`.

18. **Shell scripts: `bash -n` non basta, la CI esegue `shellcheck --severity=warning`.** Quando un worker modifica file `.sh`, `bash -n` verifica solo la sintassi (parse) ma non catcha i warning di shellcheck (variabili non quotate, pattern di quoting annidato, ecc.). La CI di steve-agent esegue `shellcheck --severity=warning instance/*.sh scripts/*.sh`: un warning e' rosso.
    - **Nei brief di task che toccano `.sh`:** il verify DEVE includere
      `shellcheck --severity=warning <file>` oltre a `bash -n <file>`. Se
      shellcheck non e' installato nel worktree, il worker lo installa
      (`apt-get install -qq shellcheck` o equivalente) o dichiara l'assenza.
    - **Quoting SSH e SC2027:** il pattern `'"'"$VAR"'"'` per passare variabili
      localmente espandendole dentro single-quote SSH e' fragilissimo: shellcheck
      lo flagga come SC2027 ("surrounding quotes actually unquote this"). La
      forma corretta e' `"'$VAR'"` (close-single-quote dopo la virgoletta
      letterale, expand double-quoted, reopen prima della virgoletta di chiusura).
      Se il task richiede quoting di variabili dentro stringhe SSH single-quoted,
      testa il pattern esplicitamente con shellcheck prima di pushare, e verifica
      empiricamente (sourcing con stub) che il comando remoto assemblato sia
      corretto sotto default e override.

19. **Code path non testabili senza credenziali: il brief di review DEVE imporre code-tracing manuale.** Quando un worker implementa uno script con path che non possono essere esercitati nel worktree (flussi di auth, chiamate di rete, gestione credenziali), il `--self-test` copre solo la logica pura. Il path di auth/rete e' codice morto fino al deploy. Il brief di review DEVE istruire esplicitamente il reviewer di tracciare quei path LEGGENDO il codice, non solo eseguendo i verify. Verificare che ogni parametro ricevuto da una funione arrivi effettivamente alla chiamata di rete (es. `curl -H "Authorization: $auth"`, non un literal placeholder). Questa sessione: merge-gate.sh `gh_api()` aveva `-H "Authorization: ***"` (asterischi letterali) invece di `$auth`: self-test 10/10 verde, shellcheck verde, CI verde. Solo il code-tracing manuale del reviewer ha catturato il bug.

**Sottocaso: code-trace della stringa SSH interna va ESEGUITO, non estratto a mano (falso positivo #49).** Quando il path da tracciare e' dentro una stringa single-quoted passata a `ssh "$HOST" "$@"` (come i check di smoke.sh), la tecnica e' giusta (parsare la stringa interna con `bash -n`) ma **l'estrazione manuale/regex della stringa "tra il primo e l'ultimo apice" e' il difetto**: perde caratteri sui boundary `'"$VAR"'` e fabbrica il bug fantasma che poi "trova". PR #49: il reviewer ha estratto la stringa a mano, perso 5 `;` ai boundary `); if`/`); [`/`); then`, verificato la stringa CORROTTA con `bash -n`, visto fallire e attribuito il difetto al codice. I `;` c'erano tutti nel codice reale. **Metodo corretto (affidabile, niente SSH):** stub della funzione `check()` che rimpiazza `ssh` con `bash -nc` per PARSE-only, definisce le STEVE_* ai default, poi source la SOLA riga del check preso dal file: bash espande variabili e quote-transition ESATTAMENTE come a runtime, `bash -nc` parsa il comando REALE. Mai estrarre a occhio o con regex: il code-trace si fa ESEGUENDO il parse sul comando espanso.

20. **Fix task con `--parent` resta in `todo` se il parent non e' `done`.** Quando crei un task di fix con `--parent` che punta a un task ancora in `ready` (bloccato con review-required), il task figlio resta in `todo` e non si promuove finche' il parent non raggiunge `done`. Il dispatcher ritorna `Spawned: 0` silenziosamente, e il coordinatore potrebbe pensare che il dispatcher sia rotto. **Sintomo:** `hermes kanban dispatch` ritorna zero spawned, il task e' in `todo` con zero run. **Fix:** completa manualmente il parent con `kanban_complete` PRIMA di dispatchare il figlio. E' lo stesso pattern del pitfall #12 (il parent bloccato non si risolve da solo), ma il sintomo e' diverso: invece di respawn_guarded loop, e' silenzio totale.

21. **Bug nei path di rete non testabili: pattern ricorrente e tecnica di scoperta (canary).** L'implementazione del merge-gate ha rivelato una classe di bug sistematica: codice che parsa risposte API GitHub e che e' invisibile a self-test, shellcheck e CI perche' il path di rete non si esercita nel worktree. Tre bug trovati in una sessione, tutti della stessa classe:
    - **Bug tipo 1 (read_field su array):** `cond_label()` usava `read_field(body, "name")` su un endpoint che ritorna un ARRAY di oggetti. `read_field` cammina dot-path e per array pretende indice numerico: `int("name")` → eccezione → stringa vuota → label mai trovata. Fix: parse diretto con Python inline.
    - **Bug tipo 2 (semantica API misconosciuta):** `cond_ci()` declassava a 0 quando GitHub rispondeva `state: "pending"` con `total_count: 0`. Su repo con solo GitHub Actions (zero legacy status), quello "pending" e' sintetico (nessuno status reale). Fix: onorare il legacy status solo se `total_count > 0`.
    - **Bug tipo 3 (substring match dove serve exact):** il `case *"$label"*` faceva match substring. `steve-approved` avrebbe matchato `steve-approved-x`. Fix: funzione pura con confronto esatto.
    - **Tecnica di scoperta (il canary):** nessuno di questi bug era visibile finche' il gate non e' stato eseguito contro un PR reale con credenziali vere (dry-run). Il `--self-test` copriva la logica pura (decide_merge, ci_verdict, label_present), ma i gatherer (cond_label, cond_ci, cond_review) fanno rete e sono codice morto nel worktree. **Il canary e' la tecnica per scoprire questi bug**: una PR safe-tier reale, con label applicata, su cui il gate viene eseguito in dry-run. Ogni condizione che risulta 0 quando dovrebbe essere 1 e' un bug da fixare con regression guard (funzione pura estratta + fixture).
    - **Lezione strutturale:** quando implementi uno script con path di rete, estrai SEMPRE la logica di interpretazione in funzioni pure (come `ci_verdict`, `label_present`) e coprile nel self-test. I gatherer diventano thin wrapper che leggono i dati e li passano alle funzioni pure. Il canary scopre i bug residui.

22. **Outage GitHub transiente (create-PR path).** GitHub puo' andare in outage sul `POST /repos/.../pulls` con HTTP 500 vuoto per decine di minuti. I GET funzionano, il push del branch funziona, il rate-limit e' sano. Il worker non puo' aprire la PR. **Non e' un errore nostro.** Il branch e' pronto, la PR nasce alla ripresa. Sintomi: `gh pr create` ritorna "Something went wrong while executing your query", `gh api -X POST .../pulls` ritorna "unexpected end of JSON input". **Azione:** non bruciare retry. Aspetta che GitHub recuperi (controlla githubstatus.com). Il worktree conserva il codice (pitfall #7). Se il timeout del worker scade, il coordinatore puo' aprire la PR dal main profile quando GitHub e' tornato.

23. **Escape hatch senza gate inferita come scelta prudente.** Disabilita in silenzio l'approve-in-chat e ripristina il merge manuale. Esegui sempre il probe prescritto nel §6 prima di prendere quel ramo.

24. **PR che richiedono rebase senza motivo apparente.** Il clone non è stato
    aggiornato prima del dispatch: i worktree, creati da `HEAD` senza fetch,
    sono partiti da una base stale. Aggiorna `main` una volta prima di creare i
    task, come descritto nel §2.

## Verification Checklist

- [ ] Il brief del task ha goal, vincoli, boundaries, verify eseguibili, stop-when.
- [ ] I check di sanitizzazione sono nel verify per ogni stringa vietata.
- [ ] La review e' assegnata a steve-reviewer con la skill github-code-review.
- [ ] I task della story sono iscritti al topic dedicato.
- [ ] Nessun merge eseguito dall'orchestratore.
- [ ] I verify su policy YAML usano un parser, non `grep -A<N>` (pitfall #9).
- [ ] Se il task usa `--project`, il worker esegue `check_privacy.sh` con
      `PRIVACY_DENYLIST` dall'ambiente; il reviewer lo riesegue come
      cintura di sicurezza (pitfall #8).
- [ ] Se steve-reviewer e' down (2+ crash consecutivi), non bruciare retry:
      documenta i verify dal main e segnala al coordinatore (pitfall #10, #11).
- [ ] Se un worker e' bloccato `review-required` con task figli in coda,
      completa il padre manualmente per evitare deadlock respawn_guarded
      (pitfall #12).
- [ ] Se un profilo crasha per 429 provider (transiente), sblocca con
      `kanban_unblock` invece di bruciare retry (pitfall #13).
- [ ] Se il worker produce testo canonico verbatim (licenze, standard), il
      brief della review include un verify che scarica la fonte ufficiale e
      confronta riga per riga, non solo grep marker (pitfall #15).
- [ ] Se aggiungi rilievi a una review in corso, BLOCCA il task con
      `kanban_block` PRIMA di commentare, poi `kanban_unblock`. Non
      commentare MAI un task `running` senza bloccarlo prima (pitfall #16).
- [ ] Se il task tocca file `.sh`, il verify include `shellcheck
      --severity=warning` oltre a `bash -n`, e il worker lo esegue prima del
      push (pitfall #18).
- [ ] Il repo ha `dismiss_stale_reviews_on_push` attivo: un commit spinto
      dopo l'approvazione INVALIDA la review. Ogni fix post-approve richiede
      una re-review esplicita. Pianifica il ciclo fix -> re-review, non
      assumere che l'approve precedente copra il nuovo commit (pitfall #16).
- [ ] Se uno script ha path non testabili senza credenziali (auth, rete), il
      brief della review impone al reviewer di tracciare quei path LEGGENDO
      il codice, non solo eseguendo i verify (pitfall #19).
      **Sottocaso stringhe SSH interne (smoke.sh):** il code-trace va fatto
      ESEGUENDO `bash -nc` sul comando ESPANSO (stub check() + source della
      riga dal file), MAI estraendo la stringa a mano/regex: l'estrazione
      perde caratteri e fabbrica falsi positivi (lesson da #49).
- [ ] Se un reviewer o un worker flagga `Authorization: ***` in un file,
      verifica i byte reali con `xxd` o `od` prima di dispatchare un fix:
      il display layer maschera i pattern Authorization (pitfall #17).
 - [ ] Se crei un fix task con `--parent`, assicurati che il parent sia `done`
 PRIMA di dispatchare: un parent in `ready`/`blocked` lascia il figlio in
 `todo` e il dispatcher ritorna `Spawned: 0` in silenzio (pitfall #20).
- [ ] Se implementi uno script con path di rete (API, auth), estrai la logica
      di interpretazione in funzioni pure e coprile nel self-test. Usa una
      PR canary safe-tier per testare end-to-end prima della produzione
      (pitfall #21).
- [ ] Se la creazione di una PR ritorna HTTP 500 vuoto, e' un outage GitHub
      transiente. Non bruciare retry: il branch e' pronto, la PR nasce alla
      ripresa (pitfall #22).
- [ ] Quando l'admin approva in chat una PR safe-tier, applichi la label
      steve-approved + commento di decisione. NON mergi: il gate (cron) o
      l'umano (GitHub UI) eseguono il merge.

## References

- `references/deterministic-gate-pattern.md` — architettura per script di
  decisione sicura (merge gate, review guard): separazione pure-decision /
  execution, fixture matrix, SSH quoting pattern, blind spot dei parametri
  non cablati alle chiamate di rete.
