import argparse
import csv
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "records.ndjson"), "w") as out:
        for name in sorted(os.listdir(args.input)):
            if not name.endswith(".csv"):
                continue
            with open(os.path.join(args.input, name), newline="") as fh:
                rows = csv.reader(fh)
                next(rows, None)
                for row in rows:
                    out.write(json.dumps({
                        "order_id": row[0],
                        "customer_email": row[1],
                        "amount": row[2],
                        "ordered_at": row[3],
                        "currency": row[4],
                        "gift": row[5],
                    }) + "\n")


if __name__ == "__main__":
    main()