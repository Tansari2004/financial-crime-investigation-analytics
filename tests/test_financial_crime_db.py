"""Run only against a disposable PostgreSQL server with CREATEDB permission."""
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

ROOT=Path(__file__).resolve().parents[1]
DSN=os.environ.get('FINANCIAL_CRIME_TEST_DATABASE_URL')
pytestmark=pytest.mark.skipif(not DSN,reason='set FINANCIAL_CRIME_TEST_DATABASE_URL')
PSQL=os.environ.get('PSQL','psql')


@pytest.fixture
def database():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict,make_conninfo
    name='crime_'+uuid4().hex
    with psycopg.connect(DSN,autocommit=True) as conn:
        conn.execute(psycopg.sql.SQL('CREATE DATABASE {}').format(psycopg.sql.Identifier(name)))
    options=conninfo_to_dict(DSN);options['dbname']=name;dsn=make_conninfo(**options)
    try:
        with psycopg.connect(dsn,autocommit=True) as conn:conn.execute((ROOT/'sql/schema.sql').read_text())
        yield dsn
    finally:
        with psycopg.connect(DSN,autocommit=True) as conn:
            conn.execute(psycopg.sql.SQL('DROP DATABASE {} WITH (FORCE)').format(psycopg.sql.Identifier(name)))


def insert(conn,when,bank,account,currency,amount,label=0):
    return conn.execute('INSERT INTO transactions(transaction_time,from_bank,from_account,to_bank,to_account,amount_received,receiving_currency,amount_paid,payment_currency,payment_format,is_laundering) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING transaction_id',
                        (when,bank,account,'receiver','B',amount,currency,amount,currency,'Wire',label)).fetchone()[0]


def run_sql(dsn,path,cwd):
    return subprocess.run([PSQL,'-X','-v','ON_ERROR_STOP=1','-d',dsn,'-f',str(ROOT/path)],cwd=cwd,text=True,capture_output=True)


def test_history_excludes_same_day_future_other_bank_and_currency(database):
    import psycopg
    with psycopg.connect(database,autocommit=True) as c:
        insert(c,'2022-09-01 09:00','1','A','USD','10')
        insert(c,'2022-09-01 12:00','1','A','USD','20')
        insert(c,'2022-09-01 09:00','2','A','USD','10000')
        insert(c,'2022-09-01 09:00','1','A','EUR','20000')
        target=insert(c,'2022-09-02 08:00','1','A','USD','30')
        insert(c,'2022-09-02 23:00','1','A','USD','50000')
        insert(c,'2022-09-03 08:00','1','A','USD','99999')
        c.execute((ROOT/'sql/model_features.sql').read_text().split('-- Export from psql')[0])
        count,average=c.execute('SELECT prior_transaction_count,prior_average_amount FROM model_features WHERE transaction_id=%s',(target,)).fetchone()
    assert count==2 and average==15


@pytest.mark.parametrize('kind',['missing','orphan','wrong_split'])
def test_bad_score_import_is_an_error_and_rolls_back(database,tmp_path,kind):
    import psycopg
    with psycopg.connect(database,autocommit=True) as c:
        insert(c,'2022-09-09','1','A','USD','10')
        insert(c,'2022-09-10','1','A','USD','20')
    p=tmp_path/'data/processed';p.mkdir(parents=True)
    rows=[[1,.7,'test','test'],[2,.3,'test','test']]
    if kind=='missing':rows=rows[:1]
    if kind=='orphan':rows[-1][0]=999
    if kind=='wrong_split':rows[-1][2]='train'
    with (p/'model_scores.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['transaction_id','review_score','data_split','model_version']);w.writerows(rows)
    result=run_sql(database,'sql/model_scores.sql',tmp_path)
    assert result.returncode!=0,result.stdout
    with psycopg.connect(database) as c:assert c.execute("SELECT to_regclass('model_scores')").fetchone()[0] is None


def test_training_scoring_loading_and_explanation_smoke(database,tmp_path):
    import psycopg
    from financial_crime.explain_cases import explain
    processed=tmp_path/'data/processed';processed.mkdir(parents=True)
    with psycopg.connect(database,autocommit=True) as c:
        for day,count in [(1,60),(8,20),(9,20)]:
            for i in range(count):insert(c,f'2022-09-{day:02d} {i%24:02d}:00',str(i%3),f'A{i%5}','USD',str(i+1),int(i%7==0))
        c.execute((ROOT/'sql/model_features.sql').read_text().split('-- Export from psql')[0])
        with c.cursor() as cursor:
            with cursor.copy('COPY model_features TO STDOUT WITH (FORMAT csv, HEADER true)') as data:
                with (processed/'model_features.csv').open('wb') as f:
                    for block in data:f.write(block)
    result=subprocess.run([sys.executable,'-m','financial_crime.train_model','--epochs','1','--chunk-size','30'],cwd=tmp_path,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    metrics=json.loads((tmp_path/'reports/model_metrics.json').read_text())
    assert metrics['train']['rows']==60 and metrics['validation']['rows']==20 and metrics['test']['rows']==20
    assert metrics['ranking_tie_policy']=='review_score descending, transaction_id ascending'
    assert run_sql(database,'sql/model_scores.sql',tmp_path).returncode==0
    assert run_sql(database,'sql/dashboard_export.sql',tmp_path).returncode==0
    frame=pd.read_csv(processed/'dashboard_cases_raw.csv')
    with np.load(tmp_path/'models/numpy_logistic_v1.npz',allow_pickle=False) as model:
        from financial_crime.train_model import numeric_matrix
        features=pd.read_csv(processed/'model_features.csv',parse_dates=['transaction_time'])
        train=features.loc[features.transaction_time < pd.Timestamp('2022-09-08')]
        assert np.allclose(model['mean'],numeric_matrix(train).mean(axis=0))
        explained=explain(frame,model)
    assert len(explained)==20 and explained.score_reconstruction_gap.max()<1e-5
    assert set(explained.data_split)=={'test'}
