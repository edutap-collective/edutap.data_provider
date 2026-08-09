"""The eduTAP vocabulary for wallets, pass lifecycle and field kinds.

A consumer that does not already depend on this package is asked to COPY these
values rather than import them: importing would point its dependency at the service
it consumes — `edutap.pass_builder` would depend on the data provider. The same rule
applies to the naming convention in `models/base.py`, for the same reason.

Where that dependency already exists the recommendation has nothing left to protect,
so importing is available and supported. These five enumerations are deliberately
re-exported from the package root (`from edutap.data_provider import WalletType`) as
well as from this module; both spellings are public API.

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


class IssuanceState(StrEnum):
    """What the issuer has done or wants — entirely under its own control.

    Separate from what is observed at the holder: Google's `State` is an issuer
    declaration, Apple's registrations are an observation of what the user did.
    Pressing both into one column never adds up, however the values are sorted.
    """

    CREATED = "CREATED"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HolderState(StrEnum):
    """Whether the pass is present at the holder — derived, never set.

    `PRESENT` when at least one instance is `ACTIVE`; `SUSPENDED` when instances
    exist, none is active and at least one is suspended; `NOT_PRESENT` otherwise.
    The pass-state consumer maintains it in the same transaction that changes an
    instance, so the stored value cannot drift from the instances it summarises.
    """

    NOT_PRESENT = "NOT_PRESENT"
    PRESENT = "PRESENT"
    SUSPENDED = "SUSPENDED"


class InstanceState(StrEnum):
    """One exemplar of a pass at the holder.

    What an exemplar is depends on the platform: a device registration or a
    provisioned credential at Apple, the save into the account at Google.
    """

    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED_BY_HOLDER = "REMOVED_BY_HOLDER"
    REMOVED_BY_ISSUER = "REMOVED_BY_ISSUER"
    FAILED = "FAILED"


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
