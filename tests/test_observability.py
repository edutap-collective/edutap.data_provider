"""What may leave the process, pinned."""

import pytest
from pydantic import SecretStr

from edutap.data_provider.observability import pseudonym

SALT = SecretStr("a-salt")
OTHER_SALT = SecretStr("another-salt")


def test_the_pseudonym_is_stable_for_one_person_and_salt():
    assert pseudonym("u123456", SALT) == pseudonym("u123456", SALT)


def test_different_people_get_different_pseudonyms():
    assert pseudonym("u123456", SALT) != pseudonym("u654321", SALT)


def test_rotating_the_salt_renames_everybody():
    """The intended property: a pseudonym does not follow a person across a rotation."""
    assert pseudonym("u123456", SALT) != pseudonym("u123456", OTHER_SALT)


def test_without_a_salt_there_is_no_pseudonym():
    """Not a pseudonym computed from an empty key. Enabling this is deliberate."""
    assert pseudonym("u123456", None) is None


def test_the_pseudonym_never_contains_the_person_uid():
    person_uid = "u123456"

    result = pseudonym(person_uid, SALT)

    assert person_uid not in result


@pytest.mark.parametrize("person_uid", ["u123456", "", "Grüße-mit-Umlaut", "a" * 500])
def test_the_pseudonym_is_twelve_hex_characters(person_uid):
    """A label, not a stored identifier. Non-ASCII must not raise."""
    result = pseudonym(person_uid, SALT)

    assert len(result) == 12
    assert all(character in "0123456789abcdef" for character in result)
