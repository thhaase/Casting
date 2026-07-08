#!/usr/bin/env bash
#
# build_site.sh — baut aus der Casting-BASE (Übersicht.base) und den
# Bewerber-Notizen (Bewerber/*.md) eine kleine statische Webseite,
# die 1:1 auf GitHub Pages hochgeladen werden kann.
#
# Nutzung:
#   ./build_site.sh [Ausgabeordner]
#
# Standard-Ausgabeordner: ./dist (gitignored). Die erzeugten Dateien sind
# Build-Artefakte und werden NICHT eingecheckt. Der Docker-Build ruft das
# Skript mit einem eigenen Zielordner auf (siehe Dockerfile).
#
# Voraussetzung: python3 mit dem Modul "yaml" (pyyaml).
#   Prüfen/Installieren: python3 -c "import yaml" || pip install pyyaml
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BEWERBER_DIR="$SCRIPT_DIR/Bewerber"
OUTPUT_DIR="${1:-$SCRIPT_DIR/dist}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Fehler: python3 wird benötigt, ist aber nicht installiert." >&2
  exit 1
fi

if ! python3 -c "import yaml" >/dev/null 2>&1; then
  echo "Fehler: Python-Modul 'yaml' (pyyaml) fehlt." >&2
  echo "Installieren mit:  pip install pyyaml   (oder: pip install --user pyyaml)" >&2
  exit 1
fi

if [ ! -d "$BEWERBER_DIR" ]; then
  echo "Fehler: Bewerber-Ordner nicht gefunden: $BEWERBER_DIR" >&2
  exit 1
fi

count=$(find "$BEWERBER_DIR" -maxdepth 1 -name '*.md' | wc -l | tr -d ' ')
if [ "$count" -eq 0 ]; then
  echo "Fehler: Keine .md-Dateien in $BEWERBER_DIR gefunden." >&2
  exit 1
fi

mkdir -p "$OUTPUT_DIR"

echo "Baue Webseite aus $count Bewerber-Notizen ..."

BEWERBER_DIR="$BEWERBER_DIR" OUTPUT_DIR="$OUTPUT_DIR" python3 - <<'PYEOF'
import os
import re
import glob
import html
import datetime

bewerber_dir = os.environ["BEWERBER_DIR"]
output_dir = os.environ["OUTPUT_DIR"]

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$\n(.*?)(?=^##\s|\Z)", re.DOTALL | re.MULTILINE)

STATUS_ORDER = [
    "Zugesagt",
    "Vor-Ort-Besuch geplant",
    "Online-Kennenlernen geplant",
    "Beworben",
    "Abgesagt",
]

STATUS_COLORS = {
    "Zugesagt": "#16a34a",
    "Vor-Ort-Besuch geplant": "#d97706",
    "Online-Kennenlernen geplant": "#6366f1",
    "Beworben": "#64748b",
    "Abgesagt": "#dc2626",
}


def parse_bullets(section_text):
    bullets = []
    for line in section_text.splitlines():
        line = line.strip()
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line.startswith("-") and len(line) > 1 and line[1] != " ":
            bullets.append(line[1:].strip())
    return bullets


def parse_file(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    m = FRONTMATTER_RE.match(raw)
    if not m:
        return None

    fm_text, body = m.group(1), m.group(2)
    fm = yaml.safe_load(fm_text) or {}

    sections = {}
    for heading, content in SECTION_RE.findall(body):
        sections[heading.strip().lower()] = parse_bullets(content)

    return {
        "name": (fm.get("name") or os.path.splitext(os.path.basename(path))[0]).strip(),
        "status": (fm.get("status") or "Beworben").strip(),
        "alter": fm.get("alter"),
        "studium_beruf": (fm.get("studium_beruf") or "").strip(),
        "kennenlernen": (fm.get("kennenlernen") or "").strip(),
        "einzug": (fm.get("einzug") or "offen").strip() if fm.get("einzug") else "offen",
        "eindruck": fm.get("eindruck"),
        "situation": sections.get("situation", []),
        "person": sections.get("person", []),
        "erwartung": sections.get("erwartung", []),
    }


def status_rank(status):
    try:
        return STATUS_ORDER.index(status)
    except ValueError:
        return len(STATUS_ORDER) - 1  # unbekannte Status zwischen Beworben und Abgesagt


def as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def eindruck_sort_key(eindruck):
    n = as_int(eindruck)
    return -n if n is not None else 0


candidates = []
for path in sorted(glob.glob(os.path.join(bewerber_dir, "*.md"))):
    c = parse_file(path)
    if c:
        candidates.append(c)

candidates.sort(key=lambda c: (status_rank(c["status"]), eindruck_sort_key(c["eindruck"]), c["name"]))

# ---- Stats ----
total = len(candidates)
status_counts = {}
for c in candidates:
    status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1


def esc(value):
    return html.escape(str(value)) if value is not None else ""


def stars(eindruck):
    n = as_int(eindruck)
    if n is None:
        return '<span class="muted">–</span>'
    n = max(0, min(5, n))
    return '<span class="stars" title="{n}/5">{filled}{empty}</span>'.format(
        n=n, filled="★" * n, empty="☆" * (5 - n)
    )


def bullet_list(items):
    if not items:
        return '<p class="muted">–</p>'
    return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"


def status_badge(status):
    color = STATUS_COLORS.get(status, "#64748b")
    return f'<span class="badge" style="--badge-color:{color}">{esc(status)}</span>'


def filter_buttons():
    buttons = ['<button class="filter-btn active" data-filter="alle">Alle ({0})</button>'.format(total)]
    for status in STATUS_ORDER:
        n = status_counts.get(status, 0)
        if n == 0:
            continue
        buttons.append(
            f'<button class="filter-btn" data-filter="{esc(status)}" style="--badge-color:{STATUS_COLORS.get(status, "#64748b")}">{esc(status)} ({n})</button>'
        )
    return "\n".join(buttons)


def table_row(c, index):
    alter = c["alter"] if c["alter"] not in (None, "") else "–"
    studium = c["studium_beruf"] or "–"
    kennenlernen = c["kennenlernen"] or "–"
    einzug = c["einzug"] or "offen"
    dimmed = " dimmed" if c["status"] == "Abgesagt" else ""
    detail_id = f"detail-{index}"
    status = esc(c["status"])

    alter_n = as_int(c["alter"])
    eindruck_n = as_int(c["eindruck"])

    # Sortierbare Rohwerte als data-Attribute auf der Zeile selbst.
    sort_attrs = (
        f'data-sort-name="{esc(c["name"].lower())}" '
        f'data-sort-status="{status_rank(c["status"])}" '
        f'data-sort-alter="{alter_n if alter_n is not None else 999}" '
        f'data-sort-studium="{esc(studium.lower())}" '
        f'data-sort-kennenlernen="{esc(kennenlernen.lower())}" '
        f'data-sort-einzug="{esc(einzug.lower())}" '
        f'data-sort-eindruck="{eindruck_n if eindruck_n is not None else -1}"'
    )

    return f"""
    <tr class="row-summary{dimmed}" data-status="{status}" {sort_attrs} role="button" tabindex="0" aria-expanded="false" aria-controls="{detail_id}" data-toggle="{detail_id}">
      <td class="name-cell">
        <span class="chevron" aria-hidden="true">›</span>{esc(c['name'])}
      </td>
      <td data-label="Status">{status_badge(c['status'])}</td>
      <td data-label="Alter">{esc(alter)}</td>
      <td data-label="Studium / Beruf">{esc(studium)}</td>
      <td data-label="Kennenlernen">{esc(kennenlernen)}</td>
      <td data-label="Einzug">{esc(einzug)}</td>
      <td data-label="Eindruck">{stars(c['eindruck'])}</td>
    </tr>
    <tr class="row-detail{dimmed}" id="{detail_id}" data-status="{status}">
      <td colspan="7">
        <div class="detail-grid">
          <section>
            <h3>Situation</h3>
            {bullet_list(c['situation'])}
          </section>
          <section>
            <h3>Person</h3>
            {bullet_list(c['person'])}
          </section>
          <section>
            <h3>Erwartung</h3>
            {bullet_list(c['erwartung'])}
          </section>
        </div>
      </td>
    </tr>"""


rows_html = "\n".join(table_row(c, i) for i, c in enumerate(candidates))
today = datetime.date.today().isoformat()

SORT_COLUMNS = [
    ("name", "Name"),
    ("status", "Status"),
    ("alter", "Alter"),
    ("studium", "Studium / Beruf"),
    ("kennenlernen", "Kennenlernen"),
    ("einzug", "Einzug"),
    ("eindruck", "Eindruck"),
]

thead_html = "\n".join(
    f'<th class="sortable" data-sort-key="{key}" tabindex="0" role="button">{label}</th>'
    for key, label in SORT_COLUMNS
)

html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="robots" content="noindex, nofollow">
<title>WG Casting – Bewerber:innen Übersicht</title>
<link rel="stylesheet" href="style.css">
</head>
<body>
  <header class="page-header">
    <h1>WG Casting – Bewerber:innen Übersicht</h1>
    <p class="muted">{total} Bewerber:innen · Stand {today}</p>
    <p><a class="tool-link" href="wg-tool.html">⭐ Voten &amp; 📅 Termine planen →</a></p>
  </header>

  <nav class="filters" id="filters">
    {filter_buttons()}
  </nav>

  <main class="table-wrap">
    <table class="candidates">
      <thead>
        <tr>
          {thead_html}
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </main>
  <p class="hint muted">Spaltenkopf klicken zum Sortieren · Zeile antippen/klicken, um Situation, Person &amp; Erwartung ein- oder auszuklappen.</p>

  <footer class="page-footer">
    <p class="muted">Automatisch generiert aus der Casting-Base &amp; den Bewerber-Notizen.</p>
  </footer>

  <script>
    // ---- Status-Filter ----
    const filterButtons = document.querySelectorAll(".filter-btn");
    filterButtons.forEach(btn => {{
      btn.addEventListener("click", () => {{
        filterButtons.forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        const filter = btn.dataset.filter;
        document.querySelectorAll("tr[data-status]").forEach(row => {{
          const match = filter === "alle" || row.dataset.status === filter;
          row.classList.toggle("hidden", !match);
        }});
      }});
    }});

    // ---- Zeilen auf-/zuklappen ----
    function toggleRow(row) {{
      const detailRow = document.getElementById(row.dataset.toggle);
      const expanded = row.classList.toggle("expanded");
      detailRow.classList.toggle("open", expanded);
      row.setAttribute("aria-expanded", expanded ? "true" : "false");
    }}

    document.querySelectorAll("tr.row-summary").forEach(row => {{
      row.addEventListener("click", () => toggleRow(row));
      row.addEventListener("keydown", (e) => {{
        if (e.key === "Enter" || e.key === " ") {{
          e.preventDefault();
          toggleRow(row);
        }}
      }});
    }});

    // ---- Spalten-Sortierung ----
    const NUMERIC_SORT_KEYS = new Set(["status", "alter", "eindruck"]);
    const tbody = document.querySelector("table.candidates tbody");
    const sortHeaders = document.querySelectorAll("th.sortable");
    let activeSort = {{ key: null, dir: 1 }};

    function capitalize(s) {{ return s.charAt(0).toUpperCase() + s.slice(1); }}

    function rowGroups() {{
      const groups = [];
      const children = Array.from(tbody.children);
      for (let i = 0; i < children.length; i += 2) {{
        groups.push([children[i], children[i + 1]]);
      }}
      return groups;
    }}

    function sortByKey(key) {{
      const dir = (activeSort.key === key) ? -activeSort.dir : 1;
      activeSort = {{ key, dir }};

      const attr = "sort" + capitalize(key);
      const groups = rowGroups();
      groups.sort((a, b) => {{
        const av = a[0].dataset[attr];
        const bv = b[0].dataset[attr];
        let cmp;
        if (NUMERIC_SORT_KEYS.has(key)) {{
          cmp = parseFloat(av) - parseFloat(bv);
        }} else {{
          cmp = av.localeCompare(bv, "de", {{ sensitivity: "base" }});
        }}
        return cmp * dir;
      }});

      groups.forEach(([summary, detail]) => {{
        tbody.appendChild(summary);
        tbody.appendChild(detail);
      }});

      sortHeaders.forEach(h => h.classList.remove("sort-asc", "sort-desc"));
      const activeHeader = document.querySelector(`th.sortable[data-sort-key="${{key}}"]`);
      activeHeader.classList.add(dir === 1 ? "sort-asc" : "sort-desc");
    }}

    sortHeaders.forEach(th => {{
      th.addEventListener("click", () => sortByKey(th.dataset.sortKey));
      th.addEventListener("keydown", (e) => {{
        if (e.key === "Enter" || e.key === " ") {{
          e.preventDefault();
          sortByKey(th.dataset.sortKey);
        }}
      }});
    }});
  </script>
</body>
</html>
"""

css_doc = """
:root {
  --bg: #f7f7f9;
  --card-bg: #ffffff;
  --text: #1a1a1f;
  --muted: #6b7280;
  --border: #e5e7eb;
  --accent: #2563eb;
  --row-hover: rgba(0,0,0,0.035);
  --detail-bg: rgba(0,0,0,0.015);
  --shadow: 0 1px 2px rgba(0,0,0,0.04), 0 1px 8px rgba(0,0,0,0.04);
  color-scheme: light dark;
}

@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0b0d12;
    --card-bg: #14161c;
    --text: #e8e8ec;
    --muted: #9aa0aa;
    --border: #262a33;
    --accent: #60a5fa;
    --row-hover: rgba(255,255,255,0.045);
    --detail-bg: rgba(255,255,255,0.02);
    --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 1px 8px rgba(0,0,0,0.3);
  }
}

* { box-sizing: border-box; }

body {
  margin: 0;
  padding: 2rem 1.25rem 4rem;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  line-height: 1.5;
}

.page-header {
  max-width: 1200px;
  margin: 0 auto 1.5rem;
  text-align: center;
}

.page-header h1 {
  font-size: 1.75rem;
  margin: 0 0 0.25rem;
}

.tool-link {
  display: inline-block;
  margin-top: 0.4rem;
  padding: 0.4rem 0.9rem;
  border: 1px solid var(--accent);
  border-radius: 999px;
  color: var(--accent);
  text-decoration: none;
  font-size: 0.9rem;
}

.tool-link:hover { background: var(--accent); color: #fff; }

.muted { color: var(--muted); }

.filters {
  max-width: 1200px;
  margin: 0 auto 2rem;
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: center;
}

.filter-btn {
  border: 1px solid var(--border);
  background: var(--card-bg);
  color: var(--text);
  border-radius: 999px;
  padding: 0.4rem 0.9rem;
  font-size: 0.85rem;
  cursor: pointer;
  transition: transform 0.1s ease, border-color 0.1s ease;
}

.filter-btn:hover { transform: translateY(-1px); }

.filter-btn.active {
  border-color: var(--badge-color, var(--text));
  box-shadow: 0 0 0 1px var(--badge-color, var(--text)) inset;
  font-weight: 600;
}

.table-wrap {
  max-width: 1200px;
  margin: 0 auto;
  overflow-x: auto;
  background: var(--card-bg);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: var(--shadow);
}

.hint {
  max-width: 1200px;
  margin: 0.75rem auto 0;
  font-size: 0.82rem;
  text-align: center;
}

table.candidates {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  font-size: 0.92rem;
}

table.candidates thead th {
  position: sticky;
  top: 0;
  background: var(--card-bg);
  text-align: left;
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--muted);
  padding: 0.85rem 1rem;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

table.candidates thead th.sortable {
  cursor: pointer;
  user-select: none;
}

table.candidates thead th.sortable:hover { color: var(--text); }

table.candidates thead th.sortable::after {
  content: "↕";
  display: inline-block;
  margin-left: 0.35rem;
  opacity: 0.35;
  font-size: 0.7rem;
}

table.candidates thead th.sortable.sort-asc::after {
  content: "↑";
  opacity: 1;
  color: var(--accent);
}

table.candidates thead th.sortable.sort-desc::after {
  content: "↓";
  opacity: 1;
  color: var(--accent);
}

tr.row-summary td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
  white-space: nowrap;
}

tr.row-summary {
  cursor: pointer;
}

tr.row-summary:hover { background: var(--row-hover); }

tr.row-summary:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}

tr.row-summary.dimmed { opacity: 0.55; }

tr.row-summary.hidden,
tr.row-detail.hidden { display: none; }

tr.row-detail { display: none; }
tr.row-detail.open { display: table-row; }

tr.row-detail td {
  padding: 0.25rem 1.25rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--detail-bg);
  white-space: normal;
  cursor: default;
}

.name-cell {
  font-weight: 600;
  color: var(--text);
}

tr.row-summary:hover .name-cell { color: var(--accent); }

.chevron {
  display: inline-block;
  width: 0.9em;
  margin-right: 0.3rem;
  color: var(--muted);
  transition: transform 0.15s ease;
}

.row-summary.expanded .chevron { transform: rotate(90deg); color: var(--accent); }

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
  padding-top: 0.75rem;
}

.detail-grid h3 {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--muted);
  margin: 0 0 0.35rem;
}

.detail-grid ul {
  margin: 0;
  padding-left: 1.1rem;
}

.detail-grid li { margin-bottom: 0.2rem; }

.badge {
  --badge-color: #64748b;
  display: inline-block;
  white-space: nowrap;
  font-size: 0.75rem;
  font-weight: 600;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  color: var(--badge-color);
  background: color-mix(in srgb, var(--badge-color) 15%, transparent);
  border: 1px solid color-mix(in srgb, var(--badge-color) 40%, transparent);
}

.stars { letter-spacing: 1px; color: #d97706; }

.page-footer {
  max-width: 1200px;
  margin: 3rem auto 0;
  text-align: center;
  font-size: 0.8rem;
}

/* ---- Mobile: kompakte, scanbare Liste statt Karten ---- */
@media (max-width: 700px) {
  body { padding: 1.5rem 0.85rem 3rem; }

  .page-header h1 { font-size: 1.3rem; }
  .page-header p { font-size: 0.82rem; }

  .filters {
    flex-wrap: nowrap;
    overflow-x: auto;
    justify-content: flex-start;
    margin: 0 -0.85rem 1.25rem;
    padding: 0 0.85rem 0.35rem;
    -webkit-overflow-scrolling: touch;
  }

  .filter-btn {
    flex: 0 0 auto;
    font-size: 0.78rem;
    padding: 0.35rem 0.75rem;
  }

  .table-wrap {
    background: transparent;
    border: none;
    box-shadow: none;
    overflow: visible;
  }

  table.candidates,
  table.candidates tbody {
    display: block;
    width: 100%;
    min-width: 0;
  }

  table.candidates thead { display: none; }

  /* Jede Bewerber:in wird eine kompakte Zeile: Name fett auf Zeile 1,
     alle übrigen Felder als eine fließende, umbrechende Zeile darunter.
     So sieht man auf einen Blick viele Personen statt einer riesigen Karte. */
  tr.row-summary {
    display: block;
    width: 100%;
    padding: 0.65rem 0.15rem;
    border-bottom: 1px solid var(--border);
  }

  tr.row-summary:first-of-type { padding-top: 0.15rem; }

  tr.row-detail { width: 100%; }
  tr.row-detail:not(.open) { display: none; }

  tr.row-summary td,
  tr.row-detail td {
    display: inline;
    padding: 0;
    border: none;
    white-space: normal;
  }

  .name-cell {
    display: block;
    font-size: 1rem;
    margin-bottom: 0.15rem;
  }

  /* Meta-Felder (Status, Alter, Studium, Kennenlernen, Einzug, Eindruck)
     fließen als ein Text mit "·"-Trennern hinter dem Namen. Spaltenreihenfolge
     ist fix (siehe SORT_COLUMNS/table_row), daher gezielt per nth-child. */
  tr.row-summary td:nth-child(n+2) {
    font-size: 0.82rem;
    color: var(--muted);
    margin-left: 0.4rem;
  }

  tr.row-summary td:nth-child(2)::before { content: ""; }                       /* Status: Badge reicht als Label */
  tr.row-summary td:nth-child(3)::before { content: "· Alter "; }
  tr.row-summary td:nth-child(4)::before { content: "· "; }                     /* Studium / Beruf */
  tr.row-summary td:nth-child(5)::before { content: "· "; }                     /* Kennenlernen */
  tr.row-summary td:nth-child(6)::before { content: "· "; }                     /* Einzug */
  tr.row-summary td:nth-child(7)::before { content: "· Eindruck "; }

  tr.row-detail.open {
    padding: 0.25rem 0.15rem 1rem;
    border-bottom: 1px solid var(--border);
  }

  tr.row-detail td { display: block; }

  .detail-grid {
    grid-template-columns: 1fr;
    gap: 1rem;
    padding-top: 0.5rem;
  }

  .hint { font-size: 0.78rem; padding: 0 0.5rem; }
}
"""

os.makedirs(output_dir, exist_ok=True)
with open(os.path.join(output_dir, "index.html"), "w", encoding="utf-8") as f:
    f.write(html_doc)
with open(os.path.join(output_dir, "style.css"), "w", encoding="utf-8") as f:
    f.write(css_doc)

# Bewerberliste für das Voten/Termine-Tool (wg-tool.html liest applicants.json).
# Reihenfolge = wie in der Übersicht (nach Status/Eindruck/Name sortiert).
import json
applicants = [{
    "name": c["name"],
    "status": c["status"],
    "alter": c["alter"],
    "studium_beruf": c["studium_beruf"],
    "kennenlernen": c["kennenlernen"],
    "einzug": c["einzug"],
    "eindruck": c["eindruck"],
    "situation": c["situation"],
    "person": c["person"],
    "erwartung": c["erwartung"],
} for c in candidates]
with open(os.path.join(output_dir, "applicants.json"), "w", encoding="utf-8") as f:
    json.dump(applicants, f, ensure_ascii=False, indent=2)

print(f"OK: {total} Bewerber:innen geschrieben nach {output_dir}")
PYEOF

# Tool-Seite (Voten & Termine) mit ins Ausgabeverzeichnis kopieren.
if [ -f "$SCRIPT_DIR/tool/wg-tool.html" ]; then
  cp "$SCRIPT_DIR/tool/wg-tool.html" "$OUTPUT_DIR/wg-tool.html"
  echo "OK: Tool-Seite kopiert nach $OUTPUT_DIR/wg-tool.html"
fi

echo
echo "Fertig. Seite liegt in: $OUTPUT_DIR"
echo "Lokal ansehen: xdg-open \"$OUTPUT_DIR/index.html\"  (Linux)  oder  open \"$OUTPUT_DIR/index.html\"  (macOS)"
echo
if [ -d "$OUTPUT_DIR/.git" ]; then
  echo "Für GitHub Pages ($OUTPUT_DIR ist bereits ein Git-Repo):"
  echo "  1. cd \"$OUTPUT_DIR\""
  echo "  2. git add . && git commit -m 'Update WG Casting Übersicht'"
  echo "  3. git push   (falls noch kein Remote gesetzt: git remote add origin <url> && git push -u origin main)"
  echo "  4. Im Repo unter Settings -> Pages: Branch 'main' und Ordner '/ (root)' auswählen"
else
  echo "Für GitHub Pages:"
  echo "  1. cd \"$OUTPUT_DIR\""
  echo "  2. git init && git add . && git commit -m 'WG Casting Übersicht'"
  echo "  3. gh repo create <repo-name> --private --source=. --push"
  echo "     (oder manuell: git remote add origin <url> && git push -u origin main)"
  echo "  4. Im Repo unter Settings -> Pages: Branch 'main' und Ordner '/ (root)' auswählen"
fi
echo
echo "ACHTUNG: GitHub Pages ist bei normalen (kostenlosen) Repos IMMER öffentlich erreichbar,"
echo "auch wenn das Repo selbst privat ist. Diese Seite enthält Namen, Alter und persönliche"
echo "Angaben echter Bewerber:innen. Nutze daher z.B. GitHub Pro/Team/Enterprise mit privater"
echo "Pages-Zugriffskontrolle, oder gib den Link nur intern weiter (die Seite hat 'noindex')."
