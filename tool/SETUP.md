# WG-Casting Tool – Voten & Termine

Ein kleines Tool für unsere WG mit zwei Tabs:

- **👥 Übersicht & Voten** – die komplette Bewerber:innen-Übersicht (dieselben Infos wie die Casting-Seite: Situation / Person / Erwartung, aufklappbar). Direkt darin bewertet jede:r der 5 Mitbewohner:innen mit 1–5 Sternen + Kommentar. Zu jeder Person: Ø-Wertung, alle Einzelstimmen und Kommentare.
- **📅 Termine** – jede:r trägt einmal die **allgemeine** freie Zeit ein (When2meet-Style, nicht pro Bewerber:in). Das Tool berechnet die Überschneidung und schlägt die besten Termine vor. Auf „Überblick & beste Termine“ gibt es zusätzlich das **Bewerber:innen-Ranking** nach Bewertung – kombiniert mit einem **Einladungs-Workflow**: pro Person eine Aktion (Termine vorschlagen → Termin eintragen → ggf. umplanen), oben ein „Nächste Schritte“-Banner, das zum Handeln anstupst.

> ## 🚀 Empfohlener Weg: selbst gehostet per Docker
>
> Neu: Die Seite **und** ein eigenes Backend (Flask + SQLite) laufen in **einem
> Container** – kein Google, keine externen Dienste. Die Bewerber:innen liegen
> in der Datenbank und lassen sich direkt in der App per KI hinzufügen
> (Button „➕ Bewerber:in hinzufügen“, nutzt Google Gemini + `AI-Anleitung.md`).
>
> **Anleitung:** [`tool/server/README.md`](server/README.md) · Kurzfassung:
> ```bash
> cp .env.example .env        # Zugangscode & Namen anpassen
> docker compose up -d --build   # -> http://localhost:8000
> ```
>
> Der Rest dieses Dokuments beschreibt den **alten, alternativen** Weg über ein
> Google Sheet + Apps Script (weiterhin funktionsfähig, gleicher HTTP-Vertrag).

```
Obsidian (Bewerber/*.md) --build_site.sh--> Statische Seite (GitHub Pages)
                                              |  wg-tool.html (Voten + Termine)
                                              v
                                       Google Apps Script (/exec)
                                              v
                                          Google Sheet  (Tabs: Votes, Avail)
```

---

## Sofort ausprobieren (Testmodus, ohne Google)

Öffne `tool/wg-tool.html` einfach im Browser (Doppelklick). Solange keine Backend-URL
eingetragen ist, läuft alles im **Testmodus**: Eingaben werden nur lokal im Browser
gespeichert (kein Teilen, kein echtes Backend). Zum Klicken/Ausprobieren der Oberfläche
reicht das.

> Im Testmodus wird die eingebaute Fallback-Bewerberliste genutzt. Auf dem echten Server
> kommt die Liste automatisch aus `applicants.json` (von `build_site.sh` erzeugt).

---

## Echtes Backend einrichten (~10 Min, einmalig)

### 1. Google Sheet anlegen
1. Auf <https://sheets.new> ein neues, leeres Google Sheet erstellen (z. B. „WG Casting Daten“).
2. Die Tabs *Votes* und *Avail* werden automatisch beim ersten Speichern angelegt – nichts vorbereiten.

### 2. Apps Script einfügen
1. Im Sheet: **Erweiterungen → Apps Script**.
2. Den gesamten Beispielcode löschen und den Inhalt von **`tool/apps-script/Code.gs`** einfügen.
3. Ganz oben `ACCESS_CODE` auf einen gemeinsamen WG-Code setzen, z. B.:
   ```js
   var ACCESS_CODE = 'unser-geheimer-code';
   ```
4. Speichern (💾).

### 3. Als Web-App bereitstellen
1. Oben rechts **Bereitstellen → Neue Bereitstellung**.
2. Zahnrad → **Web-App** wählen.
3. Einstellungen:
   - **Beschreibung:** egal (z. B. „WG Tool“)
   - **Ausführen als:** *Ich* (dein Konto)
   - **Zugriff:** *Jeder* (die Seite braucht keinen Google-Login) –
     alternativ *Jeder mit Google-Konto*, wenn ihr das wollt.
4. **Bereitstellen**, ggf. Google-Berechtigungen bestätigen
   (bei „nicht überprüfte App“: *Erweitert → Zum Projekt fortfahren*).
5. Die angezeigte **Web-App-URL** kopieren – sie endet auf **`/exec`**.

> Wichtig: Bei jeder Code-Änderung entweder **dieselbe** Bereitstellung „verwalten → bearbeiten“
> und neue Version veröffentlichen, oder eine neue URL eintragen.

### 4. URL & Code in die Seite eintragen
In **`tool/wg-tool.html`** ganz oben im `CONFIG`-Block:
```js
APPS_SCRIPT_URL: "https://script.google.com/macros/s/DEINE_ID/exec",
ACCESS_CODE: "unser-geheimer-code",   // GLEICH wie in Code.gs!
FLATMATES: ["Anna", "Ben", "Cem", "Dana", "Eli"],  // eure 5 echten Namen
```
- `FLATMATES` sind die 5 Personen, die voten & Termine abstimmen. Bitte durch die echten Vornamen ersetzen (identisch schreiben, damit die Zuordnung stimmt).
- Optional das Terminraster anpassen: `DAYS_AHEAD`, `START_HOUR`, `END_HOUR`, `SLOT_MIN`.

### 5. Bauen & veröffentlichen
```bash
./build_site.sh
```
Das kopiert `wg-tool.html` automatisch mit in den Pages-Ordner und erzeugt `applicants.json`.
Danach wie gewohnt committen/pushen. Auf der Übersichtsseite gibt es jetzt oben den Button
**„⭐ Voten & 📅 Termine planen“**.

---

## Bedienung

- **Anmelden:** eigenen Namen wählen + Zugangscode eingeben (einmal pro Gerät gemerkt).
- **Übersicht & Voten:** Karte antippen klappt Situation/Person/Erwartung auf. Sterne anklicken (nochmal auf denselben Stern = zurücksetzen), Kommentar ins Feld – wird automatisch gespeichert. Zu jeder Person: Ø-Wertung, Einzelstimmen und Kommentare.
- **Termine:**
  - *Meine Verfügbarkeit:* im Raster die eigenen freien Zeiten anklicken/ziehen – gilt allgemein für alle Kennenlern-Termine. Speichert automatisch.
  - *Überblick & beste Termine:* Heatmap (je dunkler, desto mehr Leute frei) + Top-Termine mit „X/5 frei“ + Bewerber:innen-Ranking mit Einladungs-Workflow.

### Einladungs-Workflow (im „Überblick & beste Termine“)

Ganz oben zeigt das **„Nächste Schritte“-Banner** die offenen Aufgaben (z. B. *„2 einladen · 1 nachfassen · 1 bestätigen“*) – Klick springt zur Rangliste. Pro Bewerber:in gibt es genau eine nächste Aktion:

1. **🔥 bereit zum Einladen** (ab `READY_MIN_VOTES` Stimmen) → **Termine vorschlagen**: oben „Wer kümmert sich?“ festlegen, die besten Überschneidungen sind vorausgewählt, fertige Nachricht kopieren und der/dem Bewerber:in schicken. Termine, die **schon anderen Bewerber:innen** vorgeschlagen oder mit ihnen bestätigt wurden, werden dabei automatisch ausgeblendet (keine Doppelbelegung).
2. **📨 vorgeschlagen** → nach `FOLLOWUP_DAYS` Tagen ohne Antwort wird zum **Nachfassen** genudged. Kommt die Antwort (per WhatsApp/Mail), **✅ Termin eintragen**: den vereinbarten Termin direkt auswählen – fertig, er gilt als bestätigt (kein extra Bestätigen-Schritt mehr).
3. **✔️ bestätigt** → mit **🔄 umplanen** lässt sich der Termin jederzeit (auch kurzfristig) auf einen anderen ändern – zur Auswahl stehen die Vorschläge plus frische freie Überschneidungen, und der alte Termin wird wieder frei. Nach dem Treffen **kennengelernt ✓**.

Bewertungen erscheinen in der Rangliste als Sterne mit Stimmenzahl dahinter (z. B. ★★★★☆ (3)). Die Bewerber:innen benutzen das Tool **nicht** – sie antworten wie gewohnt, die WG trägt die Antwort ein. Der Workflow-Status liegt im Tab **Meetings** des Google Sheets (getrennt vom Obsidian-`status`, den ihr wie bisher von Hand pflegt).

### 📆 Castings (dritter Tab)

Ein Monatskalender, in dem alle **bestätigten** Kennenlern-Termine eingetragen sind (mit Uhrzeit + Name), plus eine Liste der kommenden Castings. Mit ‹ › zwischen den Monaten blättern. Der aktuelle Tag ist hervorgehoben; bereits kennengelernte Termine sind ausgegraut.

---

## Datenschutz / Sicherheit

- GitHub Pages ist bei kostenlosen Repos **immer per URL öffentlich** (auch wenn das Repo privat ist). Die Seiten haben zwar `noindex`, aber der Zugangscode ist nur eine **leichte Hürde**, kein echter Schutz – Link nur intern in der WG teilen.
- Bewerber:innen sehen dieses Tool nicht; sie bekommen nur die fertigen Terminvorschläge (z. B. per Nachricht).
- Wer es dichter will: privates Hosting mit echtem Login (z. B. GitHub Pro/Team mit privater Pages-Zugriffskontrolle) statt öffentlichem Pages.

## Dateien
- `tool/wg-tool.html` – die Tool-Seite (wird beim Build mitkopiert)
- `tool/apps-script/Code.gs` – Backend für Apps Script
- `tool/SETUP.md` – diese Anleitung
