"""Read-only service delivering person views and pass states."""

from importlib.metadata import version

from .vocabulary import FieldKind, HolderState, InstanceState, IssuanceState, WalletType

__version__ = version("edutap.data_provider")

__all__ = [
    "FieldKind",
    "HolderState",
    "InstanceState",
    "IssuanceState",
    "WalletType",
    "__version__",
]
