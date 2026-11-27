#!/bin/sh
set -eu

db_path="${APOBANK_DB_PATH:-/app/data/apobank.db}"
excel_path="${APOBANK_EXCEL_PATH:-/app/data/Musterliste_apoBank.xlsx}"

# A mounted, pre-built SQLite database always has priority. For a fresh local
# setup the supplied Excel file is imported once, before the API starts.
if [ ! -s "$db_path" ] && [ -f "$excel_path" ]; then
  echo "Initialisiere apoBank-Datenbank aus $excel_path"
  python -m backend.import_excel --excel "$excel_path"
fi

exec "$@"
