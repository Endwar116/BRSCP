"""
BRSCP v0.5 — Evidence Capture Gate (ECG)
=========================================
Failure Mode #1: Evidence Bundle 被 executor 選擇性餵料

核心原則：
  「誰想完成，誰就不能單獨定義完成。」
  證據不能完全由 executor 整理。

必須包含：
  - 原始 user request (raw, immutable)
  - frozen task_spec (hash-locked)
  - deliverables manifest (file paths + hashes)
  - command log (all commands, not just successful ones)
  - validator outputs (raw stdout/stderr)
  - failed attempts (mandatory, not optional)
  - known limitations (executor must declare)
  - omitted evidence declaration (what was NOT included and why)

設計決策：
  - metadata 只能當線索，不能當證據
  - 證據要能被重新 stat、重新 hash、重新 parse logs
  - failed attempts 必須放進去（不然 agent 只交「畢業照」）
"""

import os
import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any
from enum import Enum

# ─── Constants ───────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE_ROOT = os.environ.get("BRSCP_ROOT", os.path.dirname(_HERE))

# Minimum required fields in an evidence bundle
REQUIRED_FIELDS = [
    "raw_user_request",
    "frozen_task_spec",
    "frozen_task_spec_hash",
    "deliverables_manifest",
    "command_log",
    "validator_outputs",
    "failed_attempts",
    "known_limitations",
    "omitted_evidence_declaration",
]

# ─── Data Structures ────────────────────────────────────────────────


class ECGVerdict(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class DeliverableEntry:
    path: str
    expected_hash: Optional[str] = None
    size_bytes: int = 0
    exists: bool = False
    actual_hash: Optional[str] = None
    integrity_ok: bool = False


@dataclass
class ECGResult:
    verdict: ECGVerdict
    missing_fields: List[str] = field(default_factory=list)
    integrity_failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    completeness_score: float = 0.0
    evidence_hash: str = ""
    timestamp: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


# ─── Core Functions ─────────────────────────────────────────────────


def compute_file_hash(filepath: str) -> Optional[str]:
    """Compute SHA-256 hash of a file. Returns None if file doesn't exist."""
    if not os.path.isfile(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]  # truncated for readability


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of string content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def verify_task_spec_frozen(bundle: Dict) -> tuple:
    """
    Verify that task_spec hasn't been modified after freezing.
    Returns (is_frozen: bool, detail: str)
    """
    spec = bundle.get("frozen_task_spec", "")
    declared_hash = bundle.get("frozen_task_spec_hash", "")
    
    if not spec:
        return False, "frozen_task_spec is empty"
    if not declared_hash:
        return False, "frozen_task_spec_hash is missing"
    
    actual_hash = compute_content_hash(json.dumps(spec, sort_keys=True, ensure_ascii=False)
                                        if isinstance(spec, dict) 
                                        else str(spec))
    
    if actual_hash != declared_hash:
        return False, f"INTEGRITY VIOLATION: declared={declared_hash}, actual={actual_hash}"
    
    return True, f"frozen, hash={actual_hash}"


def verify_deliverables(manifest: List[Dict], base_path: str = "") -> List[DeliverableEntry]:
    """
    Re-verify all deliverables by actually checking files.
    Does NOT trust declared metadata — re-stats and re-hashes everything.
    """
    results = []
    for item in manifest:
        path = item.get("path", "")
        if base_path and not os.path.isabs(path):
            path = os.path.join(base_path, path)
        
        entry = DeliverableEntry(path=path, expected_hash=item.get("hash"))
        
        if os.path.isfile(path):
            entry.exists = True
            entry.size_bytes = os.path.getsize(path)
            entry.actual_hash = compute_file_hash(path)
            
            # Integrity check: if expected hash provided, verify it
            if entry.expected_hash:
                entry.integrity_ok = (entry.actual_hash == entry.expected_hash)
            else:
                # No expected hash = can't verify integrity, but file exists
                entry.integrity_ok = True  # downgraded to existence check
        else:
            entry.exists = False
            entry.integrity_ok = False
        
        results.append(entry)
    
    return results


def check_failed_attempts(bundle: Dict) -> tuple:
    """
    Verify that failed_attempts is not empty or suspiciously clean.
    A real engineering process ALWAYS has failures.
    """
    attempts = bundle.get("failed_attempts", [])
    
    if attempts is None:
        return False, "failed_attempts is None (must be a list)"
    
    if not isinstance(attempts, list):
        return False, f"failed_attempts is {type(attempts).__name__}, must be list"
    
    if len(attempts) == 0:
        return False, "SUSPICIOUS: failed_attempts is empty — no real engineering has zero failures"
    
    # Check that each attempt has minimum structure
    valid_attempts = 0
    for attempt in attempts:
        if isinstance(attempt, dict) and "description" in attempt:
            valid_attempts += 1
        elif isinstance(attempt, str) and len(attempt) > 10:
            valid_attempts += 1
    
    if valid_attempts == 0:
        return False, "failed_attempts contains no valid entries (need description or >10 char string)"
    
    return True, f"{valid_attempts} valid failed attempts documented"


def check_omitted_evidence(bundle: Dict) -> tuple:
    """
    Verify that omitted_evidence_declaration exists and is explicit.
    If nothing was omitted, must explicitly say so.
    """
    declaration = bundle.get("omitted_evidence_declaration")
    
    if declaration is None:
        return False, "omitted_evidence_declaration is missing (must be explicit, even if empty)"
    
    if isinstance(declaration, str):
        if len(declaration.strip()) == 0:
            return False, "omitted_evidence_declaration is blank (must state 'none' or list omissions)"
        return True, f"declaration present: {declaration[:80]}..."
    
    if isinstance(declaration, list):
        if len(declaration) == 0:
            # Explicitly empty list = "nothing omitted" — acceptable
            return True, "explicitly empty list (nothing omitted)"
        return True, f"{len(declaration)} omissions declared"
    
    return False, f"unexpected type: {type(declaration).__name__}"


def check_command_log(bundle: Dict) -> tuple:
    """
    Verify command_log is present and contains both successes and failures.
    """
    log = bundle.get("command_log", [])
    
    if not log:
        return False, "command_log is empty"
    
    if not isinstance(log, list):
        return False, f"command_log is {type(log).__name__}, must be list"
    
    # Check for exit codes or status indicators
    has_failure = False
    has_success = False
    for entry in log:
        if isinstance(entry, dict):
            code = entry.get("exit_code", entry.get("status", ""))
            if code in (0, "success", "pass", "PASS"):
                has_success = True
            elif code not in (None, ""):
                has_failure = True
        elif isinstance(entry, str):
            if "error" in entry.lower() or "fail" in entry.lower():
                has_failure = True
            else:
                has_success = True
    
    if not has_success and not has_failure:
        return False, "command_log has no interpretable entries"
    
    # Warning if no failures logged (suspicious)
    if has_success and not has_failure:
        return True, "WARNING: only successes logged — may be selective"
    
    return True, f"{len(log)} entries, has both successes and failures"


# ─── Main Gate Function ─────────────────────────────────────────────


def run_evidence_capture_gate(bundle: Dict, base_path: str = "") -> ECGResult:
    """
    Run the Evidence Capture Gate on a provided evidence bundle.
    
    This gate checks:
    1. Completeness: all required fields present
    2. Integrity: task_spec hash matches, file hashes match
    3. Honesty: failed attempts documented, omissions declared
    4. Non-selectivity: command log has failures, not just successes
    
    Returns ECGResult with verdict PASS/FAIL/WARN.
    """
    result = ECGResult(
        verdict=ECGVerdict.PASS,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S%z")
    )
    
    # ── Step 1: Completeness Check ──
    for field_name in REQUIRED_FIELDS:
        if field_name not in bundle or bundle[field_name] is None:
            result.missing_fields.append(field_name)
    
    if result.missing_fields:
        result.verdict = ECGVerdict.FAIL
        result.details["completeness"] = f"FAIL: missing {len(result.missing_fields)} required fields"
    else:
        result.details["completeness"] = "PASS: all 9 required fields present"
    
    # ── Step 2: Task Spec Integrity ──
    spec_frozen, spec_detail = verify_task_spec_frozen(bundle)
    result.details["task_spec_integrity"] = spec_detail
    if not spec_frozen and "frozen_task_spec" not in result.missing_fields:
        result.integrity_failures.append(f"task_spec: {spec_detail}")
        result.verdict = ECGVerdict.FAIL
    
    # ── Step 3: Deliverables Integrity ──
    manifest = bundle.get("deliverables_manifest", [])
    if manifest:
        deliverable_results = verify_deliverables(manifest, base_path)
        missing_files = [d for d in deliverable_results if not d.exists]
        integrity_fails = [d for d in deliverable_results if d.exists and not d.integrity_ok]
        
        if missing_files:
            result.integrity_failures.append(
                f"deliverables: {len(missing_files)} files missing"
            )
            result.verdict = ECGVerdict.FAIL
        
        if integrity_fails:
            result.integrity_failures.append(
                f"deliverables: {len(integrity_fails)} hash mismatches"
            )
            result.verdict = ECGVerdict.FAIL
        
        result.details["deliverables"] = {
            "total": len(manifest),
            "exists": len([d for d in deliverable_results if d.exists]),
            "integrity_ok": len([d for d in deliverable_results if d.integrity_ok]),
            "entries": [asdict(d) for d in deliverable_results]
        }
    
    # ── Step 4: Failed Attempts (Honesty Check) ──
    fa_ok, fa_detail = check_failed_attempts(bundle)
    result.details["failed_attempts"] = fa_detail
    if not fa_ok:
        if "SUSPICIOUS" in fa_detail:
            result.warnings.append(fa_detail)
            if result.verdict == ECGVerdict.PASS:
                result.verdict = ECGVerdict.WARN
        else:
            result.integrity_failures.append(f"failed_attempts: {fa_detail}")
            result.verdict = ECGVerdict.FAIL
    
    # ── Step 5: Omitted Evidence Declaration ──
    oe_ok, oe_detail = check_omitted_evidence(bundle)
    result.details["omitted_evidence"] = oe_detail
    if not oe_ok:
        result.integrity_failures.append(f"omitted_evidence: {oe_detail}")
        result.verdict = ECGVerdict.FAIL
    
    # ── Step 6: Command Log Non-Selectivity ──
    cl_ok, cl_detail = check_command_log(bundle)
    result.details["command_log"] = cl_detail
    if not cl_ok:
        result.integrity_failures.append(f"command_log: {cl_detail}")
        result.verdict = ECGVerdict.FAIL
    elif "WARNING" in cl_detail:
        result.warnings.append(cl_detail)
        if result.verdict == ECGVerdict.PASS:
            result.verdict = ECGVerdict.WARN
    
    # ── Compute Completeness Score ──
    total_checks = 6  # completeness, spec, deliverables, failed_attempts, omitted, cmd_log
    passed_checks = sum([
        len(result.missing_fields) == 0,
        spec_frozen,
        len(result.integrity_failures) == 0 or not manifest,
        fa_ok,
        oe_ok,
        cl_ok
    ])
    result.completeness_score = round(passed_checks / total_checks, 3)
    
    # ── Compute Evidence Bundle Hash (for chain) ──
    bundle_str = json.dumps(bundle, sort_keys=True, ensure_ascii=False, default=str)
    result.evidence_hash = hashlib.sha256(bundle_str.encode()).hexdigest()[:16]
    
    return result


# ─── Self-Test ──────────────────────────────────────────────────────

def _self_test():
    """Run 10 self-tests to verify ECG works correctly."""
    import tempfile
    
    print("=" * 60)
    print("Evidence Capture Gate — Self-Test Suite")
    print("=" * 60)
    
    passed = 0
    total = 0
    
    # Test 1: Complete valid bundle → PASS
    total += 1
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("print('hello')\n")
        tmp_path = f.name
    
    spec_content = {"task": "write hello.py", "deliverables": ["hello.py"]}
    spec_hash = compute_content_hash(json.dumps(spec_content, sort_keys=True, ensure_ascii=False))
    
    valid_bundle = {
        "raw_user_request": "Write a hello world script",
        "frozen_task_spec": spec_content,
        "frozen_task_spec_hash": spec_hash,
        "deliverables_manifest": [{"path": tmp_path, "hash": compute_file_hash(tmp_path)}],
        "command_log": [
            {"cmd": "python hello.py", "exit_code": 0},
            {"cmd": "python broken.py", "exit_code": 1}
        ],
        "validator_outputs": [{"validator": "syntax_check", "result": "pass"}],
        "failed_attempts": [{"description": "First tried print without parens, got SyntaxError"}],
        "known_limitations": ["Only tested on Python 3.11"],
        "omitted_evidence_declaration": "No evidence omitted"
    }
    
    r = run_evidence_capture_gate(valid_bundle)
    if r.verdict == ECGVerdict.PASS:
        print(f"  ✓ T01 [PASS] Complete valid bundle → PASS")
        passed += 1
    else:
        print(f"  ✗ T01 [FAIL] Expected PASS, got {r.verdict.value}: {r.integrity_failures}")
    
    os.unlink(tmp_path)
    
    # Test 2: Missing required fields → FAIL
    total += 1
    incomplete_bundle = {"raw_user_request": "Do something"}
    r = run_evidence_capture_gate(incomplete_bundle)
    if r.verdict == ECGVerdict.FAIL and len(r.missing_fields) >= 7:
        print(f"  ✓ T02 [PASS] Missing fields → FAIL ({len(r.missing_fields)} missing)")
        passed += 1
    else:
        print(f"  ✗ T02 [FAIL] Expected FAIL with ≥7 missing, got {r.verdict.value}, {len(r.missing_fields)} missing")
    
    # Test 3: Tampered task_spec hash → FAIL
    total += 1
    tampered = valid_bundle.copy()
    tampered["frozen_task_spec_hash"] = "deadbeef12345678"
    r = run_evidence_capture_gate(tampered)
    if r.verdict == ECGVerdict.FAIL and any("INTEGRITY VIOLATION" in f for f in r.integrity_failures):
        print(f"  ✓ T03 [PASS] Tampered hash → FAIL (integrity violation detected)")
        passed += 1
    else:
        print(f"  ✗ T03 [FAIL] Expected integrity violation, got {r.verdict.value}")
    
    # Test 4: Empty failed_attempts → FAIL (suspicious)
    total += 1
    no_failures = valid_bundle.copy()
    no_failures["failed_attempts"] = []
    r = run_evidence_capture_gate(no_failures)
    if r.verdict in (ECGVerdict.FAIL, ECGVerdict.WARN):
        print(f"  ✓ T04 [PASS] Empty failed_attempts → {r.verdict.value}")
        passed += 1
    else:
        print(f"  ✗ T04 [FAIL] Expected FAIL/WARN for empty failed_attempts, got {r.verdict.value}")
    
    # Test 5: Missing omitted_evidence_declaration → FAIL
    total += 1
    no_omit = valid_bundle.copy()
    del no_omit["omitted_evidence_declaration"]
    r = run_evidence_capture_gate(no_omit)
    if r.verdict == ECGVerdict.FAIL:
        print(f"  ✓ T05 [PASS] Missing omitted_evidence → FAIL")
        passed += 1
    else:
        print(f"  ✗ T05 [FAIL] Expected FAIL, got {r.verdict.value}")
    
    # Test 6: Command log with only successes → WARN
    total += 1
    only_success = valid_bundle.copy()
    only_success["command_log"] = [{"cmd": "test", "exit_code": 0}]
    r = run_evidence_capture_gate(only_success)
    if r.verdict == ECGVerdict.WARN or any("only successes" in w for w in r.warnings):
        print(f"  ✓ T06 [PASS] Only-success command log → WARN")
        passed += 1
    else:
        print(f"  ✗ T06 [FAIL] Expected WARN, got {r.verdict.value}")
    
    # Test 7: Deliverable file doesn't exist → FAIL
    total += 1
    missing_file = valid_bundle.copy()
    missing_file["deliverables_manifest"] = [{"path": "/nonexistent/file.py"}]
    r = run_evidence_capture_gate(missing_file)
    if r.verdict == ECGVerdict.FAIL:
        print(f"  ✓ T07 [PASS] Missing deliverable file → FAIL")
        passed += 1
    else:
        print(f"  ✗ T07 [FAIL] Expected FAIL, got {r.verdict.value}")
    
    # Test 8: Deliverable hash mismatch → FAIL
    total += 1
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write("modified content\n")
        tmp2 = f.name
    bad_hash = valid_bundle.copy()
    bad_hash["deliverables_manifest"] = [{"path": tmp2, "hash": "wronghash12345678"}]
    r = run_evidence_capture_gate(bad_hash)
    if r.verdict == ECGVerdict.FAIL:
        print(f"  ✓ T08 [PASS] Hash mismatch → FAIL")
        passed += 1
    else:
        print(f"  ✗ T08 [FAIL] Expected FAIL, got {r.verdict.value}")
    os.unlink(tmp2)
    
    # Test 9: Blank omitted_evidence_declaration → FAIL
    total += 1
    blank_omit = valid_bundle.copy()
    blank_omit["omitted_evidence_declaration"] = "   "
    r = run_evidence_capture_gate(blank_omit)
    if r.verdict == ECGVerdict.FAIL:
        print(f"  ✓ T09 [PASS] Blank omitted_evidence → FAIL")
        passed += 1
    else:
        print(f"  ✗ T09 [FAIL] Expected FAIL, got {r.verdict.value}")
    
    # Test 10: failed_attempts with invalid entries → FAIL
    total += 1
    bad_fa = valid_bundle.copy()
    bad_fa["failed_attempts"] = [{"no_description": True}, "ab"]  # too short, no description
    r = run_evidence_capture_gate(bad_fa)
    if r.verdict == ECGVerdict.FAIL:
        print(f"  ✓ T10 [PASS] Invalid failed_attempts entries → FAIL")
        passed += 1
    else:
        print(f"  ✗ T10 [FAIL] Expected FAIL, got {r.verdict.value}")
    
    print("=" * 60)
    print(f"RESULTS: {passed}/{total} PASS ({100*passed/total:.1f}%)")
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    _self_test()
