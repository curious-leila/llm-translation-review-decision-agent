"""LangGraph orchestration for the MVP V1 vertical slice through GATE 3."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
from uuid import uuid4
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from review_triage.errors import (
    InvalidInputError,
    LLMProcessingError,
    PolicyConfigurationError,
    ReviewTriageError,
)
from review_triage.llm import (
    StructuredLLM,
    _provider_failure_code,
    invoke_dimension_evaluator,
    invoke_final_terminology_evaluator,
    invoke_post_eval_control_classifier,
    invoke_risk_classifier,
)
from review_triage.evidence import (
    EvidenceActionSelector,
    EvidenceCandidateAssessor,
    LLMEvidenceActionSelector,
    LLMEvidenceCandidateAssessor,
    NormativeEvidenceAdmissionPolicy,
    TerminologyEvidenceLoop,
)
from review_triage.evidence_tools import ControlledEvidenceTools, EvidenceTools
from review_triage.nodes import (
    node_00_normalize,
    node_04_reliability,
    node_05_aggregate,
)
from review_triage.persistence import SQLiteRepository
from review_triage.prompts import EvaluatorPromptLoader, ReviewPromptRegistry
from review_triage.schemas import (
    Dimension,
    BaselineDimensionEvaluation,
    DimensionEvaluation,
    EvidenceAction,
    EvidenceStatus,
    ProcessingErrorResult,
    ProcessingStatus,
    PostEvalControlDecision,
    QualityEvaluationInput,
    ReviewCase,
    ReviewCaseInput,
    RiskClassificationInput,
    RiskLevel,
    RiskResult,
    RouteDecision,
    TerminologyDetails,
    TerminologyEvidenceState,
    WorkflowState,
)


class GraphState(TypedDict, total=False):
    eval_run_id: str
    raw_input: ReviewCaseInput | dict[str, Any]
    review_case: ReviewCase
    risk_result: RiskResult
    dimension_evaluations: list[DimensionEvaluation]
    post_eval_control: PostEvalControlDecision
    terminology_evidence: TerminologyEvidenceState
    reliability_decisions: list[Any]
    route_decision: Any
    terminal_status: str


POST_EVAL_TERM_CANDIDATE_NOT_EXACT_SOURCE_SPAN = (
    "POST_EVAL_TERM_CANDIDATE_NOT_EXACT_SOURCE_SPAN"
)


def is_exact_source_span_v1(*, source_text: str, term_candidate: str) -> bool:
    """Return whether the candidate is a literal, continuous source span."""

    return bool(term_candidate) and term_candidate in source_text


@dataclass(frozen=True)
class SharedPreEvidenceState:
    """One auditable pre-evidence evaluation, reusable by B and C only."""

    review_case: ReviewCase
    risk_result: RiskResult
    dimension_evaluations: list[DimensionEvaluation]
    post_eval_control: PostEvalControlDecision
    state_hash: str


class ReviewTriageWorkflow:
    """NODE-00→01→02→03-if-needed→04→05 with explicit audit logs."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        llm: StructuredLLM,
        evidence_selector: EvidenceActionSelector | None = None,
        evidence_assessor: EvidenceCandidateAssessor | None = None,
        evidence_tools: EvidenceTools | None = None,
        normative_admission_policy: NormativeEvidenceAdmissionPolicy | None = None,
        max_tool_calls: int = 4,
        available_evidence_actions: tuple[EvidenceAction, ...] | None = None,
        baseline_id: str = "C_AGENT",
        prompt_loader: EvaluatorPromptLoader | None = None,
        prompt_registry: ReviewPromptRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.llm = llm
        self.evidence_tools = evidence_tools or ControlledEvidenceTools()
        self.normative_admission_policy = normative_admission_policy
        self.max_tool_calls = max_tool_calls
        self.available_evidence_actions = available_evidence_actions or (
            EvidenceAction.SEARCH_OFFICIAL_DOCS,
            EvidenceAction.SEARCH_GLOSSARY,
            EvidenceAction.SEARCH_MEMORY,
        )
        self.baseline_id = baseline_id
        self.prompt_registry = prompt_registry or ReviewPromptRegistry()
        self.evaluator_prompts = (prompt_loader or EvaluatorPromptLoader()).load_all()
        self.evidence_selector = evidence_selector or LLMEvidenceActionSelector(
            llm, prompt_registry=self.prompt_registry
        )
        self.evidence_assessor = evidence_assessor or LLMEvidenceCandidateAssessor(
            llm, prompt_registry=self.prompt_registry
        )
        self.graph = self._build_graph()

    def _provider_metadata(self) -> dict[str, Any]:
        metadata = getattr(self.llm, "public_metadata", {})
        if callable(metadata):
            metadata = metadata()
        return dict(metadata) if isinstance(metadata, dict) else {}

    def _build_graph(self):
        builder = StateGraph(GraphState)
        builder.add_node("node_00", self._node_00)
        builder.add_node("node_01", self._node_01)
        builder.add_node("node_02", self._node_02)
        builder.add_node("node_03", self._node_03)
        builder.add_node("node_04", self._node_04)
        builder.add_node("node_05", self._node_05)
        builder.add_edge(START, "node_00")
        builder.add_conditional_edges(
            "node_00",
            self._after_node_00,
            {"continue": "node_01", "stop": END},
        )
        builder.add_conditional_edges(
            "node_01",
            self._after_node_01,
            {"continue": "node_02", "stop": END},
        )
        builder.add_conditional_edges(
            "node_02",
            self._after_node_02,
            {"evidence": "node_03", "continue": "node_04"},
        )
        builder.add_edge("node_03", "node_04")
        builder.add_edge("node_04", "node_05")
        builder.add_edge("node_05", END)
        return builder.compile()

    def _node_00(self, state: GraphState) -> GraphState:
        case = node_00_normalize(state["raw_input"])
        self.repository.save_review_case(state["eval_run_id"], case)
        reason = (
            "content_type OTHER is outside the frozen policy scope"
            if case.processing_status == ProcessingStatus.OUT_OF_SCOPE
            else "required fields and controlled enums validated"
        )
        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-00",
            input_state=state["raw_input"],
            output_state=case,
            decision_reason=reason,
            reason_code=case.processing_status.value,
            policy_version=case.reliability_policy_id,
        )
        return {
            "review_case": case,
            "terminal_status": (
                "OUT_OF_SCOPE"
                if case.processing_status == ProcessingStatus.OUT_OF_SCOPE
                else "CONTINUE"
            ),
        }

    @staticmethod
    def _after_node_00(state: GraphState) -> str:
        return "stop" if state.get("terminal_status") == "OUT_OF_SCOPE" else "continue"

    def _node_01(self, state: GraphState) -> GraphState:
        case = state["review_case"]
        payload = RiskClassificationInput(
            source_text=case.source_text,
            content_type=case.content_type,
            brand_or_domain=case.brand_or_domain,
            context_notes=case.context_notes,
        )
        result = invoke_risk_classifier(
            self.llm,
            case_id=case.case_id,
            payload=payload,
            prompt_registry=self.prompt_registry,
        )
        self.repository.save_risk_result(result)
        needs_context = result.risk_level == RiskLevel.INSUFFICIENT_CONTEXT
        if needs_context:
            case.processing_status = ProcessingStatus.NEEDS_CONTEXT
            self.repository.update_case_status(case.case_id, case.processing_status.value)
        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-01",
            input_state=payload,
            output_state={
                "result": result,
                "provider": self._provider_metadata(),
            },
            decision_reason=result.reason,
            reason_code=("NEEDS_CONTEXT" if needs_context else f"RISK_{result.risk_level.value}"),
            policy_version=case.reliability_policy_id,
            model_version=result.model_version,
            prompt_version=result.prompt_version,
            prompt_path=result.prompt_path,
            prompt_hash=result.prompt_hash,
        )
        return {
            "review_case": case,
            "risk_result": result,
            "terminal_status": "NEEDS_CONTEXT" if needs_context else "CONTINUE",
        }

    @staticmethod
    def _after_node_01(state: GraphState) -> str:
        return "stop" if state.get("terminal_status") == "NEEDS_CONTEXT" else "continue"

    def _node_02(self, state: GraphState) -> GraphState:
        case = state["review_case"]
        payload = QualityEvaluationInput(
            source_text=case.source_text,
            translation_text=case.translation,
            content_type=case.content_type,
        )

        def evaluate(dimension: Dimension) -> BaselineDimensionEvaluation:
            return invoke_dimension_evaluator(
                self.llm,
                case_id=case.case_id,
                dimension=dimension,
                payload=payload,
                prompt=self.evaluator_prompts[dimension],
            )

        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="evaluator") as pool:
            baseline_results = list(pool.map(evaluate, list(Dimension)))
        for result in baseline_results:
            self.repository.log_node(
                eval_run_id=state["eval_run_id"],
                case_id=case.case_id,
                node_name=f"NODE-02-{result.dimension.value}",
                input_state=payload,
                output_state={
                    "result": result,
                    "provider": self._provider_metadata(),
                },
                decision_reason=result.notes,
                reason_code=f"{result.dimension.value}_{result.severity.value.upper()}",
                policy_version=case.reliability_policy_id,
                model_version=result.model_version,
                prompt_version=result.prompt_version,
                prompt_path=result.prompt_path,
                prompt_hash=result.prompt_hash,
            )
        control, results = invoke_post_eval_control_classifier(
            self.llm,
            case_id=case.case_id,
            review_case_fields={
                "source_text": case.source_text,
                "translation_text": case.translation,
                "content_type": case.content_type.value,
                "brand_or_domain": case.brand_or_domain,
                "context_notes": case.context_notes,
                "source_language": case.source_language,
                "target_locale": case.target_locale,
            },
            evaluations=baseline_results,
        )
        self.repository.save_dimension_evaluations(results)
        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-02-POST-EVAL-CONTROL",
            input_state={
                "review_case": {
                    "source_text": case.source_text,
                    "translation_text": case.translation,
                    "content_type": case.content_type.value,
                    "brand_or_domain": case.brand_or_domain,
                    "context_notes": case.context_notes,
                    "source_language": case.source_language,
                    "target_locale": case.target_locale,
                },
                "dimension_evaluations": baseline_results,
            },
            output_state={
                "result": control,
                "provider": self._provider_metadata(),
            },
            decision_reason="Single structured control judgment completed after all four baseline evaluations; baseline severity/q1/q2/notes remain unchanged.",
            reason_code="POST_EVAL_CONTROL_CLASSIFIED",
            policy_version="node02_post_eval_control_v1",
            model_version=control.model_version,
            prompt_version=control.prompt_version,
            prompt_path=control.prompt_path,
            prompt_hash=control.prompt_hash,
        )
        return {
            "dimension_evaluations": results,
            "post_eval_control": control,
        }

    @staticmethod
    def _after_node_02(state: GraphState) -> str:
        terminology = next(
            item
            for item in state["dimension_evaluations"]
            if item.dimension == Dimension.TERMINOLOGY
        )
        return "evidence" if terminology.requires_external_evidence else "continue"

    def _node_03(self, state: GraphState) -> GraphState:
        case = state["review_case"]
        evidence_mode = getattr(self.evidence_selector, "workflow_mode", "ADAPTIVE")
        terminology = next(
            item
            for item in state["dimension_evaluations"]
            if item.dimension == Dimension.TERMINOLOGY
        )
        details = terminology.dimension_specific
        if not isinstance(details, TerminologyDetails):
            raise PolicyConfigurationError(
                "NODE-03 requires structured TerminologyDetails"
            )
        evidence_state = TerminologyEvidenceState(
            case_id=case.case_id,
            term_candidate=details.term_candidate or "",
            evidence_need=details.evidence_need or "",
            normative_claim=details.normative_claim,
            brand_or_domain=case.brand_or_domain,
            target_locale=case.target_locale,
            context_notes=case.context_notes,
            source_text=case.source_text,
            translation_text=case.translation,
            max_tool_calls=self.max_tool_calls,
            available_actions=list(self.available_evidence_actions),
        )
        strict_admission_enabled = self.normative_admission_policy is not None
        exact_span_valid = (
            not strict_admission_enabled
            or is_exact_source_span_v1(
                source_text=case.source_text,
                term_candidate=evidence_state.term_candidate,
            )
        )
        if exact_span_valid:
            result = TerminologyEvidenceLoop(
                selector=self.evidence_selector,
                assessor=self.evidence_assessor,
                tools=self.evidence_tools,
                normative_admission_policy=self.normative_admission_policy,
            ).run(evidence_state)
        else:
            result = evidence_state.model_copy(
                update={
                    "evidence_status": EvidenceStatus.INSUFFICIENT,
                    "stop_action": EvidenceAction.ABSTAIN,
                    "stop_reason": (
                        POST_EVAL_TERM_CANDIDATE_NOT_EXACT_SOURCE_SPAN
                    ),
                }
            )
        self.repository.save_terminology_evidence(result)

        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-03",
            input_state=evidence_state,
            output_state=result,
            decision_reason=(
                "Post-Eval term_candidate failed the literal exact-source-span "
                "contract; evidence acquisition stopped before retrieval, assessment, "
                "or admission."
                if not exact_span_valid
                else (
                    "Fixed precomputed evidence plan completed under provenance, "
                    "conflict, normative-claim, and tool-budget guardrails"
                    if evidence_mode == "FIXED"
                    else "Dynamic action selection completed under provenance, "
                    "conflict, normative-claim, and tool-budget guardrails"
                )
            ),
            reason_code=result.stop_reason,
            policy_version="terminology_evidence_loop_v1",
            model_version=self.evidence_selector.model_version,
            prompt_version=self.evidence_selector.prompt_version,
            prompt_path=(
                result.action_history[-1].prompt_path
                if result.action_history
                else None
            ),
            prompt_hash=(
                result.action_history[-1].prompt_hash
                if result.action_history
                else None
            ),
            tool_call_count=result.tool_call_count,
            evidence_status=result.evidence_status.value,
            stop_reason=result.stop_reason,
        )

        evaluations = list(state["dimension_evaluations"])
        if result.evidence_status == EvidenceStatus.SUFFICIENT:
            payload = QualityEvaluationInput(
                source_text=case.source_text,
                translation_text=case.translation,
                content_type=case.content_type,
            )
            final_terminology = invoke_final_terminology_evaluator(
                self.llm,
                case_id=case.case_id,
                payload=payload,
                verified_evidence=result.verified_evidence,
                prompt_registry=self.prompt_registry,
            )
            self.repository.save_dimension_evaluations([final_terminology])
            evaluations = [
                final_terminology if item.dimension == Dimension.TERMINOLOGY else item
                for item in evaluations
            ]
            self.repository.log_node(
                eval_run_id=state["eval_run_id"],
                case_id=case.case_id,
                node_name="NODE-02-TERMINOLOGY-FINAL",
                input_state={
                    "base_contract": payload,
                    "verified_evidence": result.verified_evidence,
                },
                output_state=final_terminology,
                decision_reason=final_terminology.notes,
                reason_code=f"TERMINOLOGY_{final_terminology.severity.value.upper()}",
                policy_version=case.reliability_policy_id,
                model_version=final_terminology.model_version,
                prompt_version=final_terminology.prompt_version,
                prompt_path=final_terminology.prompt_path,
                prompt_hash=final_terminology.prompt_hash,
                evidence_status=result.evidence_status.value,
                tool_call_count=result.tool_call_count,
                stop_reason=result.stop_reason,
            )

        return {
            "dimension_evaluations": evaluations,
            "terminology_evidence": result,
        }

    def _node_04(self, state: GraphState) -> GraphState:
        case = state["review_case"]
        risk = state["risk_result"]
        decisions = node_04_reliability(
            case_id=case.case_id,
            case_risk=risk.risk_level,
            evaluations=state["dimension_evaluations"],
            reliability_policy_id=case.reliability_policy_id,
            terminology_evidence=state.get("terminology_evidence"),
        )
        self.repository.save_reliability_decisions(decisions)
        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-04",
            input_state={
                "case_risk": risk.risk_level,
                "evaluations": [
                    {
                        "dimension": item.dimension,
                        "unresolved_external_support": item.unresolved_external_support,
                    }
                    for item in state["dimension_evaluations"]
                ],
                "terminology_evidence_status": (
                    state["terminology_evidence"].evidence_status
                    if state.get("terminology_evidence")
                    else None
                ),
            },
            output_state=decisions,
            decision_reason="12-cell pilot-calibrated lookup plus frozen safety overrides",
            reason_code=[
                f"{item.dimension.value}_{item.verification_route.value}"
                for item in decisions
            ],
            policy_version=case.reliability_policy_id,
        )
        return {"reliability_decisions": decisions}

    def _node_05(self, state: GraphState) -> GraphState:
        case = state["review_case"]
        decision = node_05_aggregate(
            case_id=case.case_id,
            evaluations=state["dimension_evaluations"],
            reliability_decisions=state["reliability_decisions"],
        )
        case.processing_status = ProcessingStatus.ROUTED
        self.repository.save_route_decision(decision)
        self.repository.update_case_status(case.case_id, case.processing_status.value)
        self.repository.log_node(
            eval_run_id=state["eval_run_id"],
            case_id=case.case_id,
            node_name="NODE-05",
            input_state={
                "evaluations": state["dimension_evaluations"],
                "reliability_decisions": state["reliability_decisions"],
            },
            output_state=decision,
            decision_reason="Maximum Intervention Wins: HUMAN_REQUIRED > SAMPLE_POOL > AUTO_PASS",
            reason_code=decision.route_reason_codes,
            policy_version=decision.aggregation_rule_version,
        )
        return {
            "review_case": case,
            "route_decision": decision,
            "terminal_status": "ROUTED",
        }

    def prepare_shared_pre_evidence(
        self, *, eval_run_id: str, raw_input: ReviewCaseInput | dict[str, Any], run_mode: str
    ) -> SharedPreEvidenceState:
        """Run NODE00--NODE02 exactly once before the comparative fork."""

        self.repository.start_eval_run(eval_run_id, run_mode)
        state: GraphState = {"eval_run_id": eval_run_id, "raw_input": raw_input}
        state.update(self._node_00(state))
        state.update(self._node_01(state))
        if state.get("terminal_status") != "CONTINUE":
            raise PolicyConfigurationError("shared pre-evidence state requires a valid in-scope case")
        state.update(self._node_02(state))
        payload = {
            "case_id": state["review_case"].case_id,
            "risk_result": state["risk_result"].model_dump(mode="json"),
            "dimension_evaluations": [item.model_dump(mode="json") for item in state["dimension_evaluations"]],
            "post_eval_control": state["post_eval_control"].model_dump(mode="json"),
            "provider": self._provider_metadata(),
        }
        state_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self.repository.log_node(
            eval_run_id=eval_run_id, case_id=state["review_case"].case_id,
            node_name="SHARED-PRE-EVIDENCE", input_state={"raw_input": raw_input},
            output_state={"state_hash": state_hash, **payload},
            decision_reason="Frozen shared pre-evidence state prepared once for B/C comparison.",
            reason_code="SHARED_PRE_EVIDENCE_READY", policy_version="day2_v2_shared_pre_evidence_v1",
        )
        self.repository.finish_eval_run(eval_run_id, status="SHARED_PRE_EVIDENCE_READY")
        return SharedPreEvidenceState(
            review_case=state["review_case"].model_copy(deep=True),
            risk_result=state["risk_result"].model_copy(deep=True),
            dimension_evaluations=[item.model_copy(deep=True) for item in state["dimension_evaluations"]],
            post_eval_control=state["post_eval_control"].model_copy(deep=True),
            state_hash=state_hash,
        )

    def run_from_shared_pre_evidence(
        self, *, eval_run_id: str, shared: SharedPreEvidenceState, run_mode: str
    ) -> WorkflowState:
        """Run only NODE03--NODE05 from an identical, hash-bound B/C input."""

        self.repository.start_eval_run(eval_run_id, run_mode)
        runtime_case_id = str(uuid4())
        state: GraphState = {
            "eval_run_id": eval_run_id,
            "review_case": shared.review_case.model_copy(update={"case_id": runtime_case_id}, deep=True),
            "risk_result": shared.risk_result.model_copy(update={"case_id": runtime_case_id}, deep=True),
            "dimension_evaluations": [item.model_copy(update={"case_id": runtime_case_id}, deep=True) for item in shared.dimension_evaluations],
            "post_eval_control": shared.post_eval_control.model_copy(update={"case_id": runtime_case_id}, deep=True),
        }
        self.repository.save_review_case(eval_run_id, state["review_case"])
        self.repository.log_node(
            eval_run_id=eval_run_id, case_id=state["review_case"].case_id,
            node_name="SHARED-PRE-EVIDENCE-IMPORT", input_state={"state_hash": shared.state_hash},
            output_state={"state_hash": shared.state_hash},
            decision_reason="B/C branch imported the identical frozen pre-evidence state.",
            reason_code="SHARED_PRE_EVIDENCE_IMPORTED", policy_version="day2_v2_shared_pre_evidence_v1",
        )
        try:
            if self._after_node_02(state) == "evidence":
                state.update(self._node_03(state))
            state.update(self._node_04(state))
            state.update(self._node_05(state))
        except Exception as error:
            processing_error = ProcessingErrorResult(
                case_id=state["review_case"].case_id, node_name="SHARED_BRANCH",
                error_code=_provider_failure_code(error), error_message=str(error),
            )
            route = RouteDecision(
                case_id=state["review_case"].case_id, final_policy_route="HUMAN_REQUIRED",
                triggering_dimensions=[], blocking_dimensions=[], sample_audit_dimensions=[],
                route_reason_codes=["SHARED_BRANCH_FAILURE_FAIL_CLOSED"],
            )
            state["review_case"].processing_status = ProcessingStatus.ROUTED
            self.repository.update_case_status(state["review_case"].case_id, ProcessingStatus.ROUTED.value)
            self.repository.save_route_decision(route)
            self.repository.log_node(
                eval_run_id=eval_run_id, case_id=state["review_case"].case_id,
                node_name="SHARED_BRANCH", input_state={"state_hash": shared.state_hash},
                output_state=processing_error, decision_reason="Case-level branch failure failed closed; batch may continue.",
                reason_code=processing_error.error_code,
            )
            self.repository.finish_eval_run(eval_run_id, status="FAILED", error=processing_error)
            return WorkflowState(eval_run_id=eval_run_id, review_case=state["review_case"],
                risk_result=state["risk_result"], dimension_evaluations=state["dimension_evaluations"],
                post_eval_control=state["post_eval_control"], route_decision=route,
                processing_error=processing_error)
        self.repository.finish_eval_run(eval_run_id, status="ROUTED")
        result = WorkflowState(
            eval_run_id=eval_run_id, review_case=state["review_case"], risk_result=state["risk_result"],
            dimension_evaluations=state["dimension_evaluations"], post_eval_control=state["post_eval_control"],
            terminology_evidence=state.get("terminology_evidence"), reliability_decisions=state["reliability_decisions"],
            route_decision=state["route_decision"],
        )
        return result

    def run(
        self,
        *,
        eval_run_id: str,
        raw_input: ReviewCaseInput | dict[str, Any],
        run_mode: str = "DEVELOPMENT",
    ) -> WorkflowState:
        self.repository.start_eval_run(eval_run_id, run_mode)
        try:
            final = self.graph.invoke(
                {"eval_run_id": eval_run_id, "raw_input": raw_input}
            )
        except Exception as error:
            if isinstance(error, LLMProcessingError):
                code = error.code
                node_name = error.node_name
            elif isinstance(error, InvalidInputError):
                code = "INVALID_INPUT"
                node_name = "NODE-00"
            elif isinstance(error, PolicyConfigurationError):
                code = "POLICY_CONFIGURATION_ERROR"
                node_name = "NODE-04"
            elif isinstance(error, ReviewTriageError):
                code = type(error).__name__.upper()
                node_name = "NODE-00"
            else:
                code = "PROCESSING_FAILURE"
                node_name = "WORKFLOW"
            case_rows = self.repository.fetch_all(
                "SELECT case_id FROM review_cases WHERE eval_run_id=?",
                (eval_run_id,),
            )
            case_id = case_rows[0]["case_id"] if case_rows else None
            processing_error = ProcessingErrorResult(
                case_id=case_id,
                node_name=node_name,
                error_code=code,
                error_message=str(error),
            )
            if case_id:
                self.repository.update_case_status(
                    case_id, ProcessingStatus.PROCESSING_ERROR.value
                )
            self.repository.log_node(
                eval_run_id=eval_run_id,
                case_id=case_id,
                node_name=node_name,
                input_state={"run_mode": run_mode},
                output_state=processing_error,
                decision_reason="Explicit safe processing stop; no routing fallback applied",
                reason_code=code,
            )
            self.repository.finish_eval_run(
                eval_run_id, status="FAILED", error=processing_error
            )
            return WorkflowState(
                eval_run_id=eval_run_id,
                input_payload=(
                    raw_input if isinstance(raw_input, ReviewCaseInput) else None
                ),
                processing_error=processing_error,
            )

        terminal_status = final.get("terminal_status", "COMPLETED")
        self.repository.finish_eval_run(eval_run_id, status=terminal_status)
        result = WorkflowState(
            eval_run_id=eval_run_id,
            input_payload=(
                raw_input
                if isinstance(raw_input, ReviewCaseInput)
                else ReviewCaseInput.model_validate(raw_input)
            ),
            review_case=final.get("review_case"),
            risk_result=final.get("risk_result"),
            dimension_evaluations=final.get("dimension_evaluations", []),
            post_eval_control=final.get("post_eval_control"),
            terminology_evidence=final.get("terminology_evidence"),
            reliability_decisions=final.get("reliability_decisions", []),
            route_decision=final.get("route_decision"),
        )
        return result


# Backward-compatible engineering alias; the workflow now includes GATE 3.
Gate2Workflow = ReviewTriageWorkflow
