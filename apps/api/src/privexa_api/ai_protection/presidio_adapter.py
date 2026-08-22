from __future__ import annotations

from collections.abc import Mapping
from importlib.util import find_spec

from presidio_analyzer import AnalyzerEngine, RecognizerRegistry, RecognizerResult
from presidio_analyzer.nlp_engine import NlpEngineProvider

from privexa_api.ai_protection.contracts import DetectedEntity
from privexa_api.ai_protection.errors import PIIDetectionError
from privexa_api.ai_protection.recognizers import IndiaAadhaarRecognizer, IndiaPanRecognizer


class PresidioPIIDetector:
    """Privexa adapter around one reusable, immutable-after-startup analyzer."""

    def __init__(self, analyzer: AnalyzerEngine) -> None:
        self._analyzer = analyzer

    def detect(
        self,
        content: str,
        *,
        entities: tuple[str, ...],
        language: str,
        score_threshold: float,
    ) -> tuple[DetectedEntity, ...]:
        try:
            results = self._analyzer.analyze(
                text=content,
                language=language,
                entities=list(entities),
                score_threshold=score_threshold,
                return_decision_process=False,
            )
        except Exception:
            raise PIIDetectionError from None
        return tuple(_to_entity(result) for result in results)


def build_presidio_detector(*, model_name: str) -> PresidioPIIDetector:
    try:
        # Presidio otherwise attempts an implicit network download and may raise SystemExit.
        # Production startup must fail deterministically when the pinned model is unavailable.
        if find_spec(model_name) is None:
            raise PIIDetectionError
        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": model_name}],
            }
        ).create_engine()
        registry = RecognizerRegistry(supported_languages=["en"])
        registry.load_predefined_recognizers(languages=["en"], nlp_engine=nlp_engine)
        registry.add_recognizer(IndiaAadhaarRecognizer())
        registry.add_recognizer(IndiaPanRecognizer())
        analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["en"],
            log_decision_process=False,
        )
        return PresidioPIIDetector(analyzer)
    except PIIDetectionError:
        raise
    except Exception:
        raise PIIDetectionError from None


def _to_entity(result: RecognizerResult) -> DetectedEntity:
    metadata: Mapping[str, object] = result.recognition_metadata or {}
    recognizer_name = metadata.get(RecognizerResult.RECOGNIZER_NAME_KEY)
    return DetectedEntity(
        entity_type=result.entity_type,
        start=result.start,
        end=result.end,
        score=result.score,
        recognizer_name=recognizer_name if isinstance(recognizer_name, str) else None,
    )
