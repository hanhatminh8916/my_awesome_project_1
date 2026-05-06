#!/usr/bin/env bash
# =============================================================================
# kibana-setup.sh
# Creates Kibana data view, saved search, visualizations, and dashboard for
# the microservices ELK stack.
#
# Usage:
#   KIBANA_URL=http://localhost:5601 bash kibana-setup.sh
# =============================================================================
set -euo pipefail

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"

HDR_XSRF=(-H "kbn-xsrf: true")
HDR_JSON=(-H "Content-Type: application/json")

# ---------------------------------------------------------------------------
# 1. Wait for Kibana
# ---------------------------------------------------------------------------
echo "[1/5] Waiting for Kibana at ${KIBANA_URL} ..."
until curl -sf "${KIBANA_URL}/api/status" | grep -q '"level":"available"'; do
  sleep 5
done
echo "      Kibana is up."

# ---------------------------------------------------------------------------
# 2. Create data view (index pattern)
# ---------------------------------------------------------------------------
echo "[2/5] Creating data view 'microservices-logs-*' ..."
curl -sf -X POST "${KIBANA_URL}/api/data_views/data_view" \
  "${HDR_XSRF[@]}" "${HDR_JSON[@]}" \
  -d '{
    "data_view": {
      "id":            "microservices-logs",
      "name":          "Microservices Logs",
      "title":         "microservices-logs-*",
      "timeFieldName": "@timestamp"
    },
    "override": true
  }' | grep -q '"id"' && echo "      Data view created." || echo "      Data view may already exist, continuing."

# ---------------------------------------------------------------------------
# 3. Import saved objects (search + visualizations + dashboard)
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NDJSON_FILE="${SCRIPT_DIR}/saved-objects.ndjson"

echo "[3/5] Importing saved objects from ${NDJSON_FILE} ..."
IMPORT_RESULT=$(curl -sf -X POST \
  "${KIBANA_URL}/api/saved_objects/_import?overwrite=true" \
  "${HDR_XSRF[@]}" \
  -F "file=@${NDJSON_FILE}")

if echo "$IMPORT_RESULT" | grep -q '"success":true'; then
  echo "      Saved objects imported successfully."
else
  echo "      Import result: ${IMPORT_RESULT}"
fi

# ---------------------------------------------------------------------------
# 4. Set default data view
# ---------------------------------------------------------------------------
echo "[4/5] Setting default data view ..."
curl -sf -X POST "${KIBANA_URL}/api/data_views/default" \
  "${HDR_XSRF[@]}" "${HDR_JSON[@]}" \
  -d '{"data_view_id":"microservices-logs","force":true}' > /dev/null && \
  echo "      Default data view set." || true

# ---------------------------------------------------------------------------
# 5. Done
# ---------------------------------------------------------------------------
echo "[5/5] Kibana setup complete."
echo ""
echo "  Kibana URL  : ${KIBANA_URL}"
echo "  Data view   : microservices-logs-*"
echo "  Dashboard   : Microservices Overview"
echo "  Saved search: ERROR Logs - Last 1 Hour"
