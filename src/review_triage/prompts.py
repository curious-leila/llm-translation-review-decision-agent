"""Read-only evaluator prompt loading and rendering.

The Markdown files are empirical baseline artifacts.  This module validates
their declared input/output contracts and renders only the existing USER
PROMPT placeholders; it never rewrites prompt content.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from string import Formatter
from typing import Any

from review_triage.schemas import ContentType, Dimension, QualityEvaluationInput


PROMPT_VERSION_BY_DIMENSION: dict[Dimension, str] = {
    Dimension.TERMINOLOGY: "evaluator_terminology_v0",
    Dimension.ACCURACY: "evaluator_accuracy_v0",
    Dimension.LOCALE: "evaluator_locale_v0",
    Dimension.AUDIENCE: "evaluator_audience_v0",
}

PROMPT_FILENAME_BY_DIMENSION: dict[Dimension, str] = {
    Dimension.TERMINOLOGY: "prompt_terminology_v0.md",
    Dimension.ACCURACY: "prompt_accuracy_v0.md",
    Dimension.LOCALE: "prompt_locale_v0.md",
    Dimension.AUDIENCE: "prompt_audience_v0.md",
}

FROZEN_PROMPT_HASH_BY_DIMENSION: dict[Dimension, str] = {
    Dimension.TERMINOLOGY: (
        "3d32b548cbce5d95ef12c3ac3cf50e07079126f491a0ea9075ce03e154af2626"
    ),
    Dimension.ACCURACY: (
        "cb6302d09a8a77f0dc04cc30a3dd21e9dd3012e4cccec965004d7ddbb706508a"
    ),
    Dimension.LOCALE: (
        "17216c9d62c3b690916f75c657b881f0c823195a5f0c27d83c32b7a16f1a58bd"
    ),
    Dimension.AUDIENCE: (
        "18b61fc288b1bca55da5e78a28c71e3b740846f8a894ba7ffacbb799e2413bcc"
    ),
}

LEGACY_POST_EVAL_CONTROL_PROMPT_VERSION = "node02_post_eval_control_v1"
LEGACY_POST_EVAL_CONTROL_PROMPT_PATH = (
    "prompts/review_agent_v1/prompt_post_eval_control_v1.md"
)
LEGACY_POST_EVAL_CONTROL_PROMPT_HASH = (
    "56f53ef43a615faa485193bd57def41a273f97f1e6e14319ab40037007cc448e"
)

POST_EVAL_CONTROL_V2_PROMPT_VERSION = "node02_post_eval_control_v2"
POST_EVAL_CONTROL_V2_PROMPT_PATH = (
    "prompts/review_agent_v1/prompt_post_eval_control_v2.md"
)
POST_EVAL_CONTROL_V2_PROMPT_HASH = (
    "886d3358a55a1fd1a0ffc66800e3a79d93c38ee6f0be33073f310cde31417f81"
)

POST_EVAL_CONTROL_V3_PROMPT_VERSION = "node02_post_eval_control_v3"
POST_EVAL_CONTROL_V3_PROMPT_PATH = (
    "prompts/review_agent_v1/prompt_post_eval_control_v3.md"
)
POST_EVAL_CONTROL_V3_PROMPT_HASH = (
    "70211363f9b65eadb6994ef172744da56af03c6de7f40c432790f9a0c0caee38"
)

POST_EVAL_CONTROL_PROMPT_VERSION = "node02_post_eval_control_v4"
POST_EVAL_CONTROL_PROMPT_PATH = (
    "prompts/review_agent_v1/prompt_post_eval_control_v4.md"
)
POST_EVAL_CONTROL_PROMPT_HASH = (
    "171123922084549295bbcd1fc2080203fcb7ea1bc61f028ec28cb1c71efc1846"
)

REVIEW_PROMPT_PATH_BY_VERSION: dict[str, str] = {
    "node01_risk_classifier_v1": (
        "prompts/review_agent_v1/prompt_node01_risk_classifier_v1.md"
    ),
    "node01_risk_classifier_v2": (
        "prompts/review_agent_v1/prompt_node01_risk_classifier_v2.md"
    ),
    "node01_risk_classifier_v3": (
        "prompts/review_agent_v1/prompt_node01_risk_classifier_v3.md"
    ),
    "node03_evidence_action_selector_v1": (
        "prompts/review_agent_v1/prompt_node03_evidence_action_selector_v1.md"
    ),
    "node03_evidence_assessor_v1": (
        "prompts/review_agent_v1/prompt_node03_evidence_assessor_v1.md"
    ),
    "node02a_terminology_final_v1": (
        "prompts/review_agent_v1/prompt_node02a_terminology_final_v1.md"
    ),
    LEGACY_POST_EVAL_CONTROL_PROMPT_VERSION: LEGACY_POST_EVAL_CONTROL_PROMPT_PATH,
    POST_EVAL_CONTROL_V2_PROMPT_VERSION: POST_EVAL_CONTROL_V2_PROMPT_PATH,
    POST_EVAL_CONTROL_V3_PROMPT_VERSION: POST_EVAL_CONTROL_V3_PROMPT_PATH,
    POST_EVAL_CONTROL_PROMPT_VERSION: POST_EVAL_CONTROL_PROMPT_PATH,
}

REVIEW_PROMPT_HASH_BY_VERSION: dict[str, str] = {
    "node01_risk_classifier_v1": (
        "6ddc30b3d9451632b0d03fe6c046dfae727e8d0cf298488b4e1b5b30f36a5e79"
    ),
    "node01_risk_classifier_v2": (
        "9d21864d0e27c3164c5df320ad5307e0eb9063996d43901837f9b8b7d23a7f92"
    ),
    "node01_risk_classifier_v3": (
        "1acb0d50ba8d0491893c9ad801eee676aee09bdde0ddcda8758589469faf3f83"
    ),
    "node03_evidence_action_selector_v1": (
        "6f9b33ee152e3adede95e8d367b2cb0f7e012d8b97a9e7faa18b9610f221517c"
    ),
    "node03_evidence_assessor_v1": (
        "e705b043bdebbe7312a39ce8188fbac4f117a06156dfe55485ff4bf5ae43b38f"
    ),
    "node02a_terminology_final_v1": (
        "0b9ccbe8c4bee2722f65015de3df86a2021c368655811e43a1506b27b8c6ee40"
    ),
    LEGACY_POST_EVAL_CONTROL_PROMPT_VERSION: LEGACY_POST_EVAL_CONTROL_PROMPT_HASH,
    POST_EVAL_CONTROL_V2_PROMPT_VERSION: POST_EVAL_CONTROL_V2_PROMPT_HASH,
    POST_EVAL_CONTROL_V3_PROMPT_VERSION: POST_EVAL_CONTROL_V3_PROMPT_HASH,
    POST_EVAL_CONTROL_PROMPT_VERSION: POST_EVAL_CONTROL_PROMPT_HASH,
}

REVIEW_PROMPT_PLACEHOLDER_BY_VERSION: dict[str, str] = {
    "node01_risk_classifier_v1": "risk_input_json",
    "node01_risk_classifier_v2": "risk_input_json",
    "node01_risk_classifier_v3": "risk_input_json",
    "node03_evidence_action_selector_v1": "evidence_state_json",
    "node03_evidence_assessor_v1": "evidence_assessment_input_json",
    "node02a_terminology_final_v1": "terminology_final_input_json",
    LEGACY_POST_EVAL_CONTROL_PROMPT_VERSION: "control_input_json",
    POST_EVAL_CONTROL_V2_PROMPT_VERSION: "control_input_json",
    POST_EVAL_CONTROL_V3_PROMPT_VERSION: "control_input_json",
    POST_EVAL_CONTROL_PROMPT_VERSION: "control_input_json",
}

BASE_INPUT_FIELDS = ("source_text", "translation_text", "content_type")
BASE_OUTPUT_FIELDS = ("severity", "q1", "q2", "notes", "sources")
DIMENSION_OUTPUT_FIELDS: dict[Dimension, tuple[str, ...]] = {
    Dimension.TERMINOLOGY: ("term_type",),
    Dimension.ACCURACY: ("adjacent_correction", "boundary_risk"),
    Dimension.LOCALE: ("locale_element", "boundary_risk"),
    Dimension.AUDIENCE: ("audience_element",),
}
SEVERITY_TAXONOMY = ("Neutral", "Minor", "Major", "Critical")

EVALUATOR_CONTENT_TYPE_LABELS: dict[ContentType, str] = {
    ContentType.MARKETING: "营销文案",
    ContentType.CUSTOMER_SUPPORT: "客服话术",
    ContentType.UI: "UI文本",
}


class PromptContractError(ValueError):
    """A baseline prompt is missing or no longer matches its frozen contract."""


@dataclass(frozen=True)
class RenderedEvaluatorPrompt:
    """Provider-ready role content plus immutable audit metadata."""

    dimension: Dimension
    prompt_version: str
    prompt_path: str
    prompt_hash: str
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class RenderedStructuredPrompt:
    """Provider-ready non-baseline prompt plus immutable audit metadata."""

    prompt_version: str
    prompt_path: str
    prompt_hash: str
    system_prompt: str
    user_prompt: str


@dataclass(frozen=True)
class EvaluatorPrompt:
    """Validated evaluator prompt artifact."""

    dimension: Dimension
    prompt_version: str
    prompt_path: str
    prompt_hash: str
    system_prompt: str
    user_prompt_template: str
    input_fields: tuple[str, ...]
    output_fields: tuple[str, ...]
    severity_taxonomy: tuple[str, ...]

    def render(self, payload: QualityEvaluationInput) -> RenderedEvaluatorPrompt:
        try:
            content_type = EVALUATOR_CONTENT_TYPE_LABELS[payload.content_type]
        except KeyError as error:
            raise PromptContractError(
                f"{payload.content_type.value} has no evaluator prompt label"
            ) from error
        user_prompt = self.user_prompt_template.format(
            source_text=payload.source_text,
            translation_text=payload.translation_text,
            content_type=content_type,
        )
        return RenderedEvaluatorPrompt(
            dimension=self.dimension,
            prompt_version=self.prompt_version,
            prompt_path=self.prompt_path,
            prompt_hash=self.prompt_hash,
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
        )


class EvaluatorPromptLoader:
    """Load the four baseline files without changing their bytes or wording."""

    def __init__(self, prompt_directory: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[2]
        self.prompt_directory = (
            Path(prompt_directory)
            if prompt_directory is not None
            else project_root / "prompts" / "evaluator_baselines"
        )
        self.project_root = project_root

    def load(self, dimension: Dimension) -> EvaluatorPrompt:
        path = self.prompt_directory / PROMPT_FILENAME_BY_DIMENSION[dimension]
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise PromptContractError(
                f"Unable to read baseline prompt for {dimension.value}: {path}"
            ) from error
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PromptContractError(f"Baseline prompt is not UTF-8: {path}") from error

        prompt_hash = hashlib.sha256(raw).hexdigest()
        expected_hash = FROZEN_PROMPT_HASH_BY_DIMENSION[dimension]
        if prompt_hash != expected_hash:
            raise PromptContractError(
                f"Frozen evaluator prompt hash mismatch for {path.name}: "
                f"expected {expected_hash}, got {prompt_hash}"
            )

        system_prompt, user_template = self._extract_role_prompts(text, path)
        input_fields = self._extract_input_fields(user_template)
        output_fields, severity_taxonomy = self._extract_output_contract(
            system_prompt, path
        )
        expected_output = set(BASE_OUTPUT_FIELDS).union(
            DIMENSION_OUTPUT_FIELDS[dimension]
        )
        if set(output_fields) != expected_output:
            raise PromptContractError(
                f"{path.name} output fields {sorted(output_fields)} do not match "
                f"the frozen {dimension.value} contract {sorted(expected_output)}"
            )
        if input_fields != BASE_INPUT_FIELDS:
            raise PromptContractError(
                f"{path.name} input fields {input_fields} do not match "
                f"{BASE_INPUT_FIELDS}"
            )
        if set(severity_taxonomy) != set(SEVERITY_TAXONOMY):
            raise PromptContractError(
                f"{path.name} severity taxonomy {severity_taxonomy} does not match "
                f"{SEVERITY_TAXONOMY}"
            )

        try:
            prompt_path = path.resolve().relative_to(self.project_root).as_posix()
        except ValueError:
            prompt_path = path.resolve().as_posix()
        return EvaluatorPrompt(
            dimension=dimension,
            prompt_version=PROMPT_VERSION_BY_DIMENSION[dimension],
            prompt_path=prompt_path,
            prompt_hash=prompt_hash,
            system_prompt=system_prompt,
            user_prompt_template=user_template,
            input_fields=input_fields,
            output_fields=output_fields,
            severity_taxonomy=severity_taxonomy,
        )

    def load_all(self) -> dict[Dimension, EvaluatorPrompt]:
        return {dimension: self.load(dimension) for dimension in Dimension}

    @staticmethod
    def _extract_role_prompts(text: str, path: Path) -> tuple[str, str]:
        match = re.search(
            r"## SYSTEM PROMPT\s+(?P<system>.*?)\s+---\s+"
            r"## USER PROMPT[^\n]*\s+```(?:text)?\s*"
            r"(?P<user>.*?)\s*```\s+---\s+## 调用参数",
            text,
            flags=re.DOTALL,
        )
        if match is None:
            raise PromptContractError(
                f"Unable to locate SYSTEM/USER prompt sections in {path.name}"
            )
        return match.group("system").strip(), match.group("user").strip()

    @staticmethod
    def _extract_input_fields(template: str) -> tuple[str, ...]:
        fields = [
            field_name
            for _, field_name, _, _ in Formatter().parse(template)
            if field_name is not None
        ]
        return tuple(fields)

    @staticmethod
    def _extract_output_contract(
        system_prompt: str, path: Path
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        match = re.search(
            r"### 输出格式.*?```json\s*(?P<schema>\{.*?\})\s*```",
            system_prompt,
            flags=re.DOTALL,
        )
        if match is None:
            raise PromptContractError(
                f"Unable to locate JSON output contract in {path.name}"
            )
        try:
            output_example = json.loads(match.group("schema"))
        except json.JSONDecodeError as error:
            raise PromptContractError(
                f"Output contract in {path.name} is not valid JSON"
            ) from error
        severity_example = output_example.get("severity")
        if not isinstance(severity_example, str):
            raise PromptContractError(
                f"Output contract in {path.name} has no severity string"
            )
        severities = tuple(item.strip() for item in severity_example.split("|"))
        return tuple(output_example), severities


class PostEvalControlPromptLoader:
    """Load and render the frozen Review Agent control classifier prompt."""

    def __init__(
        self,
        prompt_path: str | Path | None = None,
        *,
        prompt_version: str = POST_EVAL_CONTROL_PROMPT_VERSION,
    ) -> None:
        self.project_root = Path(__file__).resolve().parents[2]
        if prompt_version not in REVIEW_PROMPT_PATH_BY_VERSION:
            raise PromptContractError(
                f"Unknown Post-Eval Control prompt version: {prompt_version}"
            )
        if not prompt_version.startswith("node02_post_eval_control_"):
            raise PromptContractError(
                f"Prompt version is not a Post-Eval Control artifact: {prompt_version}"
            )
        self.prompt_version = prompt_version
        self.expected_prompt_path = REVIEW_PROMPT_PATH_BY_VERSION[prompt_version]
        self.expected_prompt_hash = REVIEW_PROMPT_HASH_BY_VERSION[prompt_version]
        self.prompt_path = (
            Path(prompt_path)
            if prompt_path is not None
            else self.project_root / self.expected_prompt_path
        )

    def render(self, control_input: Mapping[str, Any]) -> RenderedStructuredPrompt:
        try:
            raw = self.prompt_path.read_bytes()
        except OSError as error:
            raise PromptContractError(
                f"Unable to read Post-Eval Control prompt: {self.prompt_path}"
            ) from error
        prompt_hash = hashlib.sha256(raw).hexdigest()
        if prompt_hash != self.expected_prompt_hash:
            raise PromptContractError(
                "Frozen Post-Eval Control prompt hash mismatch: "
                f"expected {self.expected_prompt_hash}, got {prompt_hash}"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PromptContractError(
                f"Post-Eval Control prompt is not UTF-8: {self.prompt_path}"
            ) from error
        system_prompt, user_template = self._extract_role_prompts(text)
        input_fields = EvaluatorPromptLoader._extract_input_fields(user_template)
        if input_fields != ("control_input_json",):
            raise PromptContractError(
                "Post-Eval Control Prompt must contain exactly the "
                "control_input_json placeholder"
            )
        user_prompt = user_template.format(
            control_input_json=json.dumps(
                dict(control_input), ensure_ascii=False, sort_keys=True, indent=2
            )
        )
        return RenderedStructuredPrompt(
            prompt_version=self.prompt_version,
            prompt_path=self.expected_prompt_path,
            prompt_hash=prompt_hash,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )

    @staticmethod
    def _extract_role_prompts(text: str) -> tuple[str, str]:
        match = re.search(
            r"## SYSTEM PROMPT\s+(?P<system>.*?)\s+---\s+"
            r"## USER PROMPT\s+(?P<user>.*)\Z",
            text,
            flags=re.DOTALL,
        )
        if match is None:
            raise PromptContractError(
                "Unable to locate SYSTEM/USER sections in Post-Eval Control Prompt"
            )
        return match.group("system").strip(), match.group("user").strip()


class ReviewPromptRegistry:
    """Hash-guard and render every frozen Review Agent Prompt artifact."""

    def __init__(self, project_root: str | Path | None = None) -> None:
        self.project_root = (
            Path(project_root)
            if project_root is not None
            else Path(__file__).resolve().parents[2]
        )

    def render(
        self,
        prompt_version: str,
        structured_input: Mapping[str, Any],
    ) -> RenderedStructuredPrompt:
        try:
            prompt_path = REVIEW_PROMPT_PATH_BY_VERSION[prompt_version]
            expected_hash = REVIEW_PROMPT_HASH_BY_VERSION[prompt_version]
            placeholder = REVIEW_PROMPT_PLACEHOLDER_BY_VERSION[prompt_version]
        except KeyError as error:
            raise PromptContractError(
                f"Unknown frozen Review Agent prompt version: {prompt_version}"
            ) from error
        path = self.project_root / prompt_path
        try:
            raw = path.read_bytes()
        except OSError as error:
            raise PromptContractError(
                f"Unable to read frozen Review Agent Prompt: {path}"
            ) from error
        prompt_hash = hashlib.sha256(raw).hexdigest()
        if prompt_hash != expected_hash:
            raise PromptContractError(
                f"Frozen Review Agent Prompt hash mismatch for {path.name}: "
                f"expected {expected_hash}, got {prompt_hash}"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PromptContractError(
                f"Frozen Review Agent Prompt is not UTF-8: {path}"
            ) from error
        system_prompt, user_template = PostEvalControlPromptLoader._extract_role_prompts(
            text
        )
        input_fields = EvaluatorPromptLoader._extract_input_fields(user_template)
        if input_fields != (placeholder,):
            raise PromptContractError(
                f"{path.name} must contain exactly the {placeholder} placeholder"
            )
        user_prompt = user_template.format(
            **{
                placeholder: json.dumps(
                    dict(structured_input),
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                )
            }
        )
        return RenderedStructuredPrompt(
            prompt_version=prompt_version,
            prompt_path=prompt_path,
            prompt_hash=prompt_hash,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
