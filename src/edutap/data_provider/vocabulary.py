"""The eduTAP vocabulary for wallets, pass lifecycle and field kinds.

Consumers COPY these values rather than importing them. Importing would point a
consumer's dependency at the service it consumes — `edutap.pass_builder` would
depend on the data provider. The same rule applies to the naming convention in
`models/base.py`, for the same reason.

These spellings supersede the older ones in `edutap.pass_builder`,
`edutap.heidi_api` and `lmu_edutap_full_view` (`APPLE`, `GOOGLE`, `SAMSUNG` with
`_ACCESS` variants). Aligning those is follow-up work.
"""

from enum import StrEnum


class WalletType(StrEnum):
    """Which wallet technology a pass was issued for."""

    GOOGLE_ST = "GOOGLE_ST"
    GOOGLE_ACCESS = "GOOGLE_ACCESS"
    APPLE_VAS = "APPLE_VAS"
    APPLE_ACCESS = "APPLE_ACCESS"
    APPLE_IDENTITY = "APPLE_IDENTITY"
    SAMSUNG_ST = "SAMSUNG_ST"
    SAMSUNG_ACCESS = "SAMSUNG_ACCESS"


class PassLifecycleState(StrEnum):
    """Where a pass stands in its life.

    The data provider stores and delivers these; it never validates a transition.
    """

    NEW = "NEW"
    INSTALL_PENDING = "INSTALL_PENDING"
    UPDATE_PENDING = "UPDATE_PENDING"
    DELETE_PENDING = "DELETE_PENDING"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class FieldKind(StrEnum):
    """What a field is good for — not what it holds.

    `edutap.pass_builder` validates mapping rules against these when a template
    version is published: a field may only go into an NFC payload if it declares
    NFC.
    """

    STRING = "STRING"
    TEXT = "TEXT"
    DATETIME = "DATETIME"
    LINK = "LINK"
    NFC = "NFC"
    BARCODE = "BARCODE"
    IMAGE = "IMAGE"
