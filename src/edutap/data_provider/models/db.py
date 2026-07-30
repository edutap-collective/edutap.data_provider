"""The two tables the data provider owns."""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field

from ..vocabulary import PassLifecycleState, WalletType
from .base import Base


def _utcnow() -> datetime:
    """Timezone-aware now, for the Python-side default."""
    return datetime.now(tz=UTC)


def _timestamp(on_update: bool = False) -> sa.Column:
    """Build a timestamptz column maintained by the database."""
    kwargs: dict[str, Any] = {"server_default": sa.func.now()}
    if on_update:
        kwargs["onupdate"] = sa.func.now()
    return sa.Column(sa.DateTime(timezone=True), nullable=False, **kwargs)


class PersonView(Base, table=True):
    """One view of one person: the payload a consumer of this view type may see."""

    __tablename__ = "person_view"
    __table_args__ = (sa.Index("ix_person_view_view_type", "view_type"),)

    person_uid: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), primary_key=True),
        description=(
            "Person identifier, uniquely determinable by the university: ePPN, UUID or "
            "hash. Never interpreted here. Byte collation so comparison and index order "
            "do not depend on a locale."
        ),
    )
    view_type: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), primary_key=True),
        description="`full_view` or a speaking slice such as `mensapass`.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(JSONB, nullable=False),
        description="Flat payload, standard-native names, arrays for multi-valued attributes.",
    )
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp(on_update=True))


class PassState(Base, table=True):
    """One issued pass and where it stands in its life."""

    __tablename__ = "pass_state"
    __table_args__ = (
        sa.Index("ix_pass_state_person_uid", "person_uid"),
        sa.Index(
            "ix_pass_state_person_template_wallet", "person_uid", "pass_template", "wallet_type"
        ),
    )

    pass_id: str = Field(
        sa_column=sa.Column(sa.String(255), primary_key=True),
        description=(
            "The provider's pass identifier. Not a UUID column: usually a UUID, but "
            "Google Wallet object identifiers carry a prefix and suffix."
        ),
    )
    person_uid: str = Field(
        sa_column=sa.Column(sa.String(64, collation="C"), nullable=False),
        description="No foreign key: a pass exists whether or not a view row currently does.",
    )
    wallet_type: WalletType = Field(
        sa_column=sa.Column(sa.String(32), nullable=False),
        description=(
            "Text column, not a native enum — a new wallet provider must not force a migration."
        ),
    )
    state: PassLifecycleState = Field(
        sa_column=sa.Column(sa.String(32), nullable=False),
        description="Stored and delivered, never validated here.",
    )
    pass_template: str = Field(
        sa_column=sa.Column(sa.String(64), nullable=False),
        description="Speaking template key, matching Template.key in edutap.pass_builder.",
    )
    pass_template_variant: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(64), nullable=True),
        description="Variant key; empty means the default variant, modelled as is_default there.",
    )
    created_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp())
    updated_at: datetime = Field(default_factory=_utcnow, sa_column=_timestamp(on_update=True))
