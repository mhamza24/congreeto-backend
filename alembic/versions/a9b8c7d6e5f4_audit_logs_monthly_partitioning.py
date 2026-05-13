"""audit_logs_monthly_partitioning

Revision ID: a9b8c7d6e5f4
Revises: f2a3b4c5d6e7
Create Date: 2026-05-10

Converts the flat audit_logs table to a PostgreSQL declarative range-partitioned
table, partitioned by created_at per calendar month.

Why partitioning?
  - audit_logs is append-only and grows without bound.
  - Old partitions (> 12 months) can be detached and archived with a single DDL
    statement instead of a DELETE that locks the whole table.
  - Query pruning: filtering by a recent created_at range scans only 1-2 partitions.

Design decisions:
  - PRIMARY KEY changed to (id, created_at) — Postgres requires the partition key
    in any primary/unique key on a partitioned table.
  - FK constraints (tenant_id → tenants, user_id → users) are DROPPED.  They
    cannot be declared on a partitioned table parent in Postgres < 15, and were
    ON DELETE SET NULL anyway (audit history is preserved even when the referenced
    row is deleted — the application still populates these columns correctly).
  - A BEFORE INSERT trigger auto-creates a new monthly partition whenever a row
    arrives for a month that has not been pre-created.  This acts as a safety net.
  - Partitions are pre-created: 6 months back, current month, 5 months ahead.

Downgrade note:
  Reversing declarative partitioning requires a full table rebuild which cannot
  be done online without an outage.  The downgrade() here converts back to a
  plain table, but it is safe only on a dev/staging database with small data
  volumes.  On production, pin the migration forward.
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f2a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _exec(sql: str) -> None:
    op.execute(sql)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ── 1. Rename existing table so we can copy data back later ────────────
    _exec("ALTER TABLE audit_logs RENAME TO audit_logs_unpartitioned")

    # ── 2. Drop existing indexes (they belong to the old table; we'll
    #       recreate them on the new partitioned parent) ────────────────────
    _exec("DROP INDEX IF EXISTS ix_audit_tenant")
    _exec("DROP INDEX IF EXISTS ix_audit_entity")
    _exec("DROP INDEX IF EXISTS ix_audit_user")

    # ── 3. Rename old SERIAL/IDENTITY sequence so BIGSERIAL on the new
    #       table can claim the canonical name audit_logs_id_seq ─────────────
    _exec("""
        DO $$
        DECLARE
            old_seq TEXT;
        BEGIN
            old_seq := pg_get_serial_sequence('audit_logs_unpartitioned', 'id');
            IF old_seq IS NOT NULL THEN
                EXECUTE format('ALTER SEQUENCE %s OWNED BY NONE', old_seq);
                EXECUTE format('ALTER SEQUENCE %s RENAME TO _audit_logs_legacy_seq', old_seq);
            END IF;
        END
        $$
    """)

    # ── 4. Create new partitioned parent ─────────────────────────────────
    #       Primary key must include the partition key (created_at).
    #       Foreign keys are intentionally omitted — see module docstring.
    _exec("""
        CREATE TABLE audit_logs (
            id          BIGSERIAL,
            tenant_id   BIGINT,
            user_id     BIGINT,
            entity_type VARCHAR(100) NOT NULL,
            entity_id   BIGINT,
            action      VARCHAR(50)  NOT NULL,
            diff        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            ip_address  VARCHAR(45),
            user_agent  TEXT,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)

    # ── 5. Helper PL/pgSQL function — create one month's partition ────────
    _exec("""
        CREATE OR REPLACE FUNCTION _audit_create_partition(target_date DATE)
        RETURNS VOID LANGUAGE plpgsql AS $$
        DECLARE
            pname  TEXT;
            pstart TIMESTAMPTZ;
            pend   TIMESTAMPTZ;
        BEGIN
            pstart := DATE_TRUNC('month', target_date AT TIME ZONE 'UTC');
            pend   := pstart + INTERVAL '1 month';
            pname  := 'audit_logs_' || TO_CHAR(pstart AT TIME ZONE 'UTC', 'YYYY_MM');
            IF NOT EXISTS (
                SELECT 1 FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relname = pname AND n.nspname = current_schema()
            ) THEN
                EXECUTE format(
                    'CREATE TABLE %I PARTITION OF audit_logs '
                    'FOR VALUES FROM (%L) TO (%L)',
                    pname, pstart, pend
                );
            END IF;
        END;
        $$
    """)

    # ── 6. BEFORE INSERT trigger — auto-creates missing monthly partitions ─
    _exec("""
        CREATE OR REPLACE FUNCTION _audit_logs_auto_partition()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM _audit_create_partition(NEW.created_at::DATE);
            RETURN NEW;
        END;
        $$
    """)

    _exec("""
        CREATE TRIGGER trg_audit_logs_auto_partition
        BEFORE INSERT ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION _audit_logs_auto_partition()
    """)

    # ── 7. Pre-create partitions: 6 months back through 5 months ahead ───
    _exec("""
        SELECT _audit_create_partition(gs::DATE)
        FROM generate_series(
            DATE_TRUNC('month', NOW() - INTERVAL '6 months'),
            DATE_TRUNC('month', NOW() + INTERVAL '5 months'),
            INTERVAL '1 month'
        ) gs
    """)

    # ── 8. Recreate indexes on parent (Postgres 11+ propagates to children) ─
    _exec("""
        CREATE INDEX ix_audit_tenant ON audit_logs (tenant_id, created_at DESC)
        WHERE tenant_id IS NOT NULL
    """)
    _exec("CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id)")
    _exec("""
        CREATE INDEX ix_audit_user ON audit_logs (user_id, created_at DESC)
        WHERE user_id IS NOT NULL
    """)

    # ── 9. Advance the new sequence past the max existing id ──────────────
    _exec("""
        SELECT setval(
            pg_get_serial_sequence('audit_logs', 'id'),
            COALESCE((SELECT MAX(id) FROM audit_logs_unpartitioned), 1),
            true
        )
    """)

    # ── 10. Copy existing rows — the trigger routes each row to the correct
    #        partition; historical months that weren't pre-created are handled
    #        automatically by the trigger ──────────────────────────────────
    _exec("""
        INSERT INTO audit_logs
            (id, tenant_id, user_id, entity_type, entity_id,
             action, diff, ip_address, user_agent, created_at)
        SELECT
            id, tenant_id, user_id, entity_type, entity_id,
            action, diff, ip_address, user_agent, created_at
        FROM audit_logs_unpartitioned
    """)

    # ── 11. Drop backup table and orphaned legacy sequence ────────────────
    _exec("DROP TABLE audit_logs_unpartitioned")
    _exec("DROP SEQUENCE IF EXISTS _audit_logs_legacy_seq")


# ---------------------------------------------------------------------------
# downgrade — rebuilds a plain unpartitioned table (dev/staging only)
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Rename partitioned parent (detaches all child partitions from it)
    _exec("ALTER TABLE audit_logs RENAME TO audit_logs_partitioned")
    _exec("DROP TRIGGER IF EXISTS trg_audit_logs_auto_partition ON audit_logs_partitioned")

    # Recreate the original flat table
    _exec("""
        CREATE TABLE audit_logs (
            id          BIGSERIAL    PRIMARY KEY,
            tenant_id   BIGINT       REFERENCES tenants(id) ON DELETE SET NULL,
            user_id     BIGINT       REFERENCES users(id)   ON DELETE SET NULL,
            entity_type VARCHAR(100) NOT NULL,
            entity_id   BIGINT,
            action      VARCHAR(50)  NOT NULL,
            diff        JSONB        NOT NULL DEFAULT '{}'::jsonb,
            ip_address  VARCHAR(45),
            user_agent  TEXT,
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)

    _exec("""
        CREATE INDEX ix_audit_tenant ON audit_logs (tenant_id, created_at DESC)
        WHERE tenant_id IS NOT NULL
    """)
    _exec("CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id)")
    _exec("""
        CREATE INDEX ix_audit_user ON audit_logs (user_id, created_at DESC)
        WHERE user_id IS NOT NULL
    """)

    # Copy data back from partitioned table
    _exec("""
        SELECT setval(
            pg_get_serial_sequence('audit_logs', 'id'),
            COALESCE((SELECT MAX(id) FROM audit_logs_partitioned), 1),
            true
        )
    """)
    _exec("""
        INSERT INTO audit_logs
            (id, tenant_id, user_id, entity_type, entity_id,
             action, diff, ip_address, user_agent, created_at)
        SELECT
            id, tenant_id, user_id, entity_type, entity_id,
            action, diff, ip_address, user_agent, created_at
        FROM audit_logs_partitioned
    """)

    # Drop the partitioned table (CASCADE detaches and drops child partitions)
    _exec("DROP TABLE audit_logs_partitioned CASCADE")
    _exec("DROP FUNCTION IF EXISTS _audit_logs_auto_partition()")
    _exec("DROP FUNCTION IF EXISTS _audit_create_partition(DATE)")
