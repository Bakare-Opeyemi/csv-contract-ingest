import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

TRUE = {"true", "yes", "1"}
FALSE = {"false", "no", "0"}


class BadValue(Exception):
    pass


def normalize(header):
    h = header.lstrip("\ufeff").strip().lower()
    return re.sub(r"\s+", "_", h)


def build_header_map(contract):
    m = {}
    for field, spec in contract["fields"].items():
        for alias in spec.get("aliases", []):
            m[normalize(alias)] = field
    for field in contract["fields"]:
        m[normalize(field)] = field
    return m


def coerce(raw, spec):
    v = raw.strip()
    t = spec["type"]

    if t == "string":
        return v

    if t == "int":
        if not re.fullmatch(r"[+-]?\d+", v):
            raise BadValue()
        return int(v)

    if t == "decimal":
        scale = spec["scale"]
        try:
            d = Decimal(v)
        except InvalidOperation:
            raise BadValue()
        if not d.is_finite():
            raise BadValue()
        q = d.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
        return f"{q:.{scale}f}"

    if t == "date":
        try:
            return datetime.strptime(v, spec["format"]).date().isoformat()
        except ValueError:
            raise BadValue()

    if t == "bool":
        if v.lower() in TRUE:
            return True
        if v.lower() in FALSE:
            return False
        raise BadValue()

    raise BadValue()


def map_columns(header, contract, header_map):
    """Decide which column feeds which field. Returns (chosen, unknown, dupes)."""
    norm = [normalize(h) for h in header]

    candidates = {}
    unknown = set()
    for i, nh in enumerate(norm):
        field = header_map.get(nh)
        if field is None:
            unknown.add(i)
        else:
            candidates.setdefault(field, []).append((i, nh))

    chosen, dupes = {}, set()
    for field, cols in candidates.items():
        canonical = [c for c in cols if c[1] == normalize(field)]
        winners = canonical or cols
        if len(winners) > 1:
            dupes.add(field)
            continue
        chosen[field] = winners[0][0]
        unknown.update(i for i, _ in cols if i != winners[0][0])

    return chosen, sorted({norm[i] for i in unknown}), dupes


def rejection_reason(contract, chosen, dupes):
    for field in contract["output_order"]:
        spec = contract["fields"][field]
        if field in dupes:
            return f"duplicate_column:{field}"
        if spec.get("required", False) and field not in chosen:
            return f"missing_required_column:{field}"
    return None


def build_row(row, contract, chosen):
    """Returns (record, None) or (None, reason)."""
    record = {}
    for field in contract["output_order"]:
        spec = contract["fields"][field]

        if field not in chosen:
            record[field] = spec.get("default")
            continue

        raw = row[chosen[field]]
        if raw.strip() == "":
            if spec.get("required", False):
                return None, "missing_required_value"
            record[field] = spec.get("default")
            continue

        try:
            record[field] = coerce(raw, spec)
        except BadValue:
            return None, "type_coercion_failed"

    return record, None


def process_file(path, name, contract, header_map):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))

    header = rows[0] if rows else []
    chosen, unknown, dupes = map_columns(header, contract, header_map)

    reason = rejection_reason(contract, chosen, dupes)
    if reason:
        return {
            "file": name, "rejected": True, "reason": reason,
            "accepted": 0, "quarantined": 0, "superseded": 0,
            "unknown_columns": [], "defaulted_columns": [],
        }, [], []

    defaulted = sorted(f for f in contract["fields"] if f not in chosen)

    records, quarantined = [], []
    for n, row in enumerate(rows[1:], start=2):
        if len(row) > len(header):
            quarantined.append({
                "file": name, "line_no": n,
                "reason": "too_many_fields", "raw": row,
            })
            continue
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))

        record, bad = build_row(row, contract, chosen)
        if bad:
            quarantined.append({
                "file": name, "line_no": n, "reason": bad, "raw": row,
            })
        else:
            records.append((record, name, n))

    return {
        "file": name, "rejected": False, "reason": None,
        "accepted": len(records), "quarantined": len(quarantined), "superseded": 0,
        "unknown_columns": unknown, "defaulted_columns": defaulted,
    }, records, quarantined

def dedupe(entries, contract):
    """Collapse rows sharing a dedupe_on key, keeping the last one read."""
    keys = contract.get("dedupe_on") or []
    if not keys:
        return [e[0] for e in entries], {}

    winners = {}
    for idx, (record, _, _) in enumerate(entries):
        winners[tuple(record[k] for k in keys)] = idx

    kept_idx = set(winners.values())
    kept, superseded = [], {}
    for idx, (record, name, _) in enumerate(entries):
        if idx in kept_idx:
            kept.append(record)
        else:
            superseded[name] = superseded.get(name, 0) + 1
    return kept, superseded

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", required=True)
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.contract, encoding="utf-8") as fh:
        contract = json.load(fh)
    header_map = build_header_map(contract)

    os.makedirs(args.out, exist_ok=True)
    names = sorted(n for n in os.listdir(args.input) if n.endswith(".csv"))

    reports, all_entries, all_quarantined = [], [], []
    for name in names:
        report, entries, quarantined = process_file(
            os.path.join(args.input, name), name, contract, header_map
        )
        reports.append(report)
        all_entries.extend(entries)
        all_quarantined.extend(quarantined)

    all_records, superseded = dedupe(all_entries, contract)

    for report in reports:
        lost = superseded.get(report["file"], 0)
        report["superseded"] = lost
        report["accepted"] -= lost

    def write_ndjson(filename, items):
        with open(os.path.join(args.out, filename), "w", encoding="utf-8") as fh:
            for item in items:
                fh.write(json.dumps(item) + "\n")

    write_ndjson("records.ndjson", all_records)
    write_ndjson("quarantine.ndjson", all_quarantined)

    with open(os.path.join(args.out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump({"contract": contract["name"], "files": reports}, fh, indent=2)
        fh.write("\n")

    if any(r["rejected"] for r in reports):
        sys.exit(3)
    if all_quarantined:
        sys.exit(2)


if __name__ == "__main__":
    main()