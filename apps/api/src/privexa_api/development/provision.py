from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence

from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from privexa_api.access_control.enums import FirmRole
from privexa_api.db import model_registry as _model_registry  # noqa: F401
from privexa_api.db.session import build_engine
from privexa_api.development.provisioning import (
    DevelopmentIdentitySpec,
    DevelopmentProvisioningError,
    provision_development_identity,
)


def validate_development_target(*, environment: str, database_url: str) -> None:
    if environment != "development":
        raise DevelopmentProvisioningError(
            "Local identity provisioning requires PRIVEXA_ENVIRONMENT=development"
        )
    database_name = make_url(database_url).database
    if not database_name:
        raise DevelopmentProvisioningError("DATABASE_URL must include a database name")
    if database_name.lower().endswith("_test"):
        raise DevelopmentProvisioningError(
            "Local identity provisioning refuses databases whose names end in '_test'"
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Idempotently provision one identity in a local Privexa development firm."
    )
    parser.add_argument("--firm-name", required=True)
    parser.add_argument("--stytch-organization-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--role", required=True, choices=[role.value for role in FirmRole])
    parser.add_argument("--stytch-member-id", required=True)
    parser.add_argument("--client", action="append", default=[])
    parser.add_argument("--assign-client", action="append", default=[])
    parser.add_argument(
        "--restrict-work-note-ai-client",
        action="append",
        default=[],
        help="Create/update a client policy override that denies ai.prepare_work_note.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    environment = os.getenv("PRIVEXA_ENVIRONMENT", "")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        raise DevelopmentProvisioningError("DATABASE_URL must be set")
    validate_development_target(environment=environment, database_url=database_url)

    engine = build_engine(database_url)
    try:
        with Session(engine) as session, session.begin():
            result = provision_development_identity(
                session,
                spec=DevelopmentIdentitySpec(
                    firm_name=arguments.firm_name,
                    stytch_organization_id=arguments.stytch_organization_id,
                    email=arguments.email,
                    display_name=arguments.display_name,
                    role=FirmRole(arguments.role),
                    stytch_member_id=arguments.stytch_member_id,
                    client_names=tuple(arguments.client),
                    assigned_client_names=tuple(arguments.assign_client),
                    restricted_work_note_client_names=tuple(arguments.restrict_work_note_ai_client),
                ),
            )
    finally:
        engine.dispose()

    print(
        json.dumps(
            {
                "firm_id": str(result.firm_id),
                "user_id": str(result.user_id),
                "membership_id": str(result.membership_id),
                "clients": {
                    name: str(identifier) for name, identifier in result.client_ids.items()
                },
                "assigned_clients": {
                    name: str(identifier) for name, identifier in result.assigned_client_ids.items()
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
