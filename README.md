# Queue Order and Dispatch in Stability-Aware Workflow Recovery

Research code and data for workflow recovery experiments on shared computing resources. The repository contains the simulator, rescheduling methods, frozen configurations, workflow adapters, inputs, compact evaluation records, verification tools, tests, and figure-generation code.

## Setup

Use Python 3.12 and install the pinned dependencies in a virtual environment:

```sh
python -m pip install -r requirements.txt
```

Run commands from the repository root. The validated workflow is:

```sh
python -m pytest -q revision_r1/test_controls.py revision_r1/test_statistics.py revision_r2/test_dispatch.py revision_r2/test_pool_accounting.py revision_r4/tests revision_r5/tests revision_r6/tests revision_r7/tests
python paper_v8/scripts/reproduce_case.py --output benchmark-replay.json
python -m revision_r7.replay --output measured-replay.json
python -m revision_r7.verify
python paper_v14/scripts/build_figures.py
```

The benchmark replay checks one saved case and both dispatchers. The default measured replay checks two saved cases using 150 validation executions and 16 offline continuations. The verifier reconstructs the recorded numerical summaries and selector decisions from all 108 compact measured-repeat cases. `--all` on the measured replay executes all 108 cases. Figure generation writes outputs under `paper_v14/manuscript/figures/` and provenance under `paper_v14/evidence/r11_figures/`.

Validate the original v2 freeze without running the study:

```sh
python -c "from pathlib import Path; from v2_preparation.frozen import verify_v2; p=Path.cwd(); c,m=verify_v2(p,p/'freeze/g2_v2_20261025'); print(c['status'],len(m['jobs']))"
```

The original confirmation configuration contains 15,780 job labels. Frozen inputs and code checksums are included. Full persisted event archives and original formal-run outputs are not included, so the original complete event audit cannot be reproduced solely from this repository. Do not write new outputs into the frozen input directories.

## Layout

- `sail/` holds the workflow model, scheduler, simulator, metrics, and event audit.
- `data/`, `v2_preparation/data/`, and `revision_r6/data/` and `revision_r7/data/` contain workflow inputs, adapters' source manifests, and provenance.
- `v2_preparation/`, `formal_v2/`, and `freeze/` contain the confirmatory implementation and frozen v1/v2 specifications.
- `revision_r1/`, `revision_r2/`, and `revision_r4/` through `revision_r7/` contain the subsequent experimental controls, measured-repeat analysis, and verifiers.
- `revision_r7/portable/` contains the compact measured-repeat cases and hash-bound reconstruction inputs.
- `paper_v8/scripts/reproduce_case.py` and `paper_v14/scripts/build_figures.py` retain their original relative paths so their source and input checks continue to work. Those directories contain experiment and plotting code, not a manuscript.
- `paper_v9/delivery_manifest.json` is the historical checksum index referenced by the frozen R7 registration.

The experiment composes measured workflow traces on a synthetic shared platform. Source runtimes are not independent observations of the workflows running together. The measured-repeat extension uses one calibration and two evaluation runtime vectors per composition. Source-history correction is recorded in `revision_r7/reports/provenance_correction.json`. Negative and zero outcomes remain in the saved analysis.

## Data provenance and rights

Workflow instances originate from [WfCommons / WfInstances](https://github.com/wfcommons/WfInstances) at commit `249866063b3bd7d6a36a5a55d4202c1f683099c0`. The associated source URLs and hashes appear in the data manifests, and the upstream license text is retained at `data/raw/wfinstances/LICENSE`. Consult that license for the third-party material. No license for the original project code is specified in this repository.
