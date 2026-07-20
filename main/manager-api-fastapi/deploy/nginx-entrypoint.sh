#!/bin/sh
set -eu

UPSTREAM=${MANAGER_API_UPSTREAM:-manager-api-fastapi:8002}
case "${UPSTREAM}" in
  ''|*[!A-Za-z0-9._:-]*)
    echo "MANAGER_API_UPSTREAM must be a hostname-or-IP and port" >&2
    exit 2
    ;;
esac

export MANAGER_API_UPSTREAM=${UPSTREAM}
envsubst '${MANAGER_API_UPSTREAM}' \
  < /etc/nginx/nginx.conf.template \
  > /tmp/manager-api-nginx.conf
exec nginx -c /tmp/manager-api-nginx.conf -g 'daemon off;'
