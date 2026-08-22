"""Stable provider-neutral identifiers shared by AI policy and execution."""

from enum import StrEnum


class AITaskType(StrEnum):
    SYNTHETIC_TEXT_SUMMARY = "synthetic_text_summary"
    PREPARE_WORK_NOTE = "ai.prepare_work_note"
