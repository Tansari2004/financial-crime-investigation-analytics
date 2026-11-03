"""Create three PBIR analysis pages plus a bounded-sample drillthrough page.

Uses Microsoft's scaffold shell and native visual contracts. No screenshot is
presented as a rendered Power BI report until the native runtime is checked.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'pipeline/powerbi/upgrade'
if not OUT.exists():OUT=ROOT
REPORT=OUT/'Banking_Analytics.Report'
DEF=REPORT/'definition'
VSCHEMA='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.9.0/schema.json'
PSCHEMA='https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json'
BLUE='#1764A0'; INK='#17324D'; MUTED='#536579'; LIGHT='#E9F1F8'


def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n')


def uid(s): return hashlib.sha256(s.encode()).hexdigest()[:20]
def lit(v):
    val='true' if v is True else 'false' if v is False else str(v)+'D' if isinstance(v,(int,float)) else "'"+v.replace("'","''")+"'"
    return {'expr':{'Literal':{'Value':val}}}
def color(v): return {'solid':{'color':lit(v)}}
def props(p,selector=False):
    d={'properties':p}
    if selector: d['selector']={'id':'default'}
    return [d]
def field(t,c,measure=False):
    return {'Measure' if measure else 'Column':{'Expression':{'SourceRef':{'Entity':t}},'Property':c}}
def projection(t,c,measure=False):
    return {'field':field(t,c,measure),'queryRef':t+'.'+c,'nativeQueryRef':c}
def ms(name): return projection('FactDaily',name,True)
def col(t,c): return projection(t,c)
def role(items): return {'projections':items}
def chrome(title=None):
    d={'background':props({'show':lit(False)}),'border':props({'show':lit(False)}),
       'padding':props({p:lit(8) for p in ['top','bottom','left','right']})}
    if title: d['title']=props({'show':lit(True),'text':lit(title),'fontSize':lit(12),'fontColor':color(INK)})
    return d


class Page:
    def __init__(self,name,title,subtitle,hidden=False):
        self.id=uid(name);self.count=0;self.visuals=[]
        self.path=DEF/'pages'/self.id
        self.page={'$schema':PSCHEMA,'name':self.id,'displayName':title,
          'displayOption':'FitToPage','height':900,'width':1440}
        if hidden:self.page['visibility']='HiddenInViewMode'
        self.text('title',title,24,18,1392,48,28,INK)
        self.text('subtitle',subtitle,24,67,1392,30,13,MUTED)

    def add(self,key,visual,x,y,w,h):
        self.count+=1;n=uid(self.id+key)
        v={'$schema':VSCHEMA,'name':n,'position':{'x':x,'y':y,'z':self.count*1000,
          'tabOrder':self.count*1000,'width':w,'height':h},'visual':visual}
        write(self.path/'visuals'/n/'visual.json',v);self.visuals.append(v)
        return v

    def text(self,key,text,x,y,w,h,size=13,ink=MUTED):
        paras=[{'textRuns':[{'value':line,'textStyle':{'fontFamily':'Segoe UI','fontSize':str(size)+'px','color':ink}}],
          'horizontalTextAlignment':'left'} for line in text.split('\n')]
        vco=chrome();vco['padding']=props({p:lit(0) for p in ['top','bottom','left','right']})
        return self.add(key,{'visualType':'textbox','objects':{'general':props({'paragraphs':paras})},
          'visualContainerObjects':vco},x,y,w,h)

    def slicer(self,key,t,c,x,y,w):
        return self.add(key,{'visualType':'slicer','query':{'queryState':{'Values':role([col(t,c)])}},
          'objects':{'data':props({'mode':lit('Dropdown')}),'header':props({'show':lit(True),'text':lit(c)})},
          'visualContainerObjects':chrome()},x,y,w,80)

    def filters(self):
        self.slicer('date','DimDate','Date',24,102,432)
        self.slicer('currency','DimCurrency','Currency',480,102,432)
        self.slicer('format','DimFormat','Payment format',936,102,480)

    def cards(self,key,measures,y=202):
        objects={
          'value':props({'fontSize':lit(30),'fontColor':color(INK),'labelDisplayUnits':lit(1)},True),
          'label':props({'fontSize':lit(11),'fontColor':color(MUTED)},True),
          'padding':props({'paddingUniform':lit(8)},True),
          'layout':props({'orientation':lit(0),'rowCount':lit(1),'columnCount':lit(len(measures)),
            'autoGrid':lit(False),'paddingUniform':lit(0)},True)}
        return self.add(key,{'visualType':'cardVisual','query':{'queryState':{'Data':role([ms(m) for m in measures])}},
          'objects':objects,'visualContainerObjects':chrome()},24,y,1392,104)

    def chart(self,key,kind,t,c,measure,x,y,w,h,title,ascending=False,tooltips=None):
        q={'Category':role([col(t,c)]),'Y':role([ms(measure)])}
        if tooltips:q['Tooltips']=role([ms(m) for m in tooltips])
        sortfield=field(t,c) if ascending else field('FactDaily',measure,True)
        return self.add(key,{'visualType':kind,'query':{'queryState':q,'sortDefinition':{
          'sort':[{'field':sortfield,'direction':'Ascending' if ascending else 'Descending'}]}},
          'objects':{'dataPoint':props({'defaultColor':color(BLUE)}),
            'legend':props({'show':lit(False)})},'visualContainerObjects':chrome(title)},x,y,w,h)

    def table(self,key,fields,x,y,w,h,title):
        return self.add(key,{'visualType':'tableEx','query':{'queryState':{'Values':role(fields)}},
          'objects':{'columnHeaders':props({'autoSizeColumnWidth':lit(True),'columnAdjustment':lit('growToFit'),
            'fontSize':lit(10),'backColor':color(LIGHT),'fontColor':color(INK)}),
            'values':props({'fontSize':lit(10),'backColorPrimary':color('#FFFFFF'),'backColorSecondary':color('#F5F8FB')}),
            'total':props({'totals':lit(False)})},'visualContainerObjects':chrome(title)},x,y,w,h)

    def footer(self):
        self.text('footer','IBM AML synthetic data | Publication 1 | 01 Oct 2026 03:33 UTC | Snapshot, not live bank activity',24,853,1392,26,11)

    def save(self):
        write(self.path/'page.json',self.page)
        for v in self.visuals:write(self.path/'visuals'/v['name']/'visual.json',v)


def main():
    # Remove only the empty initial scaffold page, if it is still empty.
    metadata=json.loads((DEF/'pages/pages.json').read_text())
    for n in metadata['pageOrder']:
        p=DEF/'pages'/n
        if p.exists() and not (p/'visuals').exists():
            (p/'page.json').unlink();p.rmdir()
    pages=[]
    overview=Page('overview','Transaction overview','Published activity across 18 event dates. Filter the complete population by date, currency and payment format.')
    overview.filters();overview.cards('headline',['Transaction Count','Risk Alert Count','Alert Rate'])
    overview.chart('daily','clusteredColumnChart','DimDate','Date','Transaction Count',24,326,880,386,
      'Daily published transactions',True,['Risk Alert Count','Alert Rate','Daily Change Percent'])
    overview.chart('formatmix','clusteredBarChart','DimFormat','Payment format','Transaction Count',928,326,488,386,
      'Payment-format mix',False,['Selected Format Share','Alert Rate'])
    overview.text('finding','Full-source finding: volume falls from 208,325 on 10 Sep to 396 on 11 Sep. SQL confirms the drop.\nThe final eight dates contain only 1,108 transactions; this is the supplied synthetic distribution, not evidence of a banking outage.',24,738,1392,76,14)
    overview.footer();overview.save();pages.append(overview)

    quality=Page('quality','Data quality and reconciliation','File-level checks cover the complete imported snapshot. Currency selection changes the detail table, not the source-file totals.')
    quality.slicer('currency','DimCurrency','Currency',24,102,432)
    quality.cards('quality',['Source Rows','Accepted Rows','Duplicate Candidates','Quality Status'])
    quality.table('recon',[col('CurrencyReconciliation',c) for c in ['Currency','Raw source total','Staged total',
      'Expected current total','Published total','Status']],24,330,1392,410,'Exact currency reconciliation | six-decimal source values')
    quality.text('qualitynote','The full run has zero invalid rejects and nine excluded duplicate candidates. These describe this run, not every possible input.\nAmounts remain separate by currency. PASS uses exact PostgreSQL checks; opposing discrepancies cannot cancel through a net sum.',24,766,1392,70,13)
    quality.footer();quality.save();pages.append(quality)

    risk=Page('risk','Alert workload','Rule-based review signals. Alert counts and rates describe workload; they are not confirmed fraud or calibrated probabilities.')
    risk.filters();risk.cards('workload',['Risk Alert Count','Alert Rate','Detail Sample Rows'])
    risk.chart('alertcount','clusteredBarChart','DimCurrency','Currency','Risk Alert Count',24,326,448,390,
      'Alert count by currency',False,['Transaction Count','Alert Rate'])
    risk.chart('alertrate','clusteredBarChart','DimCurrency','Currency','Alert Rate',496,326,448,390,
      'Alert rate by currency',False,['Transaction Count','Risk Alert Count'])
    risk.chart('rules','clusteredBarChart','DimRule','Rule','Rule Hits',968,326,448,390,
      'Triggered rules | overlapping counts')
    risk.text('finding','Full-source comparison: USD has the largest alert count; Saudi Riyal has the highest alert rate (16.04%, versus USD 15.20%).\nRight-click a currency bar to drill through to Alert sample details.\nRule counts overlap and include one-point signals below the alert threshold; they are not distinct alert totals.',24,742,1392,78,13)
    risk.footer();risk.save();pages.append(risk)

    detail=Page('detail','Alert sample details','Bounded illustration: up to three highest-score alerts per date/currency. The sample is nonrepresentative and never supplies the rate denominator.',True)
    filt='Filter'+uid('currency-drillthrough')+'0000'
    detail.page['filterConfig']={'filters':[{'name':filt,'field':field('DimCurrency','Currency'),
      'type':'Categorical','howCreated':'Drillthrough'}]}
    detail.page['pageBinding']={'name':'Pod','type':'Drillthrough','acceptsFilterContext':'Default','parameters':[{
      'name':'Param_'+filt,'boundFilter':filt,'fieldExpr':field('DimCurrency','Currency')}]}
    detail.filters();detail.cards('sample',['Risk Alert Count','Detail Sample Rows'])
    detail_table=detail.table('detail',[col('AlertSample',c) for c in ['Reference','Event time (source)','Currency',
      'Amount in currency','Payment format','Rule score','Triggered rules']],24,330,1392,430,'Sampled alert records | event timezone unspecified')
    detail_table['visual']['query']['sortDefinition']={'sort':[
      {'field':field('AlertSample','Rule score'),'direction':'Descending'},
      {'field':field('AlertSample','Event time (source)'),'direction':'Ascending'}]}
    detail.text('samplefoot','No account or original bank identifiers are included. A selection can have alerts but no sampled rows.\nHigh amount and high hourly velocity each contribute two points; repeated counterparty contributes one. Alert threshold: score 2 or higher.',24,780,1168,62,12)
    back=detail.add('back',{'visualType':'actionButton','objects':{
      'text':props({'show':lit(True),'text':lit('Back to alerts'),'fontSize':lit(12)}),
      'icon':props({'show':lit(False)})},'visualContainerObjects':{
      **chrome(),'visualLink':props({'show':lit(True),'type':lit('Back')})}},1216,785,200,48)
    detail.footer();detail.save();pages.append(detail)
    metadata['pageOrder']=[p.id for p in pages];metadata['activePageName']=overview.id
    write(DEF/'pages/pages.json',metadata)

    report=json.loads((DEF/'report.json').read_text())
    theme_name='TarikBanking-'+uid('theme-blue-white-v1')+'.json'
    theme={'name':theme_name,'dataColors':[BLUE,'#5BA6C9','#244E70','#91B9CF'],
      'background':'#FFFFFF','foreground':INK,'tableAccent':BLUE,
      'textClasses':{'label':{'fontFace':'Segoe UI','fontSize':11,'color':INK},
        'title':{'fontFace':'Segoe UI Semibold','fontSize':14,'color':INK},
        'callout':{'fontFace':'Segoe UI Semibold','fontSize':30,'color':INK}},
      'visualStyles':{'tableEx':{'*':{'columnHeaders':[{'autoSizeColumnWidth':True,'columnAdjustment':'growToFit'}]}}}}
    write(REPORT/'StaticResources/RegisteredResources'/theme_name,theme)
    report['themeCollection']['customTheme']={'name':theme_name,'type':'RegisteredResources',
      'reportVersionAtImport':{'visual':'2.9.0','report':'3.3.0','page':'2.1.0'}}
    report['resourcePackages']=[p for p in report['resourcePackages'] if p['name']!='RegisteredResources']
    report['resourcePackages'].append({'name':'RegisteredResources','type':'RegisteredResources','items':[{
      'name':theme_name,'path':theme_name,'type':'CustomTheme'}]})
    write(DEF/'report.json',report)
    layout={'pages':[{'name':p.page['displayName'],'id':p.id,'hidden':p.page.get('visibility') is not None,
      'visuals':[{'name':v['name'],'type':v['visual']['visualType'],**v['position']} for v in p.visuals]} for p in pages]}
    write(OUT/'verification/layout_manifest.json',layout)
    print(json.dumps({'visible_pages':3,'hidden_drillthrough_pages':1,
      'visuals':sum(len(p.visuals) for p in pages),'output':str(REPORT)}))


if __name__=='__main__':main()
