"""
BRSCP v0.6 Comprehensive Self-Test
三個新模組的完整驗證：TIG + Paraphrase Detector + Schema Gaming Detector

驗收標準：每個模組 ≥10 cases，全部通過
"""

import sys
import os
import json

# Add parent to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from temporal_integrity_gate import (
    lock_deliverables, verify_integrity, closure_rerun_check,
    verify_manifest_self_integrity, TIGVerdict, TIGManifest
)
from paraphrase_detector import (
    detect_paraphrase, ngram_overlap, synonym_aware_similarity,
    structural_similarity, ParaphraseVerdict
)
from schema_gaming_detector import (
    validate_bundle_quality, check_field_quality, check_duplicate_fields,
    SGDVerdict
)


def run_tig_tests():
    """15 test cases for Temporal Integrity Gate."""
    results = []
    
    bundle = {
        "task_id": "T-001",
        "intent": "Build login page",
        "test_results": [{"id": 0, "status": "PASS"}],
        "deliverables": ["login.py"],
    }
    
    # 1. Lock and verify unchanged
    m = lock_deliverables(bundle, gate_verdicts={"ECG": "PASS"})
    r = verify_integrity(bundle, m)
    results.append(("TIG-01: Unchanged → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # 2. Single field tampered
    r = verify_integrity({**bundle, "intent": "Build signup page"}, m)
    results.append(("TIG-02: Field tampered → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # 3. Field removed
    r = verify_integrity({"task_id": "T-001"}, m)
    results.append(("TIG-03: Fields removed → MISSING", r["verdict"] == TIGVerdict.MISSING))
    
    # 4. List content changed
    r = verify_integrity({**bundle, "test_results": [{"id": 0, "status": "FAIL"}]}, m)
    results.append(("TIG-04: List content changed → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # 5. New field added (should be INTACT)
    r = verify_integrity({**bundle, "bonus": "extra"}, m)
    results.append(("TIG-05: New field added → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # 6. File integrity - create, lock, verify
    test_file = "/tmp/tig_test_v06.txt"
    with open(test_file, 'w') as f:
        f.write("original content v0.6")
    m_file = lock_deliverables(bundle, file_paths=[test_file])
    r = verify_integrity(bundle, m_file)
    results.append(("TIG-06: File intact → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # 7. File modified
    with open(test_file, 'w') as f:
        f.write("TAMPERED content v0.6")
    r = verify_integrity(bundle, m_file)
    results.append(("TIG-07: File modified → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # 8. File deleted
    os.remove(test_file)
    r = verify_integrity(bundle, m_file)
    results.append(("TIG-08: File deleted → MISSING", r["verdict"] == TIGVerdict.MISSING))
    
    # 9. Closure rerun - no change
    m1 = lock_deliverables(bundle)
    m2 = lock_deliverables(bundle)
    r = closure_rerun_check(m1, m2)
    results.append(("TIG-09: Closure no change → can_complete", r["can_complete"] == True))
    
    # 10. Closure rerun - material change
    m3 = lock_deliverables({**bundle, "intent": "Different intent"})
    r = closure_rerun_check(m1, m3)
    results.append(("TIG-10: Closure material change → cannot_complete", r["can_complete"] == False))
    
    # 11. Manifest self-integrity
    md = m1.to_dict()
    r = verify_manifest_self_integrity(md)
    results.append(("TIG-11: Manifest self-check → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # 12. Manifest tampered
    md_bad = {**md, "entries": {"fake": "hash123"}}
    r = verify_manifest_self_integrity(md_bad)
    results.append(("TIG-12: Manifest tampered → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # 13. Empty bundle lock
    m_empty = lock_deliverables({})
    r = verify_integrity({}, m_empty)
    results.append(("TIG-13: Empty bundle → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # 14. Integrity score = 1.0 for intact
    r = verify_integrity(bundle, m1)
    results.append(("TIG-14: Score = 1.0", r["integrity_score"] == 1.0))
    
    # 15. Gate verdicts preserved
    m_gv = lock_deliverables(bundle, gate_verdicts={"ECG": "PASS", "JIIG": "PASS", "ISAG": "ALIGNED"})
    results.append(("TIG-15: Gate verdicts preserved", len(m_gv.gate_verdicts) == 3))
    
    return results


def run_paraphrase_tests():
    """15 test cases for Paraphrase Detector."""
    results = []
    
    # 1. Identical → PARAPHRASE
    r = detect_paraphrase("I completed all tasks", "I completed all tasks")
    results.append(("PD-01: Identical → PARAPHRASE", r["verdict"] == ParaphraseVerdict.PARAPHRASE))
    
    # 2. Completely different → INDEPENDENT
    r = detect_paraphrase(
        "The weather is sunny in Tokyo today",
        "Please evaluate the code quality metrics",
    )
    results.append(("PD-02: Different → INDEPENDENT", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # 3. Synonym substitution
    r = detect_paraphrase(
        "I built the login page and verified all tests pass",
        "I created the login page and validated all tests succeed",
    )
    results.append(("PD-03: Synonym sub → detected", r["verdict"] != ParaphraseVerdict.INDEPENDENT))
    
    # 4. Passive voice conversion
    r = detect_paraphrase(
        "I completed the task and fixed all bugs in the system",
        "The task was completed and all bugs in the system were fixed",
    )
    results.append(("PD-04: Passive voice → detected", r["verdict"] != ParaphraseVerdict.INDEPENDENT))
    
    # 5. Independent but related
    r = detect_paraphrase(
        "I implemented OAuth2 authentication with JWT tokens",
        "Check if authentication follows security best practices",
    )
    results.append(("PD-05: Related independent → INDEPENDENT", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # 6. Near-duplicate with minor edit
    r = detect_paraphrase(
        "The system handles all edge cases correctly and efficiently",
        "The system handles all edge cases correctly and effectively",
    )
    results.append(("PD-06: Near-duplicate → detected", r["verdict"] != ParaphraseVerdict.INDEPENDENT))
    
    # 7. Structural similarity with different content
    r = detect_paraphrase(
        "The application was developed quickly. All features work correctly. No bugs found.",
        "The platform was built rapidly. All components function properly. No issues detected.",
    )
    results.append(("PD-07: Structural para → detected", r["verdict"] != ParaphraseVerdict.INDEPENDENT))
    
    # 8. Short text handling
    r = detect_paraphrase("ok", "fine")
    results.append(("PD-08: Short text → no crash", r is not None))
    
    # 9. Empty text handling
    r = detect_paraphrase("", "something")
    results.append(("PD-09: Empty text → INDEPENDENT", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # 10. N-gram overlap function
    score = ngram_overlap("the quick brown fox", "the quick brown dog", n=2)
    results.append(("PD-10: N-gram overlap works", 0 < score < 1))
    
    # 11. Synonym similarity function
    score = synonym_aware_similarity(
        "I built and tested the system",
        "I created and verified the application",
    )
    results.append(("PD-11: Synonym similarity > 0.5", score > 0.5))
    
    # 12. Strict mode more sensitive
    r_strict = detect_paraphrase("I finished the work", "I completed the task", mode="strict")
    r_lenient = detect_paraphrase("I finished the work", "I completed the task", mode="lenient")
    results.append(("PD-12: Strict ≥ lenient sensitivity", r_strict["combined_score"] >= r_lenient["combined_score"] * 0.9))
    
    # 13. Chinese text → no crash
    r = detect_paraphrase("我完成了任務", "Please check the results")
    results.append(("PD-13: Chinese → no crash", r is not None))
    
    # 14. Long text handling
    long_a = "I built a comprehensive system. " * 20
    long_b = "I created a comprehensive platform. " * 20
    r = detect_paraphrase(long_a, long_b)
    results.append(("PD-14: Long text → detected", r["verdict"] != ParaphraseVerdict.INDEPENDENT))
    
    # 15. Combined score range [0, 1]
    r = detect_paraphrase("alpha beta gamma", "delta epsilon zeta")
    results.append(("PD-15: Score in [0,1]", 0 <= r["combined_score"] <= 1))
    
    return results


def run_sgd_tests():
    """15 test cases for Schema Gaming Detector."""
    results = []
    
    # 1. Genuine bundle
    genuine = {
        "task_id": "T-001",
        "intent_summary": "Build a login page with email validation and error handling",
        "test_results": [{"id": 0, "status": "PASS", "detail": "All tests green"}],
        "deliverable_paths": ["src/login.py", "src/login.html"],
    }
    r = validate_bundle_quality(genuine)
    results.append(("SGD-01: Genuine → GENUINE", r["verdict"] == SGDVerdict.GENUINE))
    
    # 2. All N/A
    na_bundle = {"task_id": "N/A", "intent": "n/a", "results": "none"}
    r = validate_bundle_quality(na_bundle)
    results.append(("SGD-02: All N/A → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # 3. Empty strings
    empty_bundle = {"task_id": "", "intent": " ", "results": "\n"}
    r = validate_bundle_quality(empty_bundle)
    results.append(("SGD-03: Empty strings → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # 4. Template placeholders
    template_bundle = {"task_id": "[INSERT]", "intent": "TODO: fill", "path": "<path>"}
    r = validate_bundle_quality(template_bundle)
    results.append(("SGD-04: Templates → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # 5. Duplicate content
    dup_bundle = {
        "field_a": "everything works perfectly fine",
        "field_b": "everything works perfectly fine",
        "field_c": "everything works perfectly fine",
    }
    r = validate_bundle_quality(dup_bundle)
    results.append(("SGD-05: Duplicates → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # 6. Repetitive characters
    r = check_field_quality("xxxxxxxxxxxxx")
    results.append(("SGD-06: Repetitive → GAMING", r["quality"] == "GAMING"))
    
    # 7. Repeated word
    r = check_field_quality("test test test test test")
    results.append(("SGD-07: Repeated word → GAMING", r["quality"] == "GAMING"))
    
    # 8. Null value
    r = check_field_quality(None)
    results.append(("SGD-08: Null → GAMING", r["quality"] == "GAMING"))
    
    # 9. Valid number
    r = check_field_quality(100)
    results.append(("SGD-09: Number → GENUINE", r["quality"] == "GENUINE"))
    
    # 10. Valid boolean
    r = check_field_quality(True)
    results.append(("SGD-10: Boolean → GENUINE", r["quality"] == "GENUINE"))
    
    # 11. Empty list
    r = check_field_quality([])
    results.append(("SGD-11: Empty list → GAMING", r["quality"] == "GAMING"))
    
    # 12. List with gaming items
    r = check_field_quality(["N/A", "none", "null"])
    results.append(("SGD-12: Gaming list → GAMING", r["quality"] == "GAMING"))
    
    # 13. Valid list
    r = check_field_quality(["src/login.py", "src/auth.py", "tests/test_login.py"])
    results.append(("SGD-13: Valid list → GENUINE", r["quality"] == "GENUINE"))
    
    # 14. Single N/A in otherwise good bundle
    mixed = {
        "task_id": "T-001",
        "intent": "Build comprehensive auth system",
        "results": [{"status": "PASS"}],
        "notes": "N/A",
    }
    r = validate_bundle_quality(mixed)
    results.append(("SGD-14: Single N/A → SUSPICIOUS", r["verdict"] == SGDVerdict.SUSPICIOUS))
    
    # 15. Gaming score range
    r = validate_bundle_quality(genuine)
    results.append(("SGD-15: Gaming score in [0,1]", 0 <= r["gaming_score"] <= 1))
    
    return results


def main():
    """Run all tests and produce summary."""
    print("\n" + "=" * 70)
    print("BRSCP v0.6 COMPREHENSIVE SELF-TEST")
    print("=" * 70)
    
    all_results = []
    
    # TIG Tests
    tig_results = run_tig_tests()
    all_results.extend(tig_results)
    tig_passed = sum(1 for _, ok in tig_results if ok)
    print(f"\n--- Temporal Integrity Gate: {tig_passed}/{len(tig_results)} ---")
    for desc, ok in tig_results:
        print(f"  {'✓' if ok else '✗'} {desc}")
    
    # Paraphrase Tests
    pd_results = run_paraphrase_tests()
    all_results.extend(pd_results)
    pd_passed = sum(1 for _, ok in pd_results if ok)
    print(f"\n--- Paraphrase Detector: {pd_passed}/{len(pd_results)} ---")
    for desc, ok in pd_results:
        print(f"  {'✓' if ok else '✗'} {desc}")
    
    # SGD Tests
    sgd_results = run_sgd_tests()
    all_results.extend(sgd_results)
    sgd_passed = sum(1 for _, ok in sgd_results if ok)
    print(f"\n--- Schema Gaming Detector: {sgd_passed}/{len(sgd_results)} ---")
    for desc, ok in sgd_results:
        print(f"  {'✓' if ok else '✗'} {desc}")
    
    # Summary
    total = len(all_results)
    passed = sum(1 for _, ok in all_results if ok)
    failed = total - passed
    
    print(f"\n{'=' * 70}")
    print(f"TOTAL: {total}  PASS: {passed}  FAIL: {failed}")
    print(f"{'=' * 70}")
    
    if failed > 0:
        print("\nFAILED TESTS:")
        for desc, ok in all_results:
            if not ok:
                print(f"  ✗ {desc}")
    
    # Save results to JSON
    results_json = {
        "timestamp": "2026-06-21",
        "version": "0.6",
        "total": total,
        "passed": passed,
        "failed": failed,
        "modules": {
            "TIG": {"passed": tig_passed, "total": len(tig_results)},
            "PD": {"passed": pd_passed, "total": len(pd_results)},
            "SGD": {"passed": sgd_passed, "total": len(sgd_results)},
        },
        "all_pass": failed == 0,
    }
    
    results_path = os.path.join(os.path.dirname(__file__), "v06_selftest_results.json")
    with open(results_path, 'w') as f:
        json.dump(results_json, f, indent=2)
    print(f"\nResults saved to: {results_path}")
    
    return passed, total


if __name__ == "__main__":
    passed, total = main()
    sys.exit(0 if passed == total else 1)
