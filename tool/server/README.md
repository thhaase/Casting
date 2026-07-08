# WG-Casting – selbst gehostetes Backend (Docker)

Alles-in-einem Container: baut die statische Seite aus den Bewerber-Notizen,
liefert sie aus **und** stellt das eigene Backend (`/api`, Flask + SQLite)
bereit. Ersetzt das frühere Google-Apps-Script + Google-Sheet.

```
Bewerber/*.md ──build_site.sh──► statische Seite (index.html, wg-tool.html …)
                                          │  (im Image gebaut)
                                          ▼
                    ┌─────────────  ein Container  ─────────────┐
                    │  gunicorn → Flask server.py               │
                    │    /            statische Seite           │
                    │    /api         Votes/Termine/Bewerber:innen │
                    │  SQLite  /data/casting.db  (Volume)        │
                    └───────────────────────────────────────────┘
```

Die Bewerber:innen liegen jetzt in der **Datenbank** (Quelle der Wahrheit).
Beim allerersten Start werden sie einmalig aus den vorhandenen Notizen
(`applicants.json`) übernommen; danach kommen neue über die App dazu.

---

## Schnellstart (lokal oder auf dem Server)

Voraussetzung: Docker mit Compose-Plugin.

```bash
cp .env.example .env        # Zugangscode & Mitbewohner:innen anpassen
docker compose up -d --build
```

→ Seite läuft auf **http://localhost:8000**. Fertig.

Beim Anmelden den `ACCESS_CODE` aus der `.env` eingeben und den eigenen Namen
wählen (die Namen kommen aus `FLATMATES`).

Nützliche Befehle:

```bash
docker compose logs -f      # Logs ansehen
docker compose down         # stoppen
docker compose up -d --build   # nach Änderungen neu bauen & starten
```

> Nach dem Ändern von Bewerber-Notizen (`Bewerber/*.md`) oder der Tool-Seite
> muss neu gebaut werden (`--build`). Die **Bewerber:innen** werden aber nur
> beim allerersten Start geseedet – spätere Notiz-Änderungen landen nicht
> automatisch in der DB (die DB ist jetzt führend). Neue Bewerber:innen legst
> du über den Button **„➕ Bewerber:in hinzufügen“** an.

---

## KI-Schlüssel (Google Gemini) in der App eintragen

Der Button **„➕ Bewerber:in hinzufügen“** lässt dich Name, Alter und den
unstrukturierten Bewerbungstext einfügen; Gemini erstellt daraus – anhand von
`AI-Anleitung.md` – automatisch einen strukturierten Eintrag.

Dafür einmalig einen API-Key hinterlegen:

1. Kostenlosen Key erstellen: <https://aistudio.google.com/apikey>
2. In der App oben auf **„⚙️ KI-Einstellungen“**, Key einfügen, speichern.

Der Key wird **serverseitig** in der SQLite-DB gespeichert (nicht im Browser),
im Volume `./data`. Das Standardmodell ist `gemini-flash-latest`; es lässt sich
in denselben Einstellungen überschreiben (oder per `GEMINI_MODEL` in `.env`).

---

## Konfiguration (`.env`)

| Variable       | Bedeutung                                              | Default              |
|----------------|--------------------------------------------------------|----------------------|
| `ACCESS_CODE`  | gemeinsamer WG-Zugangscode (Seite **und** Backend)     | `wg-casting`         |
| `FLATMATES`    | die Mitbewohner:innen, kommagetrennt                   | (Platzhalter)        |
| `GEMINI_MODEL` | Default-Gemini-Modell (in der App überschreibbar)      | `gemini-flash-latest`|

`ACCESS_CODE` und `FLATMATES` werden beim Container-Start in die ausgelieferte
`wg-tool.html` eingesetzt – kein manuelles Editieren der HTML nötig.

---

## Daten & Backup

Alles (Votes, Verfügbarkeiten, Termine, Bewerber:innen, Gemini-Key) liegt in
**einer** Datei: `./data/casting.db`.

```bash
cp data/casting.db data/casting-backup-$(date +%F).db     # Backup
```

Zum kompletten Zurücksetzen den Container stoppen und `data/casting.db` löschen –
beim nächsten Start wird wieder aus den Notizen geseedet.

---

## Auf dem Server öffentlich & mit HTTPS erreichbar machen

Der Container spricht nur HTTP auf Port 8000. Für eine öffentliche Domain mit
automatischem HTTPS am einfachsten **Caddy** davorsetzen (VPS mit Root):

`/etc/caddy/Caddyfile`:

```
casting.deine-domain.de {
    reverse_proxy 127.0.0.1:8000
}
```

Dann DNS-A-Record auf die Server-IP zeigen lassen, `systemctl reload caddy` –
Caddy holt das Let’s-Encrypt-Zertifikat automatisch. In `docker-compose.yml`
kann der Port dann auf `127.0.0.1:8000:8000` beschränkt werden, damit nur Caddy
(nicht das offene Internet) direkt an den Container kommt.

> Hinweis: Der Zugangscode ist eine leichte Hürde, kein echter Schutz. Den Link
> nur intern in der WG teilen.

---

## Ohne Docker (Entwicklung)

```bash
cd tool/server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
../../build_site.sh ../../dist                       # Seite + applicants.json bauen
CASTING_DB=./casting.db STATIC_DIR=../../dist \
  SEED_APPLICANTS=../../dist/applicants.json \
  gunicorn -b 127.0.0.1:8000 server:app
```

Beim Öffnen von `wg-tool.html` per Doppelklick (`file://`) läuft die Seite im
**Testmodus** (nur `localStorage`, kein Backend, keine echte KI).
