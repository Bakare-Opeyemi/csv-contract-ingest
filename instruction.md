Uploads that worked last month are failing, and some that "succeed" come out
with values in the wrong fields. Three customers have reordered their columns,
two are adding internal columns of their own, and one is still sending the old
`email` header instead of `customer_email`.

Make the ingest survive customers changing their column layout.

- Column order can't matter. Neither can case or spacing, and at least one file has a BOM on it.
- Some customers still send the old name for a renamed field. The contract lists what the old names were. Both can turn up in the same file.
- Ignore columns we don't recognize, but record them in the report so support can see what customers are actually sending.
- Optional fields that aren't present take the default from the contract.
- A file missing a required column is no use to us: reject it and carry on with the rest. A single bad row shouldn't cost us the whole file, though. Quarantine the row with a reason and keep going.
- Exit 0 if everything was clean, 2 if any row was quarantined, 3 if any file was rejected. Highest one wins.

Contract format is documented in /app/docs/CONTRACT.md. There's a worked example
in /app/docs/example_run/: a contract, an input directory, and the three output
files we expect from it. Match that output exactly, it's what the nightly
reconciliation reads.

contracts/orders.schema.json is what we run today. It won't be the only one;
a second feed onboards next month with a different field set.

Constraints:

- Work in /app.
- Standard library only, no network access.
- Don't modify /app/contracts/ or /app/docs/.