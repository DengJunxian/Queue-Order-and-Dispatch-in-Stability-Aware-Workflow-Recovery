"""Exploratory pilot figures; no frozen v1 artifact is overwritten."""
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

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from sail.development import dump


def main():
    folder=ROOT/'research_v2/reports';figdir=folder/'figures';figdir.mkdir(parents=True,exist_ok=True)
    s=json.loads((folder/'pilot_statistics.json').read_text())['effects']['main']
    old=json.loads((ROOT/'results/g2_v1_20261025/statistics.json').read_text())['primary'];records=[]
    def draw(labels,stats,name,title,caption):
        with plt.rc_context({'font.family':'DejaVu Sans','font.size':8,'pdf.fonttype':42,'svg.fonttype':'none'}):
            fig,axes=plt.subplots(1,2,figsize=(180/25.4,100/25.4),layout='constrained')
            for j,key in enumerate(('cdi','relative_awct')):
                ax=axes[j];factor=100 if j else 1
                for i,r in enumerate(stats):
                    v=r[key];p=v['point'];ci=v['ci95']
                    ax.errorbar(p*factor,i,xerr=np.array([[p-ci[0]],[ci[1]-p]])*factor,fmt='o' if j==0 else 's',
                                color='#0072B2' if j==0 else '#D55E00',capsize=3,markersize=4)
                ax.axvline(0,color='#222222',linewidth=.8);ax.set_yticks(range(len(labels)),labels if j==0 else ['']*len(labels));ax.invert_yaxis()
                ax.set_xlabel('CDI difference' if j==0 else 'Paired relative AWCT difference (%)');ax.grid(axis='x',alpha=.18);ax.margins(x=.14,y=.15)
                ax.spines[['top','right']].set_visible(False)
            fig.suptitle(title,fontsize=10,fontweight='bold')
            for ext in ('pdf','svg','png'):fig.savefig(figdir/f'{name}.{ext}',dpi=300,facecolor='white',transparent=False)
            with Image.open(figdir/f'{name}.png') as im:im.convert('RGB').save(figdir/f'{name}.png',dpi=(300,300))
            plt.close(fig)
            records.append({'name':name,'caption':caption,'alt':caption,
                            'source_files':['research_v2/reports/pilot_statistics.json','results/g2_v1_20261025/statistics.json'],
                            'sha256':{e:hashlib.sha256((figdir/f'{name}.{e}').read_bytes()).hexdigest() for e in ('pdf','svg','png')}})
    names=['QueueRepair0','B0AssignmentReorder','BudgetHEFT10','BudgetSelect10']
    draw(['Legacy SAIL','Queue repair (0 optional)','B0 assignment locked','Budget HEFT (10%)','Budget select (10%)'],
         [old]+[s[n]['B2'] for n in names],'pilot_vs_b2',
         'Exploratory comparison with B2 | 720 reused scenarios, 30 root blocks',
         'All new pilot methods and the frozen legacy SAIL versus B2. Points and percentile 95% intervals reuse 30 whole root blocks, 5000 draws and seed73000. '+
         'This design followed v1 outcomes; intervals describe this reused benchmark. Positive CDI and AWCT differences favor B2. Zero crossing does not establish equivalence. '+
         'Assignment budgets and predicted quality-infeasible cases are reported separately in the complete tables.')
    names=['QueueRepair0_vs_B0','B0AssignmentReorder_vs_B0','BudgetSelect10_vs_BudgetHEFT10']
    draw(['Queue repair - B0','B0 locked reorder - B0','Budget select - Budget HEFT'],[s['mechanisms'][n] for n in names],
         'pilot_mechanisms','Exploratory mechanism controls | 30 reused root blocks',
         'All three main mechanism contrasts. The second locks every unfinished-task B0 assignment, including compulsory recovery F; only queue ordering changes. '+
         'The first may also change F recovery placement. The third compares two procedures under the same optional assignment budget; their candidate pools differ. '+
         'Negative values favor the method named first. Intervals are descriptive block-bootstrap intervals on already-seen data, not new confirmatory evidence.')
    dump(figdir/'manifest.json',{'purpose':'EXPLORATORY_POST_G3','figures':records,'width_mm':180,'png_dpi':300,'no_publisher_compliance_claim':True,
                               'visual_inspection':'pending'})
    (figdir/'captions_and_alt.md').write_text('\n\n'.join('**'+r['name']+'**\n\n'+r['caption'] for r in records)+'\n')


if __name__=='__main__':main()
