"""create JobShare tables"""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("jobs", sa.Column("id", sa.String(36), primary_key=True), sa.Column("url", sa.Text(), nullable=False), sa.Column("source", sa.String(100), nullable=False), sa.Column("company", sa.String(255)), sa.Column("role", sa.String(255)), sa.Column("location", sa.String(255)), sa.Column("description", sa.Text()), sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("url"))
    op.create_table("friends", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255), nullable=False), sa.Column("token_hash", sa.String(255), nullable=False), sa.Column("active", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True)), sa.Column("updated_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("token_hash"))
    op.create_table("batches", sa.Column("id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255)), sa.Column("created_at", sa.DateTime(timezone=True)))
    op.create_table("batch_jobs", sa.Column("batch_id", sa.String(36), sa.ForeignKey("batches.id", ondelete="CASCADE"), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True), sa.Column("added_at", sa.DateTime(timezone=True)))
    op.create_table("friend_jobs", sa.Column("friend_id", sa.String(36), sa.ForeignKey("friends.id", ondelete="CASCADE"), primary_key=True), sa.Column("job_id", sa.String(36), sa.ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True), sa.Column("status", sa.String(50), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_table("friend_jobs")
    op.drop_table("batch_jobs")
    op.drop_table("batches")
    op.drop_table("friends")
    op.drop_table("jobs")