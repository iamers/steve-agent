# instance/ — blueprint dell'istanza Steve

Copia canonica, versionata e senza segreti, della configurazione di una istanza
Steve (Hermes Agent). Nasce dalla prima istanza di sviluppo; quando esisterà una
seconda istanza questo blueprint è il candidato a diventare template renderizzato.

## Contenuto

| File | Ruolo |
|---|---|
| `config.yaml` | copia canonica di `~/.hermes/config.yaml` dell'istanza |
| `env.template` | chiavi richieste in `~/.hermes/.env` (solo nomi, mai valori) |
| `smoke.sh` | verifica salute istanza (versione pinnata, gateway, telegram, env) |
| `drift-check.sh` | confronta config live vs repo; segnala derive, non ripristina |

## Regola anti-deriva

1. Le modifiche di configurazione si fanno PRIMA nella copia del repo, poi si
   applicano all'istanza (mai solo hand-edit live).
2. Se una modifica è nata live (emergenza, esperimento), riportarla qui subito
   dopo e annotarla nel journal operativo (privato, `.local/ops/`).
3. `drift-check.sh` in caso di dubbio: esce 1 se c'è deriva.

Gli identificativi specifici dell'istanza (chat id, user id, host) vivono solo
nel `.env` server-side e nel journal privato, mai in questi file.

## Uso

```bash
./smoke.sh              # default: istanza via alias SSH (set STEVE_HOST o passalo come arg1)
./smoke.sh <alias> --llm   # include una query reale al modello
./drift-check.sh        # diff config live vs repo
```

Prerequisito: alias SSH verso l'utente dell'istanza sulla macchina da cui si
esegue. La versione Hermes attesa è pinnata in `smoke.sh` (`HERMES_PIN`).

`STEVE_HOST` è una variabile **ops/clone-side**, non runtime dell'istanza: gli
script `drift-check.sh` e `smoke.sh` la leggono dal primo argomento o dalla env
ed girano dal clone di gestione verso l'istanza via SSH. Per questo non compare
in `env.template` (che elenca solo le chiavi del `.env` runtime dell'istanza):
valorizzatela nell'ambiente del clone di gestione o passatela come arg1.
