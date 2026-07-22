#!/usr/bin/env python3
"""
WG-Casting Tool – selbst gehostetes Backend (Flask + SQLite)
============================================================

Kleiner eigener Server, der die App-Seite (wg-tool.html) UND das /api ausliefert
und zugleich die "Quelle der Wahrheit" für die Bewerber:innen ist. Beim ersten
Start wird die DB einmalig aus seed_applicants.json befüllt.

Ein einziger Endpunkt /api nimmt JSON `{action, code, ...}` entgegen und
liefert JSON `{ok, ...}` zurück.

Aktionen:
  state          (lesen)          -> {ok, votes[], avail[], meetings[]}
  applicants     (lesen)          -> {ok, applicants[]}
  config         (lesen)          -> {ok, aiConfigured, aiModel}
  vote           (schreiben, Code) -> upsert (applicant, voter): rating, comment
  avail          (schreiben, Code) -> upsert (applicant, voter): slotsJSON
  meeting        (schreiben, Code) -> partielles upsert je applicant
  add_applicant  (schreiben, Code) -> Name/Alter/Text -> Gemini strukturiert
                                       gemäß AI-Anleitung.md -> neue Bewerber:in
  set_config     (schreiben, Code) -> Gemini-API-Key/Modell speichern (in DB)

Konfiguration über Umgebungsvariablen (alle optional, mit Defaults):
  ACCESS_CODE      gemeinsamer WG-Zugangscode.               Default: wg-casting
  CASTING_DB       Pfad zur SQLite-Datei.                    Default: ./casting.db
  SEED_APPLICANTS  applicants.json zum einmaligen Seeden.    Default: neben server.py
  ANLEITUNG_PATH   Pfad zur AI-Anleitung.md.                 Default: Repo-Wurzel
  GEMINI_MODEL     Default-Modell, falls in-App keins gesetzt. Default: gemini-flash-latest
  STATIC_DIR       optional: gebaute Seite mitservieren (lokale Tests).

Der Gemini-API-Key wird NICHT über eine Umgebungsvariable gesetzt, sondern in
der App (Einstellungen) eingegeben und in der DB gespeichert (Tabelle settings).

Start (Entwicklung):   flask --app server run -p 8000
Start (Produktion):    gunicorn -b 0.0.0.0:8000 server:app
"""

import json
import os
import re
import sqlite3
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

import yaml
from flask import Flask, g, jsonify, request, send_from_directory

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

ACCESS_CODE = os.environ.get("ACCESS_CODE", "wg-casting")
DB_PATH = os.environ.get("CASTING_DB", os.path.join(HERE, "casting.db"))
SEED_APPLICANTS = os.environ.get("SEED_APPLICANTS", os.path.join(HERE, "seed_applicants.json"))
ANLEITUNG_PATH = os.environ.get("ANLEITUNG_PATH", os.path.join(REPO_ROOT, "AI-Anleitung.md"))
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
STATIC_DIR = os.environ.get("STATIC_DIR")  # optional

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Spalten je Tabelle – 1:1 wie die Google-Sheet-Header in Code.gs.
VOTES_COLS = ["applicant", "voter", "rating", "comment", "updated"]
AVAIL_COLS = ["applicant", "voter", "slotsJSON", "updated"]
MEETINGS_COLS = ["applicant", "state", "proposedSlots", "proposedAt",
                 "proposedBy", "owner", "responseSlots", "confirmedSlot", "updated"]
MEETING_FIELDS = MEETINGS_COLS[1:-1]

# Eindrücke zu eingeladenen Bewerber:innen: gemeinsame Notiz, Einladedatum
# (für die 2-Wochen-Frist) und eine Stufen-Sortierung (tier: kleiner = weiter oben,
# gleiche Werte = gleiche Stufe). onBoard: 1 = manuell aufs Board, 0 = ausgeblendet.
IMPRESSIONS_COLS = ["applicant", "tier", "invitedAt", "note", "onBoard", "updated"]
IMPRESSION_FIELDS = IMPRESSIONS_COLS[1:-1]

# Bewerber:innen-Felder (wie applicants.json / wg-tool.html erwartet).
APPLICANT_SCALARS = ["name", "status", "alter", "studium_beruf", "sprache",
                     "kennenlernen", "einzug", "eindruck"]
APPLICANT_LISTS = ["situation", "person", "erwartung"]

app = Flask(__name__, static_folder=None)


# ---- Datenbank ----

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        # Bei parallelen Schreibzugriffen (mehrere Worker) kurz warten statt Fehler.
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(db):
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS votes (
            applicant TEXT NOT NULL, voter TEXT NOT NULL,
            rating TEXT, comment TEXT, updated TEXT,
            PRIMARY KEY (applicant, voter)
        );
        CREATE TABLE IF NOT EXISTS avail (
            applicant TEXT NOT NULL, voter TEXT NOT NULL,
            slotsJSON TEXT, updated TEXT,
            PRIMARY KEY (applicant, voter)
        );
        CREATE TABLE IF NOT EXISTS meetings (
            applicant TEXT PRIMARY KEY, state TEXT, proposedSlots TEXT,
            proposedAt TEXT, proposedBy TEXT, owner TEXT,
            responseSlots TEXT, confirmedSlot TEXT, updated TEXT
        );
        CREATE TABLE IF NOT EXISTS applicants (
            id TEXT PRIMARY KEY, name TEXT, status TEXT, "alter" TEXT, studium_beruf TEXT,
            sprache TEXT, kennenlernen TEXT, einzug TEXT, eindruck TEXT,
            situation TEXT, person TEXT, erwartung TEXT,
            raw_md TEXT, bewerbertext TEXT, created TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY, value TEXT
        );
        CREATE TABLE IF NOT EXISTS impressions (
            applicant TEXT PRIMARY KEY, tier REAL, invitedAt TEXT,
            note TEXT, onBoard INTEGER, updated TEXT
        );
        """
    )
    # Migration: Spalte für den vollen Original-Bewerbungstext nachrüsten (Alt-DBs).
    have = {row[1] for row in db.execute("PRAGMA table_info(applicants)").fetchall()}
    if "bewerbertext" not in have:
        db.execute('ALTER TABLE applicants ADD COLUMN bewerbertext TEXT DEFAULT ""')
    # Migration: Sprache der Bewerbung nachrüsten (Alt-DBs).
    if "sprache" not in have:
        db.execute('ALTER TABLE applicants ADD COLUMN sprache TEXT DEFAULT ""')
    db.commit()
    migrate_to_ids(db)


def new_id():
    return uuid.uuid4().hex[:12]


# Alte DBs verwendeten den Namen als Schlüssel – bei gleichen Namen (z. B. zwei
# „Clara“) hat das Anlegen die vorige Person überschrieben. Diese Migration führt
# eine stabile id ein und schreibt alle Referenztabellen (votes/avail/meetings/
# impressions) von Name auf id um. Läuft genau einmal (danach hat applicants
# bereits eine id-Spalte).
def migrate_to_ids(db):
    if "id" in {row[1] for row in db.execute("PRAGMA table_info(applicants)").fetchall()}:
        return

    # Exklusiven Schreibzugriff holen, damit bei mehreren gunicorn-Workern nur EINER
    # migriert. Läuft komplett in einer Transaktion (DDL ist in SQLite transaktional),
    # daher kein executescript (das würde die Transaktion vorzeitig committen).
    prev_iso = db.isolation_level
    db.isolation_level = None
    try:
        try:
            db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            return  # anderer Worker hält den Lock und migriert gerade -> überspringen

        if "id" in {row[1] for row in db.execute("PRAGMA table_info(applicants)").fetchall()}:
            db.execute("COMMIT")
            return

        old = db.execute("SELECT * FROM applicants ORDER BY rowid").fetchall()
        copy_cols = ["name", "status", "alter", "studium_beruf", "sprache", "kennenlernen",
                     "einzug", "eindruck", "situation", "person", "erwartung",
                     "raw_md", "bewerbertext", "created"]
        name_to_id = {}
        rows = []
        for r in old:
            keys = r.keys()
            aid = new_id()
            name_to_id[r["name"]] = aid
            rows.append([aid] + [(r[c] if c in keys else None) for c in copy_cols])

        db.execute("ALTER TABLE applicants RENAME TO applicants_old")
        db.execute(
            'CREATE TABLE applicants ('
            'id TEXT PRIMARY KEY, name TEXT, status TEXT, "alter" TEXT, studium_beruf TEXT,'
            'sprache TEXT, kennenlernen TEXT, einzug TEXT, eindruck TEXT,'
            'situation TEXT, person TEXT, erwartung TEXT,'
            'raw_md TEXT, bewerbertext TEXT, created TEXT)'
        )
        collist = ", ".join(['id'] + [f'"{c}"' for c in copy_cols])
        placeholders = ", ".join(["?"] * (len(copy_cols) + 1))
        db.executemany(f"INSERT INTO applicants ({collist}) VALUES ({placeholders})", rows)
        db.execute("DROP TABLE applicants_old")

        # Referenztabellen von Name auf id umschreiben (unbekannte Werte wie der
        # Sammel-Schlüssel für die allgemeine Verfügbarkeit bleiben unverändert).
        for tbl in ("votes", "avail", "meetings", "impressions"):
            for r in db.execute(f"SELECT rowid, applicant FROM {tbl}").fetchall():
                aid = name_to_id.get(r["applicant"])
                if aid:
                    db.execute(f"UPDATE {tbl} SET applicant = ? WHERE rowid = ?", (aid, r["rowid"]))
        db.execute("COMMIT")
    finally:
        db.isolation_level = prev_iso


def seed_applicants(db):
    """Beim allerersten Start die vorhandenen Bewerber:innen einlesen."""
    have = db.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]
    if have or not SEED_APPLICANTS or not os.path.exists(SEED_APPLICANTS):
        return
    try:
        with open(SEED_APPLICANTS, encoding="utf-8") as f:
            seed = json.load(f)
    except (OSError, ValueError):
        return
    for a in seed:
        insert_applicant(db, a, raw_md=a.get("raw_md", ""), bewerbertext=a.get("bewerbertext", ""))
    db.commit()


# ---- Helfer ----

def now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_table(db, table, cols):
    rows = db.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
    return [dict(r) for r in rows]


def as_str(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def get_setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(db, key, value):
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


# ---- API ----

@app.route("/api", methods=["GET", "POST"])
def api():
    if request.method == "POST":
        # force=True: der Body wird auch ohne "application/json"-Header als JSON
        # geparst – die Tool-Seite sendet JSON als text/plain (wie beim Apps Script).
        params = request.get_json(silent=True, force=True)
        if not isinstance(params, dict):
            params = request.form.to_dict() or {}
    else:
        params = request.args.to_dict()

    action = params.get("action", "state")
    db = get_db()

    try:
        # ---- Lesen (ohne Code) ----
        if action == "state":
            return jsonify(
                ok=True,
                votes=read_table(db, "votes", VOTES_COLS),
                avail=read_table(db, "avail", AVAIL_COLS),
                meetings=read_table(db, "meetings", MEETINGS_COLS),
                impressions=read_table(db, "impressions", IMPRESSIONS_COLS),
            )

        if action == "applicants":
            return jsonify(ok=True, applicants=read_applicants(db))

        if action == "config":
            return jsonify(
                ok=True,
                aiConfigured=bool(get_setting(db, "gemini_api_key")),
                aiModel=get_setting(db, "gemini_model", DEFAULT_MODEL),
            )

        # ---- Schreiben (Code nötig) ----
        if params.get("code") != ACCESS_CODE:
            return jsonify(ok=False, error="Falscher Zugangscode.")

        if action == "vote":
            applicant = str(params.get("applicant") or "").strip()
            voter = str(params.get("voter") or "").strip()
            if not applicant or not voter:
                return jsonify(ok=False, error="voter/applicant fehlt.")
            rating = params.get("rating")
            rating = "" if rating in ("", None) else rating
            upsert_voter_row(db, "votes", applicant, voter,
                             {"rating": rating, "comment": str(params.get("comment") or "")})
            return jsonify(ok=True)

        if action == "avail":
            applicant = str(params.get("applicant") or "").strip()
            voter = str(params.get("voter") or "").strip()
            if not applicant or not voter:
                return jsonify(ok=False, error="voter/applicant fehlt.")
            slots = params.get("slots")
            slots = slots if isinstance(slots, str) else json.dumps(slots or [], ensure_ascii=False)
            upsert_voter_row(db, "avail", applicant, voter, {"slotsJSON": slots})
            return jsonify(ok=True)

        if action == "meeting":
            applicant = str(params.get("applicant") or "").strip()
            if not applicant:
                return jsonify(ok=False, error="applicant fehlt.")
            fields = {k: as_str(params[k]) for k in MEETING_FIELDS if params.get(k) is not None}
            upsert_meeting(db, applicant, fields)
            return jsonify(ok=True)

        if action == "impression":
            applicant = str(params.get("applicant") or "").strip()
            if not applicant:
                return jsonify(ok=False, error="applicant fehlt.")
            fields = {}
            for k in IMPRESSION_FIELDS:
                if params.get(k) is None:
                    continue
                if k == "tier":
                    try:
                        fields[k] = float(params[k])
                    except (TypeError, ValueError):
                        continue
                elif k == "onBoard":
                    fields[k] = 1 if params[k] in (1, "1", True, "true") else 0
                else:
                    fields[k] = str(params[k])
            upsert_impression(db, applicant, fields)
            return jsonify(ok=True)

        if action == "set_config":
            if "gemini_api_key" in params:
                key = str(params.get("gemini_api_key") or "").strip()
                # Leerer String löscht den Key wieder.
                set_setting(db, "gemini_api_key", key)
            if params.get("gemini_model"):
                set_setting(db, "gemini_model", str(params["gemini_model"]).strip())
            return jsonify(ok=True,
                           aiConfigured=bool(get_setting(db, "gemini_api_key")),
                           aiModel=get_setting(db, "gemini_model", DEFAULT_MODEL))

        if action == "delete_applicant":
            # Löschen erfolgt jetzt über die id (Namen sind nicht mehr eindeutig).
            ids = params.get("ids")
            if not isinstance(ids, list):
                one = str(params.get("id") or params.get("applicant") or "").strip()
                ids = [one] if one else []
            ids = [str(n).strip() for n in ids if str(n).strip()]
            if not ids:
                return jsonify(ok=False, error="Keine Bewerber:innen angegeben.")
            deleted = []
            for aid in ids:
                exists = db.execute(
                    "SELECT 1 FROM applicants WHERE id = ?", (aid,)
                ).fetchone()
                if not exists:
                    continue
                db.execute("DELETE FROM applicants WHERE id = ?", (aid,))
                db.execute("DELETE FROM votes WHERE applicant = ?", (aid,))
                db.execute("DELETE FROM avail WHERE applicant = ?", (aid,))
                db.execute("DELETE FROM meetings WHERE applicant = ?", (aid,))
                db.execute("DELETE FROM impressions WHERE applicant = ?", (aid,))
                deleted.append(aid)
            db.commit()
            return jsonify(ok=True, deleted=deleted)

        if action == "add_applicant":
            return add_applicant(db, params)

        return jsonify(ok=False, error="Unbekannte action: " + str(action))
    except Exception as err:
        return jsonify(ok=False, error=str(err))


# ---- Votes / Avail / Meetings ----

def upsert_voter_row(db, table, applicant, voter, fields):
    fields = dict(fields, updated=now_iso())
    cols = ["applicant", "voter"] + list(fields.keys())
    vals = [applicant, voter] + list(fields.values())
    placeholders = ", ".join(["?"] * len(cols))
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields)
    db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(applicant, voter) DO UPDATE SET {updates}", vals)
    db.commit()


def upsert_meeting(db, applicant, fields):
    fields = dict(fields, updated=now_iso())
    cols = ["applicant"] + list(fields.keys())
    vals = [applicant] + list(fields.values())
    placeholders = ", ".join(["?"] * len(cols))
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields)
    db.execute(
        f"INSERT INTO meetings ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(applicant) DO UPDATE SET {updates}", vals)
    db.commit()


def upsert_impression(db, applicant, fields):
    fields = dict(fields, updated=now_iso())
    cols = ["applicant"] + list(fields.keys())
    vals = [applicant] + list(fields.values())
    placeholders = ", ".join(["?"] * len(cols))
    updates = ", ".join(f"{c}=excluded.{c}" for c in fields)
    db.execute(
        f"INSERT INTO impressions ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(applicant) DO UPDATE SET {updates}", vals)
    db.commit()


# ---- Bewerber:innen ----

def read_applicants(db):
    rows = db.execute(
        "SELECT * FROM applicants ORDER BY rowid"
    ).fetchall()
    out = []
    for r in rows:
        a = {k: r[k] for k in APPLICANT_SCALARS}
        a["id"] = r["id"]
        for k in APPLICANT_LISTS:
            try:
                a[k] = json.loads(r[k]) if r[k] else []
            except (TypeError, ValueError):
                a[k] = []
        keys = r.keys()
        # Voller Bewerbungstext; für Alt-Einträge ohne Original der strukturierte raw_md.
        a["bewerbertext"] = (r["bewerbertext"] if "bewerbertext" in keys else "") \
            or (r["raw_md"] if "raw_md" in keys else "") or ""
        out.append(a)
    return out


def insert_applicant(db, a, aid=None, raw_md="", bewerbertext=""):
    """Legt eine Bewerber:in an (neue id) oder aktualisiert die per aid gegebene.
    Gleiche Namen sind erlaubt – die id ist der Schlüssel. Gibt die id zurück."""
    aid = aid or new_id()
    cols = ["id"] + APPLICANT_SCALARS + APPLICANT_LISTS + ["raw_md", "bewerbertext", "created"]
    vals = [aid] + [a.get(k, "") for k in APPLICANT_SCALARS]
    vals += [json.dumps(a.get(k, []) or [], ensure_ascii=False) for k in APPLICANT_LISTS]
    vals += [raw_md, bewerbertext, now_iso()]
    placeholders = ", ".join(["?"] * len(cols))
    # Spaltennamen quoten ("alter" ist ein SQL-Schlüsselwort).
    collist = ", ".join(f'"{c}"' for c in cols)
    updates = ", ".join(f'"{c}"=excluded."{c}"' for c in cols if c != "id")
    db.execute(
        f"INSERT INTO applicants ({collist}) VALUES ({placeholders}) "
        f"ON CONFLICT(id) DO UPDATE SET {updates}", vals)
    return aid


def add_applicant(db, params):
    # Optionale id: gesetzt -> bestehende Bewerber:in aktualisieren; sonst neu anlegen.
    aid = str(params.get("id") or "").strip() or None
    name = str(params.get("name") or "").strip()
    alter = str(params.get("alter") or "").strip()
    text = str(params.get("text") or "").strip()
    if not text:
        return jsonify(ok=False, error="Bewerbungstext fehlt.")

    api_key = get_setting(db, "gemini_api_key")
    if not api_key:
        return jsonify(ok=False, error="Kein Gemini-API-Key hinterlegt. "
                       "Bitte zuerst unter „Einstellungen“ einen Key eintragen.")
    model = get_setting(db, "gemini_model", DEFAULT_MODEL)

    try:
        raw_md = call_gemini(api_key, model, name, alter, text)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        return jsonify(ok=False, error=f"Gemini-Fehler {e.code}: {detail}")
    except Exception as e:
        return jsonify(ok=False, error=f"Gemini nicht erreichbar: {e}")

    applicant = parse_note(raw_md)
    # Vom Formular ausgefüllte Felder haben Vorrang.
    if name:
        applicant["name"] = name
    if alter:
        applicant["alter"] = alter
    if not applicant.get("name"):
        return jsonify(ok=False, error="Konnte keinen Namen ermitteln – bitte Namensfeld ausfüllen.")
    applicant.setdefault("status", "Beworben")

    aid = insert_applicant(db, applicant, aid=aid, raw_md=raw_md, bewerbertext=text)
    applicant["id"] = aid
    db.commit()
    return jsonify(ok=True, applicant=applicant, raw=raw_md)


def load_anleitung():
    try:
        with open(ANLEITUNG_PATH, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def call_gemini(api_key, model, name, alter, text):
    """Ruft Gemini mit der AI-Anleitung als System-Instruktion auf."""
    anleitung = load_anleitung()
    hints = []
    if name:
        hints.append(f"Der Name der Bewerberin/des Bewerbers ist: {name}.")
    if alter:
        hints.append(f"Das Alter ist: {alter}.")
    user_text = (
        (("\n".join(hints) + "\n\n") if hints else "")
        + "Hier ist die unstrukturierte Bewerbung:\n\n" + text
    )
    body = {
        "systemInstruction": {"parts": [{"text": anleitung}]},
        "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        "generationConfig": {"temperature": 0.2},
    }
    url = GEMINI_ENDPOINT.format(model=model)
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(p.get("text", "") for p in parts).strip()


def parse_note(md):
    """Parst die von Gemini erzeugte Markdown-Notiz (YAML-Header + Sektionen)."""
    md = md.strip()
    # Umschließenden ```md ... ```-Codeblock entfernen, falls vorhanden.
    fence = re.match(r"^```[a-zA-Z]*\s*\n(.*)\n```$", md, re.DOTALL)
    if fence:
        md = fence.group(1).strip()

    applicant = {k: "" for k in APPLICANT_SCALARS}
    for k in APPLICANT_LISTS:
        applicant[k] = []

    body = md
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", md, re.DOTALL)
    if fm:
        try:
            meta = yaml.safe_load(fm.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
        for k in APPLICANT_SCALARS:
            if meta.get(k) is not None:
                applicant[k] = meta[k]
        body = fm.group(2)

    # Sektionen ## Situation / ## Person / ## Erwartung als Bulletlisten.
    section_map = {"situation": "situation", "person": "person", "erwartung": "erwartung"}
    current = None
    for line in body.splitlines():
        h = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if h:
            current = section_map.get(h.group(1).strip().lower())
            continue
        b = re.match(r"^\s*[-*]\s+(.*)$", line)
        if b and current:
            item = b.group(1).strip()
            if item:
                applicant[current].append(item)
    return applicant


# ---- iCal-Feed: bestätigte Castings als abonnierbarer Kalender ----
# Kalender-Apps (Google/Apple/Outlook) können /calendar.ics abonnieren und
# aktualisieren sich automatisch – es gibt also keine Datei zu pflegen, der
# Feed wird bei jedem Abruf frisch aus der DB erzeugt.

CASTING_TZ = os.environ.get("CASTING_TZ", "Europe/Berlin")
SLOT_MINUTES = int(os.environ.get("SLOT_MINUTES", "60"))  # Slotlänge wie im Frontend


def _ics_escape(text):
    return (str(text or "")
            .replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def _fold_ics_line(line):
    # RFC 5545: Zeilen max. 75 Oktetts; Fortsetzung mit CRLF + Leerzeichen.
    data = line.encode("utf-8")
    if len(data) <= 75:
        return line
    parts, first = [], True
    while data:
        limit = 75 if first else 74  # Fortsetzungszeilen beginnen mit 1 Space
        cut = min(limit, len(data))
        while cut > 0 and cut < len(data) and (data[cut] & 0xC0) == 0x80:
            cut -= 1  # kein Multibyte-Zeichen zerschneiden
        chunk = data[:cut].decode("utf-8")
        parts.append(chunk if first else " " + chunk)
        data = data[cut:]
        first = False
    return "\r\n".join(parts)


def _slot_to_utc(slot):
    # slot z.B. "2026-07-15T14:00" (lokale Zeit CASTING_TZ) -> UTC-datetime.
    dt = datetime.strptime(slot, "%Y-%m-%dT%H:%M")
    if ZoneInfo is not None:
        try:
            return dt.replace(tzinfo=ZoneInfo(CASTING_TZ)).astimezone(timezone.utc)
        except Exception:
            pass
    return dt.replace(tzinfo=timezone.utc)


def _parse_slot_list(v):
    if not v:
        return []
    try:
        x = json.loads(v)
        return [s for s in x if isinstance(s, str)] if isinstance(x, list) else []
    except Exception:
        return []


def build_ics(db):
    rows = read_table(db, "meetings", MEETINGS_COLS)
    # meetings.applicant ist jetzt eine id -> Namen für die Anzeige nachschlagen.
    id2name = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM applicants").fetchall()}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//WG-Casting//Termine//DE",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:WG-Casting Termine",
        "X-WR-TIMEZONE:" + CASTING_TZ,
    ]
    for m in rows:
        aid = (m.get("applicant") or "").strip()
        name = (id2name.get(aid) or "Casting").strip()
        state = m.get("state")
        # Nur bestätigte / stattgefundene Castings als feste Termine exportieren.
        if state not in ("confirmed", "met") or not m.get("confirmedSlot"):
            continue
        try:
            start = _slot_to_utc(m["confirmedSlot"])
        except Exception:
            continue
        end = start + timedelta(minutes=SLOT_MINUTES)
        slot_safe = re.sub(r"[^0-9A-Za-z]", "", m["confirmedSlot"])
        id_safe = re.sub(r"[^0-9A-Za-z]", "", aid) or "casting"
        uid = f"{id_safe}-{slot_safe}@casting.thhaase.de"
        summary = ("Casting: " if state == "confirmed" else "Casting (kennengelernt): ") + name
        lines += [
            "BEGIN:VEVENT",
            "UID:" + uid,
            "DTSTAMP:" + stamp,
            "DTSTART:" + start.strftime("%Y%m%dT%H%M%SZ"),
            "DTEND:" + end.strftime("%Y%m%dT%H%M%SZ"),
            "SUMMARY:" + _ics_escape(summary),
            "STATUS:CONFIRMED",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold_ics_line(ln) for ln in lines) + "\r\n"


@app.route("/calendar.ics")
def calendar_ics():
    body = build_ics(get_db())
    resp = app.response_class(body, mimetype="text/calendar")
    resp.headers["Content-Disposition"] = 'inline; filename="wg-casting.ics"'
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


# ---- Optional: statische Seite mitservieren (lokale Tests / Docker) ----

if STATIC_DIR:
    def _no_store(resp):
        # Verhindert, dass Browser eine alte Version der App-Seite/Assets zeigen.
        # So sieht die/der Nutzer:in neue Änderungen sofort – ohne den Cache
        # manuell leeren zu müssen.
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp

    @app.route("/")
    def index():
        # Die App selbst ist die Startseite (keine separate Übersichtsseite mehr).
        return _no_store(send_from_directory(STATIC_DIR, "wg-tool.html"))

    @app.route("/<path:path>")
    def static_files(path):
        return _no_store(send_from_directory(STATIC_DIR, path))


# ---- Start: DB anlegen & (einmalig) Bewerber:innen seeden ----
# Nach allen Funktionsdefinitionen, damit insert_applicant/seed_applicants
# beim Import (auch unter gunicorn) verfügbar sind.
with app.app_context():
    _db = get_db()
    init_db(_db)
    seed_applicants(_db)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
