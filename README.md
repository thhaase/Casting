# WG-Casting

Kleines Werkzeug, um die Bewerber:innen für unsere WG zu verwalten: Übersicht,
Bewerten (Voten), Terminfindung und ein Einladungs-Workflow – plus das Anlegen
neuer Bewerber:innen direkt in der App per KI (Google Gemini).

Alles läuft selbst gehostet in **einem Docker-Container**: eine kleine App-Seite
plus ein eigenes Backend (Flask + SQLite). Kein Google, keine externen Dienste.
Die Bewerber:innen liegen in der Datenbank – die einzige Quelle der Wahrheit.

## Schnellstart

```bash
cp .env.example .env          # Zugangscode & Mitbewohner:innen anpassen
docker compose up -d --build  # -> http://localhost:8000
```

Danach in der App unter **⚙️ KI-Einstellungen** einen Gemini-API-Key hinterlegen,
um neue Bewerber:innen aus dem Bewerbungstext automatisch anlegen zu lassen.

Ausführliche Anleitung inkl. Server/HTTPS: **[tool/server/README.md](tool/server/README.md)**.

## Aufbau

| Pfad | Inhalt |
|------|--------|
| `tool/wg-tool.html` | die App (Übersicht/Voten, Termine, Castings, Bewerber:in hinzufügen) |
| `tool/server/server.py` | Backend (Flask + SQLite): `/api` + Ausliefern der App-Seite |
| `tool/server/seed_applicants.json` | Erst-Befüllung der DB beim allerersten Start |
| `AI-Anleitung.md` | Vorgabe, wie die KI eine Bewerbung strukturiert |
| `Dockerfile`, `docker-compose.yml` | Alles-in-einem-Container |

Zur Laufzeit liegen alle Daten (Votes, Termine, Bewerber:innen, Gemini-Key) in
`data/casting.db`. Diese Datei und andere Laufzeit-Artefakte sind bewusst nicht
eingecheckt (siehe `.gitignore`).
