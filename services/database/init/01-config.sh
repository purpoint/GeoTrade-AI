#!/bin/sh
# Pull our overrides into the generated postgresql.conf (applies after the init restart).
set -e
echo "include '/etc/postgresql/geotrade.conf'" >> "$PGDATA/postgresql.conf"
