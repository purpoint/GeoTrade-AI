#!/bin/sh
# Usage: restore.sh /backups/geotrade-<ts>.dump   (replaces objects in $POSTGRES_DB)
set -eu
FILE="${1:?usage: restore.sh <dump file>}"
pg_restore --clean --if-exists --no-owner -d "${POSTGRES_DB:-geotrade}" "$FILE"
echo "restored: $FILE"
