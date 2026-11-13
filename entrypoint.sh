#!/bin/sh
# Starts as root just long enough to fix /data ownership, then runs everything as PUID:PGID
# (Unraid's nobody:users by default). Migrations run on every start.
set -e
umask 077
mkdir -p /data
chown -R "${PUID:-99}:${PGID:-100}" /data
setpriv --reuid="${PUID:-99}" --regid="${PGID:-100}" --clear-groups python manage.py migrate --noinput
exec setpriv --reuid="${PUID:-99}" --regid="${PGID:-100}" --clear-groups "$@"
