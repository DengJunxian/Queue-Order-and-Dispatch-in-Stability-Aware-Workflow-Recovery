"""Research figures from complete P4 tables, with intervals and source provenance."""
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

FOLDER=ROOT/'reports/p4';FIG=FOLDER/'figures';BLUE='#0072B2';RED='#D55E00';GREEN='#009E73';BLACK='#222222'


def forest(axes,labels,stats,title,budget=False):
    for j,metric in enumerate(('cdi','relative_awct')):
        ax=axes[j];factor=100 if j else 1
        for i,s in enumerate(stats):
            v=s[metric];p=v['point'];ci=v['ci95'];color=BLUE if j==0 else RED
            if p is None:ax.text(0,i,'NA',va='center',color=BLACK);continue
            if ci is None:
                ax.plot(p*factor,i,marker='x',color=color);ax.annotate('CI undefined',(p*factor,i),xytext=(4,3),textcoords='offset points',fontsize=7)
            else:
                ax.errorbar(p*factor,i,xerr=np.array([[p-ci[0]],[ci[1]-p]])*factor,
                            fmt='o' if j==0 else 's',color=color,ecolor=color,capsize=3,markersize=4)
        ax.axvline(0,color=BLACK,linewidth=0.9)
        if budget and j:
            ax.axvline(5,color=BLACK,linewidth=0.9,linestyle='--',label='5% research budget')
            ax.legend(loc='lower right',frameon=False,fontsize=7)
        ax.set_yticks(range(len(labels)),labels if j==0 else ['']*len(labels));ax.invert_yaxis()
        ax.set_xlabel('CDI difference (SAIL - comparator)' if j==0 else 'Relative AWCT difference (%)')
        ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True);ax.margins(x=.16,y=.18)
        ax.spines[['top','right']].set_visible(False)
    axes[0].figure.suptitle(title,fontsize=10,fontweight='bold')


def export(fig,name,caption,alt,sources):
    FIG.mkdir(parents=True,exist_ok=True);base=FIG/name
    for ext in ('pdf','svg','png'):fig.savefig(base.with_suffix('.'+ext),dpi=300,facecolor='white',transparent=False)
    png=base.with_suffix('.png')
    with Image.open(png) as im:im.convert('RGB').save(png,dpi=(300,300))
    pdf=PdfReader(base.with_suffix('.pdf'));page=pdf.pages[0]
    fonts=page.get('/Resources').get_object().get('/Font',{}).get_object()
    font_types=sorted({str(v.get_object().get('/Subtype')) for v in fonts.values()})
    assert '/Type3' not in font_types
    with Image.open(png) as im:
        assert im.mode=='RGB';size=list(im.size);dpi=list(im.info['dpi'])
    record={'name':name,'caption':caption,'alt':alt,'source_files':sources,
            'source_sha256':{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources},
            'figure_mm':[float(page.mediabox.width)*25.4/72,float(page.mediabox.height)*25.4/72],
            'png_pixels':size,'png_DPI':dpi,'png_mode':'RGB','pdf_font_subtypes':font_types,
            'exports_sha256':{ext:hashlib.sha256(base.with_suffix('.'+ext).read_bytes()).hexdigest() for ext in ('pdf','svg','png')},
            'destination':'general research-stage figures; final CSCWD template/size check remains a P5/P6 task'}
    plt.close(fig);return record


def main():
    primary=json.loads((ROOT/'results/g2_v1_20261025/statistics.json').read_text())
    extended=json.loads((FOLDER/'extended_statistics.json').read_text());diagnostics=json.loads((FOLDER/'diagnostic_summary.json').read_text())
    records=[]
    style={'font.family':'DejaVu Sans','font.size':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':8,
           'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','savefig.facecolor':'white'}
    with plt.rc_context(style):
        fig,ax=plt.subplots(1,2,figsize=(180/25.4,90/25.4),layout='constrained')
        stats=[primary['primary']]+[primary['mixes'][m] for m in 'ABC']
        forest(ax,['Overall (720)','Mix A (240)','Mix B (240)','Mix C (240)'],stats,
               'Primary comparison: SAIL versus B2 | 30 root blocks',budget=True)
        records.append(export(fig,'fig1_primary',
            'Point estimates and two-sided percentile 95% intervals from 5,000 shared-root block bootstrap draws (30 roots, seed 73000). '+
            'CDI is normalized by mean predicted task duration; positive differences mean larger protected-task delay under SAIL. '+
            'Relative AWCT uses the paired scenario ratio, then frozen equal-cell/equal-Mix weighting. The dashed 5% line is a research tolerance. All 720 CDI pairs are defined.',
            'SAIL has positive CDI and AWCT differences from B2 overall and in every Mix. All displayed CDI intervals are above zero.',
            ['results/g2_v1_20261025/statistics.json','reports/p4/data/paired_effects.csv']))
        fig,ax=plt.subplots(1,2,figsize=(180/25.4,100/25.4),layout='constrained')
        names=['NoStability','NoChurn','B0','Fixed_H1','Fixed_H2']
        forest(ax,['NoStability','NoChurn (alias)','Fixed H0 = B0','Fixed H1','Fixed H2'],[primary['mechanisms'][m] for m in names],
               'All prespecified mechanism contrasts | 30 root blocks')
        records.append(export(fig,'fig2_mechanisms',
            'SAIL minus each of the five prespecified comparators, with the same 30-root/5,000-draw bootstrap as the primary analysis. '+
            'Negative CDI differences favor SAIL; positive AWCT differences are completion-time costs. NoStability changes the stability weight only. '+
            'NoChurn is exactly SAIL because frozen mu=0; its [0,0] interval is mathematical equivalence, not independent ablation evidence. Fixed H0 aliases B0. No p values are used.',
            'SAIL reduces CDI relative to NoStability and all fixed scopes. It costs AWCT relative to NoStability, improves AWCT relative to B0 and H1, and has near-zero AWCT difference from H2. NoChurn is an alias.',
            ['results/g2_v1_20261025/statistics.json','reports/p4/data/paired_effects.csv']))
        fig,ax=plt.subplots(1,2,figsize=(180/25.4,92/25.4),layout='constrained')
        names=['main_subset','cv0.1','cv0.3','control_delay']
        forest(ax,['Matched subset','Work CV = 0.1','Work CV = 0.3','Control delay = 0.1 pbar'],[extended['robustness'][m]['statistics'] for m in names],
               'Prespecified robustness: SAIL versus B2 | 10 root blocks',budget=True)
        records.append(export(fig,'fig3_robustness',
            'Each row contains 60 scenarios: 10 roots, three Mixes, two CCR levels, four nodes, and failure at 0.6 of matched actual no-fault makespan. '+
            'The zero-error/zero-delay subset is reused from main; the other rows are the two lognormal work-error levels and common control delay. '+
            'Each condition uses the frozen block estimator, 5,000 draws and seed 73000 separately. These contrasts do not estimate a difference between perturbation levels. '+
            'All CDI values are defined. The 5% line repeats the primary research budget for context.',
            'All robustness conditions retain positive SAIL minus B2 CDI differences with intervals above zero; AWCT costs remain below the research budget.',
            ['reports/p4/extended_statistics.json','reports/p4/data/paired_effects.csv']))
        fig,ax=plt.subplots(3,1,figsize=(180/25.4,185/25.4),layout='constrained')
        for panel,field,title in ((0,'selected_hops','(a) Selected canonical hop'),(1,'unique_plans','(b) Distinct candidate plans')):
            bottom=np.zeros(3);keys=(0,1,2) if panel==0 else (1,2,3)
            for key,color,hatch in zip(keys,(BLUE,GREEN,RED),('','//','..')):
                values=np.array([diagnostics['by_mix'][m][field].get(str(key),0)/240*100 for m in 'ABC'])
                bars=ax[panel].bar(list('ABC'),values,bottom=bottom,color=color,hatch=hatch,edgecolor=BLACK,linewidth=.4,label=str(key))
                for bar,value,b in zip(bars,values,bottom):
                    if value>=7:ax[panel].text(bar.get_x()+bar.get_width()/2,b+value/2,f'{value:.1f}%',ha='center',va='center',color=BLACK,fontsize=8,
                                               bbox={'facecolor':'white','edgecolor':'none','alpha':.96,'pad':1.5})
                bottom+=values
            ax[panel].set(ylim=(0,100),ylabel='Scenarios (%)',xlabel='Mix (240 scenarios each)',title=title)
            ax[panel].legend(title='Hop' if panel==0 else 'Plans',loc='center left',bbox_to_anchor=(1.01,.5),frameon=False,fontsize=7)
            ax[panel].spines[['top','right']].set_visible(False)
        times=diagnostics['timing_summary'];labels=[r['method'].replace('_',' ') for r in times];x=np.arange(len(times))
        ax[2].plot(x-.08,[r['p50_seconds']*1000 for r in times],marker='o',linestyle='none',color=BLUE,label='p50')
        ax[2].plot(x+.08,[r['p95_seconds']*1000 for r in times],marker='s',linestyle='none',color=RED,label='p95')
        ax[2].set(xticks=x,xticklabels=labels,ylabel='Full application time (ms)',ylim=(0,None),title='(c) Local timing: 20 scenarios x 3 repeats per method')
        ax[2].tick_params(axis='x',labelsize=7);ax[2].legend(frameon=False,ncol=2);ax[2].grid(axis='y',alpha=.18);ax[2].spines[['top','right']].set_visible(False)
        records.append(export(fig,'fig4_diagnostics',
            'All 720 main SAIL scenarios were replayed exactly to recover candidate counts and the selected canonical hop, retaining degenerate plans. '+
            'Panels a/b use complete-case counts with fixed 240 scenarios per Mix. Hop aliases remain in the source table. '+
            'Panel c measures the entire Simulator._apply call (snapshot, candidate generation/forecast/scoring, validation, input invalidation and plan application). '+
            'Each physical method has 60 wall-clock samples across 20 preselected scenarios and three repeats, in one process on this host; p50/p95 are descriptive quantiles, not confidence limits. '+
            'NoChurn has no independent timing sample. All 1,120 diagnostic replays exactly match stored formal traces and add no independent experimental observations.',
            'Stacked bars show selected scopes and distinct-plan counts for every Mix. The timing panel compares median and 95th percentile full application time across seven physical configurations.',
            ['reports/p4/diagnostic_summary.json','reports/p4/data/candidate_diagnostics.csv','reports/p4/data/full_application_timings.csv']))
    dump(FIG/'figure_manifest.json',{'figures':records,'zero_baselines_shown':True,'negative_and_null_results_retained':True,
                                    'publisher_compliance_claimed':False,'visual_inspection':'pending'})
    (FIG/'captions_and_alt.md').write_text('\n\n'.join('**'+r['name']+'**\n\n'+r['caption']+'\n\nAlt: '+r['alt'] for r in records)+'\n')
    print(json.dumps({r['name']:r['figure_mm'] for r in records}))


if __name__=='__main__':main()
