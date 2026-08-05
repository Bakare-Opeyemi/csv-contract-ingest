# Contract format

One JSON file per feed. Easiest to just show the orders one with notes on it,
the real files obviously have no comments in them.

    {
      "name": "orders",                 <- ends up in report.json
      "output_order": [                 <- key order in records.ndjson.
        "order_id",                        reconciliation reads these
        "customer_email",                  positionally so check with
        "amount",                          finance before reordering
        "currency",
        "ordered_at",
        "gift"
      ],
      "fields": {
        "order_id":       {"type": "string", "required": true},
        "customer_email": {"type": "string", "required": true,
                           "aliases": ["email", "buyer_email"]},
        "amount":         {"type": "decimal", "required": true, "scale": 2},
        "ordered_at":     {"type": "date", "required": true,
                           "format": "%Y-%m-%d"},
        "currency":       {"type": "string", "default": "USD"},
        "gift":           {"type": "bool", "default": false}
      }
    }

Field options:

- type: string, int, decimal, date, bool
- required: leave it out and it's false
- aliases: header names we used to accept. Left over from the 2023 rename, a few customers never updated their exports.
- default: used when the column isn't in the file at all, and also when it is there but the cell is empty. Only means anything on optional fields.
- scale: decimal only
- format: date only, strptime string for whatever shape the customer sends

Type notes:

string is stripped of surrounding whitespace, otherwise left alone.
int is sign plus digits, nothing else. No commas, no "1.0".
decimal is rounded half up to scale, then written as a string so we keep the
trailing zero. "12.50", not 12.5. Finance complained about this one.
date is read with format and always written back as YYYY-MM-DD regardless of
what came in.
bool takes true/false/yes/no/1/0, any case.

Aliases

If a file has both the current name and one of its aliases, the current name
wins and the alias column counts as unknown. Vertex did this to us for a
month after their half-finished migration.

If two columns land on the same field and neither one is the current name,
there's no telling which is real, so the file gets rejected.

Rows

A row with fewer fields than the header gets padded out with empty values.
A row with more gets quarantined on its own, the rest of the file still goes
through.

line_no in the quarantine file counts records with the header as 1, so the
first data row is 2. Not the same as physical line numbers once a quoted
field has a newline in it.

Anything that won't parse is a coercion failure and quarantines the row.

TODO: nothing validates the contracts themselves. A typo in a type name and it blows up mid-run instead of when you save the file.
