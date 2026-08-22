"""Import every model once so Alembic sees complete metadata."""

from privexa_api.access_control.models import ClientAccessGrant, FirmMembership
from privexa_api.ai_gateway.models import AIProviderCircuitState, AIProviderRuntimeControl
from privexa_api.ai_policy.models import AIPolicyOverride, AIPolicyRuntimeControl
from privexa_api.ai_provenance.models import AIExecution, AIExecutionEvent, AIExecutionSource
from privexa_api.application_context.models import ActiveClientSession
from privexa_api.clients.models import ClientWorkspace
from privexa_api.db.base import Base
from privexa_api.db.resource_scope import validate_resource_scope_registry
from privexa_api.files.models import StoredFile
from privexa_api.identity.models import Firm, User
from privexa_api.questions.models import Question

validate_resource_scope_registry(Base.metadata)

__all__ = [
    "ActiveClientSession",
    "AIPolicyOverride",
    "AIPolicyRuntimeControl",
    "AIProviderCircuitState",
    "AIProviderRuntimeControl",
    "AIExecution",
    "AIExecutionEvent",
    "AIExecutionSource",
    "ClientAccessGrant",
    "ClientWorkspace",
    "Firm",
    "FirmMembership",
    "StoredFile",
    "Question",
    "User",
]
