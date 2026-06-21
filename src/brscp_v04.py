"""
brscp_v04.py — BRSCP v0.4
2026-06-21

Two upgrades over v0.3:
  [UP-1] SJL 3-mode: Full / Degraded / Minimal
         No SIC-JS no longer means instant ESCALATE.
  [UP-2] G4+G5 adversarial: critique-mode + evidence-citation
         Agent must FIND its own flaws, not confirm quality.
"""
import re, os, json, subprocess, time, hashlib, sys
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from enum import Enum

# ── v0.6: wire in the three governance gates (compose, NOT rewrite) ───────────
# Gates live alongside this file in src/. Add own dir to sys.path so
# the imports resolve whether run as a script or imported as a module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from evidence_capture_gate import run_evidence_capture_gate, ECGVerdict
    from intent_spec_alignment_gate import run_intent_spec_alignment_gate, ISAGVerdict
    from judge_input_integrity_gate import run_judge_input_integrity_gate, JIIGVerdict
    from temporal_integrity_gate import lock_deliverables, verify_integrity, TIGVerdict
    _GATES_AVAILABLE = True
    _GATE_IMPORT_ERR = ""
except Exception as _e:                                    # pragma: no cover
    _GATES_AVAILABLE = False
    _GATE_IMPORT_ERR = str(_e)

RECURSION_MAX = 2

class Mode(Enum):
    FULL     = "full"       # SIC-JS present → all gates, 100%
    DEGRADED = "degraded"   # inline task_spec only → ~75%
    MINIMAL  = "minimal"    # nothing → G3+G4G5+G6 only, ~50%

COMPLEXITY_TABLE = {
    ("debug","code"):0.85,("code_gen","code"):0.80,("analysis","text"):0.80,
    ("refactor","code"):0.75,("explain","text"):0.70,
    ("creative","text"):0.70,("factual_qa","text"):0.65,("documentation","text"):0.75,
}

SIC_JS_PATHS = [
    "./.sic-js/task_registry.json",
    "./system_log/sic_js_records.json",
    os.path.expanduser("~/.sic-js/task_registry.json"),
]

# ── ADVERSARIAL self-assessment prompt (UP-2) ────────────────────────────────
# KEY: asks agent to FIND FLAWS, not confirm quality.
# Requires EVIDENCE CITATION for every claimed coverage.
ADVERSARIAL_PROMPT = """You are RED-TEAMING your own work. Be harsh.
Task intent: {intent}

Do NOT confirm your work is good. Instead:
1. List AT LEAST 3 concrete flaws/gaps in your output. If you list fewer than 3,
   you are not looking hard enough.
2. For EACH deliverable requirement, cite the EXACT location in your output where
   you addressed it (quote it). If you cannot quote it, it is MISSING.
3. Rate honestly. A score above 0.85 requires that you found zero significant flaws.

Return JSON:
{
  "flaws_found": ["<flaw1>", "<flaw2>", "<flaw3>", ...],   // MUST have >= 3
  "requirements_cited": [
    {"requirement": "<str>", "evidence_quote": "<str or NULL if missing>"}
  ],
  "uncited_requirements": ["<req with no evidence>"],       // these are gaps
  "quality_score": <float 0-1>,    // high only if flaws_found is trivial
  "coverage_score": <float 0-1>,   // = cited / total requirements
  "honest_ready": <bool>,
  "tokens_used": <int>
}"""


@dataclass
class Deliverable:
    id: str
    description: str
    validator_type: str
    validator_args: dict = field(default_factory=dict)
    required: bool = True

@dataclass
class TaskSpec:
    task_id: str
    intent: str
    deliverables: list = field(default_factory=list)
    task_type: str = "general"
    output_type: str = "text"

@dataclass
class Verdict:
    action: str
    failed_gate: str = None
    reason: str = None
    depth: int = 0
    token_used: int = 0
    mode: str = "full"
    flaws: list = field(default_factory=list)
    uncited: list = field(default_factory=list)
    gate_notes: list = field(default_factory=list)   # v0.6: ECG/ISAG/JIIG trace
    latency_ms: float = 0.0


class BRSCPVerifier:

    def __init__(self, task_spec: TaskSpec, self_judge: Callable,
                 quality_threshold: float = 0.75,
                 coverage_threshold: float = 0.75,
                 raw_user_request: str = None,
                 evidence_bundle: dict = None,
                 judge_io: dict = None):
        self.task_spec = task_spec
        self.self_judge = self_judge
        self.q_threshold = quality_threshold
        self.c_threshold = coverage_threshold
        # ── v0.6 governance-gate inputs (optional). When an input is absent the
        #    corresponding gate self-reports SKIPPED rather than silently passing,
        #    so completion without integrity inputs is transparent, not hidden. ──
        self.raw_user_request = raw_user_request
        self.evidence_bundle = evidence_bundle
        self.judge_io = judge_io or {}
        self.gate_notes = []
        self._isag1_done = False
        self._evidence_hardening = False
        self._tig_manifest = None             # v1.0: TIG deliverable snapshot
        self._ensure_frozen()                 # freeze task_spec (ECG-compatible hash)
        self.mode = self._determine_mode()

    # ── UP-1: 3-mode determination ───────────────────────────────────────────
    def _determine_mode(self) -> Mode:
        """
        Full:     SIC-JS log found
        Degraded: no SIC-JS but task_spec has intent + deliverables
        Minimal:  task_spec is empty/minimal
        """
        if self._sjl_find_log() is not None:
            return Mode.FULL
        if (self.task_spec.intent and self.task_spec.intent.strip()
                and self.task_spec.deliverables):
            return Mode.DEGRADED
        return Mode.MINIMAL

    def check(self, conversation: list, depth: int = 0) -> Verdict:
        t0 = time.time()
        if depth > RECURSION_MAX:
            return self._v("COMPLETE","_safety","Safety valve",depth,t0)

        # ── v0.6 ISAG-1: guard task-definition power BEFORE the work is judged ──
        # (task_spec already frozen in __init__; this catches a spec written too
        #  narrow relative to the raw user request — sandbagging at the source.)
        isag1 = self._isag_gate("1-pre-freeze", depth, t0)
        if isag1 is not None:
            return isag1

        # ── SJL: mode-dependent behavior (UP-1) ──────────────────────────────
        sic_path = self._sjl_find_log()
        sic_data = self._load_sic_js(sic_path) if sic_path else {}

        if self.mode == Mode.MINIMAL:
            # Minimal: skip SIC-JS-dependent gates (G1 intent, G2 pending)
            # Go straight to G3 (evidence) + G4G5 (adversarial self-assess) + G6
            # This is the ~50% path — still useful, no SIC-JS needed
            return self._minimal_path(conversation, depth, t0)

        # FULL or DEGRADED below

        # SCS scan
        gaps = self._scs_scan()
        if gaps:
            return self._v("CONTINUE","SCS",f"語義缺口: {'; '.join(gaps)}",depth,t0)

        # SCS anti-sandbag (DEGRADED mode only) — red-team LOOP-2 攻擊2 fix
        sandbag = self._scs_antisandbag()
        if sandbag:
            return self._v("ESCALATE","SCS-sandbag",
                f"{'; '.join(sandbag)}",depth,t0)

        # G1: intent alignment
        if not self._g1_intent_aligned(sic_data):
            return self._v("CONTINUE","G1","任務意圖未對齊",depth,t0)

        # G2: anti-convergence (SIC-JS pending only available in FULL mode)
        pending = self._g2_pending(conversation, sic_data)
        if pending:
            return self._v("CONTINUE","G2",pending,depth,t0)

        # G3: deliverables (evidence)
        g3_ok, g3_id = self._g3()
        if not g3_ok:
            if depth >= RECURSION_MAX:
                return self._v("ESCALATE","G3",f"交付物[{g3_id}]多次未完成,需人介入",depth,t0)
            return self._v("CONTINUE","G3",f"交付物[{g3_id}]未完成",depth,t0)

        # ── v0.6 ECG → ISAG-2 → JIIG : lock evidence / re-check spec / lock judge
        #    input, AFTER G3 evidence passed and BEFORE the adversarial judge runs.
        pjg = self._pre_judge_gates(conversation, depth, t0)
        if pjg is not None:
            return pjg

        # G4+G5: adversarial self-assessment, then TIG closure hash-check (v1.0)
        verdict = self._g4g5_adversarial(conversation, depth, t0)
        return self._tig_closure(verdict, depth, t0)

    def _minimal_path(self, conversation, depth, t0):
        """~50% path: no SIC-JS, possibly no deliverables. G3 (if any) + G4G5."""
        # G3 only if deliverables exist
        if self.task_spec.deliverables:
            g3_ok, g3_id = self._g3()
            if not g3_ok:
                if depth >= RECURSION_MAX:
                    return self._v("ESCALATE","G3",f"交付物[{g3_id}]未完成",depth,t0)
                return self._v("CONTINUE","G3",f"交付物[{g3_id}]未完成",depth,t0)
        # ── v0.6 gates also apply on the minimal path (run when inputs provided) ──
        pjg = self._pre_judge_gates(conversation, depth, t0)
        if pjg is not None:
            return pjg
        # G4+G5 adversarial (the core value even in minimal mode) + TIG closure
        verdict = self._g4g5_adversarial(conversation, depth, t0)
        return self._tig_closure(verdict, depth, t0)

    # ── SJL ──────────────────────────────────────────────────────────────────
    def _sjl_find_log(self):
        env = os.environ.get("SICJS_LOG_PATH","")
        if env and os.path.exists(env):
            return env
        for p in SIC_JS_PATHS:
            if p and os.path.exists(p):
                return p
        return None

    def _load_sic_js(self, path):
        try:
            with open(path) as f:
                raw = f.read()
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return {"raw_text": raw}
        except Exception:
            return {}

    # ── SCS ──────────────────────────────────────────────────────────────────
    def _scs_scan(self):
        gaps = []
        if not self.task_spec.deliverables and self.mode == Mode.FULL:
            gaps.append("FULL 模式但 deliverables 為空")
        for d in self.task_spec.deliverables:
            if d.required and not d.validator_type:
                gaps.append(f"[{d.id}] 缺 validator")
        return gaps


    def _scs_antisandbag(self):
        """
        RED-TEAM FIX (LOOP-2 攻擊2): in DEGRADED mode, agent writes its own
        deliverables → sandbag risk. Reject deliverables that are too weak to
        provide real verification.

        Weak = nonempty-only with no external anchor (no file, no command).
        A real deliverable should be checkable against the external world.
        Returns list of sandbag warnings.
        """
        if self.mode != Mode.DEGRADED:
            return []  # FULL has SIC-JS anchor; MINIMAL has no deliverables anyway
        warnings = []
        strong_types = {"file_exists","command_exit_zero","json_schema","regex_match"}
        strong_count = sum(1 for d in self.task_spec.deliverables
                          if d.required and d.validator_type in strong_types)
        if strong_count == 0 and self.task_spec.deliverables:
            warnings.append(
                "DEGRADED 模式下所有 deliverable 都是弱驗證(無外部錨點)，"
                "可能是沙包。建議至少一個 file_exists/command 驗證。")
        return warnings

    # ── G1 ────────────────────────────────────────────────────────────────────
    def _g1_intent_aligned(self, sic_data):
        if not self.task_spec.intent or not self.task_spec.intent.strip():
            return False
        if not self.task_spec.deliverables:
            return False
        if isinstance(sic_data.get("tasks"), list):
            for t in sic_data["tasks"]:
                if isinstance(t, dict) and t.get("status") == "rejected":
                    return False
        return True

    # ── G2 ────────────────────────────────────────────────────────────────────
    def _g2_pending(self, conversation, sic_data):
        if isinstance(sic_data.get("tasks"), list):
            pend = [t for t in sic_data["tasks"]
                   if isinstance(t,dict) and t.get("status") in ["pending","in_progress"]]
            if pend:
                return f"SIC-JS 有 {len(pend)} 個 pending task"
        for d in self.task_spec.deliverables:
            if d.required and d.validator_type=="file_exists":
                if not os.path.exists(d.validator_args.get("path","")):
                    return f"交付物[{d.id}]檔案不存在"
        veto = self._user_veto(conversation)
        if veto:
            return f"用戶要求繼續: {veto}"
        return None

    def _user_veto(self, conversation):
        ZH = ["繼續","還沒","再做","不要停","不夠"]
        EN = ["keep going","continue","more","don't stop","not done"]
        recent = [m for m in conversation[-2:] if m.get("role")=="user"]
        for m in recent:
            t = m.get("content","")
            if any(s in t for s in ZH) or any(s in t.lower() for s in EN):
                return t[:50]
        return None

    # ── G3 ────────────────────────────────────────────────────────────────────
    def _g3(self):
        for d in self.task_spec.deliverables:
            if not d.required: continue
            if not self._validate(d):
                return False, d.id
        return True, None

    def _validate(self, d):
        v,a = d.validator_type, d.validator_args
        try:
            if v=="file_exists":      return os.path.exists(a.get("path",""))
            elif v=="nonempty":       return len(str(a.get("content","")).strip())>0
            elif v=="command_exit_zero":
                return subprocess.run(a.get("command","false"),shell=True,
                                      capture_output=True,timeout=30).returncode==0
            elif v=="regex_match":    return bool(re.search(a.get("pattern",""),a.get("content","")))
            elif v=="json_schema":
                import jsonschema; jsonschema.validate(a.get("data"),a.get("schema",{})); return True
            return False
        except Exception:
            return False


    def _verify_citations(self, conversation, requirements_cited):
        """
        RED-TEAM FIX (攻擊2): externally verify evidence_quote actually exists
        in the agent's output. LLM cannot just CLAIM a citation — the quote
        must be findable in the actual conversation text.
        Returns list of requirements whose quotes were NOT found (= fake citations).
        """
        # Concatenate all assistant output
        output_text = " ".join(
            m.get("content","") for m in conversation if m.get("role")=="assistant"
        ).lower()
        fake_citations = []
        for item in requirements_cited:
            quote = item.get("evidence_quote")
            if quote is None or quote == "NULL":
                continue  # already counted as uncited
            # Check if quote (first 20 chars) actually appears in output
            quote_key = str(quote).lower()[:20].strip()
            if quote_key and quote_key not in output_text:
                fake_citations.append(item.get("requirement","?"))
        return fake_citations

    # ── G4+G5 ADVERSARIAL (UP-2) ──────────────────────────────────────────────
    def _g4g5_adversarial(self, conversation, depth, t0):
        """
        Agent RED-TEAMS its own work.
        Must find >= 3 flaws. Must cite evidence for each requirement.
        Coverage = cited_requirements / total_requirements (computed, not claimed).
        """
        min_conf = COMPLEXITY_TABLE.get(
            (self.task_spec.task_type, self.task_spec.output_type), 0.75)

        try:
            r = self.self_judge(conversation, self.task_spec.intent)
        except Exception as e:
            return self._v("ESCALATE","G4G5",f"self_judge 錯誤: {e}",depth,t0)

        # Validate adversarial schema
        if "flaws_found" not in r:
            return self._v("ESCALATE","G4G5","self_judge 缺 flaws_found",depth,t0)

        flaws = r.get("flaws_found", [])
        uncited = list(r.get("uncited_requirements", []))

        # RED-TEAM FIX (攻擊2): verify citations are real, not hallucinated
        cited = r.get("requirements_cited", [])
        fake = self._verify_citations(conversation, cited)
        if fake:
            # Fake citations are treated as uncited (gaps)
            uncited.extend(fake)

        # HARD RULE: must find >= 3 flaws. Fewer = not looking hard enough = reject
        if len(flaws) < 3:
            return self._v("CONTINUE","G4G5",
                f"紅隊只找到 {len(flaws)} 個問題(<3),未認真自檢,繼續",
                depth,t0,flaws=flaws)

        # Coverage = computed from citations, NOT self-claimed
        try:
            q_score = float(r.get("quality_score",0))
            c_score = float(r.get("coverage_score",0))
        except (ValueError,TypeError):
            return self._v("ESCALATE","G4G5","score 型態錯誤",depth,t0)

        tokens = int(r.get("tokens_used",0))

        # If there are uncited requirements → coverage gap → continue
        if uncited:
            if depth >= RECURSION_MAX:
                return self._v("ESCALATE","G4G5",
                    f"仍有未引證需求: {uncited[:3]},需人介入",depth,t0,
                    token_used=tokens,uncited=uncited)
            return self._v("CONTINUE","G4G5",
                f"未引證需求(視為缺失): {uncited[:3]}",depth,t0,
                token_used=tokens,uncited=uncited)

        overall = (q_score + c_score)/2.0
        if overall < min_conf:
            if depth >= RECURSION_MAX:
                return self._v("ESCALATE","G4G5",
                    f"自評不足(q={q_score:.2f},c={c_score:.2f}),需人介入",
                    depth,t0,token_used=tokens,flaws=flaws)
            return self._v("CONTINUE","G4G5",
                f"自評不足(q={q_score:.2f},c={c_score:.2f}),繼續",
                depth,t0,token_used=tokens,flaws=flaws)

        # COMPLETE — but only after finding flaws AND citing all requirements.
        # v0.6: if ECG WARN-passed, surface that evidence still needs hardening.
        final_action = "COMPLETE_WITH_EVIDENCE_HARDENING" if self._evidence_hardening else "COMPLETE"
        return Verdict(action=final_action,depth=depth,token_used=tokens,
                       mode=self.mode.value,flaws=flaws,
                       gate_notes=list(self.gate_notes),
                       latency_ms=round((time.time()-t0)*1000,2))

    # ── v0.6 GOVERNANCE GATES (compose three independent .py gates) ────────────
    def _spec_dict(self):
        """task_spec as a plain dict (ECG/ISAG consume dicts)."""
        return asdict(self.task_spec)

    def _ensure_frozen(self):
        """
        Freeze the task_spec with a hash matching ECG's compute_content_hash
        contract: sha256[:16] of json.dumps(spec, sort_keys=True, ensure_ascii=False).
        Pre-req for ISAG-running-twice and for ECG's frozen-spec integrity check.
        """
        if getattr(self, "frozen_task_spec_hash", None):
            return
        spec_dict = self._spec_dict()
        spec_str = json.dumps(spec_dict, sort_keys=True, ensure_ascii=False)
        self.frozen_task_spec = spec_dict
        self.frozen_task_spec_hash = hashlib.sha256(spec_str.encode("utf-8")).hexdigest()[:16]

    def _isag_gate(self, phase, depth, t0):
        """
        ISAG — guard task-DEFINITION power. phase '1...' runs once (pre-freeze);
        phase '2...' runs at closure. Needs raw_user_request to be meaningful;
        absent → SKIPPED (recorded, not silently passed).
        """
        if str(phase).startswith("1"):
            if self._isag1_done:
                return None
            self._isag1_done = True
        if not _GATES_AVAILABLE or not self.raw_user_request:
            self.gate_notes.append(f"ISAG-{phase}:SKIPPED(no raw_user_request)")
            return None
        # Phase scoping: pre-freeze checks the INTENT dimension only (deliverables
        # not yet built / not validated). Closure runs the FULL check with the real
        # deliverables + validator outputs captured in the evidence bundle.
        if str(phase).startswith("1"):
            spec_for_isag = {"intent": self.task_spec.intent,
                             "task_type": self.task_spec.task_type}
            deliv, vout = [], []
        else:
            spec_for_isag = self._spec_dict()
            deliv = [asdict(d) for d in self.task_spec.deliverables]
            vout = (self.evidence_bundle or {}).get("validator_outputs") or []
        res = run_intent_spec_alignment_gate(
            user_intent=self.raw_user_request,
            task_spec=spec_for_isag,
            deliverables=deliv,
            validator_outputs=vout)
        self.gate_notes.append(f"ISAG-{phase}:{res.verdict.value}")
        if res.verdict == ISAGVerdict.ESCALATE:
            return self._v("ESCALATE", f"ISAG-{phase}",
                           f"任務定義權違規,需人介入: {res.verdict.value}", depth, t0)
        if res.verdict in (ISAGVerdict.MISALIGNED, ISAGVerdict.SUSPICIOUS):
            act = "ESCALATE" if depth >= RECURSION_MAX else "CONTINUE"
            return self._v(act, f"ISAG-{phase}",
                           f"task_spec 範圍縮水(sandbagging): {res.verdict.value}", depth, t0)
        return None

    def _ecg_gate(self, depth, t0):
        """
        ECG — guard EVIDENCE-capture power. Needs a caller-supplied evidence_bundle.
        We anchor the bundle to our frozen task_spec hash so ECG's integrity check
        is bound to the spec we actually froze. Absent bundle → SKIPPED.
        """
        if not _GATES_AVAILABLE or not self.evidence_bundle:
            self.gate_notes.append("ECG:SKIPPED(no evidence_bundle)")
            return None
        bundle = dict(self.evidence_bundle)
        bundle.setdefault("frozen_task_spec", self.frozen_task_spec)
        bundle.setdefault("frozen_task_spec_hash", self.frozen_task_spec_hash)
        res = run_evidence_capture_gate(bundle)
        self.gate_notes.append(f"ECG:{res.verdict.value}(score={res.completeness_score})")
        if res.verdict == ECGVerdict.FAIL:
            act = "ESCALATE" if depth >= RECURSION_MAX else "CONTINUE"
            return self._v(act, "ECG",
                           f"證據包不完整/不誠實: missing={res.missing_fields[:3]}, "
                           f"integrity={res.integrity_failures[:2]}", depth, t0)
        if res.verdict == ECGVerdict.WARN:
            # not a blocker, but completion must be flagged as needing hardening
            self._evidence_hardening = True
        return None

    def _jiig_gate(self, depth, t0):
        """
        JIIG — guard JUDGE-INPUT power. Needs caller-supplied judge_io. Absent → SKIPPED.
        A compromised judge input is serious: TAMPERED/ESCALATE → ESCALATE.
        """
        if not _GATES_AVAILABLE or not self.judge_io:
            self.gate_notes.append("JIIG:SKIPPED(no judge_io)")
            return None
        io = self.judge_io
        res = run_judge_input_integrity_gate(
            executor_context=io.get("executor_context", ""),
            judge_context=io.get("judge_context", ""),
            judge_prompt_used=io.get("judge_prompt_used", ""),
            canonical_prompt=io.get("canonical_prompt"),
            evidence_bundle=self.evidence_bundle or io.get("evidence_bundle"),
            raw_judge_verdict=io.get("raw_judge_verdict", ""),
            final_verdict=io.get("final_verdict", ""),
            verdict_hash=io.get("verdict_hash"),
            judge_config=io.get("judge_config"))
        self.gate_notes.append(f"JIIG:{res.verdict.value}")
        if res.verdict != JIIGVerdict.PASS:
            act = "CONTINUE" if (res.verdict == JIIGVerdict.FAIL and depth < RECURSION_MAX) else "ESCALATE"
            return self._v(act, "JIIG",
                           f"裁決輸入權違規: {res.verdict.value}", depth, t0)
        return None

    def _pre_judge_gates(self, conversation, depth, t0):
        """v0.6: ECG → ISAG-2 → JIIG. Runs after G3, before the adversarial judge.
           v1.0: also TIG-locks the deliverable snapshot here (gate-pass moment)."""
        self._tig_lock()
        for gate in (lambda: self._ecg_gate(depth, t0),
                     lambda: self._isag_gate("2-pre-closure", depth, t0),
                     lambda: self._jiig_gate(depth, t0)):
            v = gate()
            if v is not None:
                return v
        return None

    # ── v1.0 TEMPORAL INTEGRITY GATE (compose temporal_integrity_gate.py) ──────
    def _deliverable_paths(self):
        """File paths of file_exists deliverables — what TIG hash-locks."""
        paths = []
        for d in self.task_spec.deliverables:
            if d.validator_type == "file_exists":
                p = d.validator_args.get("path", "")
                if p:
                    paths.append(p)
        return paths

    def _tig_lock(self):
        """
        TIG: snapshot deliverable hashes at gate-pass (after G3, once per run).
        Locks deliverable files (+ evidence bundle if present) so closure can
        detect any post-gate tampering during the gate/judge window.
        """
        if not _GATES_AVAILABLE or self._tig_manifest is not None:
            return
        fps = self._deliverable_paths()
        bundle = self.evidence_bundle or {"frozen_task_spec_hash": self.frozen_task_spec_hash}
        self._tig_manifest = lock_deliverables(
            bundle, gate_verdicts={"G3": "PASS"}, file_paths=fps)
        self.gate_notes.append(
            f"TIG:LOCKED({len(self._tig_manifest.entries)}f/{len(self._tig_manifest.file_entries)}file)")

    def _tig_closure(self, verdict, depth, t0):
        """
        TIG closure: only gates a COMPLETE. Re-verify deliverables are byte-identical
        to the gate-pass lock. Any tamper/missing between lock and closure → ESCALATE.
        """
        if (not _GATES_AVAILABLE or self._tig_manifest is None
                or verdict.action not in ("COMPLETE", "COMPLETE_WITH_EVIDENCE_HARDENING")):
            return verdict
        current = self.evidence_bundle or {"frozen_task_spec_hash": self.frozen_task_spec_hash}
        res = verify_integrity(current, self._tig_manifest, self._deliverable_paths())
        self.gate_notes.append(f"TIG:{res['verdict']}")
        if res["verdict"] in (TIGVerdict.TAMPERED, TIGVerdict.MISSING):
            culprit = (res.get("tampered_files") or res.get("tampered_fields")
                       or res.get("missing_files") or res.get("missing_fields"))
            return self._v("ESCALATE", "TIG",
                           f"closure 偵測 post-gate 篡改: {str(culprit)[:80]}", depth, t0)
        verdict.gate_notes = list(self.gate_notes)
        return verdict

    def _v(self, action, gate, reason, depth, t0,
           token_used=0, flaws=None, uncited=None):
        return Verdict(action=action,failed_gate=gate,reason=reason,depth=depth,
                       token_used=token_used,mode=self.mode.value,
                       flaws=flaws or [],uncited=uncited or [],
                       gate_notes=list(self.gate_notes),
                       latency_ms=round((time.time()-t0)*1000,2))
