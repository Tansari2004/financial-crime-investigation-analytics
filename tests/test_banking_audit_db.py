"""Regression checks for recovered files and complete verification evidence."""
import csv
import os
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest

from banking_pipeline.analytics import publish
from banking_pipeline.bootstrap import bootstrap
from banking_pipeline.contract import HEADERS
from banking_pipeline.corrections import CORRECTION_HEADER, ingest_corrections
from banking_pipeline.ingest import ingest_file
from banking_pipeline.promote import promote

DSN = os.environ.get('BANKING_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not DSN, reason='set BANKING_TEST_DATABASE_URL')
ROOT = Path(__file__).resolve().parents[1]
spec = spec_from_file_location('banking_verifier', ROOT / 'scripts/verify_banking_full_run.py')
verifier = module_from_spec(spec)
spec.loader.exec_module(verifier)


@pytest.fixture
def database():
    """Dedicated schemas, never share the deliberate corruption with other tests."""
    import psycopg
    schema = 'audit_' + uuid4().hex
    # Each regression gets its own database; supplied DSN must be disposable/admin.
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(schema)))
    options = conninfo_to_dict(DSN)
    options['dbname'] = schema
    dsn = make_conninfo(**options)
    try:
        bootstrap(dsn)
        yield dsn
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(schema)))


def write(path, rows, header=HEADERS):
    with path.open('w', newline='') as output:
        w = csv.writer(output)
        w.writerow(header)
        w.writerows(rows)
    return path


def clean_publication(dsn):
    ingest_file(ROOT / 'tests/fixtures/clean_pipeline_Trans.csv', dsn)
    while promote(dsn)['status'] != 'skipped':
        pass
    assert publish(dsn)['status'] == 'published'


def test_retried_older_rejected_file_cannot_bypass_publication_gate(database, tmp_path, monkeypatch):
    import banking_pipeline.ingest as ingestion
    import psycopg
    # Fail after manifest creation, then publish a later file while this is failed.
    path = write(tmp_path / 'retry_Trans.csv', [['bad-date','1','A','2','B','1','USD','1','USD','Wire','0']])
    def interrupted(*args, **kwargs):
        raise RuntimeError('simulated transient interruption')
    with monkeypatch.context() as scoped:
        scoped.setattr(ingestion, '_copy_rows', interrupted)
        with pytest.raises(RuntimeError, match='interruption'):
            ingest_file(path, database)
    clean_publication(database)
    recovered = ingest_file(path, database)
    assert recovered['rejected_rows'] == 1
    with psycopg.connect(database) as conn:
        before = conn.execute('SELECT last_publication_id FROM analytics.publication_state').fetchone()[0]
    with pytest.raises(psycopg.Error, match='rejected-row fraction'):
        publish(database)
    with psycopg.connect(database) as conn:
        assert conn.execute('SELECT last_publication_id FROM analytics.publication_state').fetchone()[0] == before
    # A documented policy exception can then publish and reconcile the old ID.
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE ops.quality_policy SET max_rejected_fraction=1 WHERE policy_name='transaction_files'")
    assert publish(database)['status'] == 'published'
    assert verifier.verify(database, 5)['status'] == 'passed'


@pytest.mark.parametrize('table', ['file_row_reconciliation', 'file_amount_reconciliation'])
def test_verifier_rejects_missing_reconciliation(database, table):
    import psycopg
    clean_publication(database)
    assert verifier.verify(database, 5)['status'] == 'passed'
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL('DELETE FROM analytics.{}').format(psycopg.sql.Identifier(table)))
    assert verifier.verify(database, 5)['status'] == 'failed'


def test_verifier_rejects_pending_correction(database, tmp_path):
    import psycopg
    clean_publication(database)
    with psycopg.connect(database) as conn:
        target, payload = conn.execute("SELECT raw_record_id, payload FROM raw.transaction_record WHERE validation_status='accepted' ORDER BY raw_record_id LIMIT 1").fetchone()
    from banking_pipeline.contract import KEYS
    values = [payload[k] for k in KEYS]
    values[7] = '123.00'
    path = write(tmp_path / 'corrections.csv', [[target, *values]], CORRECTION_HEADER)
    ingest_corrections(path, database)
    assert verifier.verify(database, 5)['status'] == 'failed'


def test_non_ascii_amounts_are_quarantined_without_blocking_promotion(database, tmp_path):
    rows = []
    for index, amount in enumerate(['12.00', '１２.００', '١٢.٠٠']):
        rows.append(['2022/09/01 09:00', '1', f'A{index}', '2', 'B', amount,
                     'US Dollar', amount, 'US Dollar', 'Wire', '0'])
    result = ingest_file(write(tmp_path / 'unicode_Trans.csv', rows), database)
    assert result['accepted_rows'] == 1
    assert result['rejected_rows'] == 2
    assert promote(database)['fact_inserted_rows'] == 1


def test_verifier_rejects_failed_correction_file(database, tmp_path):
    clean_publication(database)
    path = write(tmp_path / 'bad_corrections.csv', [[999999, 'bad-date']], CORRECTION_HEADER)
    with pytest.raises(ValueError, match='wrong_column_count'):
        ingest_corrections(path, database)
    report = verifier.verify(database, 5)
    assert report['status'] == 'failed'
    assert report['incomplete_correction_files'] == 1
