# nuvio-covers

Genera ogni settimana le copertine in stile Netflix per le collections di [Nuvio](https://nuvio.tv)
(o di qualsiasi app che accetti un URL immagine) e le serve via HTTP da un indirizzo fisso.

Ogni copertina è un "muro" inclinato di poster presi da TMDB con la stessa query della riga che
rappresenta, più un'etichetta colorata (`NEW`), una didascalia e un titolo grande.

| Copertina | URL |
|---|---|
| Nuovi Film | `/novita/film.jpg` |
| Nuove Serie | `/novita/serie.jpg` |
| Nuove Stagioni | `/novita/stagioni.jpg` |

L'URL non cambia mai, cambia solo l'immagine: in Nuvio la copertina va impostata una volta sola.

## Avvio

```bash
cp compose.example.yaml compose.yaml
echo "TMDB_API_KEY=la-tua-chiave" > .env
docker compose up -d
```

L'immagine è pubblicata su `ghcr.io/privatepenguinzero/nuvio-covers` per `amd64` e `arm64`.

## Variabili

| Variabile | Default | Descrizione |
|---|---|---|
| `TMDB_API_KEY` | — | Chiave API v3 di TMDB (obbligatoria) |
| `SCHEDULE_WEEKDAY` | `0` | Giorno della rigenerazione, 0 = lunedì |
| `SCHEDULE_HOUR` | `5` | Ora locale della rigenerazione |
| `TZ` | `Europe/Rome` | Fuso orario |
| `GENERATE_ON_START` | `true` | Rigenera anche all'avvio del container |
| `REFRESH_TOKEN` | vuoto | Se impostato abilita `POST /refresh` con `Authorization: Bearer <token>` |
| `CONFIG_PATH` | `/app/config.json` | Configurazione delle copertine |

## Endpoint

- `GET /<cartella>/<nome>.jpg` — le copertine
- `GET /healthz` — stato: ultima esecuzione, prossima, eventuale errore
- `POST /refresh` — rigenera subito (solo con `REFRESH_TOKEN`)

Se una generazione fallisce (TMDB irraggiungibile, pochi poster) le copertine precedenti restano
online invariate.

## Personalizzare

`config.json` elenca le copertine: titolo, didascalia, colore e i parametri di
[TMDB discover](https://developer.themoviedb.org/reference/discover-movie). Le date accettano
valori relativi: `today`, `-30d`, `-1y`. Per cambiarle senza ricostruire l'immagine monta il file
in `/app/config.json`.
