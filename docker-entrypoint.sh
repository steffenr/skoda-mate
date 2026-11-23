#!/bin/sh
# Runs the app as the unprivileged user "mate" (uid 10001).
# Started as root (the default): first hand /data to that user, because a ./data folder from an older, root-run
# version (or one Docker just created) is owned by root, then drop root for good before the app starts.
# Started as a non-root user (`user: "10001:10001"` in compose, `docker run --user`): nothing to fix, just run.
set -e
if [ "$(id -u)" = 0 ]; then
  find /data ! -user 10001 -exec chown 10001:10001 {} + 2>/dev/null \
    || echo "skoda-mate: could not chown /data to uid 10001; the app may not be able to write there" >&2
  exec setpriv --reuid=10001 --regid=10001 --clear-groups "$@"
fi
exec "$@"
