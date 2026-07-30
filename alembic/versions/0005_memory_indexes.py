"""Memory dedup index and HNSW vector search index."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_memory_indexes"
down_revision: Union[str, None] = "0004_event_records"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_memories_kind_source_id",
        "memories",
        ["kind", "source_id"],
        unique=True,
        postgresql_where=sa.text("source_id IS NOT NULL"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_embedding_hnsw "
        "ON memories USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memories_embedding_hnsw")
    op.drop_index("uq_memories_kind_source_id", table_name="memories")
