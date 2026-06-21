"""
Schema Gaming Detector v1.0
BRSCP v0.6 — ECG 強化模組

功能：偵測 agent 透過填入「N/A」、空字串、重複內容等方式通過 ECG 的 schema 驗證
防禦目標：
  1. 空字串填充（""、" "、"\n"）
  2. N/A / None / null 填充
  3. 重複填充（同一內容複製到多個欄位）
  4. 最小長度繞過（填入無意義的短字串）
  5. 模板填充（用 placeholder 文字通過）

設計原則：
  - 每個欄位都做 content quality check
  - 支援自定義 quality rules per field type
  - 提供 gaming_score（0-1，越高越可疑）
"""

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any


class SGDVerdict:
    GENUINE = "GENUINE"        # 內容真實有意義
    GAMING = "GAMING"          # 偵測到 schema gaming
    SUSPICIOUS = "SUSPICIOUS"  # 可疑但不確定


# --- Known Gaming Patterns ---
EMPTY_PATTERNS = [
    "",
    " ",
    "  ",
    "\n",
    "\t",
    ".",
    "-",
    "--",
    "---",
]

NA_PATTERNS = [
    "n/a",
    "na",
    "none",
    "null",
    "nil",
    "undefined",
    "not applicable",
    "not available",
    "tbd",
    "todo",
    "placeholder",
    "xxx",
    "yyy",
    "zzz",
    "test",
    "asdf",
    "lorem ipsum",
    "foo",
    "bar",
    "baz",
]

TEMPLATE_PATTERNS = [
    r"^\[.*\]$",           # [placeholder]
    r"^<.*>$",             # <placeholder>
    r"^\{.*\}$",           # {placeholder}
    r"^TODO:?\s*",         # TODO: ...
    r"^FIXME:?\s*",        # FIXME: ...
    r"^INSERT\s",          # INSERT HERE
    r"^REPLACE\s",         # REPLACE WITH
    r"^YOUR\s",            # YOUR ANSWER HERE
    r"^FILL\s",            # FILL IN
]


def check_field_quality(value: Any, field_name: str = "", min_length: int = 3) -> dict:
    """
    Check if a single field value is genuine or gaming.
    
    Args:
        value: The field value to check
        field_name: Name of the field (for context)
        min_length: Minimum meaningful length
    
    Returns:
        dict with quality assessment
    """
    issues = []
    
    # Handle non-string types
    if value is None:
        return {"quality": "GAMING", "issues": ["null_value"], "score": 0.0}
    
    if isinstance(value, (int, float, bool)):
        # Numeric/boolean values are generally OK
        return {"quality": "GENUINE", "issues": [], "score": 1.0}
    
    if isinstance(value, list):
        if len(value) == 0:
            return {"quality": "GAMING", "issues": ["empty_list"], "score": 0.0}
        # Check each item in list
        gaming_items = 0
        for item in value:
            if isinstance(item, str):
                r = check_field_quality(item, field_name)
                if r["quality"] == "GAMING":
                    gaming_items += 1
        if gaming_items == len(value):
            return {"quality": "GAMING", "issues": ["all_items_gaming"], "score": 0.0}
        elif gaming_items > 0:
            return {"quality": "SUSPICIOUS", "issues": [f"{gaming_items}/{len(value)}_items_gaming"], "score": 0.5}
        return {"quality": "GENUINE", "issues": [], "score": 1.0}
    
    if isinstance(value, dict):
        if len(value) == 0:
            return {"quality": "GAMING", "issues": ["empty_dict"], "score": 0.0}
        return {"quality": "GENUINE", "issues": [], "score": 1.0}
    
    # String checks
    text = str(value).strip()
    
    # Check 1: Empty or whitespace-only
    if text in EMPTY_PATTERNS or not text:
        issues.append("empty_or_whitespace")
        return {"quality": "GAMING", "issues": issues, "score": 0.0}
    
    # Check 2: N/A patterns
    if text.lower() in NA_PATTERNS:
        issues.append(f"na_pattern: '{text}'")
        return {"quality": "GAMING", "issues": issues, "score": 0.0}
    
    # Check 3: Template patterns
    for pattern in TEMPLATE_PATTERNS:
        if re.match(pattern, text, re.IGNORECASE):
            issues.append(f"template_pattern: '{text}'")
            return {"quality": "GAMING", "issues": issues, "score": 0.1}
    
    # Check 4: Too short (for text fields)
    if len(text) < min_length:
        issues.append(f"too_short: len={len(text)} < {min_length}")
    
    # Check 5: Repetitive characters
    if len(set(text.lower())) <= 2 and len(text) > 3:
        issues.append(f"repetitive_chars: '{text[:20]}'")
        return {"quality": "GAMING", "issues": issues, "score": 0.1}
    
    # Check 6: All same word repeated
    words = text.split()
    if len(words) > 2 and len(set(words)) == 1:
        issues.append(f"repeated_word: '{words[0]}'")
        return {"quality": "GAMING", "issues": issues, "score": 0.1}
    
    # Compute quality score
    score = 1.0
    if issues:
        score -= 0.3 * len(issues)
        score = max(0.0, score)
    
    if score >= 0.7:
        quality = "GENUINE"
    elif score >= 0.4:
        quality = "SUSPICIOUS"
    else:
        quality = "GAMING"
    
    return {"quality": quality, "issues": issues, "score": round(score, 3)}


def check_duplicate_fields(bundle: dict, fields_to_check: list = None) -> dict:
    """
    Check if multiple fields contain the same content (copy-paste gaming).
    
    Args:
        bundle: The evidence bundle
        fields_to_check: Specific fields to check (default: all string fields)
    """
    if fields_to_check is None:
        fields_to_check = [k for k, v in bundle.items() if isinstance(v, str)]
    
    # Group fields by content hash
    content_groups = {}
    for field in fields_to_check:
        if field in bundle and isinstance(bundle[field], str):
            content = bundle[field].strip().lower()
            if content:  # Skip empty
                if content not in content_groups:
                    content_groups[content] = []
                content_groups[content].append(field)
    
    # Find duplicates
    duplicates = {k: v for k, v in content_groups.items() if len(v) > 1}
    
    if duplicates:
        return {
            "verdict": SGDVerdict.GAMING,
            "duplicate_groups": {content[:50]: fields for content, fields in duplicates.items()},
            "duplicate_count": sum(len(v) - 1 for v in duplicates.values()),
        }
    
    return {
        "verdict": SGDVerdict.GENUINE,
        "duplicate_groups": {},
        "duplicate_count": 0,
    }


def validate_bundle_quality(
    bundle: dict,
    required_fields: list = None,
    min_lengths: dict = None,
) -> dict:
    """
    Full quality validation of an evidence bundle.
    Combines field-level and cross-field checks.
    
    Args:
        bundle: The evidence bundle
        required_fields: Fields that must be genuine (not gaming)
        min_lengths: Dict of field_name → minimum length
    """
    if required_fields is None:
        required_fields = list(bundle.keys())
    if min_lengths is None:
        min_lengths = {}
    
    field_results = {}
    gaming_fields = []
    suspicious_fields = []
    genuine_fields = []
    
    for field in required_fields:
        if field not in bundle:
            field_results[field] = {"quality": "GAMING", "issues": ["missing_field"], "score": 0.0}
            gaming_fields.append(field)
            continue
        
        min_len = min_lengths.get(field, 3)
        result = check_field_quality(bundle[field], field, min_len)
        field_results[field] = result
        
        if result["quality"] == "GAMING":
            gaming_fields.append(field)
        elif result["quality"] == "SUSPICIOUS":
            suspicious_fields.append(field)
        else:
            genuine_fields.append(field)
    
    # Cross-field duplicate check
    dup_check = check_duplicate_fields(bundle)
    if dup_check["verdict"] == SGDVerdict.GAMING:
        gaming_fields.extend([f"dup:{k[:30]}" for k in dup_check["duplicate_groups"].keys()])
    
    # Overall verdict
    total = len(required_fields)
    # Count duplicates as additional gaming evidence
    effective_gaming = len(gaming_fields)
    if dup_check["duplicate_count"] >= 2:
        effective_gaming += dup_check["duplicate_count"]
    gaming_ratio = effective_gaming / max(1, total + dup_check["duplicate_count"])
    
    if gaming_ratio > 0.3 or len(gaming_fields) >= 2:
        verdict = SGDVerdict.GAMING
    elif gaming_ratio > 0 or len(suspicious_fields) >= 2:
        verdict = SGDVerdict.SUSPICIOUS
    else:
        verdict = SGDVerdict.GENUINE
    
    # Gaming score (0 = no gaming, 1 = full gaming)
    gaming_score = gaming_ratio
    
    return {
        "verdict": verdict,
        "gaming_score": round(gaming_score, 3),
        "field_results": field_results,
        "gaming_fields": gaming_fields,
        "suspicious_fields": suspicious_fields,
        "genuine_fields": genuine_fields,
        "duplicate_check": dup_check,
        "total_fields": total,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# --- Self-Test ---
def run_self_test():
    """Run 12 self-test cases for Schema Gaming Detector."""
    results = []
    
    # Case 1: Genuine bundle → GENUINE
    bundle1 = {
        "task_id": "T-001",
        "intent_summary": "Build a login page with email validation",
        "test_results": [{"id": 0, "status": "PASS", "detail": "Form renders correctly"}],
        "deliverable_paths": ["src/login.py", "src/login.html"],
    }
    r = validate_bundle_quality(bundle1)
    results.append(("Genuine bundle → GENUINE", r["verdict"] == SGDVerdict.GENUINE))
    
    # Case 2: N/A filled bundle → GAMING
    bundle2 = {
        "task_id": "N/A",
        "intent_summary": "n/a",
        "test_results": [],
        "deliverable_paths": [],
    }
    r = validate_bundle_quality(bundle2)
    results.append(("N/A bundle → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # Case 3: Empty string attack → GAMING
    bundle3 = {
        "task_id": "T-001",
        "intent_summary": "",
        "test_results": [],
        "deliverable_paths": [""],
    }
    r = validate_bundle_quality(bundle3)
    results.append(("Empty strings → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # Case 4: Placeholder/template attack → GAMING
    bundle4 = {
        "task_id": "[INSERT ID]",
        "intent_summary": "TODO: fill this in",
        "test_results": [{"id": 0, "status": "PASS"}],
        "deliverable_paths": ["<path>"],
    }
    r = validate_bundle_quality(bundle4)
    results.append(("Template attack → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # Case 5: Duplicate content attack → GAMING
    bundle5 = {
        "task_id": "T-001",
        "intent_summary": "everything is fine and working",
        "notes": "everything is fine and working",
        "conclusion": "everything is fine and working",
    }
    r = validate_bundle_quality(bundle5)
    results.append(("Duplicate content → GAMING", r["verdict"] == SGDVerdict.GAMING))
    
    # Case 6: Single field N/A (partial) → SUSPICIOUS
    bundle6 = {
        "task_id": "T-001",
        "intent_summary": "Build a comprehensive login system with OAuth",
        "test_results": [{"id": 0, "status": "PASS"}],
        "notes": "N/A",
    }
    r = validate_bundle_quality(bundle6)
    results.append(("Single N/A → SUSPICIOUS", r["verdict"] == SGDVerdict.SUSPICIOUS))
    
    # Case 7: Repetitive characters → GAMING
    r = check_field_quality("aaaaaaaaaa")
    results.append(("Repetitive chars → GAMING", r["quality"] == "GAMING"))
    
    # Case 8: Repeated word → GAMING
    r = check_field_quality("pass pass pass pass pass")
    results.append(("Repeated word → GAMING", r["quality"] == "GAMING"))
    
    # Case 9: Null value → GAMING
    r = check_field_quality(None)
    results.append(("Null value → GAMING", r["quality"] == "GAMING"))
    
    # Case 10: Valid numeric → GENUINE
    r = check_field_quality(42)
    results.append(("Valid numeric → GENUINE", r["quality"] == "GENUINE"))
    
    # Case 11: Empty list → GAMING
    r = check_field_quality([])
    results.append(("Empty list → GAMING", r["quality"] == "GAMING"))
    
    # Case 12: Mixed quality bundle
    bundle12 = {
        "task_id": "T-001",
        "intent_summary": "Build authentication system",
        "test_results": [{"id": 0, "status": "PASS"}],
        "deliverable_paths": ["src/auth.py"],
        "failed_attempts": [],  # empty list is OK for failed_attempts
    }
    r = validate_bundle_quality(bundle12, required_fields=["task_id", "intent_summary", "test_results", "deliverable_paths"])
    results.append(("Mixed quality → GENUINE", r["verdict"] == SGDVerdict.GENUINE))
    
    # Print results
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Schema Gaming Detector Self-Test: {passed}/{len(results)}")
    print(f"{'='*60}")
    for desc, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}: {desc}")
    print(f"{'='*60}\n")
    
    return passed, len(results)


if __name__ == "__main__":
    run_self_test()
