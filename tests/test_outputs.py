"""
Use this file to define pytest tests that verify the outputs of the task.

This file will be copied to /tests/test_outputs.py and run by the /tests/test.sh file
from the working directory.
"""


import json
import pathlib
import subprocess
import sys

import pytest

FIXTURES = pathlib.Path("/tests/fixtures")
INGEST = "/app/ingest.py"

ORDERS_ORDER = ["order_id", "customer_email", "amount", "currency", "ordered_at", "gift"]
INVOICES_ORDER = ["invoice_no", "vendor", "net_total", "due_on", "line_count", "status"]


class Result:
    def __init__(self, proc, out):
        self.proc = proc
        self.out = out

    @property
    def exit_code(self):
        return self.proc.returncode

    def _read(self, name):
        path = self.out / name
        assert path.exists(), f"{name} not written. stderr:\n{self.proc.stderr}"
        return path.read_text()

    @property
    def records(self):
        return [json.loads(l) for l in self._read("records.ndjson").splitlines() if l.strip()]

    @property
    def quarantine(self):
        return [json.loads(l) for l in self._read("quarantine.ndjson").splitlines() if l.strip()]

    @property
    def report(self):
        return json.loads(self._read("report.json"))

    def for_file(self, name):
        for entry in self.report["files"]:
            if entry["file"] == name:
                return entry
        raise AssertionError(f"{name} missing from report.json")


@pytest.fixture(scope="session")
def run_case(tmp_path_factory):
    cache = {}

    def _run(case):
        if case not in cache:
            contract = "invoices.json" if case.startswith("invoices") else "orders.json"
            out = tmp_path_factory.mktemp(case)
            proc = subprocess.run(
                [sys.executable, INGEST,
                 "--contract", str(FIXTURES / contract),
                 "--input", str(FIXTURES / "cases" / case),
                 "--out", str(out)],
                capture_output=True, text=True,
            )
            cache[case] = Result(proc, out)
        return cache[case]

    return _run


def test_all_three_outputs_are_written(run_case):
    """A clean run produces records, quarantine and report files."""
    result = run_case("orders_clean")
    for name in ("records.ndjson", "quarantine.ndjson", "report.json"):
        assert (result.out / name).exists(), f"{name} missing"


def test_clean_upload_exits_zero(run_case):
    """Nothing quarantined and nothing rejected means exit 0."""
    result = run_case("orders_clean")
    assert result.exit_code == 0
    assert len(result.records) == 2
    assert result.quarantine == []


def test_bool_accepts_documented_spellings(run_case):
    """All six spellings parse, in any case, to the JSON boolean they name."""
    gifts = {r["order_id"]: r["gift"] for r in run_case("orders_bools").records}
    assert gifts == {
        "B-1": True,   # TRUE
        "B-2": True,   # yes
        "B-3": True,   # 1
        "B-4": False,  # False
        "B-5": False,  # NO
        "B-6": False,  # 0
    }


def test_columns_matched_by_name_not_position(run_case):
    """A reordered upload with messy headers still lands values in the right fields."""
    records = run_case("orders_mixed").records
    assert [r["order_id"] for r in records] == ["M-1", "M-2"]
    assert [r["customer_email"] for r in records] == ["c@example.com", "d@example.com"]


def test_bom_does_not_hide_the_first_column(run_case):
    """A file with a UTF-8 BOM is ingested rather than rejected."""
    result = run_case("orders_mixed")
    assert result.for_file("legacy_feed.csv")["rejected"] is False
    assert len(result.records) == 2


@pytest.mark.parametrize("case,upload,unknown", [
    ("orders_mixed", "legacy_feed.csv", ["legacy_id"]),
    ("invoices_mixed", "vendor_feed.csv", ["po_ref"]),
])
def test_unknown_columns_are_reported_not_emitted(run_case, case, upload, unknown):
    """Unrecognised columns appear in the report and never in a record."""
    result = run_case(case)
    assert result.for_file(upload)["unknown_columns"] == unknown
    assert all(u not in r for r in result.records for u in unknown)

def test_every_unknown_column_is_reported(run_case):
    """A file with several unrecognised columns reports all of them, not just one."""
    result = run_case("orders_unknowns")
    unknown = ["alpha_ref", "mid_field", "zeta_note"]
    assert sorted(result.for_file("extra.csv")["unknown_columns"]) == unknown
    assert all(u not in r for r in result.records for u in unknown)


@pytest.mark.parametrize("case,upload,defaulted", [
    ("orders_mixed", "legacy_feed.csv", ["currency", "gift"]),
    ("invoices_mixed", "vendor_feed.csv", ["line_count", "status"]),
])
def test_defaulted_columns_lists_the_absent_optionals(run_case, case, upload, defaulted):
    """Fields with no column in the upload are named in the report."""
    entry = run_case(case).for_file(upload)
    assert sorted(entry["defaulted_columns"]) == defaulted


def test_defaulted_columns_ignores_empty_cells_in_present_columns(run_case):
    """A blank cell defaults the value but the column was there, so nothing is listed."""
    result = run_case("invoices_rows")
    assert result.for_file("invoices.csv")["defaulted_columns"] == []
    assert {r["invoice_no"]: r["status"] for r in result.records}["INV-5"] == "pending"


@pytest.mark.parametrize("case,field,expected", [
    ("orders_mixed", "currency", "USD"),
    ("orders_mixed", "gift", False),
    ("invoices_mixed", "status", "pending"),
    ("invoices_mixed", "line_count", 0),
])
def test_absent_optional_takes_contract_default(run_case, case, field, expected):
    """A column absent from the upload is filled from that contract's default."""
    records = run_case(case).records
    assert len(records) == 2
    for record in records:
        assert record[field] == expected


def test_empty_optional_cell_takes_contract_default(run_case):
    """A blank cell in an optional column falls back to the default."""
    statuses = {r["invoice_no"]: r["status"] for r in run_case("invoices_rows").records}
    assert statuses["INV-5"] == "pending"


def test_alias_column_resolves_to_its_field(run_case):
    """An upload using an old header name is matched to the current field."""
    assert [r["invoice_no"] for r in run_case("invoices_mixed").records] == ["INV-77", "INV-78"]


def test_current_name_beats_alias_when_both_present(run_case):
    """With both the field name and an alias present, the field name wins."""
    result = run_case("orders_conflict")
    assert result.records[0]["customer_email"] == "new@example.com"
    assert result.for_file("both.csv")["unknown_columns"] == ["email"]


def test_two_aliases_with_no_current_name_rejects_the_file(run_case):
    """An ambiguous pair of alias columns rejects the file with exit 3."""
    result = run_case("orders_dup_col")
    entry = result.for_file("ambiguous.csv")
    assert entry["rejected"] is True
    assert entry["reason"] == "duplicate_column:customer_email"
    assert result.records == []
    assert result.exit_code == 3


def test_missing_required_column_rejects_only_that_file(run_case):
    """One rejected file does not stop the others being ingested."""
    result = run_case("orders_missing_col")
    assert result.for_file("broken.csv")["reason"] == "missing_required_column:amount"
    assert result.for_file("fine.csv")["rejected"] is False
    assert [r["order_id"] for r in result.records] == ["Z-2"]
    assert result.exit_code == 3


def test_row_failures_are_quarantined_with_reasons(run_case):
    """Each bad row lands in quarantine with its line number and reason."""
    entries = run_case("orders_rows").quarantine
    assert [(e["line_no"], e["reason"]) for e in entries] == [
        (2, "missing_required_value"),
        (3, "type_coercion_failed"),
        (5, "too_many_fields"),
        (6, "type_coercion_failed"),
    ]


def test_line_no_counts_records_not_physical_lines(run_case):
    """A quoted newline shifts the physical lines, but line_no still counts records."""
    entries = run_case("invoices_lines").quarantine
    assert [(e["raw"][0], e["line_no"]) for e in entries] == [
        ("INV-21", 3),
        ("INV-23", 5),
    ]


def test_short_row_is_padded_and_accepted(run_case):
    """A row with fewer fields than the header is padded, not quarantined."""
    records = {r["order_id"]: r for r in run_case("orders_rows").records}
    assert "R-3" in records
    assert records["R-3"]["currency"] == "USD"
    assert records["R-3"]["gift"] is False


def test_quarantined_rows_give_exit_two(run_case):
    """Quarantined rows with no rejected file means exit 2."""
    assert run_case("orders_rows").exit_code == 2


def test_rejected_file_outranks_quarantined_rows(run_case):
    """A run with both a rejected file and quarantined rows exits 3, not 2."""
    result = run_case("orders_exit_precedence")
    assert result.for_file("a_reject.csv")["rejected"] is True
    assert len(result.quarantine) == 2
    assert result.exit_code == 3


def test_quarantine_entry_names_the_file_it_came_from(run_case):
    """Each quarantined row carries the upload it was read from."""
    entries = run_case("orders_exit_precedence").quarantine
    assert [(e["file"], e["line_no"], e["reason"]) for e in entries] == [
        ("b_partial.csv", 3, "missing_required_value"),
        ("c_partial.csv", 2, "type_coercion_failed"),
    ]


@pytest.mark.parametrize("case,field,expected", [
    ("orders_mixed", "amount", ["7.50", "0.01"]),
    ("invoices_rows", "net_total", ["10.001", "10.000", "7.250"]),
])
def test_decimal_written_at_contract_scale_half_up(run_case, case, field, expected):
    """Decimals are rounded half up and written as strings at the contract's scale."""
    assert [r[field] for r in run_case(case).records] == expected


def test_date_read_with_the_contract_format(run_case):
    """Dates are parsed with the contract's format and written back as ISO."""
    dates = {r["invoice_no"]: r["due_on"] for r in run_case("invoices_rows").records}
    assert dates["INV-1"] == "2026-01-05"
    assert dates["INV-2"] == "2026-12-31"


def test_date_not_matching_contract_format_is_quarantined(run_case):
    """An ISO date is a coercion failure when the contract says day first."""
    reasons = {e["raw"][0]: e["reason"] for e in run_case("invoices_rows").quarantine}
    assert reasons["INV-3"] == "type_coercion_failed"


def test_int_field_is_a_number_not_a_string(run_case):
    """An int field is emitted as a JSON number."""
    counts = {r["invoice_no"]: r["line_count"] for r in run_case("invoices_rows").records}
    assert counts["INV-1"] == 3
    assert isinstance(counts["INV-1"], int)


def test_non_numeric_int_is_quarantined(run_case):
    """A non-numeric value in an int column quarantines the row."""
    reasons = {e["raw"][0]: e["reason"] for e in run_case("invoices_rows").quarantine}
    assert reasons["INV-4"] == "type_coercion_failed"


@pytest.mark.parametrize("invoice_no,line_no", [
    ("INV-31", 3),  # 1_000
    ("INV-32", 4),  # 1.0
    ("INV-33", 5),  # 1,000
])
def test_int_takes_sign_and_digits_only(run_case, invoice_no, line_no):
    """Underscores, decimal points and thousands separators are all coercion failures."""
    entries = {e["raw"][0]: e for e in run_case("invoices_strict_values").quarantine}
    assert entries[invoice_no]["reason"] == "type_coercion_failed"
    assert entries[invoice_no]["line_no"] == line_no


def test_signed_int_is_accepted(run_case):
    """A leading + is part of the documented int shape."""
    counts = {
        r["invoice_no"]: r["line_count"]
        for r in run_case("invoices_strict_values").records
    }
    assert counts["INV-34"] == 7


def test_values_are_stripped_of_surrounding_whitespace(run_case):
    """Padded cells are stripped before coercion, strings included."""
    records = {r["invoice_no"]: r for r in run_case("invoices_strict_values").records}
    assert "INV-30" in records, "padded key was not stripped"
    assert records["INV-30"]["vendor"] == "Padded Vendor"
    assert records["INV-30"]["status"] == "open"
    assert records["INV-30"]["due_on"] == "2026-03-01"
    assert records["INV-30"]["line_count"] == 4


@pytest.mark.parametrize("case,order", [
    ("orders_clean", ORDERS_ORDER),
    ("invoices_mixed", INVOICES_ORDER),
])
def test_record_keys_follow_contract_output_order(run_case, case, order):
    """Record keys appear in the contract's output_order, not the upload's."""
    records = run_case(case).records
    assert len(records) == 2
    for record in records:
        assert list(record.keys()) == order


@pytest.mark.parametrize("case,name", [
    ("orders_clean", "orders"),
    ("invoices_rows", "invoices"),
])
def test_report_names_the_contract_it_ran(run_case, case, name):
    """report.json carries the contract's own name, not the feed's filename."""
    assert run_case(case).report["contract"] == name


def test_report_lists_every_file_sorted(run_case):
    """report.json covers all input files, rejected or not, in filename order."""
    files = [f["file"] for f in run_case("orders_missing_col").report["files"]]
    assert files == ["broken.csv", "fine.csv"]


def test_quoted_fields_survive_commas_and_escaped_quotes(run_case):
    """Quoted fields keep embedded delimiters, doubled quotes and newlines."""
    result = run_case("invoices_quoting")
    vendors = {r["invoice_no"]: r["vendor"] for r in result.records}
    assert len(result.records) == 3
    assert vendors["INV-9"] == "Smith, Jones & Co"
    assert vendors["INV-10"] == 'He said "urgent"'
    assert vendors["INV-11"].replace("\r\n", "\n") == "Multi\nLine Vendor"



def test_duplicate_key_keeps_the_last_row_read(run_case):
    """A key repeated across files collapses to the row from the later file."""
    result = run_case("orders_dupes")
    assert len(result.records) == 2
    by_id = {r["order_id"]: r for r in result.records}
    assert by_id["DUP-1"]["amount"] == "99.00"
    assert by_id["DUP-1"]["customer_email"] == "new@example.com"


def test_superseded_counted_against_the_losing_file(run_case):
    """A dropped row counts on the file it came from, not the winner's file."""
    result = run_case("orders_dupes")
    assert result.for_file("a_first.csv")["accepted"] == 1
    assert result.for_file("a_first.csv")["superseded"] == 1
    assert result.for_file("b_later.csv")["accepted"] == 1
    assert result.for_file("b_later.csv")["superseded"] == 0


def test_superseded_rows_are_not_quarantined(run_case):
    """Dropping a duplicate is not an error, so quarantine stays empty."""
    result = run_case("orders_dupes")
    assert result.quarantine == []
    assert result.exit_code == 0


def test_compound_dedupe_key_uses_every_field(run_case):
    """Rows matching on only part of the key stay as separate records."""
    result = run_case("invoices_dupes")
    assert len(result.records) == 2
    assert [r["net_total"] for r in result.records] == ["20.000", "30.000"]


def test_dedupe_compares_coerced_values(run_case):
    """5/1/2026 and 05/01/2026 are one date, so those two rows collapse."""
    result = run_case("invoices_dupes")
    assert result.for_file("reissued.csv")["superseded"] == 1
    assert [r["due_on"] for r in result.records] == ["2026-01-05", "2026-01-06"]


@pytest.mark.parametrize("case,upload,data_rows", [
    ("orders_dupes", "a_first.csv", 2),
    ("invoices_dupes", "reissued.csv", 3),
    ("orders_rows", "messy.csv", 6),
])
def test_report_counts_account_for_every_data_row(run_case, case, upload, data_rows):
    """accepted + quarantined + superseded equals the file's data row count."""
    entry = run_case(case).for_file(upload)
    assert entry["accepted"] + entry["quarantined"] + entry["superseded"] == data_rows