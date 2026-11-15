"""Offline reference contract; no model calls, authorization, or atomic nonce store."""

import copy
import re


BINDINGS = (
    "request_id", "attempt_id", "review_id", "target_sha256",
    "evidence_sha256", "policy_sha256", "delivery_nonce",
)
VERDICTS = {"SUPPORTED", "CONTRADICTED", "INSUFFICIENT_EVIDENCE"}
ERRORS = {
    "TIMEOUT", "SOURCE_UNAVAILABLE", "MODEL_IDENTITY_UNVERIFIED",
    "PARSE_ERROR", "BUDGET_EXCEEDED",
}


def _ids(values):
    return (isinstance(values, list) and bool(values)
            and all(isinstance(x, str) and bool(x.strip()) for x in values)
            and len(values) == len(set(values)))


def project(item):
    """Return a minimal reviewer view. Caller must provide verified evidence."""
    if not isinstance(item, dict):
        raise ValueError("invalid item")
    if not isinstance(item.get("review_id"), str) or not item["review_id"].strip():
        raise ValueError("missing review_id")
    result = {"schema_version": "brscp-review/0.1", "review_id": item["review_id"]}
    for key in ("requirements", "evidence"):
        values = item.get(key)
        if not isinstance(values, list) or not values:
            raise ValueError("empty " + key)
        clean = []
        for value in values:
            if (not isinstance(value, dict)
                    or not isinstance(value.get("id"), str)
                    or not isinstance(value.get("text"), str)
                    or not value["text"].strip()):
                raise ValueError("invalid " + key)
            clean.append({"id": value["id"], "text": value["text"]})
        if not _ids([v["id"] for v in clean]):
            raise ValueError("duplicate or empty ids")
        result[key] = clean
    if not isinstance(item.get("candidate_answer"), (dict, list, str)):
        raise ValueError("invalid candidate_answer")
    result["candidate_answer"] = copy.deepcopy(item["candidate_answer"])
    return result


def evaluate(context, envelope, consumed_nonces=frozenset()):
    """Validate controller-owned context and model envelope, without side effects."""
    def hold(reason):
        return {"decision": "HOLD_FOR_EVIDENCE", "reason": reason}

    if not isinstance(context, dict):
        return hold("INVALID_CONFIGURATION")
    if any(type(context.get(k)) is not bool for k in ("enabled", "required")):
        return hold("INVALID_CONFIGURATION")
    if not context["enabled"]:
        if context["required"]:
            return hold("HOLD_REQUIRED_REVIEW")
        return {"decision": "BYPASS_POLICY", "reason": "DISABLED_BY_POLICY"}
    if (not _ids(context.get("requirement_ids"))
            or not _ids(context.get("evidence_ids"))):
        return hold("INVALID_CONFIGURATION")
    for key in BINDINGS:
        value = context.get(key)
        if not isinstance(value, str) or not value.strip():
            return hold("INVALID_CONFIGURATION")
        if key.endswith("sha256") and not re.fullmatch("[0-9a-f]{64}", value):
            return hold("INVALID_CONFIGURATION")
    for key in ("budget_tokens", "deadline_ms"):
        if type(context.get(key)) is not int or context[key] <= 0:
            return hold("INVALID_CONFIGURATION")
    if not isinstance(envelope, dict):
        return hold("INVALID_REVIEW")
    if any(envelope.get(k) != context[k] for k in BINDINGS):
        return hold("BINDING_MISMATCH")
    if context["delivery_nonce"] in consumed_nonces:
        return hold("REPLAY")
    status = envelope.get("status")
    if not isinstance(status, str):
        return hold("INVALID_REVIEW")
    if status in ERRORS:
        return hold(status)
    if status != "OK":
        return hold("INVALID_REVIEW")
    for key, limit in (("usage_tokens", "budget_tokens"), ("elapsed_ms", "deadline_ms")):
        value = envelope.get(key)
        if type(value) is not int or value < 0:
            return hold("USAGE_OR_TIME_UNKNOWN")
        if value > context[limit]:
            return hold("BUDGET_EXCEEDED" if key == "usage_tokens" else "TIMEOUT")
    review = envelope.get("model_review")
    if (not isinstance(review, dict) or set(review) != {"review_id", "checks"}
            or review["review_id"] != context["review_id"]):
        return hold("INVALID_REVIEW")
    checks = review["checks"]
    if not isinstance(checks, list) or not checks:
        return hold("INCOMPLETE_COVERAGE")
    seen, outcomes = [], []
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
            "requirement_id", "verdict", "evidence_ids", "reason"
        }:
            return hold("INVALID_REVIEW")
        rid, verdict = check["requirement_id"], check["verdict"]
        refs, reason = check["evidence_ids"], check["reason"]
        if not isinstance(rid, str) or not isinstance(verdict, str) or verdict not in VERDICTS:
            return hold("INVALID_REVIEW")
        if (not isinstance(refs, list) or not all(isinstance(x, str) for x in refs)
                or len(refs) != len(set(refs))
                or not set(refs).issubset(context["evidence_ids"])):
            return hold("INVALID_EVIDENCE_REFERENCE")
        if verdict != "INSUFFICIENT_EVIDENCE" and not refs:
            return hold("INVALID_EVIDENCE_REFERENCE")
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 240:
            return hold("INVALID_REVIEW")
        seen.append(rid)
        outcomes.append(verdict)
    if len(seen) != len(set(seen)) or set(seen) != set(context["requirement_ids"]):
        return hold("INCOMPLETE_COVERAGE")
    if "CONTRADICTED" in outcomes:
        return {"decision": "RETURN_FOR_REVISION", "reason": "CONTRADICTED"}
    if "INSUFFICIENT_EVIDENCE" in outcomes:
        return hold("INSUFFICIENT_EVIDENCE")
    return {"decision": "PASS_CONTENT_REVIEW", "reason": "ALL_REQUIREMENTS_SUPPORTED"}
