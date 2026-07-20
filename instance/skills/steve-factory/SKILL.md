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

## Verification Checklist

- [ ] Il brief del task ha goal, vincoli, boundaries, verify eseguibili, stop-when.
- [ ] I check di sanitizzazione sono nel verify per ogni stringa vietata.
- [ ] La review e' assegnata a steve-reviewer con la skill github-code-review.
- [ ] I task della story sono iscritti al topic dedicato.
- [ ] Nessun merge eseguito dall'orchestratore.
