# Changelog

Two lines with separate version numbers (see README). Dates are Asia/Taipei.

## [v0.7.0-rc.1] — 2026-11-15

Repository release for the **prompt-protocol line 0.7 (candidate)**. Code-gate line unchanged at 0.6.

### Added
- `protocol/v0.7/` — prompt protocol 0.7 (2026-07-26): tiers L0 / L1 / L2, `routing.json` as the single source of truth for the state machine, reference implementation `brscp_v07.py` (`select_tier()`, prompt assembly), `state_machine_check.py` (0.6 rules 4/9, 0.7 rules 9/9), design notes and the 0.6→0.7 changelog. Byte-identical to the internal canonical copy.
- `protocol/v1.0-rc1/` — prompt protocol 1.0 trial text (2026-09-30): G layer, R layer, question-bank primer. **Experimental, not released** (see its README).
- `experiments/part2_2026-10-18/` — Part-2 benchmark: pre-registration, prereg lock, runner, analysis, difference-and-interval script, aggregated tables, report v0.2.
- `reviewer/` — external-review design v0.1 (2026-10-19): scope research, engineering spec, benchmark pre-registration draft, sources, validation notes, reference contract with 23 self-tests. Design delivered; not experimentally accepted.
- `docs/VERSIONS_AND_VALVE.zh-TW.md` — version history of the prompt-protocol line, the five-part adjustable valve, scenario recipes.
- `REDACTION_LOG.md` — de-identification done before publishing (categories and counts only).

### Changed
- `README.md` rewritten: two lines explained, findings with "can say / cannot say", help-wanted list. Fixed clone URL and citation (pointed to a repository name that does not exist publicly).
- `.gitignore`: ignore the results file that `state_machine_check.py` writes.

### History of the prompt-protocol line (before this repository tracked it)
| Date | Version | Note |
|---|---|---|
| 2026-01 | January edition | Name first used, as an engineering acceptance standard |
| 2026-06-21 | 0.1 | Chat-usable self-check text (`docs/BRSCP_PROTOCOL_v0.1.md`) |
| 2026-06-21 | 0.4–0.6 | Code modules and the three-gate spec (this repository's initial commit, tagged `v0.6.0`) |
| 2026-07-25 | — | Benchmark: pasting the whole 0.6-era text up front worked about as well as unrelated text of the same length; three closure break points found |
| 2026-07-26 | **0.7** | Risk tiers, burden of proof on escalate, state-machine fixes |
| 2026-07-28 | 1.0 proposal | Reverse direction: deliver by default; escalate needs a minimal failing case |
| 2026-09-18 | (0.7 field test) | On two free models, L0 did not reduce false completion; not adopted as a dispatch default |
| 2026-09-30 | 1.0-rc1 | Trial text written and pre-registered acceptance run |
| 2026-10-17 | (1.0 acceptance) | No verdict under the pre-registration; direct criteria not met; not sealed |
| 2026-10-18 | (Part 2) | 3,600 calls; cell ⑨ cheapest for general / delivery scenarios; no protocol made models catch their own errors |
| 2026-10-19 | (external review design) | Design and reference contract delivered; no model experiment |

## [v0.6.0] — 2026-06-21

Initial public release: code-gate line 0.6 (six self-assessment gates + ECG / ISAG / JIIG / TIG, red team 23/23 blocked). Tag added retroactively on the initial commit.
