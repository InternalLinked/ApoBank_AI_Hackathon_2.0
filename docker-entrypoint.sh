#!/bin/sh
set -eu

db_path="${APOBANK_DB_PATH:-/app/data/apobank.db}"
excel_path="${APOBANK_EXCEL_PATH:-/app/data/Musterliste_apoBank.xlsx}"

# A mounted, populated SQLite database always has priority. For a fresh or
# still empty local database the supplied Excel file is imported before the API
# starts. The import is idempotent and preserves existing conversation records.
partner_count=""
if [ -s "$db_path" ]; then
  partner_count="$(python -c 'import sqlite3, sys; conn = sqlite3.connect(sys.argv[1]); print(conn.execute("SELECT COUNT(*) FROM vermittler").fetchone()[0])' "$db_path" 2>/dev/null || printf '0')"
fi

if [ -f "$excel_path" ] && { [ ! -s "$db_path" ] || [ "${partner_count:-0}" -eq 0 ]; }; then
  echo "Initialisiere apoBank-Datenbank aus $excel_path"
  python -m backend.import_excel --excel "$excel_path"
fi

exec "$@"
