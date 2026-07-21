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
- Mai mergiare. Fino all'attivazione della fase 2 (vedi .steve/pr-lifecycle.md)
  il merge e' una decisione umana eseguita a mano su GitHub.
- La board e' la verita': se un lavoro non e' un task sulla board, non esiste.

## 2. Creare un task di sviluppo

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
i file: blast > propagazione > sicuro).

La decisione resta umana:

- `approve` nel topic -> merge (oggi manuale; fase 2 sara' tracciato).
- `reject: <motivo>` -> l'autore riceve il motivo del reject nel topic e itera
  da quello. Il redesign draft generato dal compilatore e' il comportamento
  TARGET (vedi la tabella di stato in .steve/pr-lifecycle.md), non cio' che il
  tool fa oggi: non promettere cio' che il tool non fa.

Il brief concentra la decisione: non sostituire il giudizio informato dal tier
con una opinione libera non motivata.

## 6. Convenzione topic per story

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

5. **Merge fai-da-te.** Il merge e' umano fino alla fase 2. Un approve in chat
   autorizza, non esegue.

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

8. **Sanitizzazione skippata nei worktree del project.** I worktree creati
   con `--project steve-agent` NON hanno il symlink `.local/privacy-denylist.txt`
   (vive nel clone del repo, non nei worktree derivati). Il worker non puo'
   eseguire i check negativi del brief e li skippa con una note nel result.
   **Mitigazione a carico del coordinatore**: quando crei il task di review
   per una PR nata da un worktree `--project`, scrivi nel brief di review che
   il reviewer DEVE eseguire la sanitizzazione manualmente leggendo la denylist
   da `~/.hermes/private/forbidden-strings.txt` sull'istanza e verificando i
   file della PR. Questo gap e' strutturale finche i worktree del project non
   avranno il symlink.

9. **Verify grep `-A<N>` fragili su policy YAML.** Nei brief, i check
   `grep -A20 'propagazione' <policy> | grep <path>` producono falsi positivi
   quando i blocchi YAML sono vicini: `-A20` sfora dal blocco target in quello
   adiacente. Per i verify di classificazione tier su `.steve/review-policy.yaml`,
   **usa un parser YAML** invece di grep contestuale:
   `python3 -c "import yaml; t=yaml.safe_load(open('.steve/review-policy.yaml')); assert '<path>' not in t['tiers'].get('propagazione',{}).get('paths',[])"`.
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
      steve-worker: restituisce `Review Can not approve your own pull request`.

## Verification Checklist

- [ ] Il brief del task ha goal, vincoli, boundaries, verify eseguibili, stop-when.
- [ ] I check di sanitizzazione sono nel verify per ogni stringa vietata.
- [ ] La review e' assegnata a steve-reviewer con la skill github-code-review.
- [ ] I task della story sono iscritti al topic dedicato.
- [ ] Nessun merge eseguito dall'orchestratore.
- [ ] I verify su policy YAML usano un parser, non `grep -A<N>` (pitfall #9).
- [ ] Se il task usa `--project` (worktree senza `.local/`), il brief di
      review include la sanitizzazione manuale a carico del reviewer.
- [ ] Se steve-reviewer e' down (2+ crash consecutivi), non bruciare retry:
      documenta i verify dal main e segnala al coordinatore (pitfall #10, #11).
