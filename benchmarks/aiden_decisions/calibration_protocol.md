> Historical protocol from the original local project. The standalone export
> replaces personal aliases; current source/data hashes and new results take
> precedence. These public regression sets are not a fresh blind study.

# Frozen calibration protocol — October 9, 2026

All examples are independently authored synthetic requests with explicit labels.
They are not real household telemetry, Jev outputs or a general intelligence test.
The old 56-case smoke test is excluded. Exact inputs and identifiers must be unique;
examples are partitioned before any new prediction is observed. Domain semantics
overlap across splits; this is not a domain-held-out evaluation.

The native model and three `HOME_QUESTIONS` are frozen. Each request is scored by
the model even if the deterministic parser would understand it. No result cache.

Fit one positive temperature per question on calibration examples only, by NLL.
Temperature scaling preserves class ordering. Use validation only to retain the
fitted temperature if NLL and multiclass Brier do not worsen, otherwise retain 1.
Select a suggestion-only confidence threshold on validation, requiring at least
20 accepted requests and a 95% Wilson lower bound of 80% whole-request agreement.
This gate grants no device authority and is not a safety classifier.

Report untouched test accuracy, Wilson intervals, NLL, Brier, five-bin ECE,
reliability counts and accepted coverage. Never retune using test predictions.
Activate a fitted temperature only if at least 30 test examples also show
non-worsening NLL and Brier and at least 80% task accuracy. The 80% ship guard was
added after the first report exposed weak clarification accuracy; the reported
predictions and fitted temperatures are unchanged, and no new inference or tuning
uses the test labels. A failed candidate remains visible in the report and
is not applied. Test checks are a ship/no-ship guard, not temperature selection.
Keep global calibration false; any supported result is scoped to these synthetic
tasks. Fingerprint the model digest, exact ordered question map and dataset.

Method reference: [Guo et al., ICML 2017](https://proceedings.mlr.press/v70/guo17a.html).
