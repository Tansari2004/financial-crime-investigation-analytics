"""Offline data/model checks. These do not execute Power BI, M, or DAX."""
from __future__ import annotations

import base64
from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
import re
import zlib

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'pipeline/powerbi/upgrade'
if not OUT.exists():OUT=ROOT


def main():
    doc=json.loads((OUT/'data/snapshot.json').read_text())
    model=json.loads((OUT/'Banking_Analytics.SemanticModel/model.bim').read_text())['model']
    tables={t['name']:t for t in model['tables']}
    rows={};checks=[]
    def check(name,value):
        assert value,name
        checks.append({'check':name,'passed':True})
    for name,t in tables.items():
        expr='\n'.join(t['partitions'][0]['source']['expression'])
        raw=expr.split('Encoded = Text.Combine({',1)[1].split('}),',1)[0]
        chunks=re.findall(r'"([A-Za-z0-9+/=]+)"',raw)
        data=json.loads(zlib.decompress(base64.b64decode(''.join(chunks)),-15))
        names=[c['name'] for c in t['columns']]
        rows[name]=[dict(zip(names,row)) for row in data]
        check(f'{name}: row widths match source columns',all(len(r)==len(names) for r in data))
    check('embedded daily data exactly matches audited snapshot',
        [list(r.values()) for r in rows['FactDaily']]==doc['daily'])
    f=rows['FactDaily']
    totals={k:sum(r[k] for r in f) for k in ['Transactions','Alerts','Synthetic labels']}
    check('complete accepted population',totals['Transactions']==5078336)
    check('complete distinct alert count',totals['Alerts']==766725)
    check('synthetic labels retained as evaluation-only data',totals['Synthetic labels']==5177)
    check('complete daily aggregate, unique grain',len({(r['Date'],r['Currency'],r['Payment format']) for r in f})==len(f)==862)
    check('all 18 event dates retained',len({r['Date'] for r in f})==18)
    check('all currencies and formats retained',len(rows['DimCurrency'])==15 and len(rows['DimFormat'])==7)
    check('no source account or bank identifiers exported',
        not any(any(w in c['name'].lower() for w in ['account','bank']) for t in model['tables'] for c in t['columns']))
    for rel in model['relationships']:
        dim=[r[rel['toColumn']] for r in rows[rel['toTable']]]
        fact=[r[rel['fromColumn']] for r in rows[rel['fromTable']]]
        check(rel['fromTable']+'.'+rel['fromColumn']+': unique dimension and no orphan keys',
          len(dim)==len(set(dim)) and all(v in set(dim) for v in fact))
        check(rel['name']+': single-direction many-to-one',
          rel['fromCardinality']=='many' and rel['toCardinality']=='one' and rel['crossFilteringBehavior']=='oneDirection')
    check('quality facts are not linked to event dates',not any(
        r['fromTable'] in ['FileQuality','CurrencyReconciliation'] and r['toTable']=='DimDate' for r in model['relationships']))
    check('rule selector intentionally disconnected',not any(
        r['fromTable']=='DimRule' or r['toTable']=='DimRule' for r in model['relationships']))
    by_currency=defaultdict(lambda:[0,0]);by_day=defaultdict(int)
    for r in f:
        by_currency[r['Currency']][0]+=r['Transactions'];by_currency[r['Currency']][1]+=r['Alerts']
        by_day[r['Date']]+=r['Transactions']
    check('USD maximum alert count',max(by_currency,key=lambda c:by_currency[c][1])=='US Dollar')
    check('Saudi Riyal maximum alert rate',max(by_currency,key=lambda c:by_currency[c][1]/by_currency[c][0])=='Saudi Riyal')
    check('September drop matches database',by_day['2022-09-10']==208325 and by_day['2022-09-11']==396)
    check('all later dates retained, not truncated',sum(n for d,n in by_day.items() if d>='2022-09-11')==1108)
    check('rule signals bounded and alert union consistent',all(
        0<=r['Alerts']<=r['Transactions'] and max(r['High amount hits'],r['High velocity hits'])<=r['Alerts']<=r['High amount hits']+r['High velocity hits']
        and all(0<=r[k]<=r['Transactions'] for k in ['High amount hits','High velocity hits','Repeat counterparty hits']) for r in f))
    # Check representative and empty multi-dimensional selections using full facts.
    selections=[('2022-09-01','US Dollar','ACH'),('2022-09-11','Saudi Riyal',None),
      (None,'Canadian Dollar','Wire'),('2022-09-18','Euro',None),(None,'Not present',None)]
    reference=[]
    for d,c,p in selections:
        selected=[r for r in f if (d is None or r['Date']==d) and (c is None or r['Currency']==c) and (p is None or r['Payment format']==p)]
        tx=sum(r['Transactions'] for r in selected);alerts=sum(r['Alerts'] for r in selected)
        sample=[r for r in rows['AlertSample'] if (d is None or r['Date']==d) and (c is None or r['Currency']==c) and (p is None or r['Payment format']==p)]
        rate=alerts/tx if tx else None
        check(f'filter context {d}/{c}/{p}: valid rate and bounded sample',
          (rate is None or 0<=rate<=1) and len(sample)<=alerts)
        reference.append({'date':d,'currency':c,'format':p,'transactions':tx,'alerts':alerts,'rate':rate,'sample_rows':len(sample)})
    check('sample not mistaken for population',len(rows['AlertSample'])==455<totals['Alerts'])
    check('sample transaction references unique',len({r['Reference'] for r in rows['AlertSample']})==455)
    for r in rows['CurrencyReconciliation']:
        failure=int(Decimal(r['Raw staging delta'])!=0 or Decimal(r['Effective core delta'])!=0)
        check('exact reconciliation flag: '+r['Currency'],failure==r['Failure count'] and (r['Status']=='PASS')==(failure==0))
    # Opposing discrepancies are counted as failures even when their net is zero.
    bad=[Decimal('1.000001'),Decimal('-1.000001')]
    check('opposing deltas cannot hide reconciliation failures',sum(bad)==0 and sum(v!=0 for v in bad)==2)
    check('file source arithmetic',all(r['Source rows']==r['Accepted rows']+r['Rejected rows']+r['Duplicate candidates'] for r in rows['FileQuality']))
    checks_count_before_visuals=len(checks)
    report=OUT/'Banking_Analytics.Report'
    pages=json.loads((report/'definition/pages/pages.json').read_text())
    columns={n:{c['name'] for c in t['columns']} for n,t in tables.items()}
    measures={n:{m['name'] for m in t.get('measures',[])} for n,t in tables.items()}
    def walk(node):
        if isinstance(node,dict):
            for kind in ['Column','Measure']:
                if kind in node:
                    v=node[kind];t=v.get('Expression',{}).get('SourceRef',{}).get('Entity')
                    if t:check('visual field resolves: '+t+'.'+v['Property'],v['Property'] in (measures if kind=='Measure' else columns)[t])
            for v in node.values():walk(v)
        elif isinstance(node,list):
            for v in node:walk(v)
    visible=0
    for name in pages['pageOrder']:
        page_path=report/'definition/pages'/name
        page=json.loads((page_path/'page.json').read_text())
        visible+=page.get('visibility')!='HiddenInViewMode'
        visuals=[json.loads(p.read_text()) for p in (page_path/'visuals').glob('*/visual.json')]
        for v in visuals:
            pos=v['position'];check('visual fits page: '+v['name'],pos['x']>=0 and pos['y']>=0 and pos['x']+pos['width']<=page['width'] and pos['y']+pos['height']<=page['height'])
            walk(v)
        for i,a in enumerate(visuals):
            for b in visuals[i+1:]:
                a,bp=a,b['position'];ap=a['position']
                overlap=min(ap['x']+ap['width'],bp['x']+bp['width'])-max(ap['x'],bp['x'])>0 and min(ap['y']+ap['height'],bp['y']+bp['height'])-max(ap['y'],bp['y'])>0
                check('no visual overlap: '+a['name']+'/'+b['name'],not overlap)
        if page.get('pageBinding'):
            check('drillthrough retains extra filter context',page['pageBinding']['acceptsFilterContext']=='Default')
            check('drillthrough has a Back action',any('visualLink' in v['visual'].get('visualContainerObjects',{}) for v in visuals))
    check('three visible pages and one drillthrough',visible==3 and len(pages['pageOrder'])==4)
    result={'status':'passed','offline_checks':len(checks),'data_checks':checks_count_before_visuals,
      'reference_filter_cases':reference,'checks':checks,'power_bi_runtime_verified':False,
      'note':'Reference arithmetic and structural checks do not execute native DAX, M refresh, visual rendering or browser interactions.'}
    (OUT/'verification/offline_checks.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':'passed','offline_checks':len(checks),'data_checks':checks_count_before_visuals,
      'native_runtime_verified':False}))


if __name__=='__main__':main()
