# tatsuniya/csv-contract-ingest

A Harbor task in the processing category. The agent inherits a CSV ingester that
reads columns by position and has to rewrite it to work off a schema contract.

## Layout

    environment/    the broken starting state
    solution/       reference fix
    tests/          hidden tests and fixtures
    checks/         lazy-implementation guard, see Validation

## Validation

    harbor run -p csv-contract-ingest --agent oracle
    harbor run -p csv-contract-ingest --agent nop

Oracle scores 1.0 with 51 tests passing. nop scores 0.0, so the tests reject the
starting state. 

The hidden tests also run against a second contract the agent never sees, with
different field names, output order, date format, decimal scale, defaults and a
compound dedupe key, so anything hardcoded from the visible contract fails.

    checks/run_cheat_check.sh

The suite is also checked against a deliberately lazy implementation that is
correct only where a fixture looks: physical line numbers instead of record
numbers, bare int() instead of the documented sign-plus-digits rule, and no
whitespace stripping on string values. That implementation must score 0.0, and
the guard above swaps it in, asserts that, and restores the real solve.sh on
exit. If it ever passes, close the gap it found rather than weakening the cheat.

Two shortcuts in the cheat are deliberately left uncaught, because CONTRACT.md
does not specify either way: non-finite decimals ("NaN", "Infinity") and files
in the input directory that are not .csv. Covering them means amending the
contract first.