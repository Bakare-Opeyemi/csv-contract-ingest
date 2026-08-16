# tatsuniya/csv-contract-ingest

A Harbor task in the processing category. The agent inherits a CSV ingester that
reads columns by position and has to rewrite it to work off a schema contract.

## Layout

    environment/    the broken starting state
    solution/       reference fix
    tests/          hidden tests and fixtures

## Validation

    harbor run -p csv-contract-ingest --agent oracle
    harbor run -p csv-contract-ingest --agent nop

Oracle scores 1.0 with 44 tests passing. nop scores 0.0, so the tests reject the
starting state. 

The hidden tests also run against a second contract the agent never sees, with
different field names, output order, date format, decimal scale, defaults and a
compound dedupe key, so anything hardcoded from the visible contract fails.