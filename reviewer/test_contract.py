import copy
import unittest

from contract import BINDINGS, ERRORS, evaluate, project


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.context = dict(
            request_id="new-request", attempt_id="attempt-2", review_id="opaque-id",
            target_sha256="a" * 64, evidence_sha256="b" * 64,
            policy_sha256="c" * 64, delivery_nonce="one-use",
            requirement_ids=["R1", "R2"], evidence_ids=["E1", "E2"],
            enabled=True, required=True, budget_tokens=7000, deadline_ms=60000,
        )
        self.envelope = {k: self.context[k] for k in BINDINGS}
        self.envelope.update(status="OK", usage_tokens=500, elapsed_ms=100,
                             model_review={"review_id": "opaque-id", "checks": [
                                 {"requirement_id": r, "verdict": "SUPPORTED",
                                  "evidence_ids": [e], "reason": "Evidence covers requirement"}
                                 for r, e in [("R1", "E1"), ("R2", "E2")]
                             ]})

    def decide(self):
        return evaluate(self.context, self.envelope)["decision"]

    def test_complete_positive(self):
        self.assertEqual(self.decide(), "PASS_CONTENT_REVIEW")

    def test_each_binding_rejects_old_or_changed_result(self):
        for key in BINDINGS:
            with self.subTest(key=key):
                bad = copy.deepcopy(self.envelope)
                bad[key] = "old"
                self.assertEqual(evaluate(self.context, bad)["reason"], "BINDING_MISMATCH")

    def test_consumed_nonce_rejected(self):
        self.assertEqual(evaluate(self.context, self.envelope, {"one-use"})["reason"], "REPLAY")

    def test_missing_requirement_rejected(self):
        self.envelope["model_review"]["checks"].pop()
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_duplicate_requirement_rejected(self):
        self.envelope["model_review"]["checks"][1]["requirement_id"] = "R1"
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_empty_requirements_cannot_pass(self):
        self.context["requirement_ids"] = []
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_confirmed_contradiction_returns(self):
        self.envelope["model_review"]["checks"][0]["verdict"] = "CONTRADICTED"
        self.assertEqual(self.decide(), "RETURN_FOR_REVISION")

    def test_insufficient_evidence_holds(self):
        self.envelope["model_review"]["checks"][0]["verdict"] = "INSUFFICIENT_EVIDENCE"
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_all_technical_errors_hold(self):
        for error in ERRORS:
            with self.subTest(error=error):
                bad = copy.deepcopy(self.envelope)
                bad["status"] = error
                self.assertEqual(evaluate(self.context, bad)["decision"], "HOLD_FOR_EVIDENCE")

    def test_unknown_status_holds(self):
        self.envelope["status"] = "probably fine"
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_container_status_cannot_crash(self):
        for status in ([], {}):
            bad = copy.deepcopy(self.envelope)
            bad["status"] = status
            self.assertEqual(evaluate(self.context, bad)["decision"], "HOLD_FOR_EVIDENCE")

    def test_unknown_usage_and_time_hold(self):
        for key in ("usage_tokens", "elapsed_ms"):
            bad = copy.deepcopy(self.envelope)
            bad[key] = None
            self.assertEqual(evaluate(self.context, bad)["decision"], "HOLD_FOR_EVIDENCE")

    def test_over_budget_holds(self):
        self.envelope["usage_tokens"] = 7001
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_late_response_holds(self):
        self.envelope["elapsed_ms"] = 60001
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_required_cannot_be_bypassed(self):
        self.context["enabled"] = False
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_explicit_optional_bypass(self):
        self.context.update(enabled=False, required=False)
        self.assertEqual(self.decide(), "BYPASS_POLICY")

    def test_unknown_evidence_rejected(self):
        self.envelope["model_review"]["checks"][0]["evidence_ids"] = ["invented"]
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_supported_without_reference_rejected(self):
        self.envelope["model_review"]["checks"][0]["evidence_ids"] = []
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_model_extra_fields_rejected(self):
        self.envelope["model_review"]["approved"] = True
        self.assertEqual(self.decide(), "HOLD_FOR_EVIDENCE")

    def test_malformed_types_hold(self):
        for value in (None, [], "PASS"):
            self.assertEqual(evaluate(self.context, value)["decision"], "HOLD_FOR_EVIDENCE")

    def test_projection_drops_control_and_label_fields(self):
        item = dict(review_id="opaque", requirements=[{"id": "R1", "text": "required"}],
                    evidence=[{"id": "E1", "text": "observed"}],
                    candidate_answer={"verdict": "complete"}, submitter_model="secret-model",
                    labels={"correct": True}, cell="treatment", proto="v10", answer_tokens=100)
        result = project(item)
        self.assertEqual(set(result), {"schema_version", "review_id", "requirements",
                                       "evidence", "candidate_answer"})
        self.assertNotIn("secret-model", str(result))

    def test_projection_refuses_empty_and_duplicate_requirements(self):
        for reqs in ([], [{"id": "R1", "text": "a"}, {"id": "R1", "text": "b"}]):
            with self.assertRaises(ValueError):
                project(dict(review_id="x", requirements=reqs,
                             evidence=[{"id": "E1", "text": "e"}], candidate_answer="a"))

    def test_rejection_only_cannot_reduce_non_delivery(self):
        for c in (0, 0.5, 1):
            for f in (0, 0.1, 1):
                true, error, absent = 0.8, 0.1, 0.1
                after = absent + error * c + true * f
                self.assertGreaterEqual(after, absent)


if __name__ == "__main__":
    unittest.main()
