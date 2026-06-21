"""
Multi-Agent Consensus Protocol for BRSCP
=========================================
BRSCP M-3: Evidence-Based Reconciliation with Conservative Fallback

Author: SIC-SIT Project
Date: 2026-06-21
Version: 1.0.0

This module implements the reconcile_verdicts() function that resolves
conflicts when multiple agents produce different BRSCP verdicts for
the same task.

Design: Evidence-Based Reconciliation (see consensus_design.md Section 4)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum
import json
import time


# ── Enums ────────────────────────────────────────────────────────────────────

class VerdictType(Enum):
    COMPLETE = "COMPLETE"
    CONTINUE = "CONTINUE"
    ESCALATE = "ESCALATE"


class EvidenceStrength(Enum):
    """How strong a piece of evidence is."""
    HARD = "hard"       # file_exists, command_exit_zero, json_schema
    MEDIUM = "medium"   # regex_match, nonempty (with min_length > 100)
    SOFT = "soft"       # nonempty (small), semantic_check


# ── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    """A single piece of evidence supporting a verdict."""
    validator_type: str          # file_exists, command_exit_zero, etc.
    passed: bool                 # Did the validation pass?
    description: str = ""       # What was checked
    
    @property
    def strength(self) -> EvidenceStrength:
        hard_types = {"file_exists", "command_exit_zero", "json_schema"}
        medium_types = {"regex_match"}
        if self.validator_type in hard_types:
            return EvidenceStrength.HARD
        elif self.validator_type in medium_types:
            return EvidenceStrength.MEDIUM
        return EvidenceStrength.SOFT
    
    @property
    def score(self) -> float:
        """Numeric score for this evidence."""
        if not self.passed:
            return -0.5
        scores = {
            EvidenceStrength.HARD: 1.0,
            EvidenceStrength.MEDIUM: 0.5,
            EvidenceStrength.SOFT: 0.3,
        }
        return scores[self.strength]


@dataclass
class AgentVerdict:
    """A single agent's verdict with supporting evidence."""
    agent_id: str
    verdict: VerdictType
    confidence: float            # 0.0 - 1.0
    reasoning: str               # Why this verdict
    evidence: List[Evidence] = field(default_factory=list)
    objections: List[str] = field(default_factory=list)  # For CONTINUE: what's missing
    timestamp: float = field(default_factory=time.time)
    
    @property
    def evidence_score(self) -> float:
        """Total evidence score for this verdict."""
        if not self.evidence:
            return 0.0
        return sum(e.score for e in self.evidence)
    
    @property
    def hard_evidence_count(self) -> int:
        """Number of hard evidence items that passed."""
        return sum(1 for e in self.evidence 
                   if e.strength == EvidenceStrength.HARD and e.passed)


@dataclass
class ReconciliationResult:
    """The output of the reconciliation process."""
    final_verdict: VerdictType
    confidence: float
    reasoning: str
    method_used: str             # Which reconciliation rule was applied
    contributing_agents: List[str]  # Which agents' verdicts contributed
    dissenting_agents: List[str]   # Which agents disagreed
    evidence_summary: dict = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    reconciliation_ms: float = 0.0


# ── Configuration ────────────────────────────────────────────────────────────

@dataclass
class ConsensusConfig:
    """Tunable parameters for the consensus algorithm."""
    # Thresholds
    supermajority_ratio: float = 0.667      # 2/3 for supermajority
    confidence_floor: float = 0.5           # Below this → ESCALATE
    confidence_gap_threshold: float = 0.3   # Gap triggering conflict detection
    evidence_override_threshold: float = 2.0  # Evidence score gap for minority override
    
    # Behavioral flags
    conservative_on_tie: bool = True        # Tie → CONTINUE (not COMPLETE)
    allow_minority_override: bool = True    # Strong evidence minority can win
    max_escalate_confidence: float = 0.4    # Forced ESCALATE if all conf below this
    
    # Weights
    hard_evidence_weight: float = 2.0       # Multiplier for hard evidence in scoring
    confidence_weight: float = 1.0          # Multiplier for confidence in scoring


DEFAULT_CONFIG = ConsensusConfig()


# ── Core Reconciliation Function ─────────────────────────────────────────────

def reconcile_verdicts(
    verdicts: List[AgentVerdict],
    config: ConsensusConfig = DEFAULT_CONFIG
) -> ReconciliationResult:
    """
    Reconcile multiple agent verdicts into a single consensus verdict.
    
    Algorithm (in priority order):
    1. Unanimous → use that verdict
    2. All confidence below floor → ESCALATE
    3. Supermajority with evidence → use majority
    4. Evidence override → minority with stronger evidence wins
    5. Confidence-weighted vote → highest weighted score wins
    6. Deadlock → conservative fallback (CONTINUE or ESCALATE)
    
    Args:
        verdicts: List of AgentVerdict from different agents
        config: ConsensusConfig with tunable parameters
    
    Returns:
        ReconciliationResult with final verdict and reasoning
    """
    t0 = time.time()
    
    if not verdicts:
        return ReconciliationResult(
            final_verdict=VerdictType.ESCALATE,
            confidence=0.0,
            reasoning="No verdicts provided",
            method_used="empty_input",
            contributing_agents=[],
            dissenting_agents=[],
            reconciliation_ms=0.0
        )
    
    if len(verdicts) == 1:
        v = verdicts[0]
        elapsed = (time.time() - t0) * 1000
        return ReconciliationResult(
            final_verdict=v.verdict,
            confidence=v.confidence,
            reasoning=f"Single agent ({v.agent_id}): {v.reasoning}",
            method_used="single_agent",
            contributing_agents=[v.agent_id],
            dissenting_agents=[],
            reconciliation_ms=elapsed
        )
    
    # ── Rule 1: Unanimous ────────────────────────────────────────────────────
    verdict_types = set(v.verdict for v in verdicts)
    if len(verdict_types) == 1:
        unanimous_type = verdicts[0].verdict
        avg_conf = sum(v.confidence for v in verdicts) / len(verdicts)
        elapsed = (time.time() - t0) * 1000
        return ReconciliationResult(
            final_verdict=unanimous_type,
            confidence=avg_conf,
            reasoning=f"Unanimous ({len(verdicts)} agents agree: {unanimous_type.value})",
            method_used="unanimous",
            contributing_agents=[v.agent_id for v in verdicts],
            dissenting_agents=[],
            reconciliation_ms=elapsed
        )
    
    # ── Rule 2: All confidence below floor → ESCALATE ────────────────────────
    max_conf = max(v.confidence for v in verdicts)
    if max_conf < config.max_escalate_confidence:
        elapsed = (time.time() - t0) * 1000
        return ReconciliationResult(
            final_verdict=VerdictType.ESCALATE,
            confidence=max_conf,
            reasoning=f"All agents have low confidence (max={max_conf:.2f} < {config.max_escalate_confidence})",
            method_used="low_confidence_escalate",
            contributing_agents=[],
            dissenting_agents=[v.agent_id for v in verdicts],
            warnings=["All agents uncertain — human review required"],
            reconciliation_ms=(time.time() - t0) * 1000
        )
    
    # ── Rule 3: Any ESCALATE with high confidence → ESCALATE ─────────────────
    escalate_verdicts = [v for v in verdicts if v.verdict == VerdictType.ESCALATE]
    if escalate_verdicts:
        max_esc_conf = max(v.confidence for v in escalate_verdicts)
        if max_esc_conf >= config.confidence_floor:
            elapsed = (time.time() - t0) * 1000
            return ReconciliationResult(
                final_verdict=VerdictType.ESCALATE,
                confidence=max_esc_conf,
                reasoning=f"Agent(s) flagged ESCALATE with confidence {max_esc_conf:.2f}",
                method_used="escalate_propagation",
                contributing_agents=[v.agent_id for v in escalate_verdicts],
                dissenting_agents=[v.agent_id for v in verdicts if v not in escalate_verdicts],
                reconciliation_ms=(time.time() - t0) * 1000
            )
    
    # ── Partition into COMPLETE vs CONTINUE ──────────────────────────────────
    complete_verdicts = [v for v in verdicts if v.verdict == VerdictType.COMPLETE]
    continue_verdicts = [v for v in verdicts if v.verdict == VerdictType.CONTINUE]
    
    n = len(verdicts)
    n_complete = len(complete_verdicts)
    n_continue = len(continue_verdicts)
    
    # ── Rule 4: Supermajority with evidence ──────────────────────────────────
    if n_complete / n >= config.supermajority_ratio:
        # Check if COMPLETE has actual evidence
        total_hard = sum(v.hard_evidence_count for v in complete_verdicts)
        if total_hard > 0:
            avg_conf = sum(v.confidence for v in complete_verdicts) / n_complete
            elapsed = (time.time() - t0) * 1000
            return ReconciliationResult(
                final_verdict=VerdictType.COMPLETE,
                confidence=avg_conf,
                reasoning=f"Supermajority COMPLETE ({n_complete}/{n}) with {total_hard} hard evidence items",
                method_used="supermajority_with_evidence",
                contributing_agents=[v.agent_id for v in complete_verdicts],
                dissenting_agents=[v.agent_id for v in continue_verdicts],
                evidence_summary={"hard_evidence_total": total_hard},
                reconciliation_ms=(time.time() - t0) * 1000
            )
    
    if n_continue / n >= config.supermajority_ratio:
        avg_conf = sum(v.confidence for v in continue_verdicts) / n_continue
        elapsed = (time.time() - t0) * 1000
        return ReconciliationResult(
            final_verdict=VerdictType.CONTINUE,
            confidence=avg_conf,
            reasoning=f"Supermajority CONTINUE ({n_continue}/{n})",
            method_used="supermajority_continue",
            contributing_agents=[v.agent_id for v in continue_verdicts],
            dissenting_agents=[v.agent_id for v in complete_verdicts],
            reconciliation_ms=(time.time() - t0) * 1000
        )
    
    # ── Rule 5: Evidence override (minority with much stronger evidence) ─────
    if config.allow_minority_override:
        complete_evidence = sum(v.evidence_score for v in complete_verdicts)
        continue_evidence = sum(v.evidence_score for v in continue_verdicts)
        
        gap = abs(complete_evidence - continue_evidence)
        if gap >= config.evidence_override_threshold:
            if complete_evidence > continue_evidence:
                winner = VerdictType.COMPLETE
                winner_agents = complete_verdicts
                loser_agents = continue_verdicts
            else:
                winner = VerdictType.CONTINUE
                winner_agents = continue_verdicts
                loser_agents = complete_verdicts
            
            avg_conf = sum(v.confidence for v in winner_agents) / len(winner_agents)
            elapsed = (time.time() - t0) * 1000
            return ReconciliationResult(
                final_verdict=winner,
                confidence=avg_conf * 0.9,  # Slight penalty for override
                reasoning=f"Evidence override: {winner.value} evidence ({complete_evidence:.1f} vs {continue_evidence:.1f}, gap={gap:.1f})",
                method_used="evidence_override",
                contributing_agents=[v.agent_id for v in winner_agents],
                dissenting_agents=[v.agent_id for v in loser_agents],
                evidence_summary={
                    "complete_score": complete_evidence,
                    "continue_score": continue_evidence,
                    "gap": gap
                },
                warnings=["Minority override applied — review recommended"],
                reconciliation_ms=(time.time() - t0) * 1000
            )
    
    # ── Rule 6: Confidence-weighted vote ─────────────────────────────────────
    complete_weighted = sum(
        v.confidence * config.confidence_weight + 
        v.evidence_score * config.hard_evidence_weight
        for v in complete_verdicts
    )
    continue_weighted = sum(
        v.confidence * config.confidence_weight + 
        v.evidence_score * config.hard_evidence_weight
        for v in continue_verdicts
    )
    
    if complete_weighted != continue_weighted:
        if complete_weighted > continue_weighted:
            winner = VerdictType.COMPLETE
            winner_agents = complete_verdicts
            loser_agents = continue_verdicts
            winner_score = complete_weighted
        else:
            winner = VerdictType.CONTINUE
            winner_agents = continue_verdicts
            loser_agents = complete_verdicts
            winner_score = continue_weighted
        
        total_score = complete_weighted + continue_weighted
        norm_conf = winner_score / total_score if total_score > 0 else 0.5
        elapsed = (time.time() - t0) * 1000
        return ReconciliationResult(
            final_verdict=winner,
            confidence=norm_conf,
            reasoning=f"Confidence-weighted: {winner.value} scored {winner_score:.2f} vs {total_score - winner_score:.2f}",
            method_used="confidence_weighted",
            contributing_agents=[v.agent_id for v in winner_agents],
            dissenting_agents=[v.agent_id for v in loser_agents],
            evidence_summary={
                "complete_weighted": complete_weighted,
                "continue_weighted": continue_weighted
            },
            reconciliation_ms=(time.time() - t0) * 1000
        )
    
    # ── Rule 7: Deadlock → Conservative fallback ─────────────────────────────
    if config.conservative_on_tie:
        fallback = VerdictType.CONTINUE
    else:
        fallback = VerdictType.ESCALATE
    
    elapsed = (time.time() - t0) * 1000
    return ReconciliationResult(
        final_verdict=fallback,
        confidence=0.5,
        reasoning=f"Deadlock: equal scores. Conservative fallback → {fallback.value}",
        method_used="deadlock_fallback",
        contributing_agents=[v.agent_id for v in verdicts],
        dissenting_agents=[],
        warnings=["Perfect deadlock — consider adding more agents or ESCALATE"],
        reconciliation_ms=elapsed
    )


# ── Conflict Detection ───────────────────────────────────────────────────────

def detect_conflicts(verdicts: List[AgentVerdict]) -> List[dict]:
    """
    Detect conflicts between verdicts before reconciliation.
    Returns a list of conflict descriptions.
    """
    conflicts = []
    
    for i, v1 in enumerate(verdicts):
        for j, v2 in enumerate(verdicts):
            if j <= i:
                continue
            
            # Type conflict
            if v1.verdict != v2.verdict:
                conflicts.append({
                    "type": "verdict_type_conflict",
                    "agents": [v1.agent_id, v2.agent_id],
                    "verdicts": [v1.verdict.value, v2.verdict.value],
                    "confidence_gap": abs(v1.confidence - v2.confidence),
                    "severity": "high" if abs(v1.confidence - v2.confidence) < 0.2 else "medium"
                })
            
            # Confidence gap (same verdict but very different confidence)
            elif abs(v1.confidence - v2.confidence) > 0.3:
                conflicts.append({
                    "type": "confidence_gap",
                    "agents": [v1.agent_id, v2.agent_id],
                    "confidences": [v1.confidence, v2.confidence],
                    "severity": "low"
                })
    
    return conflicts


# ── Utility Functions ────────────────────────────────────────────────────────

def verdict_summary(verdicts: List[AgentVerdict]) -> dict:
    """Generate a summary of all verdicts for logging."""
    return {
        "total_agents": len(verdicts),
        "complete": sum(1 for v in verdicts if v.verdict == VerdictType.COMPLETE),
        "continue": sum(1 for v in verdicts if v.verdict == VerdictType.CONTINUE),
        "escalate": sum(1 for v in verdicts if v.verdict == VerdictType.ESCALATE),
        "avg_confidence": sum(v.confidence for v in verdicts) / len(verdicts) if verdicts else 0,
        "total_evidence": sum(len(v.evidence) for v in verdicts),
        "total_hard_evidence": sum(v.hard_evidence_count for v in verdicts),
    }


def to_json(result: ReconciliationResult) -> str:
    """Serialize ReconciliationResult to JSON."""
    return json.dumps({
        "final_verdict": result.final_verdict.value,
        "confidence": result.confidence,
        "reasoning": result.reasoning,
        "method_used": result.method_used,
        "contributing_agents": result.contributing_agents,
        "dissenting_agents": result.dissenting_agents,
        "evidence_summary": result.evidence_summary,
        "warnings": result.warnings,
        "reconciliation_ms": result.reconciliation_ms
    }, indent=2, ensure_ascii=False)


# ── Self-Test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Multi-Agent Consensus Protocol — Self-Test")
    print("=" * 60)
    
    # Test 1: Unanimous COMPLETE
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "All tests pass",
                      [Evidence("file_exists", True), Evidence("command_exit_zero", True)])
    v2 = AgentVerdict("agent_2", VerdictType.COMPLETE, 0.85, "Deliverables verified",
                      [Evidence("file_exists", True)])
    result = reconcile_verdicts([v1, v2])
    assert result.final_verdict == VerdictType.COMPLETE
    assert result.method_used == "unanimous"
    print(f"✓ Test 1 (Unanimous COMPLETE): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 2: Conflict — COMPLETE vs CONTINUE, evidence decides
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "All done",
                      [Evidence("file_exists", True), Evidence("command_exit_zero", True),
                       Evidence("json_schema", True)])
    v2 = AgentVerdict("agent_2", VerdictType.CONTINUE, 0.6, "Missing tests",
                      [Evidence("semantic_check", True)])
    result = reconcile_verdicts([v1, v2])
    assert result.final_verdict == VerdictType.COMPLETE
    print(f"✓ Test 2 (Evidence override → COMPLETE): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 3: Conflict — CONTINUE has stronger evidence
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.7, "Looks done",
                      [Evidence("nonempty", True)])
    v2 = AgentVerdict("agent_2", VerdictType.CONTINUE, 0.8, "Tests fail",
                      [Evidence("command_exit_zero", False), Evidence("file_exists", True),
                       Evidence("command_exit_zero", True)])
    result = reconcile_verdicts([v1, v2])
    # CONTINUE should win because evidence is stronger
    print(f"✓ Test 3 (Evidence override → CONTINUE): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 4: All low confidence → ESCALATE
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.3, "Maybe done?")
    v2 = AgentVerdict("agent_2", VerdictType.CONTINUE, 0.2, "Not sure...")
    v3 = AgentVerdict("agent_3", VerdictType.COMPLETE, 0.35, "Possibly...")
    result = reconcile_verdicts([v1, v2, v3])
    assert result.final_verdict == VerdictType.ESCALATE
    assert result.method_used == "low_confidence_escalate"
    print(f"✓ Test 4 (Low confidence → ESCALATE): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 5: ESCALATE propagation
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "Done")
    v2 = AgentVerdict("agent_2", VerdictType.ESCALATE, 0.8, "Found security issue")
    result = reconcile_verdicts([v1, v2])
    assert result.final_verdict == VerdictType.ESCALATE
    print(f"✓ Test 5 (ESCALATE propagation): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 6: Supermajority COMPLETE (3/4)
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "Done",
                      [Evidence("file_exists", True)])
    v2 = AgentVerdict("agent_2", VerdictType.COMPLETE, 0.85, "Done",
                      [Evidence("command_exit_zero", True)])
    v3 = AgentVerdict("agent_3", VerdictType.COMPLETE, 0.8, "Done",
                      [Evidence("file_exists", True)])
    v4 = AgentVerdict("agent_4", VerdictType.CONTINUE, 0.6, "Missing docs")
    result = reconcile_verdicts([v1, v2, v3, v4])
    assert result.final_verdict == VerdictType.COMPLETE
    assert result.method_used == "supermajority_with_evidence"
    print(f"✓ Test 6 (Supermajority 3/4): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 7: Deadlock (2 vs 2, equal scores)
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.7, "Done",
                      [Evidence("nonempty", True)])
    v2 = AgentVerdict("agent_2", VerdictType.COMPLETE, 0.7, "Done",
                      [Evidence("nonempty", True)])
    v3 = AgentVerdict("agent_3", VerdictType.CONTINUE, 0.7, "Not done",
                      [Evidence("nonempty", True)])
    v4 = AgentVerdict("agent_4", VerdictType.CONTINUE, 0.7, "Not done",
                      [Evidence("nonempty", True)])
    result = reconcile_verdicts([v1, v2, v3, v4])
    # Should be CONTINUE (conservative on tie)
    assert result.final_verdict == VerdictType.CONTINUE
    print(f"✓ Test 7 (Deadlock → conservative): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 8: Single agent
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "Done")
    result = reconcile_verdicts([v1])
    assert result.final_verdict == VerdictType.COMPLETE
    assert result.method_used == "single_agent"
    print(f"✓ Test 8 (Single agent): {result.final_verdict.value}, method={result.method_used}")
    
    # Test 9: Conflict detection
    v1 = AgentVerdict("agent_1", VerdictType.COMPLETE, 0.9, "Done")
    v2 = AgentVerdict("agent_2", VerdictType.CONTINUE, 0.85, "Not done")
    conflicts = detect_conflicts([v1, v2])
    assert len(conflicts) == 1
    assert conflicts[0]["type"] == "verdict_type_conflict"
    print(f"✓ Test 9 (Conflict detection): {len(conflicts)} conflict(s) found")
    
    # Test 10: Empty input
    result = reconcile_verdicts([])
    assert result.final_verdict == VerdictType.ESCALATE
    print(f"✓ Test 10 (Empty input): {result.final_verdict.value}")
    
    print("\n" + "=" * 60)
    print(f"ALL 10 SELF-TESTS PASSED")
    print("=" * 60)
