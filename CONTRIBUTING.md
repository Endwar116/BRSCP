# Contributing to SIC-SCS

## The one rule that matters

This project builds a protocol whose core principle is:
**whoever wants completion cannot define completion alone.**

So contributions follow the same discipline the protocol enforces:

1. **No single-shot delivery.** A PR includes: the change, before/after diff,
   failed attempts, and a closure justification.
2. **Evidence, not claims.** "Tests pass" must be reproducible: include the
   command and its output. CI must be green.
3. **Red-team your own change.** List at least 3 weaknesses of your own PR.
   "I found none" means you didn't look hard enough.

## Running tests

```bash
PYTHONPATH=src python3 tests/test_v06_integration.py
PYTHONPATH=src python3 tests/v06_comprehensive_selftest.py
PYTHONPATH=src python3 tests/v06_redteam_attacks.py
```

## Scope discipline

- Gate logic is tested (red team 23/23). Don't change gate internals without re-running all red-team suites.
- Integration is "wiring", not rewriting.

## License

Code contributions are under Apache 2.0. Docs under CC BY 4.0.
