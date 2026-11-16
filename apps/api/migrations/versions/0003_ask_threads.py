"""Assistant conversation history: one thread per conversation, its questions and answers.

Additive and reversible (docs/UX_QA_AUDIT.md ASK-08). Threads belong to a user and go with them; a thread
keeps the field it was last about, set to NULL if that field is deleted. `request_id` lets a question the
farmer stopped be removed even when the answer was already saved.

Revision ID: 0003_ask_threads
"""
from alembic import op

revision = "0003_ask_threads"
down_revision = "0002_extensions"
branch_labels = None
depends_on = None

SQL = r"""
CREATE TABLE ask_threads (
  id               BIGSERIAL PRIMARY KEY,
  user_id          BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title            TEXT NOT NULL CHECK (char_length(title) BETWEEN 1 AND 120),
  field_id         BIGINT REFERENCES fields(id) ON DELETE SET NULL,
  pinned           BOOLEAN NOT NULL DEFAULT FALSE,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ask_threads_user_recent ON ask_threads (user_id, last_activity_at DESC, id DESC);

CREATE TABLE ask_messages (
  id         BIGSERIAL PRIMARY KEY,
  thread_id  BIGINT NOT NULL REFERENCES ask_threads(id) ON DELETE CASCADE,
  role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content    TEXT NOT NULL,
  payload    JSONB NOT NULL DEFAULT '{}'::jsonb,
  request_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_ask_messages_thread ON ask_messages (thread_id, id);
CREATE INDEX ix_ask_messages_request ON ask_messages (request_id) WHERE request_id IS NOT NULL;
"""

DOWN = r"""
DROP TABLE IF EXISTS ask_messages;
DROP TABLE IF EXISTS ask_threads;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    op.get_bind().exec_driver_sql(DOWN)
