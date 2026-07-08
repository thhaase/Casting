# WG-Casting Tool – alles-in-einem Container
# ==========================================
# Startet das Flask-Backend, das die App-Seite (wg-tool.html) UND das /api
# ausliefert. Die Bewerber:innen liegen in der SQLite-DB (Quelle der Wahrheit);
# beim allerersten Start werden sie einmalig aus seed_applicants.json übernommen.
#
#   docker compose up -d --build     # bauen & starten
#   -> http://localhost:8000
#
FROM python:3.12-slim

# Python-Abhängigkeiten zuerst (bessere Layer-Cache-Nutzung).
COPY tool/server/requirements.txt /app/tool/server/requirements.txt
RUN pip install --no-cache-dir -r /app/tool/server/requirements.txt

# Backend, App-Seite, KI-Anleitung und Seed-Daten.
COPY . /app
WORKDIR /app

# Nur die App-Seite ausliefern (keine generierte Übersichtsseite mehr).
RUN mkdir -p /app/static && cp tool/wg-tool.html /app/static/wg-tool.html

ENV STATIC_DIR=/app/static \
    SEED_APPLICANTS=/app/tool/server/seed_applicants.json \
    ANLEITUNG_PATH=/app/AI-Anleitung.md \
    CASTING_DB=/data/casting.db \
    GEMINI_MODEL=gemini-flash-latest \
    ACCESS_CODE=wg-casting

RUN mkdir -p /data && chmod +x tool/server/entrypoint.sh

EXPOSE 8000
WORKDIR /app/tool/server
ENTRYPOINT ["/app/tool/server/entrypoint.sh"]
