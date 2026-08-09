from edutap.data_provider.vocabulary import FieldKind, WalletType


def test_wallet_types_carry_the_edutap_spellings():
    assert WalletType.GOOGLE_ST == "GOOGLE_ST"
    assert WalletType.APPLE_VAS == "APPLE_VAS"
    assert {"GOOGLE_ACCESS", "APPLE_ACCESS", "APPLE_IDENTITY"} <= {w.value for w in WalletType}


def test_issuance_states_are_the_issuers_own_intent():
    from edutap.data_provider.vocabulary import IssuanceState

    assert {s.value for s in IssuanceState} == {
        "CREATED",
        "ISSUED",
        "REVOKED",
        "EXPIRED",
        "COMPLETED",
        "FAILED",
    }


def test_holder_states_are_derived_never_set():
    from edutap.data_provider.vocabulary import HolderState

    assert {s.value for s in HolderState} == {"NOT_PRESENT", "PRESENT", "SUSPENDED"}


def test_instance_states_cover_one_exemplar_at_the_holder():
    from edutap.data_provider.vocabulary import InstanceState

    assert {s.value for s in InstanceState} == {
        "PROVISIONING",
        "ACTIVE",
        "SUSPENDED",
        "REMOVED_BY_HOLDER",
        "REMOVED_BY_ISSUER",
        "FAILED",
    }


def test_the_single_axis_vocabulary_is_gone():
    """The old enum mixed issuer intent with observation at the holder.

    Kept as an explicit test so a re-introduction has to argue with a red test
    rather than slip back in as a convenience import.
    """
    import edutap.data_provider.vocabulary as vocabulary

    assert not hasattr(vocabulary, "PassLifecycleState")


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
    from edutap.data_provider.vocabulary import IssuanceState

    assert WalletType("APPLE_VAS") == "APPLE_VAS"
    assert IssuanceState("ISSUED") in ("ISSUED", "REVOKED")
