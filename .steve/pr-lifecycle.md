# PR Lifecycle v1 — processo di review

Questo documento definisce come una pull request nasce, viene valutata e
raggiunge `main` nel repo steve-agent. Esegue il brief di board
`t_9c2689f2` ("PR Lifecycle v1"). Il processo si appoggia a un solo tool
nuovo — il compilatore di brief (`tools/pr-brief.py`) — e racchiude tutto il
flusso in questo unico documento: niente secondi tool, niente file temporanei
di appoggio in git.

## Le quattro decisioni fondanti

Sono le scelte approvate dal team e vanno rispettate fedelmente:

- **D1 — approve -> merge automatico.** Alla risposta `approve` la PR viene
  mergiata senza un secondo go. Un solo segnale positivo basta.
- **D2 — reject -> redesign draft, non "no" secco.** Alla risposta
  `reject: <motivo>` il sistema non chiude la PR: produce un redesign draft
  che elenca i vincoli violati e cosa cambiare, lasciando all'autore un
  percorso concreto per riprovare.
- **D3 — il compilatore di brief e' un GATE su OGNI PR aperta.** Nessuna
  review parte finche' il compilatore non ha prodotto un brief valido. Il
  brief e' prerequisito, non accessorio.
- **D4 — blocco a priori se i nuovi vincoli non hanno test.** Se la policy
  introduce un vincolo nuovo senza il test corrispondente nel compilatore,
  la PR viene bloccata prima della review. Un vincolo non testato e' un
  vincolo che non esiste.

## Il flusso end-to-end

Il criterio di verifica del brief ammette due path.

### happy path (approvazione)

1. Una PR viene aperta.
2. Il compilatore (`tools/pr-brief.py`) calcola il tier di ogni file modificato
   contro `.steve/review-policy.yaml` e produce il brief: il tier della PR e'
   il massimo tra i file (`blast > propagazione > sicuro`).
3. Il brief viene consegnato nel topic Backlog (oggi tramite il watcher
   `instance/pr-watch.sh` su cron).
4. Un revisore risponde `approve` (oppure `approve with: <nota>`).
5. La PR viene mergiata.

### iterate path (riprova)

1. Il revisore risponde `reject: <motivo>`.
2. Il compilatore genera il **redesign draft**: un commento markdown sulla PR
   che elenca i vincoli violati e cosa cambiare. Non viene scritto alcun file
   temporaneo in git: il draft vive solo come commento della PR.
3. L'autore corregge e ripinge la PR (o forza un nuovo giro del compilatore).
4. Si torna al happy path o a un nuovo giro di iterate.

In entrambi i path il brief resta l'artefatto centrale: e' lui che concentra
la decisione, non il giudizio libero del revisore.

## Stato di implementazione (onesto)

| Componente | Oggi | Da costruire |
|---|---|---|
| Compilatore di brief (`tools/pr-brief.py`) | esiste: triage deterministico, template, `--self-test` | genera anche il redesign draft su reject |
| Watcher PR (`instance/pr-watch.sh`) | esiste: gira su cron, rileva PR nuove | trigger a evento (webhook) invece di cron |
| Consegna del brief | nel topic Backlog via cron | consegna push su evento |
| Approvazione | `approve` in chat, merge manuale su GitHub | comando approve tracciato + auto-merge |
| Auto-merge | non implementato | identita' bot dedicata, solo con marcatura |
| Check "vincoli senza test" (D4) | non implementato | gate nel compilatore: vincolo nuovo senza test = blocco |

Oggi l'approve porta a un merge manuale su GitHub eseguito da un umano: il
sistema concentra la decisione ma non chiude ancora il ciclo in autonomia.

## Fase 2 — auto-merge sicuro (specifica, non implementazione)

La fase 2 porta l'approve dal "decidi" all'"esegui in autonomia", mantenendo
la tracciabilita' e la guardia su main. Specifica:

1. **Approve tracciato e verificabile.** L'approve non e' piu' solo una
   frase in chat: parte da un comando admin, e si traduce in una marcatura
   sulla PR — una label o un commento firmato dall'identita' di coordinamento.
   La marcatura e' l'unica prova accettabile di approvazione.
2. **Auto-merge solo da identita' bot dedicata.** Il merge automatico lo
   esegue un bot dedicato, e lo esegue SOLO in presenza della marcatura di
   approve. Senza marcatura, niente merge.
3. **main-guard v2.** Oggi lo smoke (`instance/smoke.sh`) segnala QUALSIASI
   commit su `origin/main` committato da un'identita' bot: ogni push diretto
   o merge del bot e' un allarme. Nella fase 2 la guardia evolve: deve
   accettare i merge bot SOLO per PR con approve tracciato, e continuare a
   segnalare tutto il resto. Il main resta protetto; l'eccezione e' ristretta
   e auditabile.
4. **Tier esclusi dall'auto-merge.** Restano fuori dall'auto-merge i tier per
   cui la policy richiede il brief con firma umana, secondo
   `rules.brief_required_for` in `.steve/review-policy.yaml` (oggi: blast e
   propagazione). Per quei tier l'approve va oltre la marcatura e richiede
   firma umana esplicita: l'auto-merge si ferma al tier `sicuro`.

La fase 2 e' disegno: nessuna di queste parti e' ancora codice. Quando si
implementera', ogni voce di questa sezione diventera' un task separato, e la
tabella di stato qui sopra si aggiornera' di conseguenza.
