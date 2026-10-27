#!/bin/sh
set -e

# Only the web container migrates; the scheduler waits for it to finish.
if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  python manage.py migrate --noinput
  if [ "${SEED_DEMO:-0}" = "1" ]; then
    python manage.py seed_demo || echo "seed_demo skipped"
    if [ "${LDAP_ENABLED:-false}" = "true" ]; then python manage.py seed_ldap || true; fi
  fi
fi

exec "$@"
