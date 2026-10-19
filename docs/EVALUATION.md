# Evaluation and confidence

## Standalone release results — October 19, 2026

The installed package passed **65 unit checks**, including the optional MCP
tests. A second environment with only the core wheel and no third-party
dependencies passed the **61 core checks**. Real stdio discovery/calls verified
all five MCP tools, a cached repeat and a dependent workflow.

The fixed smoke corpus matched **53/56** examples: 22/24 handler requests and
31/32 typed-decision examples. The public 126-case audit produced these results
on its 56-example test partition:

| Task | Correct | Agreement | 95% Wilson interval |
| --- | --- | --- | --- |
| Handler | 54/56 | 96.4% | 87.9–99.0% |
| Explicit room | 55/56 | 98.2% | 90.6–99.7% |
| Clarification | 47/56 | 83.9% | 72.2–91.3% |

Only the clarification calibration candidate passed its shipping checks.
Routing/room calibration candidates and **both automatic suggestion gates remain
disabled**. These small synthetic results are not overall assistant accuracy.

Model calls in the smoke run had a 651 ms median and 964 ms p95; parser median was
0.26 ms. Two evaluations shared the same local model concurrently, and these
timings exclude a new model download/cold-load comparison. They are not a
prediction of another computer's latency or proof of end-to-end speed gains.

Full receipts, including mistakes, model/corpus fingerprints, and environment:
[smoke](../benchmarks/results/smoke.json),
[confidence audit](../benchmarks/results/confidence-audit.json),
[MCP smoke](../benchmarks/results/mcp-smoke.json),
[environment](../benchmarks/results/environment.json).

## What the release tests

The unit suite covers request/response validation, ordered cache keys, model
drift, rejected remote/cloud endpoints, parser isolation, HTTP bounds/origin
checks, workflow batching/branching/deadlines, MCP schemas and hook privacy.
It runs without hardware or a model. It measures software behavior, not model
accuracy.

Two optional local-model evaluations are included:

```sh
python scripts/benchmark_decisions.py
python scripts/evaluate_decision_calibration.py \
  --cases benchmarks/aiden_decisions/confidence_audit_cases.jsonl
```

The first uses 56 fixed synthetic smoke cases. The second uses 126 synthetic
examples split 42 fit / 28 validation / 56 test, with labels for handler, explicit
room and clarification. They come from the original assistant project, with
personal aliases removed for this export. Because the task definitions changed,
old private calibration profiles and old headline metrics are not shipped as
applicable evidence. The corpora are public regression diagnostics; they are
not an unseen external benchmark or a Jev head-to-head comparison.

Generated reports include corpus/model/question fingerprints, per-case outputs,
errors, timing and token counts. They go into ignored `output/`. No evaluation
script sends commands to appliances. Compare the exact same corpus/model/settings
when evaluating a change, and collect independent real-workload labels before
drawing wider conclusions.

## Calibration is separate from a raw model score

- Raw probabilities are retained. A concentrated distribution may still be wrong.
- Temperature scaling fits on the fit partition and is selected on validation.
- Correctness bins estimate whether the top prediction is right. Small bins pool
  fit observations and disclose sample counts and Wilson intervals.
- Test metrics are used for reporting and a ship/reject check, not parameter fit.
  This code was already developed with similar task categories; do not call the
  included test partition an independent blind study.
- Rejected candidates remain disabled. Handler suggestion gates require at least
  20 accepted validation cases and a lower 95% Wilson bound of 80%.
- Profiles are rejected after model-digest or ordered-question-map changes.
  None establish global calibration or action authority.

Evaluation writes an optional profile to
`output/aiden-decisions/calibration-profile.json`. To try that exact artifact:

```sh
aiden-decisions --calibration output/aiden-decisions/calibration-profile.json \
  preflight "Explain how a heat pump works"
```

Alternatively place a reviewed profile at
`~/.config/aiden-decisions/calibration.json`. Nothing is installed there by the
evaluation script, and no profile is bundled by default. Generic workflow
question sets do not inherit calibration for the example routing questions.

## Limits

This project does not train a new model, reconstruct Jev's internals, guarantee
faster end-to-end reasoning, or prove prompt-injection resistance. Short synthetic
examples cannot establish broad real-world accuracy. Tev1's model card documents
limited context/training coverage and uncertain calibration; review it before
using the outputs for consequential decisions.

References: [Tev1 model card](https://ollama.com/library/tev1),
[temperature scaling](https://proceedings.mlr.press/v70/guo17a.html).
