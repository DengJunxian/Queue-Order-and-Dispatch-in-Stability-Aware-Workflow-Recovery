"""Complete protocol-v2 result figures with explicit NA and source provenance."""
import hashlib
import json
import os
import sys
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR','/private/tmp/cscwd2-mpl-cache')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump

BLUE='#0072B2';RED='#D55E00';BLACK='#222222'


def main():
    folder=ROOT/'formal_v2/reports';figdir=folder/'figures';figdir.mkdir(parents=True,exist_ok=True)
    frozen=json.loads((ROOT/'results/g2_v2_20261025/statistics.json').read_text());extra=json.loads((folder/'reporting_statistics.json').read_text())
    records=[];comparators=('PoolMinAWCT10','BudgetHEFT10')
    def export(fig,name,caption,alt):
        for ext in ('pdf','svg','png'):fig.savefig(figdir/f'{name}.{ext}',dpi=300,facecolor='white',transparent=False)
        with Image.open(figdir/f'{name}.png') as im:im.convert('RGB').save(figdir/f'{name}.png',dpi=(300,300))
        page=PdfReader(figdir/f'{name}.pdf').pages[0]
        for font in page['/Resources']['/Font'].get_object().values():
            obj=font.get_object()
            for child in obj.get('/DescendantFonts',[obj]):
                descriptor=child.get_object()['/FontDescriptor'].get_object();assert any(k in descriptor for k in ('/FontFile','/FontFile2','/FontFile3'))
        sources=['results/g2_v2_20261025/statistics.json','formal_v2/reports/reporting_statistics.json','formal_v2/reports/data/paired_effects.csv','formal_v2/reports/audit_summary.json']
        records.append({'name':name,'caption':caption,'alt':alt,'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},
            'exports_sha256':{e:hashlib.sha256((figdir/f'{name}.{e}').read_bytes()).hexdigest() for e in ('pdf','svg','png')},
            'page_mm':[float(page.mediabox.width)*25.4/72,float(page.mediabox.height)*25.4/72],'pdf_fonts_embedded':True,'png_mode':'RGB','png_dpi':300})
        plt.close(fig)
    def forest(labels,stats,title,name,caption,alt,height=110):
        fig,axes=plt.subplots(1,2,figsize=(180/25.4,height/25.4),layout='constrained')
        for j,key in enumerate(('cdi','relative_awct')):
            ax=axes[j];factor=100 if j else 1
            for c,(comp,color,marker) in enumerate(zip(comparators,(BLUE,RED),('o','s'))):
                for i,g in enumerate(stats):
                    v=g[comp][key];p=v['point'];ci=v['ci95'];y=i+(-.12 if c==0 else .12)
                    if p is None:ax.text(0,y,'NA',va='center',fontsize=7,color=color)
                    elif ci is None:
                        ax.plot(p*factor,y,marker=marker,color=color,markersize=4);ax.annotate('CI NA',(p*factor,y),xytext=(4,0),textcoords='offset points',fontsize=7)
                    else:
                        ax.plot([ci[0]*factor,ci[1]*factor],[y,y],color=color,linewidth=1)
                        ax.plot([ci[0]*factor,ci[1]*factor],[y,y],linestyle='none',marker='|',color=color,markersize=7)
                        ax.plot(p*factor,y,marker=marker,color=color,markersize=4)
                ax.plot([],[],color=color,marker=marker,linestyle='none',label='vs '+comp)
            ax.axvline(0,color=BLACK,linewidth=.8)
            if j:ax.axvline(5,color=BLACK,linewidth=.8,linestyle='--')
            ax.set_yticks(range(len(labels)),labels if j==0 else ['']*len(labels));ax.invert_yaxis();ax.margins(x=.15,y=.3)
            ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True);ax.spines[['top','right']].set_visible(False)
            ax.set_xlabel('CDI difference (BudgetSelect - comparator)' if j==0 else 'Paired relative AWCT difference (%)')
        axes[0].legend(loc='lower left',frameon=False,fontsize=7)
        fig.suptitle(title,fontsize=10,fontweight='bold');export(fig,name,caption,alt)
    with plt.rc_context({'font.family':'DejaVu Sans','font.size':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':8,'pdf.fonttype':42,'svg.fonttype':'none'}):
        stats=[{c:frozen['primary'][c]['overall'] for c in comparators}]+[{c:frozen['primary'][c]['mixes'][m] for c in comparators} for m in 'ABC']
        forest(['Overall (1,440)','Mix A (480)','Mix B (480)','Mix C (480)'],stats,'Frozen v2 primary contrasts | 60 root blocks','fig1_primary',
            'Both predeclared BudgetSelect10 comparisons overall and in every Mix. Points and two-sided percentile 95% intervals use 5000 common-root bootstrap draws, seed83000. '+
            'Negative CDI differences favor BudgetSelect; positive AWCT differences are completion costs. The 5% dashed line is the research tolerance, evaluated using the one-sided upper95 bound in the tables. '+
            'CDI NA counts and draw applicability remain in the source table; an undefined interval is shown as CI NA. The 60 blocks vary the environment on six fixed unseen topology groups.',
            'Paired CDI and relative AWCT differences show both frozen comparators, overall and by Mix, with zero and research-budget references.')
        labels=['Work CV = 0.1','Work CV = 0.3','Control delay = 0.1 pbar'];variants=('cv0.1','cv0.3','control_delay')
        forest(labels,[{c:frozen['robustness'][v][c] for c in comparators} for v in variants],
            'Frozen v2 robustness | 10 root blocks, 60 scenarios per condition','fig2_robustness',
            'All mandatory perturbations on the fixed matched subset: first10 roots, three Mixes, two CCR levels, four nodes and failure0.6 of matched actual no-fault makespan. '+
            'Each condition retains all methods and uses the same frozen root bootstrap. Shared work-error fields are paired across methods. Control delay is a common waiting sensitivity; measured algorithm wall time is not injected. '+
            'The dashed 5% line repeats the primary research tolerance for context.',
            'Both primary comparisons are retained under two work-error levels and common control delay; missing intervals remain explicitly labelled.',100)
        fig,axes=plt.subplots(1,2,figsize=(180/25.4,105/25.4),layout='constrained');tags=['0','0.05','0.1','0.2','0.5','1']
        for j,key in enumerate(('cdi','relative_awct')):
            ax=axes[j];factor=100 if j else 1
            for k,(base,color,marker) in enumerate(zip(('PoolMinAWCT','BudgetHEFT'),(BLUE,RED),('o','s'))):
                for i,tag in enumerate(tags):
                    result=extra['supplemental']['theta0.1'][base+'10'] if tag=='0.1' else frozen['budget_sensitivity'][tag][base]
                    v=result[key];p=v['point'];ci=v['ci95'];x=i+(-.1 if k==0 else .1)
                    if p is None:ax.text(x,0,'NA',rotation=90,color=color,fontsize=7)
                    elif ci is None:ax.plot(x,p*factor,marker=marker,color=color);ax.annotate('CI NA',(x,p*factor),fontsize=6)
                    else:
                        ax.plot([x,x],[ci[0]*factor,ci[1]*factor],color=color,linewidth=1)
                        ax.plot([x,x],[ci[0]*factor,ci[1]*factor],linestyle='none',marker='_',color=color,markersize=7)
                        ax.plot(x,p*factor,marker=marker,color=color,markersize=4)
                ax.plot([],[],color=color,marker=marker,linestyle='none',label='vs '+base)
            ax.axhline(0,color=BLACK,linewidth=.8);ax.axvline(2,color=BLACK,linewidth=.7,linestyle=':');ax.set_xticks(range(6),tags)
            ax.set(xlabel='Optional assignment budget theta (categorical levels)',ylabel='CDI difference' if not j else 'Paired relative AWCT difference (%)')
            ax.grid(axis='y',alpha=.18);ax.spines[['top','right']].set_visible(False)
        axes[0].legend(frameon=False,fontsize=7);fig.suptitle('All frozen budget levels | 10 root blocks, matched 60 scenarios',fontsize=10,fontweight='bold')
        export(fig,'fig3_budget','All six predeclared theta levels on the same60-case no-error/no-delay subset. Theta0.10 is reused from main; other rows are frozen sensitivity jobs. '+
               'The categorical axis shows every level without interpolation, and the dotted reference identifies the primary theta0.10. '+
               'At theta0/1 the BudgetHEFT label reuses QueueRepair0/B2; aliases add no independent timing or scientific samples. Intervals retain the frozen NA rule.',
               'CDI and AWCT effects at all six optional reassignment budgets, compared with same-budget pool-AWCT and budget-HEFT controls.')
        names=['B0','B1','B2','LegacySAIL','QueueRepair0','BudgetHEFT10','BudgetSelect10','PoolMinAWCT10','B0AssignmentReorder']
        summaries={r['method']:r for r in extra['method_summary'] if r['variant']=='main'}
        fig,axes=plt.subplots(1,3,figsize=(180/25.4,130/25.4),layout='constrained');y=np.arange(len(names))
        for j,(field,title) in enumerate((('mean_Churn','Mean optional\nassignment changes'),('mean_order_disturbance','Mean retained-pair\ninversions'))):
            ax=axes[j]
            for i,n in enumerate(names):
                v=summaries[n][field]
                if v is None:ax.text(0,i,'NA',va='center')
                else:ax.plot(v,i,'o',color=BLUE);ax.annotate(f'{100*v:.1f}%',(v,i),xytext=(5,0),textcoords='offset points',va='center',fontsize=7)
            ax.set(yticks=y,yticklabels=names if j==0 else ['']*len(names),xlim=(-.02,1.02),title=title,xlabel='Fraction');ax.invert_yaxis();ax.grid(axis='x',alpha=.18)
        ax=axes[2]
        for i,n in enumerate(names):
            r=summaries[n]
            for field,offset,color,marker in (('full_apply_p50_seconds',-.1,BLUE,'o'),('full_apply_p95_seconds',.1,RED,'s')):
                if r[field] is not None:ax.plot(r[field]*1000,i+offset,marker=marker,color=color)
        ax.plot([],[],color=BLUE,marker='o',linestyle='none',label='p50');ax.plot([],[],color=RED,marker='s',linestyle='none',label='p95')
        ax.set(yticks=y,yticklabels=['']*len(names),xlabel='Full application wall time (ms)',title='Descriptive\nlocal timings');ax.invert_yaxis();ax.set_xlim(left=0);ax.grid(axis='x',alpha=.18);ax.legend(frameon=False,fontsize=7)
        for ax in axes:ax.spines[['top','right']].set_visible(False)
        fig.suptitle('All main methods | 1,440 scenarios per method',fontsize=10,fontweight='bold')
        export(fig,'fig4_disturbance_cost','All nine main configurations. Churn counts optional assignment changes divided by original Q, excluding compulsory F moves. '+
               'Order disturbance conditions on Q\\F tasks retained on their original healthy node; its denominator and NA counts are retained and differ when tasks move. '+
               'The first two panels are per-scenario descriptive means, not independent-task estimates. Timings cover the entire application call in the actual single-process batch; p50/p95 are descriptive quantiles, not confidence limits. '+
               'Method calls and cases share root blocks; other host activity was not controlled.',
               'Assignment changes, conditional queue-order inversions and full application wall time are displayed separately for every main configuration.')
    dump(figdir/'manifest.json',{'figures':records,'visual_inspection':'pending','publisher_compliance_claimed':False,'destination':'research stage report; final CSCWD layout remains a later check'})
    (figdir/'captions_and_alt.md').write_text('\n\n'.join('**'+r['name']+'**\n\n'+r['caption']+'\n\nAlt: '+r['alt'] for r in records)+'\n')


if __name__=='__main__':main()
