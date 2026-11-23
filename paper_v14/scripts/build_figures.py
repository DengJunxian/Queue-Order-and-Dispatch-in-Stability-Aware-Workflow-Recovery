"""R11 evidence plots rebuilt from the frozen R5--R7 records."""
import base64,hashlib,json,math,xml.etree.ElementTree as ET
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
import numpy as np
from PIL import Image

PAPER=Path(__file__).resolve().parents[1];ROOT=PAPER.parent
R6=ROOT/'revision_r6/analysis/results.json';R7=ROOT/'revision_r7/analysis/results.json'
OLD=json.loads(R6.read_text());NEW=json.loads(R7.read_text());FIG=PAPER/'manuscript/figures';EVID=PAPER/'evidence/r11_figures';EVID.mkdir(parents=True,exist_ok=True)
INK,BLUE,AMBER,GRID='#242424','#3E6F9E','#B66126','#D8DADD'
plt.rcParams.update({'font.family':'DejaVu Serif','font.size':9,'axes.labelsize':9,'axes.titlesize':9.2,'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8.3,'text.color':INK,'axes.labelcolor':INK,'axes.edgecolor':INK,'xtick.color':INK,'ytick.color':INK,'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','svg.hashsalt':'cscwd-r11-fixed','axes.spines.top':False,'axes.spines.right':False,'axes.linewidth':.7,'axes.axisbelow':True,'grid.color':GRID,'grid.linewidth':.48,'hatch.linewidth':.52,'savefig.facecolor':'white','figure.facecolor':'white','xtick.major.width':.7,'ytick.major.width':.7})
manifest=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(fig,name,data,caption,alt,sources):
    for ax in fig.axes:
        # Axis draws only ticks within limits; prune unused auto-tick text before
        # checking rendered extents, without altering scientific axis ranges.
        lo,hi=sorted(ax.get_xlim());ticks=ax.get_xticks()
        if any(t<lo or t>hi for t in ticks):ax.set_xticks([t for t in ticks if lo<=t<=hi])
        lo,hi=sorted(ax.get_ylim());ticks=ax.get_yticks()
        if any(t<lo or t>hi for t in ticks):ax.set_yticks([t for t in ticks if lo<=t<=hi])
    fig.canvas.draw();renderer=fig.canvas.get_renderer();w,h=fig.canvas.get_width_height();clipped=[]
    for t in fig.findobj(matplotlib.text.Text):
        if not t.get_visible() or not t.get_text():continue
        box=t.get_window_extent(renderer)
        if box.x0 < -2 or box.y0 < -2 or box.x1>w+2 or box.y1>h+2:clipped.append(t.get_text())
    assert not clipped,(name,clipped)
    paths=[]
    for fmt in ['pdf','svg','png']:
        path=FIG/(name+'.'+fmt);fig.savefig(path,dpi=600,bbox_inches=None,metadata={'Creator':'CSCWD source-bound plotting script','CreationDate':None} if fmt=='pdf' else None);paths.append(path)
    # Font embedding retains SVG text as text, with a standard installed fallback.
    svg=FIG/(name+'.svg');tree=ET.parse(svg);root=tree.getroot();ns='{http://www.w3.org/2000/svg}'
    defs=root.find(ns+'defs');style=ET.SubElement(defs,ns+'style',{'type':'text/css'})
    rules=[]
    for weight in ['normal','bold']:
        font=Path(font_manager.findfont(font_manager.FontProperties(family='DejaVu Serif',weight=weight)))
        rules.append("@font-face{font-family:'DejaVu Serif';font-style:normal;font-weight:"+weight+";src:url(data:font/ttf;base64,"+base64.b64encode(font.read_bytes()).decode()+") format('truetype');}")
    style.text='\n'.join(rules);tree.write(svg,encoding='utf-8',xml_declaration=True)
    preview=FIG/(name+'_preview.png');gray=FIG/(name+'_grayscale.png')
    im=Image.open(FIG/(name+'.png'));im.thumbnail((1650,1200));im.save(preview);im.convert('L').save(gray)
    source=EVID/(name+'.json');source.write_text(json.dumps({'figure':name,'data':data,'caption':caption,'alt_text':alt,'sources':{str(p.relative_to(ROOT)):sha(p) for p in sources}},indent=2,allow_nan=False)+'\n')
    (EVID/(name+'_caption.md')).write_text(caption+'\n\nAlt text: '+alt+'\n')
    manifest.append({'name':name,'width_pt':fig.get_size_inches()[0]*72,'height_pt':fig.get_size_inches()[1]*72,'raster_dpi':600,'svg_text_editable':True,'svg_fonts_embedded':True,'source_data':str(source.relative_to(PAPER)),'source_data_sha256':sha(source),'outputs':{str(p.relative_to(PAPER)):sha(p) for p in paths+[preview,gray]},'text_outside_canvas':clipped})
    plt.close(fig)


def dispatch_witness():
    path=ROOT/'revision_r5/reports/projection_dispatch_witness.json';data=json.loads(path.read_text())
    assert data['status']=='PASS' and data['benchmark_samples_added']==0
    fig,axs=plt.subplots(1,2,figsize=(7.15,1.65),sharex=True,sharey=True)
    fig.subplots_adjust(left=.112,right=.983,bottom=.28,top=.76,wspace=.18)
    for ax,row,title in zip(axs,data['rows'],['(a) Strict dispatch','(b) Bypass dispatch']):
        for y,kind in [(1,'reference_events'),(0,'recovery_events')]:
            events=row[kind]
            for ev in events:
                if ev['kind']!='CPU_START' or ev['node']!=0:continue
                task=ev['task'];end=next(e['time'] for e in events if e['kind']=='CPU_DONE' and e['task']==task)
                assert end>ev['time'] and end-ev['time']==data['workload'][task]
                ax.barh(y,end-ev['time'],left=ev['time'],height=.39,color=BLUE if task=='p' else '#F3DAC2',edgecolor=INK,linewidth=.65,hatch=None if task=='p' else '///',zorder=3)
                ax.text((end+ev['time'])/2,y,task,ha='center',va='center',color='white' if task=='p' else INK,fontsize=8.2,zorder=4)
        ax.axvline(.5,color=AMBER,ls=':',lw=1.05)
        ax.axvline(2,color=INK,ls='--',lw=.8,ymax=.81)
        ax.text(.51,1.48,'Fault',ha='left',fontsize=7.6)
        ax.text(2.12,1.48,'p ready',ha='left',fontsize=7.6)
        ax.set_title(title,loc='left',pad=8,fontweight='bold');ax.set_xlim(0,13.5);ax.set_ylim(-.45,1.72)
        ax.set_xticks([0,2,6,10,13]);ax.set_xlabel('Time (unit-speed work)');ax.set_yticks([1,0],['No fault','Recovery'])
        ax.tick_params(axis='y',length=0);ax.spines['left'].set_visible(False);ax.grid(axis='y')
    emit(fig,'dispatch_witness',data,'Executed correctness witness, not a benchmark sample. Three unit-speed nodes initially queue (p), (r), (f), with work 1, 2, 10 and dependency r→p. Node 2 fails at t=0.5 (dotted line). Both repairs use the same feasible queue (p,f) on node 0; PS leaves it unchanged. Task p becomes ready at t=2 (dashed line). Strict recovery starts p at 2, bypass at 10.5. This supplied B0-style queue is not claimed to be selected by EFT.', 'Two time-aligned Gantt panels show the same protected-first queue. Strict dispatch waits for p; bypass starts nonpreemptive f, delaying p despite identical assignments and repaired order.',[path])


def ordering_summary():
    fig,ax=plt.subplots(figsize=(3.5,1.85));fig.subplots_adjust(left=.255,right=.987,bottom=.25,top=.76)
    data=[]
    for y,net in [(1,'independent'),(0,'shared')]:
        for rule,offset,color,marker in [('strict',.16,BLUE,'o'),('skip-unready',-.16,AMBER,'s')]:
            x=OLD['networks'][net][rule]['contrasts']['B0AssignmentReorder_minus_B0']['cdi']
            point, (lo,hi)=x['point'],x['ci95']
            assert lo<=point<=hi and -8<lo and hi<.65
            ax.errorbar(point,y+offset,xerr=[[point-lo],[hi-point]],fmt=marker,color=color,mfc=color if rule=='strict' else 'white',mew=.9,markersize=4.4 if rule=='strict' else 2.3,capsize=2.3,lw=1.1,zorder=4)
            data.append({'network':net,'rule':rule,**x})
    ax.axvline(0,color=INK,lw=.87,ls='--');ax.axhline(.5,color=GRID,lw=.6)
    ax.set_xlim(-8,.65);ax.set_ylim(-.43,1.43);ax.set_yticks([1,0],['Independent\ntransfers','Shared link'])
    ax.set_xticks([-8,-6,-4,-2,0]);ax.tick_params(axis='y',length=0);ax.spines['left'].set_visible(False);ax.grid(axis='x')
    ax.legend(handles=[Line2D([],[],marker='o',ls='-',color=BLUE,label='Strict'),Line2D([],[],marker='s',mfc='white',ls='-',color=AMBER,label='Bypass')],loc='lower left',bbox_to_anchor=(0,1.0),ncol=2,frameon=False,borderaxespad=0)
    ax.set_xlabel('AL − B0 CDI')
    emit(fig,'r7_order_summary',data,'Structural holdout: AL−B0 CDI differences and pointwise 95% family-stratified graph/root bootstrap intervals. Twelve source DAGs, four keyed environments per graph; independent transfers average four node/CCR cells, shared transfers use the registered four-node CCR-2 cells. Negative favors AL.','Four horizontal confidence intervals show a strict ordering benefit under both networks; bypass intervals cross zero.',[R6])


def ordering_graphs():
    fig,axs=plt.subplots(1,2,figsize=(7.15,3.7),sharey=True);fig.subplots_adjust(left=.265,right=.98,bottom=.17,top=.87,wspace=.15)
    names=list(OLD['by_graph']);data=[];short=[]
    for name in names:
        group=name.replace('-chameleon-',' / ').removesuffix('-001');short.append(group)
    for ax,net,title in zip(axs,['independent','shared'],['(a) Independent transfers','(b) Shared aggregate link']):
        for i,name in enumerate(names):
            for rule,off,col,m in [('strict',.13,BLUE,'o'),('skip-unready',-.13,AMBER,'s')]:
                d=OLD['by_graph'][name][net][rule];value=d['B0AssignmentReorder']['cdi']-d['B0']['cdi']
                ax.plot(value,len(names)-1-i+off,m,color=col,mfc=col if rule=='strict' else 'white',ms=4.4);data.append({'graph':name,'network':net,'rule':rule,'AL_minus_B0_CDI':value})
        ax.axvline(0,color=INK,lw=.7,ls='--');ax.set_title(title,loc='left',fontweight='bold');ax.set_xlabel('AL − B0 CDI');ax.tick_params(axis='y',length=0);ax.spines['left'].set_visible(False);ax.grid(axis='x')
        for y in [2.5,5.5,8.5]:ax.axhline(y,color='#DDDDDD',lw=.5)
    axs[0].set_xlim(-3.1,1.1);axs[1].set_xlim(-20,1.1)
    axs[0].set_yticks(range(len(names)),list(reversed(short)));axs[0].set_ylim(-.6,len(names)-.4)
    fig.legend(handles=[Line2D([],[],marker='o',ls='',color=BLUE,label='Strict'),Line2D([],[],marker='s',mfc='white',ls='',color=AMBER,label='Bypass')],loc='upper center',ncol=2,frameon=False,bbox_to_anchor=(.64,1.0))
    emit(fig,'r7_graph_heterogeneity',data,'Every new source graph, with four environment roots averaged per point. Independent transfers additionally average defined node/CCR cells. Graph means are descriptive, not confidence intervals. The panels have explicitly different horizontal ranges to retain the independent-transfer detail; both retain normalized CDI units and the zero reference.','Paired strict and bypass points for all twelve new DAGs reveal family and graph heterogeneity, including positive and near-zero effects.',[R6])


def calibration():
    fig,axs=plt.subplots(1,3,figsize=(7.15,2.25),sharex=True,sharey=True);fig.subplots_adjust(left=.22,right=.98,bottom=.24,top=.77,wspace=.17)
    data=[];conditions=['independent/strict','independent/skip-unready','shared/strict','shared/skip-unready']
    for ax,mix,title in zip(axs,['BLAST_new','BWA_SRA_new','SRA_seen'],['(a) BLAST','(b) BWA + SRA','(c) SRA']):
        for i,cond in enumerate(conditions):
            e=NEW['calibration_cells'][mix][cond];absolute=100*((1+e['eta'])/(1-e['eta'])-1);paired=100*math.expm1(e['global_delta'])
            ax.plot([paired,absolute],[3-i,3-i],color='#969696',lw=.9);ax.plot(absolute,3-i,'x',color=AMBER,ms=6,mew=1.15,zorder=4);ax.plot(paired,3-i,'o',color=BLUE,mfc='white',ms=4.8,mew=1.15,zorder=3)
            data.append({'composition':mix,'condition':cond,'eta':e['eta'],'global_delta':e['global_delta'],'uniform_ratio_inflation_pct':absolute,'paired_ratio_inflation_pct':paired})
        ax.axvline(5,color=INK,ls='--',lw=.8);ax.set_title(title,loc='left',fontweight='bold');ax.set_xlim(-3,70);ax.set_ylim(-.5,3.5);ax.set_xticks([0,20,40,60]);ax.set_xlabel('Ratio inflation bound (%)');ax.tick_params(axis='y',length=0);ax.spines['left'].set_visible(False);ax.grid(axis='x')
    axs[0].set_yticks([3,2,1,0],['Independent / strict','Independent / bypass','Shared / strict','Shared / bypass'])
    fig.legend(handles=[Line2D([],[],marker='x',ls='',color=AMBER,label='Separate absolute errors'),Line2D([],[],marker='o',mfc='white',ls='',color=BLUE,label='Paired ratio errors'),Line2D([],[],color=INK,ls='--',label='5% boundary')],ncol=3,loc='upper center',frameon=False,bbox_to_anchor=(.57,.99))
    emit(fig,'r7_calibration_bounds',data,'Calibration envelopes for repeat 003, using every original cap-feasible candidate in twelve environments per cell. The separate-error factor is (1+η)/(1−η), while the paired factor is exp(δ). The dashed 5% line is the nonempty-set boundary for a uniform factor against the minimum-mean reference. Both are empirical envelopes. BLAST has singleton pools, so its near-zero paired residual does not demonstrate useful admission.','Dumbbell plots show that paired completion errors reduce the empirical inflation envelope, but the global envelope remains above five percent in every BWA–SRA and SRA cell.',[R7])


def error_transfer():
    path=ROOT/'revision_r7/analysis/candidate_errors.json';records=json.loads(path.read_text())
    fig,axs=plt.subplots(2,3,figsize=(7.15,3.8),sharex=True,sharey=True)
    fig.subplots_adjust(left=.10,right=.98,bottom=.16,top=.82,wspace=.16,hspace=.28)
    seen=0
    for col,(mix,title) in enumerate([('BLAST_new','BLAST (new)'),('BWA_SRA_new','BWA + SRA (mixed)'),('SRA_seen','SRA (seen)')]):
        for row,net in enumerate(['independent','shared']):
            ax=axs[row,col];counts=[];maxima=[]
            for stage,color,style in [('evaluation',BLUE,'-'),('calibration',AMBER,'--')]:
                vals=np.sort([100*math.expm1(r['ratio_log_error']) for r in records if r['composition']==mix and r['stage']==stage and r['condition'].startswith(net+'/')])
                assert len(vals)>0 and vals[0]>=-30 and vals[-1]<=105
                unique,counts_at=np.unique(vals,return_counts=True);cdf=np.cumsum(counts_at)/len(vals)
                assert cdf[-1]==1 and np.all(np.diff(cdf)>0)
                # Include both endpoints so a singleton distribution has a visible jump.
                ax.step(np.r_[-30,unique,105],np.r_[0,cdf,1],where='post',color=color,ls=style,lw=1.25)
                seen+=len(vals);counts.append(len(vals));maxima.append(vals[-1])
            ax.axvline(0,color='#A6A6A6',lw=.6);ax.set_xlim(-30,105);ax.set_ylim(0,1.03);ax.grid(axis='y')
            ax.set_xticks([0,50,100]);ax.set_yticks([0,.5,1]);ax.text(.97,.12,f'n = {counts[1]} / {counts[0]}\nmax = {maxima[1]:.1f} / {maxima[0]:.1f}%',transform=ax.transAxes,ha='right',fontsize=7.6,linespacing=1.45)
            if row==0:ax.set_title(f'({chr(97+col)}) {title}',loc='left',fontweight='bold')
            if col==0:ax.set_ylabel(('Independent' if row==0 else 'Shared link')+'\nEmpirical fraction')
    assert seen==len(records)==3780
    fig.supxlabel('Paired ratio error: 100 × [exp(z) − 1] (%)',fontsize=8.5,y=.025)
    fig.legend(handles=[Line2D([],[],color=AMBER,ls='--',lw=1.25,label='Calibration (003)'),Line2D([],[],color=BLUE,lw=1.25,label='Evaluation (004 / 005)')],loc='upper center',ncol=2,frameon=False)
    emit(fig,'r7_error_transfer',records,'Empirical distributions of all 3,780 candidate/workflow paired-ratio errors, faceted by composition and network. Counts give calibration / evaluation records. Curves are exact empirical CDFs with ties retained, no smoothing or independent-sample confidence bands. Zero means exact candidate/reference error cancellation. Singleton BLAST pools have zero paired error and no alternative plan. Records share candidates, workflows and runtime vectors and do not constitute independent runtime replications.', 'Six cumulative-distribution panels separate calibration and evaluation without overplotting individual observations. BLAST errors are zero because its candidate pools are singletons; BWA–SRA shared-link evaluation includes a long positive tail.',[path])


def worst_case():
    import gzip
    diag=ROOT/'revision_r7/reports/post_analysis_diagnostics.json';item=json.loads(diag.read_text())['worst_conditioned_guard_case'];path=ROOT/item['source_event_file'];assert sha(path)==item['source_event_sha256'];d=json.loads(gzip.decompress(path.read_bytes()));key=item['network']+'/'+item['rule'];g=item['workflow'];methods=['DispatchMinAWCT','ConditionalRatioGuard'];data=[]
    from matplotlib.patches import Patch
    fig,ax=plt.subplots(figsize=(3.5,1.9));fig.subplots_adjust(left=.165,right=.988,bottom=.25,top=.77)
    for i,m in enumerate(methods):
        predicted=d['predictions'][key][m]['workflow_completion'][g];actual=dict(d['runs'][key+'/'+m]['clock']['workflow_finishes'])[g]
        for y,value,color,hatch in [(1-i+.17,predicted,'#F3DAC2','///'),(1-i-.17,actual,BLUE,None)]:
            assert 0<=value<=410
            ax.barh(y,value,height=.27,color=color,edgecolor=INK,hatch=hatch,linewidth=.6,zorder=3)
            ax.text(value+8,y,f'{value:.1f}',va='center',fontsize=8)
        data.append({'method':m,'workflow':g,'predicted_completion':predicted,'realized_completion':actual})
    ax.set_ylim(-.37,1.38);ax.set_xlim(0,465);ax.set_xticks([0,100,200,300,400]);ax.set_yticks([1,0],['DPM','CRG']);ax.set_xlabel('Completion (normalized time)');ax.tick_params(axis='y',length=0);ax.grid(axis='x')
    ax.legend(handles=[Patch(facecolor='#F3DAC2',edgecolor=INK,hatch='///',label='Predicted'),Patch(facecolor=BLUE,edgecolor=INK,label='Realized')],loc='lower left',bbox_to_anchor=(0,1),ncol=2,frameon=False,borderaxespad=0)
    emit(fig,'r7_worst_case',{'case':item,'values':data},'Largest observed CRG workflow increase, selected over the entire evaluation: BWA–SRA, repeat 005, root 94001, shared link, bypass, workflow w01. Predictions are 385.9 (DPM) and 386.4 (CRG); realized completions are 194.1 and 382.9. The zero-based axis shows the reference finishing far earlier than forecast, breaking error cancellation. Case selection is post-analysis, not independent confirmation.', 'Paired bars compare forecasts and realized completions for DPM and CRG. The two forecasts are nearly equal, while the realized CRG completion is 97.29 percent higher than DPM.',[diag,path])
    tau=d['failure']['time'];staging={};timeline=[]
    for m in methods:
        run=d['runs'][key+'/'+m]['clock'];active={};intervals=[]
        for ev in run['events']:
            task=ev.get('task','')
            if not task.startswith(g+'::'):continue
            if ev['kind']=='input_start':active[task]=ev
            if ev['kind']=='input_reset':active.pop(task,None)
            if ev['kind']=='input_ready' and task in active:
                start=active.pop(task)
                if ev['time']>tau and start['total']>0:
                    intervals.append({'task':task,'stage_start':start['time'],'stage_finish':ev['time'],'remote_bytes':start['total'],'node':ev['node']})
        staging[m]={v['task']:v for v in intervals}
    tasks=sorted(set(staging[methods[0]])|set(staging[methods[1]]))
    fig,axs=plt.subplots(1,2,figsize=(7.15,3.5),sharex=True,sharey=True);fig.subplots_adjust(left=.18,right=.98,bottom=.18,top=.78,wspace=.14)
    end=max(v['realized_completion'] for v in data)
    for ax,m,title in zip(axs,methods,['(a) Reference DPM','(b) Conditional CRG']):
        run=d['runs'][key+'/'+m]['clock'];start=dict(run['starts']);finish=dict(run['finishes'])
        for i,v in enumerate(tasks):
            y=len(tasks)-1-i;stage=staging[m].get(v)
            if stage:
                left=max(tau,stage['stage_start']);ax.broken_barh([(left-tau,stage['stage_finish']-left)],(y-.16,.32),facecolors='#F3DAC2',edgecolors=AMBER,linewidths=.7,hatch='//')
            if finish[v]>tau:
                left=max(tau,start[v]);ax.broken_barh([(left-tau,finish[v]-left)],(y-.2,.4),facecolors=BLUE)
                ax.plot(finish[v]-tau,y,'|',color=INK,ms=5)
            timeline.append({'method':m,'task':v,'input_stage':stage,'cpu_start':start[v],'cpu_finish':finish[v]})
        done=dict(run['workflow_finishes'])[g];ax.axvline(done-tau,color=INK,lw=.9,ls=':');ax.set_title(title,loc='left',fontweight='bold');ax.set_xlabel('Time since fault (normalized units)');ax.set_xlim(0,(end-tau)*1.04);ax.tick_params(axis='y',length=0);ax.spines['left'].set_visible(False);ax.grid(axis='x')
    axs[0].set_yticks(range(len(tasks)),[v.split('::')[1].replace('_ID00000','#') for v in reversed(tasks)]);axs[0].set_ylim(-.6,len(tasks)-.4)
    fig.legend(handles=[Patch(facecolor='#F3DAC2',edgecolor=AMBER,hatch='//',label='Input staging'),Patch(facecolor=BLUE,label='CPU (tick at finish)'),Line2D([],[],color=INK,ls=':',label='Workflow completion')],loc='upper center',ncol=3,frameon=False,columnspacing=1.)
    emit(fig,'r7_worst_timeline',{'case':item,'fault_time':tau,'tasks':timeline},'Observed staging and CPU intervals for workflow w01 in the deterministically selected worst case. Include every task with a nonzero post-fault remote-input stage in either plan. Both panels share task and time axes, with zero at the common failure. Outlined bars show staging; solid bars show actual CPU durations and ticks keep short tasks visible without inflating their duration. The dotted line marks whole-workflow completion. These are logged interleavings and placements, not an isolated causal decomposition.', 'The two plans produce different remote-input stages in the same workflow; CRG retains long stages for bowtie2 tasks and completes near 383, whereas the reference completes near 194, in original normalized time.',[diag,path])



def main():
    assert json.loads((ROOT/'revision_r7/reports/independent_recomputation.json').read_text())['status']=='PASS'
    dispatch_witness();ordering_summary();ordering_graphs();calibration();error_transfer();worst_case()
    assert len(manifest)==7
    (EVID/'manifest.json').write_text(json.dumps({'figures':manifest,'code_sha256':sha(Path(__file__)),'data_integrity':'All plots use saved results; no new scientific samples','replication_warning':'Environment and candidate observations do not add source runtime replicates'},indent=2)+'\n')
    print(json.dumps({'status':'PASS','figures':len(manifest),'formats':['PDF','SVG with embedded editable fonts','600dpi PNG','grayscale preview'],'canvas_text_clipping':0}))


if __name__=='__main__':main()
