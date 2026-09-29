"""Separate pending manifests from canonical providers."""

import hashlib

import sqlalchemy as sa
from alembic import op


revision = "20260713_0004"
down_revision = "20260713_0003"
branch_labels = None
depends_on = None


NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
}
OWNER_HASH_UNIQUE = "uq_manifests_owner_manifest_hash"
LEGACY_HASH_UNIQUE = "uq_manifests_manifest_hash"
LEGACY_PROVIDER_FK = "fk_manifests_provider_id_providers"
AUDIT_ID_LIMIT = 10


def _constraint_name(item, fallback):
    return item.get("name") or fallback


def _canonical_provider_id(domain):
    normalized = str(domain).strip().lower().rstrip(".")
    digest = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return f"provider_{digest}"


def _audit_canonical_providers(bind, inspector):
    if not inspector.has_table("providers"):
        return
    columns = {item["name"] for item in inspector.get_columns("providers")}
    if "domain" not in columns:
        provider_ids = bind.execute(
            sa.text("SELECT provider_id FROM providers ORDER BY provider_id")
        )
        examples = []
        count = 0
        for provider_id, in provider_ids:
            count += 1
            if len(examples) < AUDIT_ID_LIMIT:
                examples.append(str(provider_id))
        if count:
            raise RuntimeError(
                "cannot audit canonical providers without domain column: "
                f"count={count} ids={','.join(examples)}"
            )
        return

    mismatches = 0
    examples = []
    providers = bind.execute(
        sa.text("SELECT provider_id, domain FROM providers ORDER BY provider_id")
    )
    for provider_id, domain in providers:
        if not isinstance(domain, str) or provider_id != _canonical_provider_id(domain):
            mismatches += 1
            if len(examples) < AUDIT_ID_LIMIT:
                examples.append(str(provider_id))
    if mismatches:
        raise RuntimeError(
            "noncanonical provider ids block pending manifest migration: "
            f"count={mismatches} ids={','.join(examples)}"
        )


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # SQLite DDL is not transactional, so this audit must precede every schema change.
    _audit_canonical_providers(bind, inspector)
    if not inspector.has_table("manifests"):
        return
    provider_fks = [
        item
        for item in inspector.get_foreign_keys("manifests")
        if item.get("referred_table") == "providers"
        and item.get("constrained_columns") == ["provider_id"]
    ]
    unique_constraints = inspector.get_unique_constraints("manifests")
    global_hash = [
        item
        for item in unique_constraints
        if item.get("column_names") == ["manifest_hash"]
    ]
    owner_hash_exists = any(
        item.get("column_names") == ["owner_wallet_address", "manifest_hash"]
        for item in unique_constraints
    )
    if not provider_fks and not global_hash and owner_hash_exists:
        return

    with op.batch_alter_table(
        "manifests", naming_convention=NAMING_CONVENTION
    ) as batch:
        for item in provider_fks:
            batch.drop_constraint(
                _constraint_name(item, LEGACY_PROVIDER_FK), type_="foreignkey"
            )
        for item in global_hash:
            batch.drop_constraint(
                _constraint_name(item, LEGACY_HASH_UNIQUE), type_="unique"
            )
        if not owner_hash_exists:
            batch.create_unique_constraint(
                OWNER_HASH_UNIQUE, ["owner_wallet_address", "manifest_hash"]
            )


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("manifests"):
        return
    duplicate_hashes = bind.execute(sa.text("""
        SELECT COUNT(*) FROM (
            SELECT manifest_hash
            FROM manifests
            GROUP BY manifest_hash
            HAVING COUNT(*) > 1
        ) AS duplicate_hashes
    """)).scalar_one()
    if duplicate_hashes:
        raise RuntimeError(
            "cannot restore global manifest hash uniqueness while duplicate hashes exist"
        )
    orphan_manifests = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM manifests AS manifests
        LEFT JOIN providers AS providers
          ON providers.provider_id = manifests.provider_id
        WHERE providers.provider_id IS NULL
    """)).scalar_one()
    if orphan_manifests:
        raise RuntimeError(
            "cannot restore manifest provider foreign key while pending manifests exist"
        )

    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("manifests")
    owner_hash = [
        item
        for item in unique_constraints
        if item.get("column_names") == ["owner_wallet_address", "manifest_hash"]
    ]
    global_hash_exists = any(
        item.get("column_names") == ["manifest_hash"]
        for item in unique_constraints
    )
    provider_fk_exists = any(
        item.get("referred_table") == "providers"
        and item.get("constrained_columns") == ["provider_id"]
        for item in inspector.get_foreign_keys("manifests")
    )
    with op.batch_alter_table(
        "manifests", naming_convention=NAMING_CONVENTION
    ) as batch:
        for item in owner_hash:
            batch.drop_constraint(
                _constraint_name(item, OWNER_HASH_UNIQUE), type_="unique"
            )
        if not global_hash_exists:
            batch.create_unique_constraint(LEGACY_HASH_UNIQUE, ["manifest_hash"])
        if not provider_fk_exists:
            batch.create_foreign_key(
                LEGACY_PROVIDER_FK,
                "providers",
                ["provider_id"],
                ["provider_id"],
                ondelete="CASCADE",
            )
