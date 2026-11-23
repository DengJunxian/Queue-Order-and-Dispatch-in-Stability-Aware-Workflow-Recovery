from revision_r6.measured import observed_workload

def test_realized_repeat_does_not_change_prediction_or_file_model():
    a,truth3,source3=observed_workload(3)
    b,truth4,source4=observed_workload(4)
    c,truth5,source5=observed_workload(5)
    assert a==b==c and truth3!=truth4 and truth4!=truth5
    assert len(a.tasks)==190
    assert abs(a.pbar-1)<1e-12
    assert {r['role'] for r in source3['sources']}=={'prediction','calibration','evaluation'}
