#!/bin/bash
#
# Regression guard for test-suite teeth.
#
# Swaps checks/cheat_solve.sh in as the solution, runs the oracle against it,
# and fails unless it scores 0.0. A pass means the suite has stopped catching
# one of the shortcuts the cheat takes, and the gap needs closing rather than
# the guard relaxing.
#
# The real solution/solve.sh is restored on exit, including on failure or
# interrupt. `cp` onto an existing file keeps that file's mode, so the swap
# leaves no permission churn behind.
#
# Usage:  checks/run_cheat_check.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
TASK="$(basename "$REPO")"
WORKDIR="$(cd "$REPO/.." && pwd)"

REAL="$REPO/solution/solve.sh"
BACKUP="$(mktemp)"
cp "$REAL" "$BACKUP"

restore() {
    cp "$BACKUP" "$REAL"
    rm -f "$BACKUP"
    echo "[restored $REAL]"
}
trap restore EXIT INT TERM

cp "$HERE/cheat_solve.sh" "$REAL"
echo "[cheat swapped in, running oracle]"

cd "$WORKDIR"
output="$(harbor run -p "$TASK" -a oracle 2>&1)"
echo "$output"

job="$(printf '%s\n' "$output" \
    | sed -n 's|.*Results written to \(jobs/[^ ]*\)/result\.json.*|\1|p' \
    | tail -1)"

if [ -z "$job" ]; then
    echo "FAIL: could not find the job directory in harbor output" >&2
    exit 1
fi

reward="$(python3 - "$WORKDIR/$job/result.json" <<'PY'
import json, sys
evals = json.load(open(sys.argv[1]))["stats"]["evals"]
print(next(iter(evals.values()))["metrics"][0]["mean"])
PY
)"

echo
if [ "$reward" = "0.0" ]; then
    echo "PASS: cheat scored $reward, the suite rejects it"
else
    echo "FAIL: cheat scored $reward, expected 0.0" >&2
    echo "The suite no longer catches one of the shortcuts listed in" >&2
    echo "checks/cheat_solve.sh. Close the gap; do not weaken the cheat." >&2
    exit 1
fi
