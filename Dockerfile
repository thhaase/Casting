# WG-Casting Tool – alles-in-einem Container
# ==========================================
# Baut die statische Seite aus den Bewerber-Notizen und startet das
# Flask-Backend (das /api UND die statische Seite ausliefert).
#
#   docker compose up -d --build     # bauen & starten
#   -> http://localhost:8000
#
FROM python:3.12-slim

# Python-Abhängigkeiten zuerst (bessere Layer-Cache-Nutzung).
COPY tool/server/requirements.txt /app/tool/server/requirements.txt
RUN pip install --no-cache-dir -r /app/tool/server/requirements.txt

# Gesamtes Repo (Bewerber-Notizen, build_site.sh, AI-Anleitung.md, tool/).
COPY . /app
WORKDIR /app

# Statische Seite bauen: index.html, style.css, applicants.json, wg-tool.html
# landen in /app/static. applicants.json dient als Erst-Seed für die DB.
RUN chmod +x build_site.sh && ./build_site.sh /app/static

ENV STATIC_DIR=/app/static \
    SEED_APPLICANTS=/app/static/applicants.json \
    ANLEITUNG_PATH=/app/AI-Anleitung.md \
    CASTING_DB=/data/casting.db \
    GEMINI_MODEL=gemini-flash-latest \
    ACCESS_CODE=wg-casting

RUN mkdir -p /data && chmod +x tool/server/entrypoint.sh

EXPOSE 8000
WORKDIR /app/tool/server
ENTRYPOINT ["/app/tool/server/entrypoint.sh"]
