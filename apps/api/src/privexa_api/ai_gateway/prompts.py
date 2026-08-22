from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class AIPromptTemplate:
    """Immutable identity and content for one governed system prompt version."""

    template_id: str
    version: str
    system_instruction: str = field(repr=False)
    content_hash: str

    def __post_init__(self) -> None:
        if not self.template_id or not self.version or not self.system_instruction:
            raise ValueError("AI prompt template identity and content are required")
        expected_hash = hashlib.sha256(self.system_instruction.encode("utf-8")).hexdigest()
        if self.content_hash != expected_hash:
            raise ValueError("AI prompt template content hash does not match its instruction")


SYNTHETIC_TEXT_SUMMARY_PROMPT = AIPromptTemplate(
    template_id="synthetic_text_summary",
    version="1",
    system_instruction=(
        "You are validating Privexa's internal AI execution infrastructure. "
        "Summarize the supplied synthetic text concisely. "
        "Return only the structured response required by the schema."
    ),
    content_hash="f79f28ff0c8f9e52f8ba8149b3c438bbcd3c433c50a0b001eb06b753d6f46ac1",
)

PREPARE_WORK_NOTE_PROMPT = AIPromptTemplate(
    template_id="ai.prepare_work_note",
    version="1",
    system_instruction=(
        "You prepare a concise, provisional client work-note draft from the supplied note. "
        "Return only the structured response required by the schema. Do not declare legal "
        "compliance or non-compliance, make authoritative legal conclusions, update records, "
        "advance workflows, or send communications. Use cautious professional language. "
        "Include a practical follow-up and a caveat when facts are incomplete or professional "
        "judgement is required."
    ),
    content_hash="b243f9258dd29a898d7dce6e6bff8268f795b5f08074b590bc348486064e3624",
)


class AIPromptRegistry:
    def __init__(
        self,
        definitions: Mapping[tuple[str, str], AIPromptTemplate],
    ) -> None:
        if not definitions:
            raise ValueError("at least one AI prompt template is required")
        if any(key != (value.template_id, value.version) for key, value in definitions.items()):
            raise ValueError("AI prompt registry keys must match their definitions")
        self._definitions = MappingProxyType(dict(definitions))

    def resolve(self, template_id: str, version: str) -> AIPromptTemplate:
        try:
            return self._definitions[(template_id, version)]
        except KeyError as error:
            raise ValueError("unknown AI prompt template version") from error


def build_prompt_registry() -> AIPromptRegistry:
    prompts = (SYNTHETIC_TEXT_SUMMARY_PROMPT, PREPARE_WORK_NOTE_PROMPT)
    return AIPromptRegistry({(prompt.template_id, prompt.version): prompt for prompt in prompts})
