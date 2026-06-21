# SIC-SCS — Semantic Self-Check Sensor (BRSCP)

> An AI agent self-verification protocol that runs before an agent declares a task complete.
> **Core principle: whoever wants completion cannot define completion alone.**

[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![Red Team](https://img.shields.io/badge/red--team-23%2F23%20blocked-brightgreen)]()
[![License](https://img.shields.io/badge/code-Apache%202.0-blue)]()
[![Docs](https://img.shields.io/badge/docs-CC%20BY%204.0-lightgrey)]()

---

## What is this

BRSCP (Bidirectional Recursive Self-Check Protocol), internally **SCS** (Self-Check Sensor),
is a governance protocol for the moment an AI agent is about to say "done".

It addresses two failure modes from the MAST taxonomy (1642 multi-agent failures):
- **Premature termination** — declaring complete before the work actually is.
- **FM-3.3 (Incorrect Verification)** — an agent grading its own work and inflating.

Unlike guardrails, every gate is **agent self-assessment**, not user-signal detection.
The user appears only in the ESCALATE path.

## Quick start

```bash
git clone https://github.com/Endwar116/sic-scs.git
cd sic-scs
PYTHONPATH=src python3 tests/test_v06_integration.py    # → 5/5
PYTHONPATH=src python3 tests/v06_comprehensive_selftest.py  # → 45/45
PYTHONPATH=src python3 tests/v06_redteam_attacks.py     # → 15/15 blocked
```

## Architecture (v0.6)

```
Task start
  → TSIG (infer task_spec, shown as first line to user)
  → ISAG-1 (intent-spec alignment, pre-freeze)
  → task_spec FREEZE (hash lock)
  → [agent does the work]
  → SJL → SCS → G1 → G2 → G3          (six self-assessment gates)
  → ECG (+ SGD)   evidence capture, anti gaming
  → ISAG-2         intent-spec alignment, pre-closure
  → JIIG (+ PD)   judge input integrity, anti paraphrase
  → G4G5 (adversarial self-judge)
  → TIG            temporal integrity (hash lock, anti post-gate tamper)
  → G6 + closure rerun
  → COMPLETE / COMPLETE_WITH_EVIDENCE_HARDENING / CONTINUE / ESCALATE
```

## Three operating modes

| Mode | Condition | Capability |
|------|-----------|-----------|
| FULL | SIC-JS record present | 100% |
| DEGRADED | inline task_spec, no SIC-JS | 95% (sweet spot) |
| MINIMAL | nothing | 20% (self-assessment only) |

**Key insight: the value is in the checklist (G3), not in SIC-JS.** A three-line
inline task_spec gets you to 95%.

## Modules

| Module | Role | Defends against |
|--------|------|-----------------|
| `brscp_v04.py` | main protocol (6 gates + orchestration) | premature termination |
| `tsig_module.py` | task-spec inference | user not writing a spec |
| `evidence_capture_gate.py` (ECG) | evidence capture | selective evidence feeding |
| `intent_spec_alignment_gate.py` (ISAG) | intent-spec alignment | task_spec sandbagging |
| `judge_input_integrity_gate.py` (JIIG) | judge input integrity | judge sees only executor summary |
| `temporal_integrity_gate.py` (TIG) | temporal integrity | post-gate modification |
| `paraphrase_detector.py` (PD) | JIIG hardening | paraphrase attacks |
| `schema_gaming_detector.py` (SGD) | ECG hardening | N/A / template / empty gaming |
| `multi_agent_consensus.py` | consensus | conflicting verdicts across agents |
| `a2a_escalate_adapter.py` | A2A binding | ESCALATE → standard protocol |

## Status & honest limitations

This is **v0.6, research-grade**. What is true:
- All tests pass; red team 23/23 blocked (8 v0.5 + 15 v0.6).
- Capability percentages (100/95/20) are **structural coverage estimates**, not measured interception rates.
- FM-3.3 is **mitigated, not solved** — the judge is still the agent itself. Full independence needs a separate judge agent (see specs/).
- LLM experiments used an internal proxy (labeled INTERNAL_PROXY_TEST), not third-party validation.

See `docs/` and `specs/` for the full picture.

## License

- **Code** (`src/`, `tests/`): Apache 2.0 — see [LICENSE](LICENSE)
- **Docs & specs** (`docs/`, `specs/`): CC BY 4.0 — see [LICENSE-DOCS](LICENSE-DOCS)

## Citation

```bibtex
@software{brscp_scs_2026,
  author = {Andwar (鄭安驊)},
  title  = {SIC-SCS: A Self-Check Protocol for AI Agent Task Completion},
  year   = {2026},
  url    = {https://github.com/Endwar116/sic-scs}
}
```

## Acknowledgements

Developed within the SIC-SIT / IMCC multi-agent ecosystem.
