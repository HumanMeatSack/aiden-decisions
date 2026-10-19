# Local decision benchmark

56 frozen synthetic examples cover household routing, topic classification,
contrastive yes/no facts, negation, injected instructions inside data and ordered
rubric judgments. They were authored before the first inference run. No Jev API,
private recordings, real customer records or live appliance actions are involved.

Run `python scripts/benchmark_decisions.py`. The report
records the exact corpus hash, all answers, errors, review flags, local token
counts and timing. Repeated requests bypass the cache during evaluation. No
training or threshold fitting is performed on these cases.

The cases are small and relatively straightforward. Agreement is a useful smoke
test, not a claim of general intelligence, prompt-injection resistance or parity
with Jev. Brier score over the small yes/no subset does not establish calibration.

Public export: personal aliases have been replaced by generic bedroom labels.
These are fixed regression examples, not a new blind evaluation dataset.
