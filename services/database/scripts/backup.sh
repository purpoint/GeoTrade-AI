#!/bin/sh
# Custom-format dump into /backups, keeping the newest $KEEP files.
set -eu
DIR="${BACKUP_DIR:-/backups}"
KEEP="${KEEP:-7}"
mkdir -p "$DIR"
FILE="$DIR/geotrade-$(date -u +%Y%m%dT%H%M%SZ).dump"
pg_dump -Fc -f "$FILE.tmp" "${POSTGRES_DB:-geotrade}"
mv "$FILE.tmp" "$FILE"
echo "backup written: $FILE"
# off-box copy (P3-DB-05): any rclone remote, e.g. Cloudflare R2 "r2:geotrade-backups" set up with rclone config
if [ -n "${BACKUP_RCLONE_REMOTE:-}" ]; then
  rclone copy "$FILE" "$BACKUP_RCLONE_REMOTE" && echo "copied off-box: $BACKUP_RCLONE_REMOTE"
fi
ls -1t "$DIR"/geotrade-*.dump | tail -n +"$((KEEP + 1))" | xargs -r rm --
