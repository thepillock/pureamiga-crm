#!/bin/sh
# Starts as root just long enough to fix /data ownership, then drops to PUID:PGID.
set -e
umask 077
mkdir -p /data
chown -R "${PUID:-99}:${PGID:-100}" /data
as_app() { setpriv --reuid="${PUID:-99}" --regid="${PGID:-100}" --clear-groups "$@"; }
as_app python manage.py migrate --noinput
exec setpriv --reuid="${PUID:-99}" --regid="${PGID:-100}" --clear-groups "$@"
