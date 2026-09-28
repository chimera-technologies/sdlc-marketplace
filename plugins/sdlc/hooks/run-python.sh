#!/usr/bin/env bash
# Run a hook script with the first working Python 3 (python3 on Linux/macOS,
# python on Windows where python3 is often a Store stub).
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 9))' >/dev/null 2>&1; then
    exec "$py" "$@"
  fi
done
echo "sdlc hooks: Python 3.9+ not found." >&2
# Fail closed in headless runs (the guard must hold); open for interactive users.
[ "${SDLC_HEADLESS:-}" = "1" ] && exit 2
exit 0
