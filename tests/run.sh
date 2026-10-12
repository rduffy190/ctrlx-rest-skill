#!/usr/bin/env bash
# Regression test for the ctrlx-rest scripts.
#   tests/run.sh          offline: dl.py and motion_axes.py against mock_ctrlx.py (HTTPS, throwaway cert)
#   tests/run.sh --live   also a READ-ONLY smoke test against the real controller (CTRLX_HOST)
# Needs python3 and openssl. Exits non-zero on any failure.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
echo "== offline (mock controller)"
python3 "$HERE/test_offline.py"
if [ "${1:-}" = "--live" ]; then
    [ -n "${CTRLX_HOST:-}" ] || { echo "--live needs CTRLX_HOST=<controller ip>[:port]"; exit 2; }
    echo "== live, read-only ($CTRLX_HOST)"
    python3 "$HERE/test_live.py"
fi
echo "ALL OK"
