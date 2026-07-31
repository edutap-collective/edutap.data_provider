from edutap.data_provider.vocabulary import FieldKind, PassLifecycleState, WalletType


def test_wallet_types_carry_the_edutap_spellings():
    assert WalletType.GOOGLE_ST == "GOOGLE_ST"
    assert WalletType.APPLE_VAS == "APPLE_VAS"
    assert {"GOOGLE_ACCESS", "APPLE_ACCESS", "APPLE_IDENTITY"} <= {w.value for w in WalletType}


def test_lifecycle_states_cover_the_pass_life():
    assert {s.value for s in PassLifecycleState} == {
        "NEW",
        "INSTALL_PENDING",
        "UPDATE_PENDING",
        "DELETE_PENDING",
        "ACTIVE",
        "INACTIVE",
    }


def test_field_kinds_say_what_a_field_is_good_for():
    assert {k.value for k in FieldKind} == {
        "STRING",
        "TEXT",
        "DATETIME",
        "LINK",
        "NFC",
        "BARCODE",
        "IMAGE",
    }


def test_values_compare_as_plain_strings():
    assert WalletType("APPLE_VAS") == "APPLE_VAS"
    assert PassLifecycleState("ACTIVE") in ("ACTIVE", "INACTIVE")
