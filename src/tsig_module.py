"""
tsig_module.py — TSIG (Task Spec Inference Gate) Module
BRSCP/SCS P0-1 Implementation
2026-06-21 | SIC-SIT Project

Purpose:
  Infer user intent and deliverables from conversation context.
  This is the FIRST gate in BRSCP: before the agent does anything,
  TSIG locks down WHAT the user actually wants.

Architecture:
  User message → TSIG prompt → LLM inference → TSIGResult (frozen)
  
  The TSIGResult is then used by:
  - BRSCP G1 (intent alignment check)
  - BRSCP G3 (deliverable validation)
  - BRSCP G4G5 (adversarial self-check against deliverables)

Integration:
  - Standalone: tsig = infer_task_spec(conversation)
  - Decorator: @brscp_runtime wraps any agent function
  - A2A: returns TSIGResult as JSON for protocol interop
"""

import json, re, time, os
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

# ── Configuration ────────────────────────────────────────────────────────────

TSIG_VERSION = "1.0.0"
TSIG_MAX_RETRIES = 2
TSIG_MAX_TOKENS = 2000  # Must be high enough for thinking models
TSIG_TOKEN_BUDGET = 250  # target: ~200 tokens output

# ── Data Classes ─────────────────────────────────────────────────────────────

class ValidatorType(Enum):
    FILE_EXISTS = "file_exists"
    NONEMPTY = "nonempty"
    COMMAND_EXIT_ZERO = "command_exit_zero"
    REGEX_MATCH = "regex_match"
    JSON_SCHEMA = "json_schema"
    SEMANTIC_CHECK = "semantic_check"  # for soft deliverables


@dataclass
class Deliverable:
    id: str
    description: str
    validator_type: str
    validator_args: dict = field(default_factory=dict)
    required: bool = True


@dataclass
class TSIGResult:
    intent: str                       # One sentence, verb-first
    deliverables: list                # List of Deliverable dicts
    display_line: str                 # User-facing confirmation line
    confidence: float                 # 0.0 - 1.0
    mode: str                         # FULL / DEGRADED / MINIMAL
    task_type: str = "general"        # For complexity table lookup
    output_type: str = "text"         # text / code / file / mixed
    raw_llm_response: str = ""        # For debugging
    inference_ms: float = 0.0         # Latency tracking
    token_count: int = 0              # Actual tokens used
    version: str = TSIG_VERSION


# ── Prompt Templates ─────────────────────────────────────────────────────────

TSIG_SYSTEM_PROMPT = """You are TSIG. Infer what the user wants and what "done" looks like.
Return ONLY valid JSON (no markdown, no explanation).

Rules:
- intent: one verb-first sentence
- task_type: debug|code_gen|analysis|refactor|explain|creative|factual_qa|documentation|integration|design
- output_type: text|code|file|mixed
- confidence: 0.0-1.0 (0.5=guessing, 0.9=clear)
- deliverables: array of {id, description, validator_type, validator_args, required}
- validator_type: file_exists|nonempty|command_exit_zero|regex_match|json_schema|semantic_check
- Prefer strong validators (file_exists, command_exit_zero). If ambiguous, confidence<0.6."""

TSIG_USER_PROMPT = """User said: {last_user_message}

Conversation context (last 3 messages):
{conversation_summary}

Infer the task specification. Return ONLY valid JSON:
{{
  "intent": "<verb-first one sentence>",
  "deliverables": [
    {{
      "id": "d1",
      "description": "<specific and verifiable>",
      "validator_type": "<from list above>",
      "validator_args": {{}},
      "required": true
    }}
  ],
  "display_line": "<one line for user confirmation, in user's language>",
  "confidence": <0.0-1.0>,
  "task_type": "<from list>",
  "output_type": "<from list>"
}}"""


# ── Core Inference Function ──────────────────────────────────────────────────

def infer_task_spec(
    conversation: list,
    llm_fn=None,
    task_type_hint: str = None,
    output_type_hint: str = None,
    sic_js_path: str = None,
) -> TSIGResult:
    """
    Main TSIG entry point.
    
    Args:
        conversation: List of {"role": "user"|"assistant", "content": str}
        llm_fn: Callable that takes (system_prompt, user_prompt) -> str
                If None, uses deterministic fallback (rule-based)
        task_type_hint: Override task_type if known
        output_type_hint: Override output_type if known
        sic_js_path: Path to SIC-JS log (determines mode)
    
    Returns:
        TSIGResult with frozen intent and deliverables
    """
    t0 = time.time()
    
    # Extract last user message
    last_user_msg = _get_last_user_message(conversation)
    if not last_user_msg:
        return _empty_result("No user message found", t0)
    
    # Build conversation summary (last 3 messages)
    conv_summary = _build_summary(conversation)
    
    # Determine mode
    mode = _determine_mode(sic_js_path, last_user_msg)
    
    # Try LLM inference
    if llm_fn:
        result = _llm_inference(llm_fn, last_user_msg, conv_summary, t0)
        if result:
            result.mode = mode
            if task_type_hint:
                result.task_type = task_type_hint
            if output_type_hint:
                result.output_type = output_type_hint
            return result
    
    # Fallback: rule-based inference
    return _rule_based_inference(last_user_msg, conv_summary, mode, t0,
                                 task_type_hint, output_type_hint)


# ── LLM Inference ────────────────────────────────────────────────────────────

def _llm_inference(llm_fn, last_user_msg, conv_summary, t0) -> Optional[TSIGResult]:
    """Call LLM to infer task spec. Returns None on failure."""
    user_prompt = TSIG_USER_PROMPT.format(
        last_user_message=last_user_msg,
        conversation_summary=conv_summary
    )
    
    for attempt in range(TSIG_MAX_RETRIES + 1):
        try:
            raw_response = llm_fn(TSIG_SYSTEM_PROMPT, user_prompt)
            if raw_response is None:
                continue  # Model returned None (e.g., thinking model budget exhausted)
            parsed = _parse_llm_response(raw_response)
            if parsed:
                elapsed = (time.time() - t0) * 1000
                return TSIGResult(
                    intent=parsed["intent"],
                    deliverables=parsed.get("deliverables", []),
                    display_line=parsed.get("display_line", parsed["intent"]),
                    confidence=float(parsed.get("confidence", 0.7)),
                    mode="DEGRADED",  # will be overwritten
                    task_type=parsed.get("task_type", "general"),
                    output_type=parsed.get("output_type", "text"),
                    raw_llm_response=raw_response,
                    inference_ms=elapsed,
                    token_count=len(raw_response.split()) * 2  # rough estimate
                )
        except Exception as e:
            if attempt == TSIG_MAX_RETRIES:
                return None
            continue
    return None


def _parse_llm_response(raw: str) -> Optional[dict]:
    """Extract JSON from LLM response, handling markdown fences."""
    # Try direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    
    # Try extracting from markdown code block
    patterns = [
        r'```json\s*\n?(.*?)\n?\s*```',
        r'```\s*\n?(.*?)\n?\s*```',
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.DOTALL)
        if match:
            try:
                candidate = match.group(1)
                return json.loads(candidate)
            except (json.JSONDecodeError, IndexError):
                continue
    
    # Try finding the largest JSON object
    brace_depth = 0
    start = -1
    for i, c in enumerate(raw):
        if c == '{':
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif c == '}':
            brace_depth -= 1
            if brace_depth == 0 and start >= 0:
                try:
                    return json.loads(raw[start:i+1])
                except json.JSONDecodeError:
                    start = -1
    return None


# ── Rule-Based Fallback ──────────────────────────────────────────────────────

# Intent detection patterns (ordered by specificity)
INTENT_PATTERNS = [
    # Code generation (highest priority — explicit code creation)
    (r'(?:寫|做|建|build|create|implement|make|write).*?(?:程式|code|script|module|腳本|函數|function|class|API|server|endpoint|演算法|algorithm|排序|sort)',
     "code_gen", "code"),
    (r'(?:寫|做|建).*?(?:一個|一套|一份).*?(?:來|to|for|用來)',
     "code_gen", "code"),
    (r'(?:implement|create|build|make)\s+(?:a|an|the)\s+\w+\s*(?:server|API|endpoint|system|app|function)',
     "code_gen", "code"),
    # Bug fix (high priority — but NOT if negated)
    (r'(?<!不是要你)(?:修復|修正|修|fix|debug|repair|解決|resolve).*?(?:bug|錯誤|問題|error|issue|故障)',
     "debug", "code"),
    (r'(?:fix|debug|repair)\s+(?:the|my|a|this)',
     "debug", "code"),
    # Refactor (before analysis — "optimize" is action-oriented)
    (r'(?:重構|refactor|優化|optimize|改善|improve|升級|upgrade).*?(?:code|程式|效能|performance|結構)',
     "refactor", "code"),
    # Analysis
    (r'(?:分析|analyze|研究|investigate|比較|compare|評估|evaluate)',
     "analysis", "text"),
    # Integration (only if not preceded by code-gen verbs)
    (r'(?<!寫|做|建)(?:整合|integrate|接入|connect|串接|merge)(?!.*(?:server|endpoint|function|API))',
     "integration", "mixed"),
    # Documentation
    (r'(?:整理|organize|文件|document|README|報告|report|歸檔|archive)',
     "documentation", "text"),
    (r'(?:寫|write).*?(?:文件|document|README|報告|report|說明|doc)',
     "documentation", "text"),
    # Creative
    (r'(?:設計|design|創作|creative|想|brainstorm|發想)',
     "creative", "text"),
    # Explanation
    (r'(?:解釋|explain|說明|describe|教|teach|什麼是|what is|how does)',
     "explain", "text"),
    # File operations
    (r'(?:打包|zip|搬|move|複製|copy|備份|backup)',
     "documentation", "file"),
]

# Deliverable inference patterns
DELIVERABLE_PATTERNS = [
    # File creation indicators
    (r'(?:做成|輸出|產出|生成|建立)\s*(?:一個|一份)?\s*(\w+(?:\.(?:py|js|html|md|json|zip|pdf))?)',
     "file_exists"),
    # Test/verify indicators  
    (r'(?:測試|test|驗證|verify|確認|confirm|跑|run)\s+(.+)',
     "command_exit_zero"),
    # Content indicators
    (r'(?:包含|include|有|contain|列出|list)\s+(.+)',
     "nonempty"),
]


# Negation patterns that override intent detection
NEGATION_OVERRIDES = [
    # "不是要你修 bug，是要你分析" → analysis
    (r'(?:不是|不要|別).*?(?:修|做|fix|debug).*?(?:是要|而是|我要).*?(?:分析|analyze|看|研究)',
     "analysis", "text"),
    (r'(?:不是|不要|別).*?(?:修|做|fix|debug).*?(?:是要|而是|我要).*?(?:解釋|explain|說明)',
     "explain", "text"),
]


def _rule_based_inference(last_user_msg, conv_summary, mode, t0,
                           task_type_hint=None, output_type_hint=None) -> TSIGResult:
    """Deterministic fallback when no LLM available."""
    elapsed = (time.time() - t0) * 1000
    
    # Detect task type
    task_type = task_type_hint or "general"
    output_type = output_type_hint or "text"
    
    # Check negation overrides FIRST (higher priority)
    negation_matched = False
    for pattern, tt, ot in NEGATION_OVERRIDES:
        if re.search(pattern, last_user_msg, re.IGNORECASE):
            task_type = tt
            output_type = ot
            negation_matched = True
            break
    
    # Then check normal patterns (only if no negation override)
    if not negation_matched:
        for pattern, tt, ot in INTENT_PATTERNS:
            if re.search(pattern, last_user_msg, re.IGNORECASE):
                task_type = tt
                output_type = ot
                break
    
    # Build intent (simplified: use first sentence or first 50 chars)
    intent = _extract_intent(last_user_msg)
    
    # Build deliverables (rule-based)
    deliverables = _extract_deliverables(last_user_msg, task_type)
    
    # Confidence is lower for rule-based
    confidence = 0.55 if len(deliverables) > 0 else 0.35
    
    # Display line
    display_line = f"📋 任務：{intent}\n📌 標準：{' · '.join(d['description'][:20] for d in deliverables[:3])}"
    
    return TSIGResult(
        intent=intent,
        deliverables=deliverables,
        display_line=display_line,
        confidence=confidence,
        mode=mode,
        task_type=task_type,
        output_type=output_type,
        raw_llm_response="[rule-based fallback]",
        inference_ms=elapsed,
        token_count=0
    )


def _extract_intent(msg: str) -> str:
    """Extract a verb-first intent from user message."""
    # Take first sentence (up to period, newline, or 80 chars)
    first_line = msg.split('\n')[0].strip()
    # If starts with a verb-like character, use as-is
    if len(first_line) <= 80:
        return first_line
    # Truncate at natural boundary
    for sep in ['。', '，', ',', '.', '；', ';']:
        idx = first_line.find(sep)
        if 10 < idx < 80:
            return first_line[:idx]
    return first_line[:80] + "..."


def _extract_deliverables(msg: str, task_type: str) -> list:
    """Extract deliverables from message using patterns."""
    deliverables = []
    
    # Always add a basic deliverable based on task type
    if task_type in ("code_gen", "debug", "refactor"):
        deliverables.append({
            "id": "d1",
            "description": "可執行的程式碼產出",
            "validator_type": "file_exists",
            "validator_args": {"path": "./output.py"},
            "required": True
        })
    elif task_type == "documentation":
        deliverables.append({
            "id": "d1",
            "description": "文件產出",
            "validator_type": "file_exists",
            "validator_args": {"path": "./output"},
            "required": True
        })
    else:
        deliverables.append({
            "id": "d1",
            "description": "任務完成回應",
            "validator_type": "nonempty",
            "validator_args": {"min_length": 50},
            "required": True
        })
    
    # Try to extract more specific deliverables from message
    for pattern, vtype in DELIVERABLE_PATTERNS:
        matches = re.findall(pattern, msg, re.IGNORECASE)
        for i, match in enumerate(matches[:3]):  # max 3 extra
            did = f"d{len(deliverables)+1}"
            deliverables.append({
                "id": did,
                "description": match.strip()[:60],
                "validator_type": vtype,
                "validator_args": {},
                "required": True
            })
    
    return deliverables[:5]  # max 5 deliverables


# ── Helper Functions ─────────────────────────────────────────────────────────

def _get_last_user_message(conversation: list) -> Optional[str]:
    """Get the last substantive user message (skip greetings)."""
    greetings = {'hi', 'hello', '你好', '嗨', 'hey', 'yo', '哈囉'}
    
    for msg in reversed(conversation):
        if msg.get("role") == "user":
            content = msg.get("content", "").strip()
            if content.lower() in greetings:
                continue
            if len(content) < 3:
                continue
            return content
    return None


def _build_summary(conversation: list, max_messages: int = 3) -> str:
    """Build a brief summary of recent conversation."""
    recent = conversation[-max_messages:]
    lines = []
    for msg in recent:
        role = msg.get("role", "?")
        content = msg.get("content", "")[:100]
        lines.append(f"[{role}]: {content}")
    return "\n".join(lines) if lines else "(no prior context)"


def _determine_mode(sic_js_path: str, user_msg: str) -> str:
    """Determine BRSCP mode based on available context."""
    # Check SIC-JS availability
    if sic_js_path:
        paths_to_check = [sic_js_path] if sic_js_path else []
        paths_to_check.extend([
            "./.sic-js/task_registry.json",
            os.path.expanduser("~/.sic-js/task_registry.json"),
        ])
        for p in paths_to_check:
            if p and os.path.exists(p):
                return "FULL"
    
    # If user message is substantial (>5 words or >10 chars for CJK), DEGRADED
    # CJK characters carry more meaning per character than Latin
    cjk_count = sum(1 for c in user_msg if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff')
    word_count = len(user_msg.split())
    if cjk_count >= 5 or word_count >= 5 or len(user_msg) > 20:
        return "DEGRADED"
    
    return "MINIMAL"


def _empty_result(reason: str, t0: float) -> TSIGResult:
    """Return an empty result for edge cases."""
    return TSIGResult(
        intent=f"[TSIG ERROR] {reason}",
        deliverables=[],
        display_line=f"⚠️ 無法推理任務意圖：{reason}",
        confidence=0.0,
        mode="MINIMAL",
        raw_llm_response="",
        inference_ms=(time.time() - t0) * 1000,
    )


# ── Display Functions ────────────────────────────────────────────────────────

def display_tsig(result: TSIGResult) -> str:
    """Format TSIG result for user-facing display."""
    mode_icons = {"FULL": "🟢", "DEGRADED": "🟡", "MINIMAL": "🔴"}
    icon = mode_icons.get(result.mode, "⚪")
    
    lines = [
        f"📋 任務：{result.intent}",
        f"📌 標準：{' · '.join(d.get('description','')[:30] if isinstance(d, dict) else str(d)[:30] for d in result.deliverables[:4])}",
        f"🎯 信心：{result.confidence:.0%}  [{result.mode} {icon}]",
        "─" * 40,
    ]
    return "\n".join(lines)


def tsig_to_task_spec(result: TSIGResult):
    """Convert TSIGResult to BRSCP TaskSpec for verifier integration."""
    # Import here to avoid circular dependency
    from brscp_v04 import TaskSpec, Deliverable as BRSCPDeliverable
    
    deliverables = []
    for d in result.deliverables:
        if isinstance(d, dict):
            deliverables.append(BRSCPDeliverable(
                id=d.get("id", "d?"),
                description=d.get("description", ""),
                validator_type=d.get("validator_type", "nonempty"),
                validator_args=d.get("validator_args", {}),
                required=d.get("required", True),
            ))
    
    return TaskSpec(
        task_id=f"tsig-{int(time.time())}",
        intent=result.intent,
        deliverables=deliverables,
        task_type=result.task_type,
        output_type=result.output_type,
    )


# ── Serialization ────────────────────────────────────────────────────────────

def tsig_to_json(result: TSIGResult) -> str:
    """Serialize TSIGResult to JSON string."""
    data = {
        "version": result.version,
        "intent": result.intent,
        "deliverables": result.deliverables,
        "display_line": result.display_line,
        "confidence": result.confidence,
        "mode": result.mode,
        "task_type": result.task_type,
        "output_type": result.output_type,
        "inference_ms": round(result.inference_ms, 2),
        "token_count": result.token_count,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)


def tsig_from_json(json_str: str) -> TSIGResult:
    """Deserialize TSIGResult from JSON string. Raises ValueError on invalid data."""
    data = json.loads(json_str)
    
    # Type validation (strict)
    if not isinstance(data.get("intent"), str):
        raise ValueError(f"intent must be str, got {type(data.get('intent'))}")
    conf = data.get("confidence", 0.5)
    if not isinstance(conf, (int, float)):
        raise ValueError(f"confidence must be numeric, got {type(conf)}: {conf}")
    if not (0.0 <= float(conf) <= 1.0):
        raise ValueError(f"confidence must be 0.0-1.0, got {conf}")
    
    return TSIGResult(
        intent=data["intent"],
        deliverables=data.get("deliverables", []),
        display_line=data.get("display_line", ""),
        confidence=float(conf),
        mode=data.get("mode", "MINIMAL"),
        task_type=data.get("task_type", "general"),
        output_type=data.get("output_type", "text"),
        inference_ms=data.get("inference_ms", 0),
        token_count=data.get("token_count", 0),
        version=data.get("version", TSIG_VERSION),
    )


# ── Runtime Decorator ────────────────────────────────────────────────────────

def brscp_runtime(task_type="general", output_type="text", tau=0.80, llm_fn=None):
    """
    Decorator: wraps any agent function with BRSCP always-on runtime.
    
    Usage:
        @brscp_runtime(task_type="code_gen", output_type="code")
        def my_agent(conversation):
            return llm.chat(conversation)
    """
    def decorator(agent_fn):
        def wrapper(conversation, **kwargs):
            # Step 1: TSIG inference
            tsig_result = infer_task_spec(
                conversation, llm_fn=llm_fn,
                task_type_hint=task_type, output_type_hint=output_type
            )
            
            # Display TSIG to user
            print(display_tsig(tsig_result))
            
            # Step 2: Run agent
            response = agent_fn(conversation, **kwargs)
            
            # Step 3: BRSCP verification
            from brscp_v04 import BRSCPVerifier
            task_spec = tsig_to_task_spec(tsig_result)
            
            def self_judge(conv, intent):
                # Default self-judge (should be overridden for real use)
                return {
                    "flaws_found": ["default judge - no real analysis performed"] * 3,
                    "requirements_cited": [],
                    "uncited_requirements": [],
                    "quality_score": 0.5,
                    "coverage_score": 0.5,
                    "honest_ready": False,
                    "tokens_used": 0,
                }
            
            verifier = BRSCPVerifier(task_spec, self_judge, tau)
            full_conv = conversation + [{"role": "assistant", "content": response}]
            verdict = verifier.check(full_conv)
            
            if verdict.action == "COMPLETE":
                return response
            elif verdict.action == "ESCALATE":
                return f"{response}\n\n[BRSCP ESCALATE] {verdict.reason}"
            else:  # CONTINUE
                # In real use, this would loop back
                return f"{response}\n\n[BRSCP CONTINUE] {verdict.reason}"
        
        wrapper.__wrapped__ = agent_fn
        wrapper.__tsig_config__ = {"task_type": task_type, "output_type": output_type, "tau": tau}
        return wrapper
    return decorator


# ── Main (self-test) ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("TSIG Module v1.0 — Self Test")
    print("=" * 60)
    
    # Test 1: Basic Chinese request
    conv1 = [{"role": "user", "content": "幫我寫一個 Python 腳本來分析 CSV 資料"}]
    r1 = infer_task_spec(conv1)
    print(f"\n[Test 1] Chinese code request")
    print(display_tsig(r1))
    print(f"  task_type={r1.task_type}, output_type={r1.output_type}")
    
    # Test 2: English debug request
    conv2 = [{"role": "user", "content": "Fix the bug in my login function that causes a 500 error"}]
    r2 = infer_task_spec(conv2)
    print(f"\n[Test 2] English debug request")
    print(display_tsig(r2))
    print(f"  task_type={r2.task_type}, output_type={r2.output_type}")
    
    # Test 3: Ambiguous request
    conv3 = [{"role": "user", "content": "做得更好一點"}]
    r3 = infer_task_spec(conv3)
    print(f"\n[Test 3] Ambiguous request")
    print(display_tsig(r3))
    print(f"  confidence={r3.confidence}")
    
    # Test 4: Empty conversation
    conv4 = []
    r4 = infer_task_spec(conv4)
    print(f"\n[Test 4] Empty conversation")
    print(display_tsig(r4))
    
    # Test 5: Greeting only
    conv5 = [{"role": "user", "content": "你好"}]
    r5 = infer_task_spec(conv5)
    print(f"\n[Test 5] Greeting only")
    print(display_tsig(r5))
    
    # Test 6: Serialization roundtrip
    json_str = tsig_to_json(r1)
    r1_restored = tsig_from_json(json_str)
    assert r1_restored.intent == r1.intent
    assert r1_restored.confidence == r1.confidence
    print(f"\n[Test 6] Serialization roundtrip: PASS")
    
    print(f"\n{'=' * 60}")
    print("Self-test complete. All basic tests passed.")
    print(f"{'=' * 60}")
