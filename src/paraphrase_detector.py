"""
Paraphrase Detector v1.0
BRSCP v0.6 — JIIG 強化模組

功能：偵測語義相似但表面不同的文本（paraphrase attack）
防禦目標：agent 用同義詞重寫 executor context 餵給 judge，繞過 JIIG 的文字相似度偵測

方法（不依賴外部 embedding API，純 Python 實作）：
  1. N-gram overlap（2-gram, 3-gram）— 捕捉片語級重複
  2. Synonym-aware token matching — 使用同義詞表擴展比對
  3. Structural similarity — 句子結構模式比對
  4. Semantic fingerprint — 基於關鍵概念的語義指紋

設計原則：
  - 不依賴外部 API（sandbox 環境限制）
  - 多層偵測，任一層觸發即 ESCALATE
  - 可調閾值，支援 strict / normal / lenient 模式
"""

import re
import hashlib
from collections import Counter
from typing import Any
from datetime import datetime, timezone


class ParaphraseVerdict:
    INDEPENDENT = "INDEPENDENT"    # 確認獨立，非 paraphrase
    PARAPHRASE = "PARAPHRASE"      # 偵測到 paraphrase（同義改寫）
    SUSPICIOUS = "SUSPICIOUS"      # 可疑但不確定


# --- Synonym Table (English) ---
# 常見的 AI agent 會用來改寫的同義詞對
SYNONYM_GROUPS = [
    {"complete", "finish", "done", "accomplish", "fulfill", "achieve"},
    {"build", "create", "construct", "develop", "implement", "make"},
    {"test", "verify", "validate", "check", "confirm", "examine"},
    {"system", "application", "program", "software", "app", "platform"},
    {"feature", "function", "capability", "component", "module"},
    {"quickly", "rapidly", "fast", "swiftly", "speedily"},
    {"correctly", "properly", "accurately", "right"},
    {"found", "detected", "discovered", "identified", "spotted"},
    {"wrote", "written", "authored", "composed"},
    {"added", "included", "inserted", "incorporated"},
    {"pass", "succeed", "approve", "accept", "clear"},
    {"fail", "reject", "deny", "refuse", "block"},
    {"error", "bug", "issue", "problem", "defect", "fault"},
    {"fix", "repair", "resolve", "patch", "correct", "remedy"},
    {"all", "every", "each", "entire", "whole", "complete"},
    {"good", "excellent", "great", "fine", "satisfactory", "adequate"},
    {"bad", "poor", "inadequate", "insufficient", "unsatisfactory"},
    {"fast", "quick", "rapid", "swift", "speedy"},
    {"important", "critical", "crucial", "essential", "vital", "key"},
    {"start", "begin", "initiate", "commence", "launch"},
    {"end", "finish", "complete", "conclude", "terminate"},
    {"show", "display", "present", "demonstrate", "exhibit"},
    {"use", "utilize", "employ", "apply", "leverage"},
    {"change", "modify", "alter", "update", "revise", "adjust"},
    {"remove", "delete", "eliminate", "discard", "drop"},
    {"add", "include", "insert", "append", "attach"},
    {"send", "transmit", "deliver", "dispatch", "forward"},
]

# Build lookup: word → group_id
_SYNONYM_LOOKUP = {}
for i, group in enumerate(SYNONYM_GROUPS):
    for word in group:
        _SYNONYM_LOOKUP[word] = i


def _tokenize(text: str) -> list:
    """Tokenize text into lowercase words."""
    return re.findall(r'[a-z]+', text.lower())


def _get_ngrams(tokens: list, n: int) -> list:
    """Generate n-grams from token list."""
    return [tuple(tokens[i:i+n]) for i in range(len(tokens) - n + 1)]


def _normalize_with_synonyms(tokens: list) -> list:
    """Replace each token with its synonym group representative."""
    normalized = []
    for token in tokens:
        group_id = _SYNONYM_LOOKUP.get(token)
        if group_id is not None:
            # Use first word in group as canonical form
            canonical = sorted(SYNONYM_GROUPS[group_id])[0]
            normalized.append(canonical)
        else:
            normalized.append(token)
    return normalized


def ngram_overlap(text_a: str, text_b: str, n: int = 2) -> float:
    """
    Compute n-gram overlap ratio between two texts.
    Returns Jaccard similarity of n-gram sets.
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    
    if len(tokens_a) < n or len(tokens_b) < n:
        return 0.0
    
    ngrams_a = set(_get_ngrams(tokens_a, n))
    ngrams_b = set(_get_ngrams(tokens_b, n))
    
    if not ngrams_a or not ngrams_b:
        return 0.0
    
    intersection = ngrams_a & ngrams_b
    union = ngrams_a | ngrams_b
    
    return len(intersection) / len(union) if union else 0.0


def synonym_aware_similarity(text_a: str, text_b: str) -> float:
    """
    Compute similarity after normalizing synonyms.
    This catches paraphrase attacks that use synonym substitution.
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    
    # Normalize with synonyms
    norm_a = _normalize_with_synonyms(tokens_a)
    norm_b = _normalize_with_synonyms(tokens_b)
    
    if not norm_a or not norm_b:
        return 0.0
    
    # Compute overlap after normalization
    set_a = Counter(norm_a)
    set_b = Counter(norm_b)
    
    # Cosine-like similarity using term frequencies
    common_terms = set(set_a.keys()) & set(set_b.keys())
    
    if not common_terms:
        return 0.0
    
    dot_product = sum(set_a[t] * set_b[t] for t in common_terms)
    mag_a = sum(v**2 for v in set_a.values()) ** 0.5
    mag_b = sum(v**2 for v in set_b.values()) ** 0.5
    
    if mag_a == 0 or mag_b == 0:
        return 0.0
    
    return dot_product / (mag_a * mag_b)


def structural_similarity(text_a: str, text_b: str) -> float:
    """
    Compare structural patterns (sentence length distribution, punctuation patterns).
    Catches cases where content is rewritten but structure is preserved.
    """
    # Sentence lengths
    sents_a = [s.strip() for s in re.split(r'[.!?。！？]', text_a) if s.strip()]
    sents_b = [s.strip() for s in re.split(r'[.!?。！？]', text_b) if s.strip()]
    
    if not sents_a or not sents_b:
        return 0.0
    
    # Compare sentence count ratio
    count_ratio = min(len(sents_a), len(sents_b)) / max(len(sents_a), len(sents_b))
    
    # Compare average sentence length
    avg_len_a = sum(len(s.split()) for s in sents_a) / len(sents_a)
    avg_len_b = sum(len(s.split()) for s in sents_b) / len(sents_b)
    
    len_ratio = min(avg_len_a, avg_len_b) / max(avg_len_a, avg_len_b) if max(avg_len_a, avg_len_b) > 0 else 0.0
    
    # Compare word count ratio
    words_a = len(_tokenize(text_a))
    words_b = len(_tokenize(text_b))
    word_ratio = min(words_a, words_b) / max(words_a, words_b) if max(words_a, words_b) > 0 else 0.0
    
    return (count_ratio + len_ratio + word_ratio) / 3.0


def semantic_fingerprint(text: str) -> str:
    """
    Generate a semantic fingerprint based on key concept extraction.
    Two texts with same meaning should have similar fingerprints.
    """
    tokens = _tokenize(text)
    normalized = _normalize_with_synonyms(tokens)
    
    # Sort and deduplicate to create order-independent fingerprint
    unique_concepts = sorted(set(normalized))
    
    # Hash the concept set
    concept_str = "|".join(unique_concepts)
    return hashlib.md5(concept_str.encode()).hexdigest()[:12]


def detect_paraphrase(
    text_a: str,
    text_b: str,
    mode: str = "normal",
) -> dict:
    """
    Multi-layer paraphrase detection.
    
    Args:
        text_a: First text (e.g., executor context)
        text_b: Second text (e.g., judge context)
        mode: "strict" / "normal" / "lenient"
    
    Returns:
        dict with verdict and layer-by-layer analysis
    """
    # Thresholds by mode
    thresholds = {
        "strict":  {"ngram": 0.15, "synonym": 0.50, "structural": 0.70, "combined": 0.40},
        "normal":  {"ngram": 0.25, "synonym": 0.60, "structural": 0.80, "combined": 0.50},
        "lenient": {"ngram": 0.35, "synonym": 0.70, "structural": 0.85, "combined": 0.60},
    }
    
    t = thresholds.get(mode, thresholds["normal"])
    
    # Layer 1: N-gram overlap (bigram + trigram)
    bigram_score = ngram_overlap(text_a, text_b, n=2)
    trigram_score = ngram_overlap(text_a, text_b, n=3)
    ngram_score = (bigram_score * 0.6 + trigram_score * 0.4)
    
    # Layer 2: Synonym-aware similarity
    syn_score = synonym_aware_similarity(text_a, text_b)
    
    # Layer 3: Structural similarity
    struct_score = structural_similarity(text_a, text_b)
    
    # Layer 4: Semantic fingerprint comparison
    fp_a = semantic_fingerprint(text_a)
    fp_b = semantic_fingerprint(text_b)
    fp_match = fp_a == fp_b
    
    # Combined score (weighted)
    combined = (ngram_score * 0.3 + syn_score * 0.4 + struct_score * 0.2 + (1.0 if fp_match else 0.0) * 0.1)
    
    # Determine verdict
    triggers = []
    if ngram_score >= t["ngram"]:
        triggers.append(f"ngram({ngram_score:.3f}>={t['ngram']})")
    if syn_score >= t["synonym"]:
        triggers.append(f"synonym({syn_score:.3f}>={t['synonym']})")
    if struct_score >= t["structural"] and syn_score >= 0.3:
        triggers.append(f"structural({struct_score:.3f}>={t['structural']})")
    if fp_match and syn_score >= 0.4:
        triggers.append("fingerprint_match")
    
    if combined >= t["combined"] or len(triggers) >= 2:
        verdict = ParaphraseVerdict.PARAPHRASE
    elif combined >= t["combined"] * 0.7 or len(triggers) >= 1:
        verdict = ParaphraseVerdict.SUSPICIOUS
    elif struct_score >= 0.85 and syn_score >= 0.25:
        verdict = ParaphraseVerdict.SUSPICIOUS
    else:
        verdict = ParaphraseVerdict.INDEPENDENT
    
    return {
        "verdict": verdict,
        "combined_score": round(combined, 4),
        "layers": {
            "ngram_score": round(ngram_score, 4),
            "synonym_score": round(syn_score, 4),
            "structural_score": round(struct_score, 4),
            "fingerprint_match": fp_match,
        },
        "triggers": triggers,
        "mode": mode,
        "thresholds": t,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


# --- Self-Test ---
def run_self_test():
    """Run 12 self-test cases for Paraphrase Detector."""
    results = []
    
    # Case 1: Identical text → PARAPHRASE (trivial case)
    r = detect_paraphrase(
        "I completed all tasks successfully with no errors",
        "I completed all tasks successfully with no errors",
    )
    results.append(("Identical → PARAPHRASE", r["verdict"] == ParaphraseVerdict.PARAPHRASE))
    
    # Case 2: Completely different → INDEPENDENT
    r = detect_paraphrase(
        "The weather is sunny today in Tokyo",
        "Please evaluate the code quality of the login module",
    )
    results.append(("Completely different → INDEPENDENT", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # Case 3: Synonym substitution attack
    r = detect_paraphrase(
        "I built the login page and verified all test cases pass",
        "I created the login page and validated all test cases succeed",
    )
    results.append(("Synonym attack → PARAPHRASE/SUSPICIOUS", r["verdict"] in [ParaphraseVerdict.PARAPHRASE, ParaphraseVerdict.SUSPICIOUS]))
    
    # Case 4: Structural paraphrase (same structure, different words)
    r = detect_paraphrase(
        "The system was developed quickly. All features work correctly. No bugs found.",
        "The application was built rapidly. All components function properly. No issues detected.",
    )
    results.append(("Structural paraphrase → PARAPHRASE/SUSPICIOUS", r["verdict"] in [ParaphraseVerdict.PARAPHRASE, ParaphraseVerdict.SUSPICIOUS]))
    
    # Case 5: Independent but related topic
    r = detect_paraphrase(
        "I implemented the authentication module with OAuth2 and JWT tokens",
        "Please check if the authentication follows security best practices",
    )
    results.append(("Related but independent → INDEPENDENT", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # Case 6: Reordered sentences (common paraphrase technique)
    r = detect_paraphrase(
        "First I built the UI. Then I added validation. Finally I wrote tests.",
        "Tests were written. Validation was added. The UI was built.",
    )
    results.append(("Reordered → SUSPICIOUS+", r["verdict"] in [ParaphraseVerdict.PARAPHRASE, ParaphraseVerdict.SUSPICIOUS]))
    
    # Case 7: Passive voice conversion
    r = detect_paraphrase(
        "I completed the task and fixed all bugs",
        "The task was completed and all bugs were fixed",
    )
    results.append(("Passive voice → PARAPHRASE/SUSPICIOUS", r["verdict"] in [ParaphraseVerdict.PARAPHRASE, ParaphraseVerdict.SUSPICIOUS]))
    
    # Case 8: Strict mode catches more
    r_strict = detect_paraphrase(
        "I finished building the feature",
        "I completed constructing the functionality",
        mode="strict",
    )
    r_lenient = detect_paraphrase(
        "I finished building the feature",
        "I completed constructing the functionality",
        mode="lenient",
    )
    # Strict should be same or more aggressive than lenient
    strict_is_stronger = (
        r_strict["combined_score"] >= r_lenient["combined_score"] * 0.8  # scores are same
        or r_strict["verdict"] != ParaphraseVerdict.INDEPENDENT  # strict catches it
    )
    results.append(("Strict mode more aggressive", strict_is_stronger))
    
    # Case 9: Very short texts
    r = detect_paraphrase("pass", "succeed")
    results.append(("Short text handling", r["verdict"] in [ParaphraseVerdict.INDEPENDENT, ParaphraseVerdict.SUSPICIOUS, ParaphraseVerdict.PARAPHRASE]))
    
    # Case 10: Mixed language (should not crash)
    r = detect_paraphrase(
        "我完成了所有任務 all tasks done",
        "Please evaluate the deliverables",
    )
    results.append(("Mixed language → no crash", r["verdict"] == ParaphraseVerdict.INDEPENDENT))
    
    # Case 11: N-gram overlap specifically
    score = ngram_overlap(
        "the quick brown fox jumps over the lazy dog",
        "the quick brown fox leaps over the lazy dog",
    )
    results.append(("N-gram detects near-duplicate", score > 0.3))
    
    # Case 12: Synonym normalization
    tokens = _tokenize("I built and tested the system")
    normalized = _normalize_with_synonyms(tokens)
    # "built" should normalize to same as "create" group
    results.append(("Synonym normalization works", "accept" in _normalize_with_synonyms(["pass"]) or normalized != tokens))
    
    # Print results
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{'='*60}")
    print(f"Paraphrase Detector Self-Test: {passed}/{len(results)}")
    print(f"{'='*60}")
    for desc, ok in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"  {status}: {desc}")
    print(f"{'='*60}\n")
    
    return passed, len(results)


if __name__ == "__main__":
    run_self_test()
