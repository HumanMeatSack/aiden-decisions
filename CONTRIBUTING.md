# Contributing

Install `.[mcp]`, run `python -m unittest discover -s tests -v`, and run
`python scripts/check_release.py` before opening a pull request.

For a model or question change, record the model digest, dataset hash and both
mistakes and successes. Keep evaluation labels separate from parameter fitting.
Do not copy an old calibration fingerprint onto a different model/question map.

Use synthetic examples. Do not include credentials, real customer records,
home/device configuration, captured conversations or model weights in reports.
Small reproducible bug reports and portable examples are especially welcome.

The roadmap starts with configurable example intent catalogs, domain-specific
evaluation corpora and additional decision-capable local backends. Keep the
decision layer independent of execution and credentials.
