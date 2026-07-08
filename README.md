# WG-Casting

Kleines Werkzeug, um die Bewerber:innen für unsere WG zu verwalten: Übersicht,
Bewerten (Voten), Terminfindung und ein Einladungs-Workflow – plus das Anlegen
neuer Bewerber:innen direkt in der App per KI (Google Gemini).

## Schnellstart

```bash
cp .env.example .env          # Zugangscode & Mitbewohner:innen anpassen
docker compose up -d --build  # -> http://localhost:8000
```

Danach in der App unter **⚙️ KI-Einstellungen** einen Gemini-API-Key hinterlegen,
um neue Bewerber:innen aus dem Bewerbungstext automatisch anlegen zu lassen.

Ausführliche Anleitung (inkl. Server/HTTPS): **[tool/server/README.md](tool/server/README.md)**.

## Aufbau

| Pfad | Inhalt |
|------|--------|
| `Bewerber/*.md` | Obsidian-Notizen je Bewerber:in (YAML-Header + Stichpunkte) |
| `AI-Anleitung.md` | Vorgabe, wie die KI eine Bewerbung strukturiert |
| `Übersicht.base` | Obsidian-„Base“ für die Vault-Ansicht |
| `build_site.sh` | erzeugt aus den Notizen die statische Seite (→ `./dist`) |
| `tool/wg-tool.html` | die App (Übersicht/Voten, Termine, Castings) |
| `tool/server/` | selbst gehostetes Backend (Flask + SQLite) + Docker-Setup |
| `tool/apps-script/` | altes, alternatives Backend (Google Apps Script) |
| `Dockerfile`, `docker-compose.yml` | Alles-in-einem-Container |

Die Bewerber:innen liegen zur Laufzeit in der Datenbank (`data/casting.db`), die
beim ersten Start einmalig aus den Notizen befüllt wird. Build-Artefakte (`dist/`,
`static/`, `data/`, `*.db`) sind bewusst nicht eingecheckt.
