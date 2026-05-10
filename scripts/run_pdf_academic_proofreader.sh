#!/bin/sh
set -eu

usage() {
  echo "Usage: ./scripts/run_pdf_academic_proofreader.sh <pdf-folder> [scan|annotate] [findings-json]"
  echo ""
  echo "Modes:"
  echo "  scan               Scan one PDF and write candidate findings to disk (default)"
  echo "  annotate <json>    Annotate one PDF using reviewed findings JSON"
  exit 1
}

if [ "$#" -lt 1 ]; then
  usage
fi

ROOT="$1"
MODE="${2:-scan}"
FINDINGS_JSON="${3:-}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ "$MODE" = "annotate" ] && [ -z "$FINDINGS_JSON" ]; then
  echo "Error: annotate mode requires a findings JSON file path."
  usage
fi

if [ "$MODE" = "auto" ]; then
  echo "Error: 'auto' mode is disabled in this wrapper to enforce human review."
  echo "Use 'scan' to generate candidates, review them, then use 'annotate <json>'."
  exit 1
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
else
  echo "python3 not found"
  exit 1
fi

if [ -n "$FINDINGS_JSON" ]; then
  exec "$PYTHON_BIN" "$SCRIPT_DIR/low_cost_pdf_pipeline.py" \
    --root "$ROOT" \
    --output "$ROOT/BBB" \
    --mode "$MODE" \
    --same-name \
    --limit 1 \
    --render-dpi 144 \
    --findings-json "$FINDINGS_JSON"
else
  exec "$PYTHON_BIN" "$SCRIPT_DIR/low_cost_pdf_pipeline.py" \
    --root "$ROOT" \
    --output "$ROOT/BBB" \
    --mode "$MODE" \
    --same-name \
    --limit 1 \
    --render-dpi 144
fi
