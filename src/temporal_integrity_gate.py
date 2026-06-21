"""
Temporal Integrity Gate (TIG) v1.0
BRSCP v0.6 — 防 post-gate modification（通過閘道後偷改）

功能：
  1. lock_deliverables(bundle) → 在 gate 通過時對交付物做 hash 快照
  2. verify_integrity(bundle, manifest) → 比對當前狀態與快照，偵測篡改
  3. closure_rerun_check(before_manifest, after_manifest) → closure 時比對

防禦目標：
  - agent 通過所有 gate 後，在最終交付前偷偷修改 deliverables
  - agent 在 closure rerun 前後偷改內容
  - agent 替換已通過驗證的檔案

Gate 位置：所有 Gate 通過後的最終鎖定層（G6.5 / Final Seal）

設計原則：
  - 使用 SHA-256 hash 確保不可偽造
  - 支援多檔案、多欄位的 bundle 鎖定
  - 支援 incremental verification（部分驗證）
  - 提供 tamper report（哪些欄位被改了）
"""

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional


class TIGVerdict:
    INTACT = "INTACT"          # 完整，無篡改
    TAMPERED = "TAMPERED"      # 偵測到篡改
    MISSING = "MISSING"        # 檔案或欄位遺失
    NO_MANIFEST = "NO_MANIFEST"  # 沒有 manifest 可比對


class TIGManifest:
    """Hash manifest — 記錄 gate 通過時的交付物狀態快照。"""
    
    def __init__(self):
        self.entries = {}       # field_name → hash
        self.file_entries = {}  # file_path → hash
        self.locked_at = None
        self.gate_verdicts = {} # gate_name → verdict at lock time
        self.metadata = {}
    
    def to_dict(self) -> dict:
        return {
            "entries": self.entries,
            "file_entries": self.file_entries,
            "locked_at": self.locked_at,
            "gate_verdicts": self.gate_verdicts,
            "metadata": self.metadata,
            "manifest_hash": self._compute_manifest_hash(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TIGManifest":
        m = cls()
        m.entries = data.get("entries", {})
        m.file_entries = data.get("file_entries", {})
        m.locked_at = data.get("locked_at")
        m.gate_verdicts = data.get("gate_verdicts", {})
        m.metadata = data.get("metadata", {})
        return m
    
    def _compute_manifest_hash(self) -> str:
        """Compute hash of the manifest itself (self-integrity)."""
        content = json.dumps({
            "entries": self.entries,
            "file_entries": self.file_entries,
            "locked_at": self.locked_at,
            "gate_verdicts": self.gate_verdicts,
        }, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


def _hash_value(value: Any) -> str:
    """Compute SHA-256 hash of any JSON-serializable value."""
    serialized = json.dumps(value, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode()).hexdigest()[:16]


def _hash_file(filepath: str) -> Optional[str]:
    """Compute SHA-256 hash of file contents."""
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'rb') as f:
            content = f.read()
        return hashlib.sha256(content).hexdigest()[:16]
    except (IOError, PermissionError):
        return None


def lock_deliverables(
    bundle: dict,
    gate_verdicts: dict = None,
    file_paths: list = None,
) -> TIGManifest:
    """
    Lock deliverables at the moment all gates pass.
    Creates a hash manifest that can be verified later.
    
    Args:
        bundle: The evidence bundle (dict of field → value)
        gate_verdicts: Dict of gate_name → verdict (e.g., {"ECG": "PASS", "JIIG": "PASS"})
        file_paths: Optional list of file paths to also hash-lock
    
    Returns:
        TIGManifest with all hashes recorded
    """
    manifest = TIGManifest()
    manifest.locked_at = datetime.now(timezone.utc).isoformat()
    manifest.gate_verdicts = gate_verdicts or {}
    
    # Hash each field in the bundle
    for key, value in bundle.items():
        manifest.entries[key] = _hash_value(value)
    
    # Hash files if provided
    if file_paths:
        for fpath in file_paths:
            file_hash = _hash_file(fpath)
            if file_hash:
                manifest.file_entries[fpath] = file_hash
            else:
                manifest.file_entries[fpath] = "FILE_NOT_FOUND"
    
    # Record metadata
    manifest.metadata = {
        "field_count": len(manifest.entries),
        "file_count": len(manifest.file_entries),
        "total_locked": len(manifest.entries) + len(manifest.file_entries),
    }
    
    return manifest


def verify_integrity(
    current_bundle: dict,
    manifest: TIGManifest,
    current_file_paths: list = None,
) -> dict:
    """
    Verify current state against locked manifest.
    
    Args:
        current_bundle: Current state of the evidence bundle
        manifest: The locked manifest from lock_deliverables()
        current_file_paths: Current file paths to verify (optional)
    
    Returns:
        dict with verdict, tampered_fields, missing_fields, details
    """
    tampered_fields = []
    missing_fields = []
    intact_fields = []
    
    # Check bundle fields
    for field_name, locked_hash in manifest.entries.items():
        if field_name not in current_bundle:
            missing_fields.append(field_name)
        else:
            current_hash = _hash_value(current_bundle[field_name])
            if current_hash != locked_hash:
                tampered_fields.append({
                    "field": field_name,
                    "locked_hash": locked_hash,
                    "current_hash": current_hash,
                })
            else:
                intact_fields.append(field_name)
    
    # Check files
    tampered_files = []
    missing_files = []
    intact_files = []
    
    for fpath, locked_hash in manifest.file_entries.items():
        current_hash = _hash_file(fpath)
        if current_hash is None:
            missing_files.append(fpath)
        elif current_hash != locked_hash:
            tampered_files.append({
                "file": fpath,
                "locked_hash": locked_hash,
                "current_hash": current_hash,
            })
        else:
            intact_files.append(fpath)
    
    # Determine verdict
    if tampered_fields or tampered_files:
        verdict = TIGVerdict.TAMPERED
    elif missing_fields or missing_files:
        verdict = TIGVerdict.MISSING
    else:
        verdict = TIGVerdict.INTACT
    
    return {
        "verdict": verdict,
        "tampered_fields": tampered_fields,
        "tampered_files": tampered_files,
        "missing_fields": missing_fields,
        "missing_files": missing_files,
        "intact_fields": intact_fields,
        "intact_files": intact_files,
        "total_checked": len(manifest.entries) + len(manifest.file_entries),
        "integrity_score": len(intact_fields + intact_files) / max(1, len(manifest.entries) + len(manifest.file_entries)),
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def closure_rerun_check(
    before_manifest: TIGManifest,
    after_manifest: TIGManifest,
) -> dict:
    """
    Compare two manifests (before and after closure rerun).
    Detects material changes between runs.
    
    Args:
        before_manifest: Manifest from first run
        after_manifest: Manifest from closure rerun
    
    Returns:
        dict with material_change flag and details
    """
    changed_fields = []
    new_fields = []
    removed_fields = []
    
    # Compare entries
    all_keys = set(before_manifest.entries.keys()) | set(after_manifest.entries.keys())
    
    for key in all_keys:
        before_hash = before_manifest.entries.get(key)
        after_hash = after_manifest.entries.get(key)
        
        if before_hash is None:
            new_fields.append(key)
        elif after_hash is None:
            removed_fields.append(key)
        elif before_hash != after_hash:
            changed_fields.append({
                "field": key,
                "before_hash": before_hash,
                "after_hash": after_hash,
            })
    
    # Compare file entries
    changed_files = []
    all_files = set(before_manifest.file_entries.keys()) | set(after_manifest.file_entries.keys())
    
    for fpath in all_files:
        before_hash = before_manifest.file_entries.get(fpath)
        after_hash = after_manifest.file_entries.get(fpath)
        
        if before_hash and after_hash and before_hash != after_hash:
            changed_files.append({
                "file": fpath,
                "before_hash": before_hash,
                "after_hash": after_hash,
            })
    
    # Material change = any field/file actually changed
    has_material_change = bool(changed_fields or changed_files or removed_fields)
    
    return {
        "material_change": has_material_change,
        "changed_fields": changed_fields,
        "changed_files": changed_files,
        "new_fields": new_fields,
        "removed_fields": removed_fields,
        "can_complete": not has_material_change,
        "justification": (
            "No material changes detected between runs — safe to COMPLETE"
            if not has_material_change
            else f"Material changes detected: {len(changed_fields)} fields, {len(changed_files)} files changed — CANNOT COMPLETE"
        ),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def verify_manifest_self_integrity(manifest_dict: dict) -> dict:
    """
    Verify the manifest itself hasn't been tampered with.
    Recomputes manifest_hash and compares.
    """
    stored_hash = manifest_dict.get("manifest_hash", "")
    
    # Recompute
    content = json.dumps({
        "entries": manifest_dict.get("entries", {}),
        "file_entries": manifest_dict.get("file_entries", {}),
        "locked_at": manifest_dict.get("locked_at"),
        "gate_verdicts": manifest_dict.get("gate_verdicts", {}),
    }, sort_keys=True)
    computed_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    
    if stored_hash == computed_hash:
        return {"verdict": TIGVerdict.INTACT, "reason": "Manifest self-hash matches"}
    else:
        return {
            "verdict": TIGVerdict.TAMPERED,
            "reason": "Manifest self-hash mismatch — manifest itself was tampered",
            "stored_hash": stored_hash,
            "computed_hash": computed_hash,
        }


# --- Self-Test ---
def run_self_test():
    """Run comprehensive self-test for TIG (≥12 cases)."""
    results = []
    
    # === Lock & Verify Tests ===
    
    # Case 1: Lock and verify unchanged bundle → INTACT
    bundle = {
        "task_id": "T-001",
        "intent": "Build login page",
        "test_results": [{"id": 0, "status": "PASS"}],
        "deliverables": ["login.py", "login.html"],
    }
    manifest = lock_deliverables(bundle, gate_verdicts={"ECG": "PASS", "JIIG": "PASS"})
    r = verify_integrity(bundle, manifest)
    results.append(("Lock+verify unchanged → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # Case 2: Modify a field after lock → TAMPERED
    tampered_bundle = {**bundle, "test_results": [{"id": 0, "status": "PASS"}, {"id": 1, "status": "PASS"}]}
    r = verify_integrity(tampered_bundle, manifest)
    results.append(("Modified field → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # Case 3: Remove a field after lock → MISSING
    partial_bundle = {k: v for k, v in bundle.items() if k != "deliverables"}
    r = verify_integrity(partial_bundle, manifest)
    results.append(("Removed field → MISSING", r["verdict"] == TIGVerdict.MISSING))
    
    # Case 4: Subtle modification (change one character) → TAMPERED
    subtle_bundle = {**bundle, "intent": "Build login pages"}  # added 's'
    r = verify_integrity(subtle_bundle, manifest)
    results.append(("Subtle 1-char change → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # Case 5: Add new field (should still be INTACT for locked fields)
    extended_bundle = {**bundle, "extra_field": "bonus"}
    r = verify_integrity(extended_bundle, manifest)
    results.append(("Add new field → INTACT (locked fields OK)", r["verdict"] == TIGVerdict.INTACT))
    
    # === File Integrity Tests ===
    
    # Case 6: Lock with file, file unchanged → INTACT
    test_file = "/tmp/tig_test_file.txt"
    with open(test_file, 'w') as f:
        f.write("original content")
    manifest_with_file = lock_deliverables(bundle, file_paths=[test_file])
    r = verify_integrity(bundle, manifest_with_file)
    results.append(("File unchanged → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # Case 7: Modify file after lock → TAMPERED
    with open(test_file, 'w') as f:
        f.write("MODIFIED content")
    r = verify_integrity(bundle, manifest_with_file)
    results.append(("File modified → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # Case 8: Delete file after lock → MISSING
    os.remove(test_file)
    r = verify_integrity(bundle, manifest_with_file)
    results.append(("File deleted → MISSING", r["verdict"] == TIGVerdict.MISSING))
    
    # === Closure Rerun Tests ===
    
    # Case 9: No material change between runs → can_complete
    manifest_before = lock_deliverables(bundle)
    manifest_after = lock_deliverables(bundle)  # same bundle
    r = closure_rerun_check(manifest_before, manifest_after)
    results.append(("No change between runs → can_complete", r["can_complete"] == True))
    
    # Case 10: Material change between runs → cannot_complete
    modified_bundle = {**bundle, "intent": "Build signup page"}
    manifest_after_mod = lock_deliverables(modified_bundle)
    r = closure_rerun_check(manifest_before, manifest_after_mod)
    results.append(("Material change → cannot_complete", r["can_complete"] == False))
    
    # Case 11: Field removed between runs → material change
    smaller_bundle = {"task_id": "T-001", "intent": "Build login page"}
    manifest_smaller = lock_deliverables(smaller_bundle)
    r = closure_rerun_check(manifest_before, manifest_smaller)
    results.append(("Field removed → material change", r["material_change"] == True))
    
    # === Manifest Self-Integrity ===
    
    # Case 12: Manifest self-integrity check → INTACT
    manifest_dict = manifest_before.to_dict()
    r = verify_manifest_self_integrity(manifest_dict)
    results.append(("Manifest self-integrity → INTACT", r["verdict"] == TIGVerdict.INTACT))
    
    # Case 13: Tampered manifest → TAMPERED
    tampered_manifest_dict = {**manifest_dict, "entries": {"fake": "hash"}}
    r = verify_manifest_self_integrity(tampered_manifest_dict)
    results.append(("Tampered manifest → TAMPERED", r["verdict"] == TIGVerdict.TAMPERED))
    
    # Case 14: Gate verdicts recorded correctly
    manifest_gv = lock_deliverables(bundle, gate_verdicts={"ECG": "PASS", "ISAG": "ALIGNED", "JIIG": "PASS"})
    results.append(("Gate verdicts recorded", manifest_gv.gate_verdicts == {"ECG": "PASS", "ISAG": "ALIGNED", "JIIG": "PASS"}))
    
    # Case 15: Integrity score calculation
    r = verify_integrity(bundle, manifest_before)
    results.append(("Integrity score = 1.0", r["integrity_score"] == 1.0))
    
    # Print results
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"TIG Self-Test: {passed}/{len(results)}")
    print(f"{'='*60}")
    for desc, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}: {desc}")
    print(f"{'='*60}\n")
    
    return passed, len(results)


if __name__ == "__main__":
    run_self_test()
