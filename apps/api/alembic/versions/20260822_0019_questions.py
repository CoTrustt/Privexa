"""Create the client-scoped Question professional object.

Revision ID: 20260822_0019
Revises: 20260822_0018
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260822_0019"
down_revision: str | None = "20260822_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TIMESTAMPTZ = sa.DateTime(timezone=True)


def _runtime_role() -> str:
    role = context.config.attributes.get("runtime_database_role")
    if not isinstance(role, str) or not role:
        raise RuntimeError("Alembic runtime_database_role is required")
    return op.get_bind().dialect.identifier_preparer.quote(role)


def upgrade() -> None:
    op.create_table(
        "questions",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("context", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "RESOLVED",
                "CLOSED",
                name="question_status",
                native_enum=False,
                create_constraint=False,
            ),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("firm_id", UUID, nullable=False),
        sa.Column("client_id", UUID, nullable=False),
        sa.Column("created_by_membership_id", UUID, nullable=False),
        sa.Column("updated_by_membership_id", UUID, nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column(
            "created_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            TIMESTAMPTZ,
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("version >= 1", name="version_positive"),
        sa.CheckConstraint("updated_at >= created_at", name="timestamps_ordered"),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED', 'CLOSED')",
            name="question_status",
        ),
        sa.CheckConstraint(
            "char_length(title) BETWEEN 1 AND 255 AND title ~ '[^[:space:]]'",
            name="question_title_valid",
        ),
        sa.CheckConstraint(
            "char_length(question_text) BETWEEN 1 AND 20000 AND question_text ~ '[^[:space:]]'",
            name="question_text_valid",
        ),
        sa.CheckConstraint(
            "context IS NULL OR (char_length(context) BETWEEN 1 AND 50000 "
            "AND context ~ '[^[:space:]]')",
            name="question_context_valid",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "client_id"],
            ["client_workspaces.firm_id", "client_workspaces.id"],
            name="fk_questions_firm_client",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "created_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_questions_firm_creator_membership",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["firm_id", "updated_by_membership_id"],
            ["firm_memberships.firm_id", "firm_memberships.id"],
            name="fk_questions_firm_updater_membership",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_questions"),
        sa.UniqueConstraint("firm_id", "client_id", "id", name="uq_questions_tenant_id"),
    )
    op.create_index(
        "ix_questions_firm_client_created",
        "questions",
        ["firm_id", "client_id", "created_at"],
    )
    op.create_index(
        "ix_questions_firm_client_status_created_id",
        "questions",
        ["firm_id", "client_id", "status", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    op.execute("ALTER TABLE questions ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE questions FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY questions_scoped_select
        ON questions
        FOR SELECT
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
        )
        """
    )
    op.execute(
        """
        CREATE POLICY questions_scoped_insert
        ON questions
        FOR INSERT
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
            AND created_by_membership_id =
                privexa_private.current_context_uuid('privexa.membership_id')
            AND updated_by_membership_id =
                privexa_private.current_context_uuid('privexa.membership_id')
        )
        """
    )
    op.execute(
        """
        CREATE POLICY questions_scoped_update
        ON questions
        FOR UPDATE
        USING (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
        )
        WITH CHECK (
            firm_id = privexa_private.validated_firm_id()
            AND client_id = privexa_private.validated_client_id()
            AND updated_by_membership_id =
                privexa_private.current_context_uuid('privexa.membership_id')
        )
        """
    )

    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON questions FROM {runtime_role}")
    op.execute(f"GRANT SELECT, INSERT ON questions TO {runtime_role}")
    op.execute(
        "GRANT UPDATE (title, question_text, context, status, updated_by_membership_id, "
        f"updated_at, version) ON questions TO {runtime_role}"
    )


def downgrade() -> None:
    runtime_role = _runtime_role()
    op.execute(f"REVOKE ALL PRIVILEGES ON questions FROM {runtime_role}")
    op.execute("DROP POLICY IF EXISTS questions_scoped_update ON questions")
    op.execute("DROP POLICY IF EXISTS questions_scoped_insert ON questions")
    op.execute("DROP POLICY IF EXISTS questions_scoped_select ON questions")
    op.execute("ALTER TABLE questions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE questions DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_questions_firm_client_status_created_id", table_name="questions")
    op.drop_index("ix_questions_firm_client_created", table_name="questions")
    op.drop_table("questions")
