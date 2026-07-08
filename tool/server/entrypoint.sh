#!/usr/bin/env bash
# Container-Start: Zugangscode/Mitbewohner:innen in die gebaute Seite
# einsetzen (aus den Env-Variablen), dann den Server starten.
set -eu

HTML=/app/static/wg-tool.html

if [ -n "${ACCESS_CODE:-}" ] && [ -f "$HTML" ]; then
  sed -i "s#ACCESS_CODE: \"[^\"]*\"#ACCESS_CODE: \"${ACCESS_CODE}\"#" "$HTML"
fi

# FLATMATES="Anna,Ben,Cem" -> FLATMATES: ["Anna","Ben","Cem"],
if [ -n "${FLATMATES:-}" ] && [ -f "$HTML" ]; then
  arr=$(printf '%s' "$FLATMATES" | awk -F, '{
    out="["; for (i=1;i<=NF;i++){ gsub(/^[ \t]+|[ \t]+$/,"",$i); out=out (i>1?",":"") "\"" $i "\"" } print out "]" }')
  sed -i "s#^  FLATMATES:.*#  FLATMATES: ${arr},#" "$HTML"
fi

# 2 Worker reichen für eine WG; SQLite serialisiert Schreibzugriffe selbst.
exec gunicorn -b 0.0.0.0:8000 -w 2 --timeout 90 server:app
