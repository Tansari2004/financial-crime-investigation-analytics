from pathlib import Path

import pytest

from banking_pipeline.contract import HEADERS, validate_row
from banking_pipeline.ingest import parse_records, sha256_file


FIXTURE = Path(__file__).parent / "fixtures" / "pipeline_transactions.csv"


def test_fixture_contract_and_quality() -> None:
    rows = list(parse_records(FIXTURE))
    assert len(rows) == 7
    assert rows[0][2]["from_account"] == "A001"
    assert rows[0][2]["to_account"] == "B001"
    assert rows[0][3] == []
    assert rows[3][3] == ["invalid_timestamp"]
    assert rows[4][3] == ["missing_from_account"]
    assert rows[5][3] == ["invalid_amount_received"]
    assert rows[6][3] == ["wrong_column_count"]
    assert rows[6][1].endswith("40.00,USD")


def test_bad_header_fails_file(tmp_path: Path) -> None:
    path = tmp_path / "wrong.csv"
    path.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError, match="header_mismatch"):
        list(parse_records(path))


def test_malformed_csv_line_is_quarantinable(tmp_path: Path) -> None:
    path = tmp_path / "broken.csv"
    path.write_text(",".join(HEADERS) + "\n\"unclosed,field\n")
    rows = list(parse_records(path))
    assert rows[0][3] == ["malformed_csv"]
    assert rows[0][1] == '"unclosed,field'


def test_amount_and_label_contract() -> None:
    values = ["2022/09/01 09:00", "001", "A", "002", "B", "1.234", "USD",
              "NaN", "USD", "Wire", "2"]
    assert validate_row(values) == ["invalid_amount_received", "invalid_amount_paid",
                                    "invalid_laundering_label"]
    assert len(HEADERS) == 11
    assert len(sha256_file(FIXTURE)) == 64


def test_amount_exceeding_typed_numeric_capacity_is_rejected() -> None:
    values = ["2022/09/01 09:00", "001", "A", "002", "B", "1000000000000000000.00",
              "USD", "1.00", "USD", "Wire", "0"]
    assert validate_row(values) == ["invalid_amount_received"]
