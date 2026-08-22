from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from privexa_api.ai_policy.contracts import AIProtectionProfileId
from privexa_api.ai_protection.contracts import ProtectionAction

EMAIL_ADDRESS = "EMAIL_ADDRESS"
PHONE_NUMBER = "PHONE_NUMBER"
PERSON = "PERSON"
LOCATION = "LOCATION"
IP_ADDRESS = "IP_ADDRESS"
CREDIT_CARD = "CREDIT_CARD"
INDIA_AADHAAR = "INDIA_AADHAAR"
INDIA_PAN = "INDIA_PAN"


@dataclass(frozen=True, slots=True)
class AIProtectionProfile:
    profile_id: AIProtectionProfileId
    language: str
    score_threshold: float
    actions: Mapping[str, ProtectionAction]
    precedence: Mapping[str, int]

    def __post_init__(self) -> None:
        if not 0 <= self.score_threshold <= 1:
            raise ValueError("protection score threshold must be between zero and one")
        if not self.actions or set(self.actions) != set(self.precedence):
            raise ValueError("protection actions and precedence must cover the same entities")


_MODEL_ENTITY_ACTIONS = MappingProxyType(
    {
        EMAIL_ADDRESS: ProtectionAction.TOKENIZE,
        PHONE_NUMBER: ProtectionAction.TOKENIZE,
        PERSON: ProtectionAction.TOKENIZE,
        LOCATION: ProtectionAction.TOKENIZE,
        IP_ADDRESS: ProtectionAction.REPLACE,
        CREDIT_CARD: ProtectionAction.MASK,
        INDIA_AADHAAR: ProtectionAction.TOKENIZE,
        INDIA_PAN: ProtectionAction.TOKENIZE,
    }
)

_MODEL_ENTITY_PRECEDENCE = MappingProxyType(
    {
        INDIA_AADHAAR: 100,
        INDIA_PAN: 95,
        CREDIT_CARD: 90,
        EMAIL_ADDRESS: 80,
        IP_ADDRESS: 75,
        PHONE_NUMBER: 70,
        PERSON: 60,
        LOCATION: 50,
    }
)

EXTERNAL_MODEL_PII_V1 = AIProtectionProfile(
    profile_id=AIProtectionProfileId.EXTERNAL_MODEL_PII_V1,
    language="en",
    score_threshold=0.4,
    actions=_MODEL_ENTITY_ACTIONS,
    precedence=_MODEL_ENTITY_PRECEDENCE,
)

PROTECTION_PROFILES: Mapping[AIProtectionProfileId, AIProtectionProfile] = MappingProxyType(
    {EXTERNAL_MODEL_PII_V1.profile_id: EXTERNAL_MODEL_PII_V1}
)


def resolve_protection_profile(profile_id: AIProtectionProfileId) -> AIProtectionProfile:
    from privexa_api.ai_protection.errors import UnsupportedProtectionProfile

    profile = PROTECTION_PROFILES.get(profile_id)
    if profile is None:
        raise UnsupportedProtectionProfile
    return profile
