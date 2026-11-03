"""Build a self-contained PBIP semantic model from the verified aggregate snapshot.

No account identifiers, external credentials, local paths, or Power BI cache are
included. Power Query loads compressed snapshot rows and applies explicit types.
The resulting model still requires a native Power BI refresh/runtime check.
"""
from __future__ import annotations

import base64
from collections import defaultdict
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'pipeline/powerbi/upgrade'
if not OUT.exists(): OUT = ROOT
MODEL = OUT / 'Banking_Analytics.SemanticModel'


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False)+'\n')


def m_query(names, rows, types):
    payload = json.dumps(rows,separators=(',',':'),ensure_ascii=False).encode()
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    encoded = base64.b64encode(compressor.compress(payload)+compressor.flush()).decode()
    chunks = [encoded[i:i+16000] for i in range(0,len(encoded),16000)]
    literals = ',\n        '.join(json.dumps(c) for c in chunks)
    columns = json.dumps(names,ensure_ascii=False).replace('[','{').replace(']','}')
    type_map = {'string':'type text','int64':'Int64.Type','boolean':'type logical','dateTime':'type date'}
    changes = ', '.join('{'+json.dumps(n)+', '+type_map[t]+'}' for n,t in zip(names,types))
    return '\n'.join([
      'let', '    Encoded = Text.Combine({'+literals+'}),',
      '    Data = Json.Document(Binary.Decompress(Binary.FromText(Encoded, BinaryEncoding.Base64), Compression.Deflate)),',
      '    Rows = Table.FromRows(Data, '+columns+'),',
      '    Selected = Table.SelectColumns(Rows, '+columns+'),',
      '    Typed = Table.TransformColumnTypes(Selected, {'+changes+'}, "en-US")',
      'in', '    Typed'])


def table(name, columns, rows, hidden_columns=False, description=''):
    names = [c[0] for c in columns]
    types = [c[1] for c in columns]
    cols = []
    for n,t in columns:
        c = {'name':n,'dataType':t,'sourceColumn':n,'summarizeBy':'none',
             'isHidden':hidden_columns}
        if t == 'int64': c['formatString'] = '#,0'
        if t == 'dateTime':
            c['formatString'] = 'dd MMM yyyy'
            c['annotations'] = [{'name':'UnderlyingDateTimeDataType','value':'Date'}]
        cols.append(c)
    return {'name':name,'description':description,'columns':cols,
      'partitions':[{'name':name,'mode':'import','source':{'type':'m','expression':m_query(names,rows,types).splitlines()}}]}


MEASURES = [
 ('Transaction Count', 'SUM(FactDaily[Transactions])', '#,0', 'Activity', 'Complete published daily fact, not the detail sample.'),
 ('Risk Alert Count', 'SUM(FactDaily[Alerts])', '#,0', 'Activity', 'Distinct transactions with rule score at least two.'),
 ('Alert Rate', 'DIVIDE([Risk Alert Count], [Transaction Count])', '0.00%', 'Activity', 'Numerator and denominator share the current date/currency/format context.'),
 ('Synthetic Label Count', 'SUM(FactDaily[Synthetic labels])', '#,0', 'Evaluation', 'Synthetic answer-key labels; not verified real crime.'),
 ('Previous Day Transactions', '''VAR CurrentDate = SELECTEDVALUE(DimDate[Date])
RETURN IF(NOT ISBLANK(CurrentDate), CALCULATE([Transaction Count], REMOVEFILTERS(DimDate), DimDate[Date] = CurrentDate - 1))''', '#,0', 'Activity', 'Returns blank if there is no single current date or no preceding observation.'),
 ('Daily Change', 'IF(NOT ISBLANK([Previous Day Transactions]), [Transaction Count] - [Previous Day Transactions])', '#,0;-#,0', 'Activity', 'Daily comparison at a single event date; preserves the other filters.'),
 ('Daily Change Percent', 'DIVIDE([Daily Change], [Previous Day Transactions])', '0.0%;-0.0%', 'Activity', 'Blank when the prior day is unavailable or zero.'),
 ('Selected Format Share', 'DIVIDE([Transaction Count], CALCULATE([Transaction Count], ALLSELECTED(DimFormat[Payment format])))', '0.0%', 'Activity', 'Share within the externally selected formats, retaining other dimensions.'),
 ('High Amount Hits', 'SUM(FactDaily[High amount hits])', '#,0', 'Rules', 'Transactions meeting the high-amount rule; flags can overlap.'),
 ('High Velocity Hits', 'SUM(FactDaily[High velocity hits])', '#,0', 'Rules', 'Transactions meeting the high-hourly-velocity rule; flags can overlap.'),
 ('Repeated Counterparty Hits', 'SUM(FactDaily[Repeat counterparty hits])', '#,0', 'Rules', 'Includes one-point repeated-counterparty signals below the alert threshold.'),
 ('Rule Hits', '''SWITCH(SELECTEDVALUE(DimRule[Rule]),
    "High amount", [High Amount Hits],
    "High hourly velocity", [High Velocity Hits],
    "Repeated counterparty", [Repeated Counterparty Hits],
    BLANK())''', '#,0', 'Rules', 'Intentionally disconnected rule selector; never sum these counts as distinct alerts.'),
 ('Source Rows', 'SUM(FileQuality[Source rows])', '#,0', 'Quality', 'All selected source files; event-date/format slicers do not apply.'),
 ('Accepted Rows', 'SUM(FileQuality[Accepted rows])', '#,0', 'Quality', 'File acceptance count, separate from event-date-filtered transaction count.'),
 ('Rejected Rows', 'SUM(FileQuality[Rejected rows])', '#,0', 'Quality', 'Invalid rejects; duplicate candidates are counted separately.'),
 ('Duplicate Candidates', 'SUM(FileQuality[Duplicate candidates])', '#,0', 'Quality', 'Excluded from the published transaction fact.'),
 ('Row Balance Variance', '[Source Rows] - [Accepted Rows] - [Rejected Rows] - [Duplicate Candidates]', '#,0', 'Quality', 'Zero is expected; missing data is separately checked by Quality Status.'),
 ('Reconciliation Failures', 'SUM(CurrencyReconciliation[Failure count])', '#,0', 'Quality', 'Counts exact PostgreSQL failure flags before aggregation; opposing deltas cannot cancel.'),
 ('Quality Status', '''VAR FilesPresent = COUNTROWS(FileQuality)
VAR CurrencyRows = CALCULATE(COUNTROWS(CurrencyReconciliation), REMOVEFILTERS(DimCurrency))
VAR AllFailures = CALCULATE([Reconciliation Failures], REMOVEFILTERS(DimCurrency))
VAR BadFiles = COUNTROWS(FILTER(FileQuality, NOT(FileQuality[Row balance OK])))
RETURN IF(FilesPresent = 0 || CurrencyRows = 0, "NO DATA",
    IF([Row Balance Variance] = 0 && AllFailures = 0 && BadFiles = 0, "PASS", "CHECK"))''', None, 'Quality', 'Overall selected-file status; currency slicers cannot hide another currency failure.'),
 ('Detail Sample Rows', 'COUNTROWS(AlertSample)', '#,0', 'Sample', 'Bounded highest-score sample; never a population denominator.'),
 ('Detail Sample Note', '"Illustrative sample: " & FORMAT([Detail Sample Rows], "#,0") & " rows in the current context. Full alert workload is " & FORMAT([Risk Alert Count], "#,0") & "."', None, 'Sample', 'The sample is intentionally nonrepresentative and may contain no rows for a valid selection.'),
 ('Publication', '"Publication " & FORMAT(MAX(Snapshot[Publication ID]), "0") & " | " & SELECTEDVALUE(Snapshot[Published at UTC]) & " | static verified snapshot"', None, 'Provenance', 'Publication time is UTC; event timestamps are not assigned a timezone.'),
 ('Selected Period', 'FORMAT(MIN(DimDate[Date]), "dd MMM yyyy") & " to " & FORMAT(MAX(DimDate[Date]), "dd MMM yyyy")', None, 'Provenance', 'Current date selection.'),
]


def main():
    src = OUT/'data/snapshot.json'
    doc = json.loads(src.read_text())
    doc['detail_columns'][2] = 'Event time (source)'
    src.write_text(json.dumps(doc,separators=(',',':'))+'\n')
    daily = doc['daily']
    dates = sorted({r[0] for r in daily})
    start,end = date.fromisoformat(dates[0]),date.fromisoformat(dates[-1])
    date_rows = [[(start+timedelta(days=i)).isoformat()] for i in range((end-start).days+1)]
    currencies = sorted({r[1] for r in daily})
    formats = sorted({r[2] for r in daily})
    columns = list(zip(doc['daily_columns'],['dateTime','string','string']+['int64']*6))
    tables = [
      table('DimDate',[('Date','dateTime')],date_rows),
      table('DimCurrency',[('Currency','string')],[[c] for c in currencies]),
      table('DimFormat',[('Payment format','string')],[[c] for c in formats]),
      table('DimFile',[('File key','int64'),('Dataset','string')],[[r[0],'IBM AML HI-Small'] for r in doc['files']]),
      table('DimRule',[('Rule','string')],[[r] for r in ['High amount','High hourly velocity','Repeated counterparty']],description='Disconnected selector for the Rule Hits measure; no relationship is intended.'),
      table('FactDaily',columns,daily,True,'One row per event date / payment currency / payment format. Full source daily fact aggregated across sender banks without a row limit.'),
      table('FileQuality',list(zip(doc['file_columns'],['int64']*8+['boolean'])),doc['files'],True,'One row per source file. No event-date relationship.'),
      table('CurrencyReconciliation',list(zip(doc['reconciliation_columns'],['int64','string']+['string']*6+['int64','string'])),doc['reconciliation'],False,'One row per file/currency. Monetary values are exact SQL decimal text; no cross-currency sum.'),
      table('AlertSample',list(zip(doc['detail_columns'],['string','dateTime','string','string','string','string','int64','string'])),doc['detail'],False,'Up to three highest-rule-score alerts per date/currency. Nonrepresentative bounded detail sample.'),
      table('Snapshot',[('Publication ID','int64'),('Published at UTC','string')],[[doc['publication']['publication_id'],doc['publication']['published_at_utc']]],True),
    ]
    for t in tables:
        for c in t['columns']:
            if c['name'] in ['Bank key','File key']: c['isHidden']=True
    fact = next(t for t in tables if t['name']=='FactDaily')
    fact['measures'] = []
    for n,e,f,folder,description in MEASURES:
        m={'name':n,'expression':e.splitlines(),'displayFolder':folder,'description':description}
        if f: m['formatString']=f
        fact['measures'].append(m)
    rel=[]
    def relate(fact,col,dim,to=None):
        rel.append({'name':str(uuid.uuid5(uuid.NAMESPACE_URL,f'{fact}.{col}:{dim}.{to or col}')),
          'fromTable':fact,'fromColumn':col,'fromCardinality':'many',
          'toTable':dim,'toColumn':to or col,'toCardinality':'one',
          'crossFilteringBehavior':'oneDirection','isActive':True})
    for fact in ['FactDaily','AlertSample']:
        for col,dim in [('Date','DimDate'),('Currency','DimCurrency'),('Payment format','DimFormat')]: relate(fact,col,dim)
    for fact in ['FileQuality','CurrencyReconciliation']: relate(fact,'File key','DimFile')
    relate('CurrencyReconciliation','Currency','DimCurrency')
    model={'name':'Banking_Analytics','compatibilityLevel':1600,
      'model':{'culture':'en-US','defaultPowerBIDataSourceVersion':'powerBI_V3',
      'sourceQueryCulture':'en-US','tables':tables,'relationships':rel,
      'annotations':[{'name':'__PBI_TimeIntelligenceEnabled','value':'0'},
       {'name':'SnapshotSHA256','value':hashlib.sha256(src.read_bytes()).hexdigest()},
       {'name':'RuntimeVerification','value':'Power BI Desktop refresh and render pending; no service deployment claimed.'}]}}
    write(MODEL/'model.bim',model)
    write(MODEL/'definition.pbism',{'$schema':'https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json','version':'1.0','settings':{}})
    write(MODEL/'.platform',{'$schema':'https://developer.microsoft.com/json-schemas/fabric/gitIntegration/platformProperties/2.0.0/schema.json',
      'metadata':{'type':'SemanticModel','displayName':'Banking Analytics'},
      'config':{'version':'2.0','logicalId':str(uuid.uuid5(uuid.NAMESPACE_URL,'tarik-banking-semanticmodel-upgrade'))}})
    dax='\n\n'.join('// '+description+'\n'+n+' =\n'+e for n,e,f,folder,description in MEASURES)
    (OUT/'Measures.dax').write_text(dax+'\n')
    (OUT/'PowerQuery.m').write_text('\n\n'.join('// '+t['name']+'\n'+'\n'.join(t['partitions'][0]['source']['expression']) for t in tables)+'\n')
    grouped=defaultdict(lambda:[0,0])
    for r in daily: grouped[r[0]][0]+=r[3];grouped[r[0]][1]+=r[4]
    tail=sum(v[0] for d,v in grouped.items() if d>='2022-09-11')
    evidence={'source_snapshot_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),
      'controls':doc['controls'],'daily':[{'date':d,'transactions':v[0],'alerts':v[1]} for d,v in sorted(grouped.items())],
      'late_period_transactions':tail,'detail_sample_rows':len(doc['detail']),
      'event_time_timezone':'unspecified','publication':doc['publication'],
      'power_bi_runtime_verified':False,'live_report_updated':False}
    write(OUT/'verification/data_checks.json',evidence)
    print(json.dumps({'model':str(MODEL),'tables':len(tables),'relationships':len(rel),
        'measures':len(MEASURES),'daily_fact_rows':len(daily),'detail_rows':len(doc['detail']),
        'late_period_transactions':tail,'model_bytes':(MODEL/'model.bim').stat().st_size}))


if __name__=='__main__': main()
