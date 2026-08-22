"""Register the bounded customer work-note AI task.

Revision ID: 20260822_0015
Revises: 20260822_0014
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260822_0015"
down_revision: str | None = "20260822_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO ai_policy_runtime_controls
                (task_id, enabled, revision, configuration_hash, id)
            VALUES
                ('ai.prepare_work_note', true, 1, :configuration_hash, :id)
            """
        ),
        {
            "configuration_hash": (
                "3bacb79a071e53a4797e3d345647218f6daca87e7d03e52cb81abd7f62dfeed1"
            ),
            "id": "00000000-0000-4000-8000-000000001103",
        },
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM ai_policy_runtime_controls WHERE id = '00000000-0000-4000-8000-000000001103'"
    )
