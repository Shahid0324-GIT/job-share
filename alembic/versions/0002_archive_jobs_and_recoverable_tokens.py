"""archive jobs and retain encrypted friend tokens"""
from alembic import op
import sqlalchemy as sa

revision = "0002_archive_tokens"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("friends", sa.Column("token_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("friends", "token_encrypted")
    op.drop_column("jobs", "archived_at")