"""
A2A ESCALATE Adapter for BRSCP
================================
BRSCP M-2: Bind BRSCP ESCALATE verdict to A2A input-required state.

Author: SIC-SIT Project
Date: 2026-06-21
Version: 1.0.0

When BRSCP produces an ESCALATE verdict, this adapter transforms it into
a standard A2A (Agent-to-Agent) protocol message with state="input-required",
enabling upstream agents or humans to receive and act on the escalation.

Reference: Google A2A Protocol Spec (2025)
  - Task states: submitted → working → input-required → completed / failed / canceled
  - input-required = agent needs external input to proceed
"""

import json
import uuid
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum


# ── A2A Protocol Types ───────────────────────────────────────────────────────

class A2ATaskState(Enum):
    """A2A Task lifecycle states."""
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class A2APartType(Enum):
    """A2A Message part types."""
    TEXT = "text"
    FILE = "file"
    DATA = "data"


@dataclass
class A2APart:
    """A single part of an A2A message."""
    type: str           # "text", "file", "data"
    content: str        # text content or file URI
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        d = {"type": self.type, "content": self.content}
        if self.metadata:
            d["metadata"] = self.metadata
        return d


@dataclass
class A2AMessage:
    """An A2A protocol message."""
    role: str                   # "agent" or "user"
    parts: List[A2APart]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "role": self.role,
            "parts": [p.to_dict() for p in self.parts],
            "metadata": self.metadata
        }


@dataclass
class A2ATask:
    """An A2A protocol task object."""
    id: str
    state: str                  # A2ATaskState value
    messages: List[A2AMessage] = field(default_factory=list)
    artifacts: List[dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "messages": [m.to_dict() for m in self.messages],
            "artifacts": self.artifacts,
            "metadata": self.metadata
        }
    
    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# ── BRSCP Verdict Types (imported concept) ───────────────────────────────────

@dataclass
class BRSCPVerdict:
    """Represents a BRSCP verdict (simplified for adapter use)."""
    verdict_type: str           # "COMPLETE", "CONTINUE", "ESCALATE"
    confidence: float           # 0.0 - 1.0
    reasoning: str              # Why this verdict
    objections: List[str] = field(default_factory=list)
    evidence: List[dict] = field(default_factory=list)
    agent_id: str = "brscp_agent"
    task_context: Dict[str, Any] = field(default_factory=dict)


# ── Adapter Configuration ────────────────────────────────────────────────────

@dataclass
class EscalateAdapterConfig:
    """Configuration for the ESCALATE → A2A adapter."""
    # Task ID generation
    task_id_prefix: str = "brscp-esc"
    
    # Message formatting
    include_evidence: bool = True
    include_objections: bool = True
    include_confidence: bool = True
    max_objections_in_message: int = 10
    
    # Metadata
    protocol_version: str = "1.0"
    source_system: str = "BRSCP/SCS"
    
    # Escalation severity mapping
    severity_thresholds: Dict[str, float] = field(default_factory=lambda: {
        "critical": 0.9,    # Confidence >= 0.9 in ESCALATE → critical
        "high": 0.7,        # 0.7 - 0.9 → high
        "medium": 0.5,      # 0.5 - 0.7 → medium
        "low": 0.0          # < 0.5 → low (uncertain escalation)
    })


DEFAULT_ADAPTER_CONFIG = EscalateAdapterConfig()


# ── Core Adapter Function ────────────────────────────────────────────────────

def verdict_to_a2a(
    verdict: BRSCPVerdict,
    config: EscalateAdapterConfig = DEFAULT_ADAPTER_CONFIG,
    existing_task_id: Optional[str] = None
) -> A2ATask:
    """
    Transform a BRSCP ESCALATE verdict into an A2A input-required task.
    
    This is the primary adapter function. It:
    1. Validates the verdict is ESCALATE
    2. Determines severity from confidence
    3. Constructs A2A message with structured escalation info
    4. Returns an A2A Task in input-required state
    
    Args:
        verdict: The BRSCP verdict (must be ESCALATE)
        config: Adapter configuration
        existing_task_id: If provided, reuse this task ID (for task updates)
    
    Returns:
        A2ATask in input-required state
    
    Raises:
        ValueError: If verdict is not ESCALATE
    """
    if verdict.verdict_type != "ESCALATE":
        raise ValueError(
            f"Adapter only handles ESCALATE verdicts, got: {verdict.verdict_type}"
        )
    
    # Generate task ID
    task_id = existing_task_id or f"{config.task_id_prefix}-{uuid.uuid4().hex[:12]}"
    
    # Determine severity
    severity = _determine_severity(verdict.confidence, config.severity_thresholds)
    
    # Build message parts
    parts = _build_message_parts(verdict, config, severity)
    
    # Build metadata
    metadata = {
        "protocol": config.source_system,
        "protocol_version": config.protocol_version,
        "escalation_severity": severity,
        "escalation_confidence": verdict.confidence,
        "source_agent": verdict.agent_id,
        "timestamp_unix": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    
    if verdict.task_context:
        metadata["original_task_context"] = verdict.task_context
    
    # Build A2A message
    message = A2AMessage(
        role="agent",
        parts=parts,
        metadata={"severity": severity}
    )
    
    # Build A2A task
    task = A2ATask(
        id=task_id,
        state=A2ATaskState.INPUT_REQUIRED.value,
        messages=[message],
        metadata=metadata
    )
    
    return task


def verdict_to_a2a_json(
    verdict: BRSCPVerdict,
    config: EscalateAdapterConfig = DEFAULT_ADAPTER_CONFIG,
    existing_task_id: Optional[str] = None
) -> str:
    """Convenience: verdict → A2A JSON string."""
    task = verdict_to_a2a(verdict, config, existing_task_id)
    return task.to_json()


# ── Helper Functions ─────────────────────────────────────────────────────────

def _determine_severity(confidence: float, thresholds: Dict[str, float]) -> str:
    """Map confidence to severity level."""
    if confidence >= thresholds.get("critical", 0.9):
        return "critical"
    elif confidence >= thresholds.get("high", 0.7):
        return "high"
    elif confidence >= thresholds.get("medium", 0.5):
        return "medium"
    return "low"


def _build_message_parts(
    verdict: BRSCPVerdict,
    config: EscalateAdapterConfig,
    severity: str
) -> List[A2APart]:
    """Build A2A message parts from verdict."""
    parts = []
    
    # Part 1: Human-readable summary (always present)
    summary_lines = [
        f"[BRSCP ESCALATION — {severity.upper()}]",
        f"",
        f"Reason: {verdict.reasoning}",
    ]
    
    if config.include_confidence:
        summary_lines.append(f"Confidence: {verdict.confidence:.0%}")
    
    if config.include_objections and verdict.objections:
        summary_lines.append("")
        summary_lines.append("Unresolved issues:")
        for i, obj in enumerate(verdict.objections[:config.max_objections_in_message], 1):
            summary_lines.append(f"  {i}. {obj}")
    
    summary_lines.append("")
    summary_lines.append("Action required: Please review and provide guidance.")
    
    parts.append(A2APart(
        type=A2APartType.TEXT.value,
        content="\n".join(summary_lines)
    ))
    
    # Part 2: Structured data (for programmatic consumption)
    structured_data = {
        "verdict_type": verdict.verdict_type,
        "confidence": verdict.confidence,
        "reasoning": verdict.reasoning,
        "objections": verdict.objections,
        "severity": severity,
        "agent_id": verdict.agent_id,
    }
    
    if config.include_evidence and verdict.evidence:
        structured_data["evidence"] = verdict.evidence
    
    parts.append(A2APart(
        type=A2APartType.DATA.value,
        content=json.dumps(structured_data, ensure_ascii=False),
        metadata={"schema": "brscp_escalation_v1"}
    ))
    
    return parts


# ── Batch Processing ─────────────────────────────────────────────────────────

def batch_escalate(
    verdicts: List[BRSCPVerdict],
    config: EscalateAdapterConfig = DEFAULT_ADAPTER_CONFIG
) -> List[A2ATask]:
    """
    Process multiple ESCALATE verdicts into A2A tasks.
    Non-ESCALATE verdicts are silently skipped.
    """
    tasks = []
    for v in verdicts:
        if v.verdict_type == "ESCALATE":
            tasks.append(verdict_to_a2a(v, config))
    return tasks


# ── Validation ───────────────────────────────────────────────────────────────

def validate_a2a_task(task: A2ATask) -> List[str]:
    """
    Validate an A2A task against the protocol spec.
    Returns list of validation errors (empty = valid).
    """
    errors = []
    
    # Required fields
    if not task.id:
        errors.append("Task ID is required")
    
    valid_states = {s.value for s in A2ATaskState}
    if task.state not in valid_states:
        errors.append(f"Invalid state: {task.state}. Must be one of: {valid_states}")
    
    # For input-required, must have at least one message
    if task.state == "input-required" and not task.messages:
        errors.append("input-required tasks must have at least one message")
    
    # Messages validation
    for i, msg in enumerate(task.messages):
        if msg.role not in ("agent", "user"):
            errors.append(f"Message {i}: invalid role '{msg.role}'")
        if not msg.parts:
            errors.append(f"Message {i}: must have at least one part")
        for j, part in enumerate(msg.parts):
            if part.type not in ("text", "file", "data"):
                errors.append(f"Message {i}, Part {j}: invalid type '{part.type}'")
            if not part.content:
                errors.append(f"Message {i}, Part {j}: content is empty")
    
    # Metadata validation for BRSCP escalations
    if "protocol" in task.metadata:
        if "escalation_severity" not in task.metadata:
            errors.append("BRSCP escalation tasks must include escalation_severity in metadata")
        if "escalation_confidence" not in task.metadata:
            errors.append("BRSCP escalation tasks must include escalation_confidence in metadata")
    
    return errors


# ── Self-Test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("A2A ESCALATE Adapter — Self-Test")
    print("=" * 60)
    
    # Test 1: Basic ESCALATE → input-required
    verdict = BRSCPVerdict(
        verdict_type="ESCALATE",
        confidence=0.85,
        reasoning="Found security vulnerability in authentication flow",
        objections=["SQL injection in login endpoint", "No rate limiting"],
        evidence=[{"type": "command_exit_zero", "passed": False}],
        agent_id="brscp_agent_1",
        task_context={"original_task": "Review auth module"}
    )
    
    task = verdict_to_a2a(verdict)
    assert task.state == "input-required"
    assert "brscp-esc" in task.id
    assert len(task.messages) == 1
    assert task.messages[0].role == "agent"
    assert len(task.messages[0].parts) == 2  # text + data
    assert task.metadata["escalation_severity"] == "high"
    errors = validate_a2a_task(task)
    assert len(errors) == 0, f"Validation errors: {errors}"
    print(f"✓ Test 1 (Basic ESCALATE): state={task.state}, severity={task.metadata['escalation_severity']}")
    
    # Test 2: Critical severity (confidence >= 0.9)
    verdict_critical = BRSCPVerdict(
        verdict_type="ESCALATE",
        confidence=0.95,
        reasoning="Data loss detected",
        objections=["Production database corrupted"],
        agent_id="brscp_agent_2"
    )
    task_critical = verdict_to_a2a(verdict_critical)
    assert task_critical.metadata["escalation_severity"] == "critical"
    print(f"✓ Test 2 (Critical severity): severity={task_critical.metadata['escalation_severity']}")
    
    # Test 3: Low severity (confidence < 0.5)
    verdict_low = BRSCPVerdict(
        verdict_type="ESCALATE",
        confidence=0.3,
        reasoning="Uncertain about requirements",
        agent_id="brscp_agent_3"
    )
    task_low = verdict_to_a2a(verdict_low)
    assert task_low.metadata["escalation_severity"] == "low"
    print(f"✓ Test 3 (Low severity): severity={task_low.metadata['escalation_severity']}")
    
    # Test 4: Non-ESCALATE should raise ValueError
    verdict_complete = BRSCPVerdict(
        verdict_type="COMPLETE",
        confidence=0.9,
        reasoning="All done"
    )
    try:
        verdict_to_a2a(verdict_complete)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "ESCALATE" in str(e)
    print(f"✓ Test 4 (Non-ESCALATE raises ValueError)")
    
    # Test 5: JSON output is valid
    json_output = verdict_to_a2a_json(verdict)
    parsed = json.loads(json_output)
    assert parsed["state"] == "input-required"
    assert "messages" in parsed
    assert len(parsed["messages"]) == 1
    print(f"✓ Test 5 (JSON output valid): {len(json_output)} bytes")
    
    # Test 6: Batch processing
    verdicts_batch = [
        BRSCPVerdict("ESCALATE", 0.8, "Issue A", agent_id="a1"),
        BRSCPVerdict("COMPLETE", 0.9, "Done"),  # Should be skipped
        BRSCPVerdict("ESCALATE", 0.6, "Issue B", agent_id="a2"),
        BRSCPVerdict("CONTINUE", 0.7, "More work"),  # Should be skipped
    ]
    tasks = batch_escalate(verdicts_batch)
    assert len(tasks) == 2  # Only ESCALATE verdicts
    print(f"✓ Test 6 (Batch processing): {len(tasks)} tasks from {len(verdicts_batch)} verdicts")
    
    # Test 7: Validation catches errors
    bad_task = A2ATask(id="", state="invalid", messages=[])
    errors = validate_a2a_task(bad_task)
    assert len(errors) >= 2  # Missing ID + invalid state
    print(f"✓ Test 7 (Validation catches errors): {len(errors)} errors found")
    
    # Test 8: Custom config
    custom_config = EscalateAdapterConfig(
        task_id_prefix="custom",
        include_evidence=False,
        include_objections=False,
        source_system="CUSTOM_BRSCP"
    )
    task_custom = verdict_to_a2a(verdict, custom_config)
    assert "custom-" in task_custom.id
    assert task_custom.metadata["protocol"] == "CUSTOM_BRSCP"
    # Data part should not have evidence
    data_part = task_custom.messages[0].parts[1]
    data_content = json.loads(data_part.content)
    assert "evidence" not in data_content
    print(f"✓ Test 8 (Custom config): prefix={task_custom.id[:7]}, protocol={task_custom.metadata['protocol']}")
    
    # Test 9: Message content is human-readable
    text_part = task.messages[0].parts[0]
    assert "BRSCP ESCALATION" in text_part.content
    assert "HIGH" in text_part.content
    assert "SQL injection" in text_part.content
    assert "Action required" in text_part.content
    print(f"✓ Test 9 (Human-readable message): contains escalation info")
    
    # Test 10: Existing task ID reuse
    task_reuse = verdict_to_a2a(verdict, existing_task_id="existing-task-123")
    assert task_reuse.id == "existing-task-123"
    print(f"✓ Test 10 (Task ID reuse): id={task_reuse.id}")
    
    print("\n" + "=" * 60)
    print("ALL 10 SELF-TESTS PASSED")
    print("=" * 60)
    
    # Print example output
    print("\n--- Example A2A Output ---")
    print(verdict_to_a2a_json(verdict))
