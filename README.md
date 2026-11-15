# BRSCP — Bidirectional Recursive Self-Check Protocol

> Rules for the moment an AI agent is about to say "done".
> **Core principle: whoever wants completion cannot define completion alone.**
> 中文摘要在最下面。

[![Release](https://img.shields.io/badge/release-v0.7.0--rc.1-orange)]()
[![Code](https://img.shields.io/badge/code-Apache%202.0-blue)]()
[![Docs](https://img.shields.io/badge/docs-CC%20BY%204.0-lightgrey)]()

---

## Two lines, two version numbers — read this first

BRSCP has two separate lines. **Their version numbers are not comparable.**

| Line | What it is | Where | Current |
|---|---|---|---|
| **Prompt-protocol line** | Text you paste into a prompt. It tells the model when it may claim `complete`, when to `continue`, and when to `escalate` — and that escalating needs evidence too. | [`protocol/`](protocol/) | **0.7 (candidate, not finalized)**; 1.0-rc1 is experimental and failed its acceptance test |
| **Code-gate line** (SCS) | Python gates that run at closure time (evidence capture, intent alignment, judge-input integrity, temporal integrity, …). | [`src/`](src/), [`tests/`](tests/) | 0.6 (unchanged in this release) |

The repository release tag (`v0.7.0-rc.1`) follows the prompt-protocol line, because that is what changed.

## What is new in v0.7.0-rc.1

1. **Prompt protocol 0.7** ([`protocol/v0.7/`](protocol/v0.7/)) — three risk tiers (L0 / L1 / L2), three terminal states, and a burden of proof on *both* `complete` and `escalate`. A state-machine checker scores the old 0.6 rules 4/9 and 0.7 rules 9/9.
2. **Prompt protocol 1.0-rc1** ([`protocol/v1.0-rc1/`](protocol/v1.0-rc1/)) — the opposite direction: *deliver by default*, escalate only with a minimal failing case. **Not released**: its acceptance experiment could not reach a verdict, and the direct criteria were not met.
3. **Part-2 benchmark** ([`experiments/part2_2026-10-18/`](experiments/part2_2026-10-18/)) — four new free models × 9 configurations × 100 items (3,600 calls). Pre-registration, analysis code, aggregated tables and the report. Raw answers and the question bank are not public (see that folder's README).
4. **External-review design** ([`reviewer/`](reviewer/)) — the fifth "valve" part: a different model checks the answer before it is delivered. Scope research, engineering spec, a pre-registration draft and a reference contract (23/23 self-tests). **No model experiment has been run yet.**
5. **Version table and the adjustable valve** ([`docs/VERSIONS_AND_VALVE.zh-TW.md`](docs/VERSIONS_AND_VALVE.zh-TW.md)) — every version since January, the five valve parts, and which configuration to use per scenario.

Full list: [`CHANGELOG.md`](CHANGELOG.md).

## What the experiments say (and do not say)

Scope: one task type (judge whether a delivery is complete, ~100 items per cell), free cloud models only.

**Can say**
- Protocol text changes *whether a model dares to deliver*. 0.7 pushes models toward escalating; 1.0 pushes them toward delivering.
- For general and delivery-oriented scenarios, all four Part-2 models had the lowest expected cost with cell ⑨ (SIC-JS 3.0 question format + a short primer + 1.0 G layer). Per true completion it was 3.8×–7.3× cheaper in tokens (all intervals above 1).
- Adding a short primer to the question bank makes models deliver more — reproduced in July, October 1 and Part 2.

**Cannot say**
- That any protocol makes models more accurate (no detected difference in all-correct rate).
- That any protocol lets a model pick out its own wrong answers (the "selection gap" is near 0; best +0.14 across 36 cells).
- That 1.0 delivers fewer wrong answers than no protocol. Against the clean baseline, three of four models delivered *more* wrong answers.
- That results transfer to other task types.

That last gap is why external review (part 5 of the valve) is the next step.

## Repository map

```
protocol/            prompt-protocol line
  v0.7/              current candidate: tiers/L0–L2, routing.json, reference impl, state-machine check
  v1.0-rc1/          experimental, not released
reviewer/            external-review design (design + reference contract; not experimentally accepted)
experiments/
  part2_2026-10-18/  Part-2 benchmark: prereg, code, aggregated data, report v0.2
  V06_REDTEAM_REPORT.md
docs/                protocol docs (v0.1 text) + version table and valve
specs/               code-gate specs (0.5 / 0.6)
src/, tests/         code-gate line 0.6
REDACTION_LOG.md     what was de-identified before publishing
```

## Quick start

No third-party packages. Tested on Python 3.12.

```bash
git clone https://github.com/Endwar116/BRSCP.git
cd BRSCP

# prompt protocol 0.7 — the checker writes a results file, so run it on a copy
cp -R protocol/v0.7 /tmp/brscp_v07 && cd /tmp/brscp_v07
python3 -B state_machine_check.py     # → v0.6: 4/9   v0.7: 9/9, exit 0
python3 -B brscp_v07.py               # → tier selection + prompt assembly demo
cd -

# external-review reference contract
cd reviewer && python3 -B -m unittest test_contract.py   # → 23 tests OK
cd ..

# code-gate line 0.6
PYTHONPATH=src python3 tests/test_v06_integration.py
PYTHONPATH=src python3 tests/v06_comprehensive_selftest.py
PYTHONPATH=src python3 tests/v06_redteam_attacks.py
```

## Using prompt protocol 0.7

1. Pick a tier by risk with `routing.json` (reference: `select_tier()` in `brscp_v07.py`). Irreversible, external, money, or security/privacy → L2. Unclear risk → L2. You may go up a tier, never down.
2. Paste the tier text **at the end** of the prompt. L0 is 483 characters, L1 1,189, L2 1,528.
3. Read `claimed_status`: `complete` needs evidence for every criterion; `escalate` needs (1) what was tried, (2) why it failed, (3) who must provide what.

Field note: on two small free models, the L0 tier did **not** reduce false completion (it was ≈1.0 under every condition). Protocol text alone does not fix this; the runner has to enforce escalation in code.

---

# 🙋 HELP WANTED

Contributions follow [`CONTRIBUTING.md`](CONTRIBUTING.md): evidence, not claims; pre-register experiments; red-team your own change.

## 1. Run the external-review experiment

The design is in [`reviewer/`](reviewer/). Needed: a replay runner that sends anonymized items and structured answers to a reviewer model from a **different family**, records every raw output, and keeps failed rows. Upper bound of the main replay: about 5,580 model calls. Then measure: catch rate, false-block rate, cost per item.

## 2. A second task type

All conclusions come from one task type. Needed: at least 50 code-fix items **where tests decide the ground truth**, not a model.

## 3. A clean "no protocol" baseline that actually delivers

In Part 2 the no-protocol group delivered only 9–14 items, so "1.0 is no worse than no protocol" could not be tested. Needed: a pre-registered design where the control group delivers enough items (for example, no escalate option, or a forced-delivery control).

## 4. Local-model anchors

Re-run the 9 cells on at least two local models, so the results do not rest on free cloud endpoints only.

## 5. L0 wording sweep

Finalizing 0.7 still requires a wording sweep of the L0 tier (condition 1 in `protocol/v0.7/BRSCP_v0.7_PROTOCOL.md`). It has not been done.

---

## Status & honest limitations

- 0.7 is a **candidate**. Finalizing it, and deciding whether to seal 1.0, is the project owner's call — a protocol about not self-certifying completion does not self-certify its own release.
- Part 2 was designed and analyzed by one agent; no third-party replication yet. Intervals for some comparisons were computed after the fact (stated in the report).
- The code-gate line's capability percentages (100 / 95 / 20) are structural coverage estimates, not measured interception rates. FM-3.3 is mitigated, not solved.

## Contributors

Developed inside the SIC-SIT / IMCC multi-agent ecosystem. Prompt protocol 0.7 by 德德; 1.0 proposal, 1.0-rc1 and the Part-2 benchmark by 協德; external-review design by 扣評; code-gate 0.6 integration by 扣德; field test of 0.7 by VS德. All are AI agents working for the project owner.

## License

- **Code** (`*.py` anywhere, `src/`, `tests/`): Apache 2.0 — see [LICENSE](LICENSE)
- **Docs, specs, protocol text, reports and data tables** (`docs/`, `specs/`, and the non-code files in `protocol/`, `reviewer/`, `experiments/`): CC BY 4.0 — see [LICENSE-DOCS](LICENSE-DOCS)

## Citation

```bibtex
@software{brscp_2026,
  author  = {Andwar (鄭安驊)},
  title   = {BRSCP: A Self-Check Protocol for AI Agent Task Completion},
  year    = {2026},
  version = {0.7.0-rc.1},
  url     = {https://github.com/Endwar116/BRSCP}
}
```

---

## 中文摘要

- BRSCP 有兩條線，版號不能互比：**提示協議線**（貼進 prompt 的文字，在 `protocol/`，現行 0.7 候選版）和**程式閘線**（收尾時跑的程式，在 `src/`，仍是 0.6）。
- 這一版新增：0.7 條文與檢查程式、1.0 試跑版（驗收沒過、不發行）、第二部分基準測試、外部核對設計、版本總表與可調閥。
- 實驗結論：協議只改「敢不敢交」，沒改「分辨得出自己哪題錯」；一般與交付導向場景，第 ⑨ 格成本最低；交出去的錯答案沒有變少。
- 下一步是外部核對：交出前讓另一家模型看過。設計已在 `reviewer/`，實驗還沒跑。
- 需要協助的五件事見上面 **HELP WANTED**。
