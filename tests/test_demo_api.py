from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from review_triage.demo.app import create_app
from review_triage.demo.offline import create_offline_app
from review_triage.schemas import (
    ContentType,
    FinalPolicyRoute,
    ProcessingErrorResult,
    ProcessingStatus,
    ReviewCase,
    RiskLevel,
    RiskResult,
    RouteDecision,
    WorkflowState,
)


REQUEST = {
    "source_text": "Delete this workspace permanently.",
    "translation": "永久删除此工作区。",
    "content_type": "UI",
    "brand_or_domain": None,
    "context_notes": None,
}


def routed_state(
    *,
    route: FinalPolicyRoute = FinalPolicyRoute.HUMAN_REQUIRED,
    risk: RiskLevel = RiskLevel.HIGH,
) -> WorkflowState:
    case = ReviewCase(
        case_id="api-case-1",
        source_text=REQUEST["source_text"],
        translation=REQUEST["translation"],
        content_type=ContentType.UI,
        processing_status=ProcessingStatus.ROUTED,
    )
    return WorkflowState(
        eval_run_id="api-run-1",
        review_case=case,
        risk_result=RiskResult(
            case_id=case.case_id,
            risk_level=risk,
            risk_factors=["stub"],
            reason="Backend-owned risk reason.",
            missing_context_fields=(
                ["deployment_surface"]
                if risk == RiskLevel.INSUFFICIENT_CONTEXT
                else []
            ),
            clarification_question=(
                "Where will this copy be shown?"
                if risk == RiskLevel.INSUFFICIENT_CONTEXT
                else None
            ),
            model_version="stub-v1",
            prompt_version="stub-risk-v1",
        ),
        route_decision=RouteDecision(
            case_id=case.case_id,
            final_policy_route=route,
            triggering_dimensions=[],
            blocking_dimensions=[],
            sample_audit_dimensions=[],
            route_reason_codes=["BACKEND_OWNED_REASON"],
        ),
    )


class StubService:
    def __init__(self, result: WorkflowState) -> None:
        self.result = result
        self.calls = []

    def process_case(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class DemoAPITests(unittest.TestCase):
    def test_valid_request_reaches_service_and_returns_http_success(self) -> None:
        service = StubService(routed_state())
        client = TestClient(
            create_app(
                service_provider=lambda: service,
                eval_run_id_factory=lambda: "offline-test-run-id",
            )
        )

        response = client.post("/api/review", json=REQUEST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["case_id"], "api-case-1")
        self.assertEqual(len(service.calls), 1)
        self.assertEqual(service.calls[0]["raw_input"].translation, REQUEST["translation"])
        self.assertEqual(service.calls[0]["eval_run_id"], "offline-test-run-id")
        self.assertEqual(service.calls[0]["run_mode"], "DEVELOPMENT")

    def test_backend_enums_receive_correct_chinese_display_labels(self) -> None:
        route_labels = {
            FinalPolicyRoute.AUTO_PASS: "自动放行",
            FinalPolicyRoute.SAMPLE_POOL: "进入抽检",
            FinalPolicyRoute.HUMAN_REQUIRED: "必须人工复核",
        }
        risk_labels = {
            RiskLevel.HIGH: "高风险",
            RiskLevel.MEDIUM: "中风险",
            RiskLevel.LOW: "低风险",
            RiskLevel.INSUFFICIENT_CONTEXT: "上下文不足",
        }
        for route, route_label in route_labels.items():
            for risk, risk_label in risk_labels.items():
                with self.subTest(route=route, risk=risk):
                    service = StubService(routed_state(route=route, risk=risk))
                    response = TestClient(
                        create_app(service_provider=lambda: service)
                    ).post("/api/review", json=REQUEST)
                    payload = response.json()
                    self.assertEqual(payload["final_route"]["code"], route.value)
                    self.assertEqual(payload["final_route"]["label_zh"], route_label)
                    self.assertEqual(payload["risk"]["level"], risk.value)
                    self.assertEqual(payload["risk"]["label_zh"], risk_label)

    def test_invalid_request_has_controlled_validation_error(self) -> None:
        service = StubService(routed_state())
        response = TestClient(create_app(service_provider=lambda: service)).post(
            "/api/review",
            json={"source_text": "", "translation": "候选译文", "content_type": "UI"},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(service.calls, [])

    def test_service_safe_processing_error_is_frontend_safe(self) -> None:
        service = StubService(
            WorkflowState(
                eval_run_id="failed-run",
                processing_error=ProcessingErrorResult(
                    node_name="NODE-01",
                    error_code="LLM_API_FAILURE",
                    error_message="Provider unavailable after configured retries",
                ),
            )
        )
        response = TestClient(create_app(service_provider=lambda: service)).post(
            "/api/review", json=REQUEST
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["processing_status"], "PROCESSING_ERROR")
        self.assertIsNone(payload["final_route"])
        self.assertEqual(payload["processing_error"]["code"], "LLM_API_FAILURE")
        self.assertEqual(payload["processing_error"]["safe_disposition"], "STOP_PROCESSING")

    def test_adapter_preserves_backend_route_without_deriving_or_overriding(self) -> None:
        service = StubService(
            routed_state(route=FinalPolicyRoute.SAMPLE_POOL, risk=RiskLevel.HIGH)
        )
        payload = TestClient(create_app(service_provider=lambda: service)).post(
            "/api/review", json=REQUEST
        ).json()

        self.assertEqual(payload["final_route"]["code"], "SAMPLE_POOL")
        self.assertEqual(payload["route_reason_codes"], ["BACKEND_OWNED_REASON"])

    def test_offline_app_executes_real_workflow_without_paid_provider(self) -> None:
        offline_app = create_offline_app()
        with patch(
            "review_triage.providers.deepseek.DeepSeekProvider.invoke_structured",
            side_effect=AssertionError("paid provider must not be called"),
        ):
            response = TestClient(offline_app).post("/api/review", json=REQUEST)
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["processing_status"], "ROUTED")
        self.assertEqual(payload["final_route"]["code"], "HUMAN_REQUIRED")
        self.assertEqual(payload["case"]["source_text"], REQUEST["source_text"])
        self.assertEqual(len(payload["dimensions"]), 4)
        self.assertEqual(
            {item["dimension"] for item in payload["dimensions"]},
            {"TERMINOLOGY", "ACCURACY", "LOCALE", "AUDIENCE"},
        )
        self.assertNotIn("model_reported_sources", payload["dimensions"][0])
        self.assertTrue(payload["reliability_decisions"])
        self.assertIsNone(payload["evidence"])
        self.assertGreater(len(offline_app.state.offline_llm.calls), 0)


if __name__ == "__main__":
    unittest.main()
