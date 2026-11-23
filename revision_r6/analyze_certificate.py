"""Post-analysis check of the sufficient-margin infeasibility corollary."""
import gzip,json,math,hashlib
from fractions import Fraction
from pathlib import Path
from statistics import mean
ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'revision_r6'
def main():
    ledger=json.loads((BASE/'compact/manifest.json').read_text());cal=json.loads((BASE/'measured/calibration.json').read_text());witnesses=0;cases=0;rejections=0;gammas={}
    critical=(Fraction(105,100)-1)/(Fraction(105,100)+1);assert critical==Fraction(1,41)
    for entry in ledger['entries']:
        d=json.loads(gzip.decompress((ROOT/entry['compact_path']).read_bytes()))
        for model,pool in d['pool_forecasts'].items():
            reference=d['predictions'][model]['DispatchMinAWCT']['workflow_completion'];rmean=mean(reference.values())
            for c in pool:assert mean(c['workflow_completion'].values())>=rmean-1e-10
            witnesses+=1
            if entry['stage']=='measured/evaluation':
                rule=model.split('/')[1];eta=cal['eta'][rule];gamma=1.05*(1-eta)/(1+eta);assert eta>float(critical) and gamma<1
                gammas[rule]=gamma
                for c in pool:
                    assert any(t>gamma*reference[g]+1e-10 for g,t in c['workflow_completion'].items());rejections+=1
                assert d['metadata'][model]['calibrated_reference_fallback'];cases+=1
    out={'status':'PASS','classification':'POST_ANALYSIS_THEORETICAL_DIAGNOSTIC','scope':'Infeasibility of the sufficient uniform-error certificate; not impossibility of all robust protection','error_threshold_exact':'1/41','error_threshold':float(critical),'minimum_mean_reference_checks':witnesses,'evaluation_rule_cases':cases,'evaluation_candidate_rejections':rejections,'tightened_gamma':gammas,'empirical_margin_is_future_error_bound':False}
    (BASE/'reports/admission_certificate.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out))
if __name__=='__main__':main()
