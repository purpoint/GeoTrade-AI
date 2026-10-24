# Local and CI only. Railway uses its managed Postgres (run init/00-extensions.sql there once).
FROM postgres:16

# rclone pushes nightly dumps off the box when BACKUP_RCLONE_REMOTE is set (P3-DB-05)
RUN apt-get update && apt-get install -y --no-install-recommends rclone && rm -rf /var/lib/apt/lists/*
COPY config/postgresql.conf /etc/postgresql/geotrade.conf
COPY init/ /docker-entrypoint-initdb.d/
COPY scripts/ /usr/local/bin/geotrade/
RUN chmod +x /usr/local/bin/geotrade/*.sh
