#!/bin/sh
# Second database, for the MLflow tracking server and its AI Gateway.
#
# `litellm` is created by POSTGRES_DB in compose.yml; that variable takes one
# name, so a second database needs this hook. Both servers then apply their own
# migrations on first startup, and neither can see the other's tables.
#
# RUNS ONLY ON AN EMPTY DATA DIRECTORY. Postgres executes
# /docker-entrypoint-initdb.d/* the first time it initialises the cluster and
# never again, so adding this file does nothing to a `postgres_data` volume that
# already exists. On an existing volume, create it by hand, once:
#
#   podman compose exec postgres psql -U postgres -c "CREATE DATABASE mlflow;"
set -e

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<-'SQL'
	CREATE DATABASE mlflow;
SQL
