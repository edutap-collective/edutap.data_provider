"""The controlled values this service delivers, re-exported from the shared package.

They used to be declared here, with a docstring saying that the spellings were the
leading ones and that aligning the other copies was follow-up work. That work
happened: `edutap.data_models` now carries them, and the tables this service reads
are typed with *those* enums.

Keeping a second declaration would mean two `IssuanceState` classes in one process
that compare unequal -- the exact drift the shared package exists to end. The module
stays as this package's façade so `from edutap.data_provider.vocabulary import ...`
keeps working; there is simply nothing declared in it any more.
"""

from edutap.data_models.vocabulary import (
    FieldKind,
    HolderState,
    InstanceState,
    IssuanceState,
    WalletType,
)

__all__ = ["FieldKind", "HolderState", "InstanceState", "IssuanceState", "WalletType"]
