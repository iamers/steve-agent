---
status: accepted
date: 2026-07-27
---

# Una mergeability sconosciuta non è una pull request non mergiabile

## Context

GitHub calcola la mergeability di una pull request in modo asincrono. La prima
lettura può quindi restituire `null`, mentre una lettura successiva restituisce
il valore calcolato. Il gate trasformava quel `null` in una stringa vuota e lo
riferiva come pull request non mergiabile. Il rifiuto era prudente, ma la
motivazione comunicata in chat era falsa.

## Decision

Quando la prima lettura dei metadati restituisce una mergeability sconosciuta,
il gate attende una pausa breve e fissa, poi ripete una sola volta la stessa
richiesta. Questo segue il rimedio documentato da GitHub per il calcolo
asincrono e rimuove il transitorio nel caso ordinario.

Se anche la seconda risposta non contiene un valore, il gate mantiene lo stato
sconosciuto come terzo stato distinto. Il gate rifiuta comunque la pull request,
ma dichiara che la mergeability non è ancora nota invece di dichiarare che la
pull request non è mergiabile.

## Consequences

Nel caso ordinario il gate usa il valore disponibile alla seconda lettura. La
valutazione aggiunge al massimo una richiesta e una pausa fissa, senza cicli.
Se GitHub non ha ancora terminato il calcolo, il comportamento resta fail-closed
e il messaggio descrive correttamente l'incertezza.

## Alternatives considered

Non ripetere la richiesta: scartato, perché conserverebbe un transitorio che
GitHub indica di risolvere con una nuova lettura. Ripetere in un ciclo:
scartato, perché non offre un limite fisso all'attesa né al numero di richieste.
Trattare lo stato sconosciuto come non mergiabile: scartato, perché produce una
motivazione falsa. Consentire il merge quando lo stato è sconosciuto: scartato,
perché violerebbe il principio fail-closed.
