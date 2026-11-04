# Documentation claim auditor

An offline static checker for documentation promises and Python call evidence.
It reads root README.md and Markdown beneath any docs directory, excluding
fenced blocks. Inline code counts. Python is parsed without execution.
Symlinks, fixtures, examples and documentation sources do not supply production
evidence; tests are reported separately. Each complete evidence pair must occur
in a single module. Static matches indicate call shapes, not runtime correctness.

Install and run:

```sh
python3 -m pip install .
voice-conversion-claim-audit .
python3 -m voice_conversion_claim_audit . --json
python3 -m voice_conversion_claim_audit . --ignore build --ignore dist --verbose
python3 -m voice_conversion_claim_audit . --fail-on MEDIUM
python3 -m voice_conversion_claim_audit --version
```

Exit status is 0 for results below the threshold, 2 for findings meeting it,
and 1 for usage or input errors. The default threshold is HIGH; LOW and MEDIUM
are also accepted. JSON includes verdict, findings with messages, inspected
paths and evidence paths. A test-only finding has MEDIUM severity. A missing
production implementation or a contradicted denial has HIGH severity.

Finding identifiers:

```text
documented-voice-conversion-claim-false
documented-no-voice-conversion-claim-false
```

Development:

```sh
python3 -m unittest discover
python3 -m build
```

Version 0.1.0. MIT licensed. The checker uses no network and writes no files.
