"""
test_v06_integration.py — BRSCP v0.6 three-gate integration test (dogfood)
==========================================================================
Proves the three governance gates are ACTUALLY WIRED into brscp_v04.check(),
not merely importable. Each case forces one gate to fire.

  A. legacy caller (no governance inputs)  → gates SKIPPED, COMPLETE (back-compat)
  B. faithful spec + honest bundle + clean judge io → COMPLETE (gates allow)
  C. sandbagged task_spec (broad request, narrow spec) → ISAG-1 blocks
  D. hollow evidence bundle (missing required fields)  → ECG blocks
  E. tampered judge verdict (raw=CONTINUE, final=COMPLETE) → JIIG blocks

Run: python3 test_v06_integration.py   (exit 0 = all assertions passed)
"""
import os, sys, json, tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))

from brscp_v04 import BRSCPVerifier, TaskSpec, Deliverable


def make_self_judge(quote: str):
    """A self_judge that passes G4G5: >=3 flaws, a real citation, high scores."""
    def _judge(conversation, intent):
        return {
            "flaws_found": ["edge cases thin", "no perf test", "docs sparse"],
            "requirements_cited": [
                {"requirement": "wire gates", "evidence_quote": quote}
            ],
            "uncited_requirements": [],
            "quality_score": 0.9,
            "coverage_score": 1.0,
            "honest_ready": True,
            "tokens_used": 100,
        }
    return _judge


def good_bundle(raw_request: str) -> dict:
    """
    An honest, complete bundle that is a SUPERSET satisfying BOTH gate schemas:
      - ECG wants: deliverables_manifest, command_log, validator_outputs,
        failed_attempts, known_limitations, omitted_evidence_declaration, raw_user_request
      - JIIG wants: deliverables, test_results (incl. a failure so it's not all-pass)
    """
    return {
        # ECG fields
        "raw_user_request": raw_request,
        "deliverables_manifest": [],          # empty = skip file re-hash, no fail
        "command_log": [
            {"cmd": "python3 redteam_8_failure_modes.py", "exit_code": 0},
            {"cmd": "python3 brscp_v04.py --bad-flag", "exit_code": 1},  # a real failure
        ],
        "validator_outputs": [{"validator": "redteam", "result": "8/8"}],
        "failed_attempts": [
            {"description": "first wiring imported gates at wrong path; fixed via sys.path"}
        ],
        "known_limitations": ["gates self-report SKIPPED when governance inputs absent"],
        "omitted_evidence_declaration": [],   # explicit: nothing omitted
        # JIIG fields (judge must see deliverables + tests incl. a failure)
        "deliverables": [{"type": "code", "path": "brscp_v04.py"}],
        "test_results": [
            {"test": "redteam_8fm", "result": "pass"},
            {"test": "isag_edge_case", "result": "fail"},   # a real failure shown to judge
        ],
    }


def run():
    results = []
    quote = "i wired ECG ISAG JIIG into the brscp check flow"
    convo = [
        {"role": "user", "content": "integrate the three gates"},
        {"role": "assistant", "content": "Done. " + quote + " at the spec'd positions."},
    ]
    tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    tmp.write(b"deliverable artifact"); tmp.close()
    deliv = [Deliverable(id="d1", description="artifact",
                         validator_type="file_exists",
                         validator_args={"path": tmp.name})]

    BROAD = ("Integrate all three gates, add a freeze mechanism, rerun the full "
             "redteam suite of 8 attacks, run tsig 41 tests, and verify zero "
             "regression across every existing gate. Do not converge early.")

    # ── A. legacy: no governance inputs → all gates SKIPPED, still COMPLETE ──
    vA = BRSCPVerifier(TaskSpec("tA", BROAD, deliv), make_self_judge(quote)).check(convo)
    okA = (vA.action == "COMPLETE"
           and any("SKIPPED" in n for n in vA.gate_notes)
           and sum("SKIPPED" in n for n in vA.gate_notes) >= 3)
    results.append(("A legacy→SKIPPED+COMPLETE", okA, f"{vA.action} | {vA.gate_notes}"))

    # ── B. faithful spec + honest bundle + clean judge io → COMPLETE (gates allow) ──
    faithful = BROAD  # spec intent faithfully echoes the request → ISAG ALIGNED
    vB = BRSCPVerifier(
        TaskSpec("tB", faithful, deliv), make_self_judge(quote),
        raw_user_request=BROAD,
        evidence_bundle=good_bundle(BROAD),
        judge_io={"executor_context": "I built the integration with gates A,B,C.",
                  "judge_context": "Independent review of evidence bundle and diffs.",
                  "judge_prompt_used": "You are an independent judge. Evaluate objectively.",
                  "canonical_prompt": "You are an independent judge. Evaluate objectively.",
                  "raw_judge_verdict": "COMPLETE", "final_verdict": "COMPLETE",
                  "judge_config": {"temperature": 0.5}},
    ).check(convo)
    okB = (vB.action in ("COMPLETE", "COMPLETE_WITH_EVIDENCE_HARDENING")
           and any("ISAG-1" in n and "ALIGNED" in n for n in vB.gate_notes)
           and any(n.startswith("ECG:") and "SKIPPED" not in n for n in vB.gate_notes)
           and any(n.startswith("JIIG:") and "SKIPPED" not in n for n in vB.gate_notes))
    results.append(("B good→gates ran+COMPLETE", okB, f"{vB.action} | {vB.gate_notes}"))

    # ── C. sandbagged spec → ISAG-1 blocks ──
    NARROW = "make a file"
    vC = BRSCPVerifier(
        TaskSpec("tC", NARROW, deliv), make_self_judge(quote),
        raw_user_request=BROAD,
    ).check(convo)
    okC = (vC.failed_gate or "").startswith("ISAG-1") and vC.action in ("CONTINUE", "ESCALATE")
    results.append(("C sandbag→ISAG-1 blocks", okC, f"{vC.action}/{vC.failed_gate} | {vC.gate_notes}"))

    # ── D. hollow evidence bundle → ECG blocks ──
    vD = BRSCPVerifier(
        TaskSpec("tD", BROAD, deliv), make_self_judge(quote),
        raw_user_request=BROAD,
        evidence_bundle={"deliverables": ["x.py"]},   # missing all required ECG fields
    ).check(convo)
    okD = vD.failed_gate == "ECG" and vD.action in ("CONTINUE", "ESCALATE")
    results.append(("D hollow→ECG blocks", okD, f"{vD.action}/{vD.failed_gate} | {vD.gate_notes}"))

    # ── E. tampered judge verdict → JIIG blocks ──
    vE = BRSCPVerifier(
        TaskSpec("tE", BROAD, deliv), make_self_judge(quote),
        raw_user_request=BROAD,
        evidence_bundle=good_bundle(BROAD),
        judge_io={"executor_context": "exec", "judge_context": "judge",
                  "judge_prompt_used": "You are an independent judge.",
                  "canonical_prompt": "You are an independent judge.",
                  "raw_judge_verdict": "CONTINUE", "final_verdict": "COMPLETE",  # tamper
                  "verdict_hash": "deadbeef", "judge_config": {"temperature": 0.5}},
    ).check(convo)
    okE = vE.failed_gate == "JIIG" and vE.action in ("ESCALATE", "CONTINUE")
    results.append(("E tamper→JIIG blocks", okE, f"{vE.action}/{vE.failed_gate} | {vE.gate_notes}"))

    # ── F. post-gate deliverable tampering → TIG blocks (v1.0) ──
    # Gates pass on the original file; the judge step then mutates the deliverable
    # AFTER the TIG lock. TIG closure must catch the byte change → ESCALATE.
    tmpF = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
    tmpF.write(b"original deliverable content"); tmpF.close()
    delivF = [Deliverable(id="dF", description="artifact",
                          validator_type="file_exists",
                          validator_args={"path": tmpF.name})]
    def tampering_judge(conversation, intent):
        # simulate post-gate tampering: overwrite the deliverable after it was locked
        with open(tmpF.name, "w") as fh:
            fh.write("TAMPERED content injected after gates passed")
        return {
            "flaws_found": ["edge cases thin", "no perf test", "docs sparse"],
            "requirements_cited": [{"requirement": "wire gates", "evidence_quote": quote}],
            "uncited_requirements": [], "quality_score": 0.9, "coverage_score": 1.0,
            "honest_ready": True, "tokens_used": 100,
        }
    vF = BRSCPVerifier(TaskSpec("tF", BROAD, delivF), tampering_judge).check(convo)
    okF = vF.failed_gate == "TIG" and vF.action == "ESCALATE"
    results.append(("F post-gate tamper→TIG blocks", okF, f"{vF.action}/{vF.failed_gate} | {vF.gate_notes}"))
    os.unlink(tmpF.name)

    os.unlink(tmp.name)

    print("=" * 70)
    print("BRSCP v0.6 — Three-Gate Integration Test (dogfood)")
    print("=" * 70)
    passed = 0
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        print(f"         {detail}")
        if ok: passed += 1
    print("-" * 70)
    print(f"  {passed}/{len(results)} cases passed")
    print("=" * 70)
    out = {"test": "brscp_v06_integration", "passed": passed, "total": len(results),
           "cases": [{"name": n, "ok": ok, "detail": d} for n, ok, d in results]}
    with open(os.path.join(_HERE, "test_v06_integration_results.json"), "w") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
