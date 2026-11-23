"""Independent QA paths must preserve the frozen missing-data arithmetic."""
import itertools
from types import SimpleNamespace

import pytest

from formal_v2.analyze_reporting import independent_bootstrap
from formal_v2.audit_outputs import independent_order
from sail.model import Plan
from sail.statistics import paired_bootstrap


@pytest.mark.parametrize('missing',[False,True])
def test_separate_bootstrap_matches_with_missing_cells(missing):
    rows=[]
    for root,mix,nodes in itertools.product(range(5),('A','B'),(4,8)):
        p=0 if missing and (root+nodes+(mix=='B'))%3==0 else 2
        for method in ('Target','Control'):
            rows.append({'root_seed':root,'mix':mix,'nodes':nodes,'ccr':.5,'failure_fraction':.3,'method':method,'protected_count':p,
                         'awct':10+root+nodes+(method=='Target')*.2,'cdi':(1+root*.1+(mix=='B')*.3+(method=='Target')*.2) if p else None})
    expected=paired_bootstrap([{**r,'method':'SAIL' if r['method']=='Target' else r['method']} for r in rows],'Control',seed=83000)
    actual=independent_bootstrap(rows,'Target','Control')
    for metric in ('cdi','relative_awct'):
        for key in ('point','ci95','upper95'):assert actual[metric][key]==pytest.approx(expected[metric][key])
        for key in ('defined_pairs','undefined_pairs','defined_bootstrap_draws'):assert actual[metric][key]==expected[metric][key]


def test_ci_undefined_when_a_resampled_mix_has_no_population():
    rows=[]
    for root,mix in itertools.product(range(3),('A','B')):
        p=int(root==(0 if mix=='A' else 1))
        for method in ('Target','Control'):
            rows.append({'root_seed':root,'mix':mix,'nodes':4,'ccr':.5,'failure_fraction':.3,'method':method,'protected_count':p,
                         'awct':10,'cdi':(1 if method=='Target' else 2) if p else None})
    expected=paired_bootstrap([{**r,'method':'SAIL' if r['method']=='Target' else r['method']} for r in rows],'Control',seed=83000)
    actual=independent_bootstrap(rows,'Target','Control')
    assert actual['cdi']['ci95'] is expected['cdi']['ci95'] is None
    assert actual['cdi']['defined_bootstrap_draws']==expected['cdi']['defined_bootstrap_draws']<5000


def test_order_fenwick_uses_same_node_retained_pairs_only():
    ctx=SimpleNamespace(Q=frozenset('abcde'),F=frozenset('e'),old_assignment=tuple((v,0 if v in 'abc' else 1) for v in 'abcde'),original_queues=(tuple('abc'),tuple('de')))
    result=independent_order(ctx,Plan((tuple('cba'),tuple('de'))))
    assert result['queue_inversions']==3 and result['comparable_pairs']==3 and result['order_disturbance']==1
    result=independent_order(ctx,Plan((tuple('a'),tuple('bcde'))))
    assert result['comparable_pairs']==0 and result['order_disturbance'] is None
