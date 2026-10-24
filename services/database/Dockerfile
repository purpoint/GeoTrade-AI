# Local and CI only. Railway uses its managed Postgres (run init/00-extensions.sql there once).
FROM postgres:16

COPY config/postgresql.conf /etc/postgresql/geotrade.conf
COPY init/ /docker-entrypoint-initdb.d/
COPY scripts/ /usr/local/bin/geotrade/
RUN chmod +x /usr/local/bin/geotrade/*.sh
