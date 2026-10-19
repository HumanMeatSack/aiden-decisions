> Historical protocol from the original local project. The standalone export
> replaces personal aliases; current source/data hashes and new results take
> precedence. These public regression sets are not a fresh blind study.

# Prediction-confidence audit — frozen before new audit inference

The first 112-case evaluation exposed weak clarification and rejected temperatures.
Those 42 original test cases are now development diagnostics; they are not reused
as the final holdout. The original 42 calibration and 28 validation examples stay
unchanged. `confidence_audit_cases.jsonl` contains 56 new test requests with no exact
overlap with the old set. Semantic categories still overlap; all cases are synthetic.

Retain the original temperature method. Add a distinct prediction-correctness
estimator: fixed raw-top-probability bins at 0/.5/.75/.9/1. In each bin, estimate
correctness with (correct+1)/(count+2). Bins with fewer than eight calibration
examples pool the calibration partition. No validation/test label enters the fit.

Select/ship the estimator only if correctness Brier and five-bin ECE do not worsen
on validation and the fresh final audit. This measures confidence in the predicted
label; it does not rewrite per-class probabilities or improve class accuracy.
Raw distributions, finite-sample Wilson intervals, pooled-bin flags and the scope
remain visible. The measured scope is this small synthetic task distribution,
not general calibration, real-home accuracy or a Jev comparison. A weak classifier
may have honestly low calibrated confidence; that is not permission to act.
