"""The payload round: a second, explicit stage that may read derived fields.

Two questions this file settles, and both were silent failures before it:

* a `derived` rule that reads another `derived` name resolved to `None` at read
  time while `validate_config` accepted it, because `known` contained the
  derived names;
* a payload such as an NFC message could not be expressed at all — the rule
  language had no way to join strings or format a date.

`payloads` is a round, not two magic field names. Round one (`derived`) sees
stored fields and constants. Round two (`payloads`) additionally sees round one.
A cycle is not rejected here, it is unrepresentable: neither round can read
itself.
"""

import pytest

from edutap.data_provider.config import ConfigError, load_config
from edutap.data_provider.rules import RuleError, evaluate, parse_rule
from edutap.data_provider.validation import validate_config
from edutap.data_provider.vocabulary import FieldKind

MENSAPASS = """
constants:
  dns: lmu.de
views:
  mensapass:
    fields:
      stwm_role: [STRING, TEXT]
      role_valid_until: [STRING, DATETIME]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        rule: min(add_days(today(), 7), role_valid_until)
    payloads:
      nfc_payload:
        kinds: [STRING, NFC]
        rule: >
          concat('stwm.de:', dns, ':', stwm_role, ':',
                 format_date(pass_valid_until, 'YYYYMMDD'), '@',
                 format_date(today(), 'YYYYMMDD'))
"""


def write(tmp_path, text):
    path = tmp_path / "views.yaml"
    path.write_text(text)
    return path


# --- the round ------------------------------------------------------------------


def test_a_payload_may_read_a_derived_field(tmp_path):
    config = load_config(write(tmp_path, MENSAPASS))
    validate_config(config)
    assert "nfc_payload" in config.views["mensapass"].payloads


def test_a_derived_field_may_not_read_another_derived_field(tmp_path):
    """The trap this round exists to close.

    Before, `known` in `_check_view` contained the derived names, so this
    configuration loaded and the rule quietly evaluated to `None` on every
    request. Round one sees stored fields and constants, nothing else.
    """
    text = """
views:
  v:
    fields:
      a: [STRING]
    derived:
      one:
        kinds: [STRING]
        rule: a
      two:
        kinds: [STRING]
        rule: one
"""
    with pytest.raises(ConfigError, match="one"):
        validate_config(load_config(write(tmp_path, text)))


def test_a_payload_may_not_read_another_payload(tmp_path):
    """Round two cannot read itself either -- that is what makes it a round."""
    text = """
views:
  v:
    fields:
      a: [STRING]
    payloads:
      one:
        kinds: [STRING, NFC]
        rule: a
      two:
        kinds: [STRING, BARCODE]
        rule: one
"""
    with pytest.raises(ConfigError, match="one"):
        validate_config(load_config(write(tmp_path, text)))


def test_a_payload_name_may_not_collide_with_a_field_or_a_derived_name(tmp_path):
    text = """
views:
  v:
    fields:
      a: [STRING]
    derived:
      b:
        kinds: [STRING]
        rule: a
    payloads:
      b:
        kinds: [STRING, NFC]
        rule: a
"""
    with pytest.raises(ConfigError, match="b"):
        load_config(write(tmp_path, text))


def test_a_payload_rule_still_has_to_read_something_declared(tmp_path):
    text = """
views:
  v:
    fields:
      a: [STRING]
    payloads:
      p:
        kinds: [STRING, NFC]
        rule: concat(a, nowhere)
"""
    with pytest.raises(ConfigError, match="nowhere"):
        validate_config(load_config(write(tmp_path, text)))


# --- evaluation -----------------------------------------------------------------


def test_the_payload_is_built_from_the_derived_value(tmp_path):
    """The whole point, end to end: round two sees what round one computed."""
    import datetime

    config = load_config(write(tmp_path, MENSAPASS))
    validate_config(config)
    view = config.views["mensapass"]
    today = datetime.date(2026, 9, 12)
    payload = {"stwm_role": "student", "role_valid_until": "2027-03-31"}
    dates = {"role_valid_until", "pass_valid_until"}

    computed = {
        name: evaluate(parse_rule(spec.rule), payload, config.constants, dates, today=today)
        for name, spec in view.derived.items()
    }
    assert computed["pass_valid_until"] == datetime.date(2026, 9, 19)

    value = evaluate(
        parse_rule(view.payloads["nfc_payload"].rule),
        payload,
        config.constants,
        dates,
        today=today,
        computed=computed,
    )
    assert value == "stwm.de:lmu.de:student:20260919@20260912"
    assert len(value) < 64, "Apple VAS refuses an NFC message of 64 characters or more"


def test_a_computed_value_wins_over_a_payload_key_of_the_same_name():
    """Declared beats stored, and the file is where a reader looks first."""
    expression = parse_rule("x")
    assert evaluate(expression, {"x": "stored"}, {}, set(), computed={"x": "derived"}) == "derived"


def test_exists_sees_a_computed_value():
    expression = parse_rule("exists(x)")
    assert evaluate(expression, {}, {}, set(), computed={"x": "derived"}) is True
    assert evaluate(expression, {}, {}, set()) is False


# --- the two new functions ------------------------------------------------------


def test_concat_joins_scalars_and_skips_nothing():
    assert evaluate(parse_rule("concat('a', 'b', 'c')"), {}, {}, set()) == "abc"


def test_concat_renders_a_missing_value_as_the_empty_string():
    """A None in the middle must not become the text 'None' on a pass."""
    assert evaluate(parse_rule("concat('a', missing, 'b')"), {}, {}, set()) == "ab"


def test_concat_needs_at_least_one_argument():
    with pytest.raises(RuleError):
        parse_rule("concat()")


def test_format_date_writes_the_compact_form():

    value = evaluate(
        parse_rule("format_date(d, 'YYYYMMDD')"),
        {"d": "2026-09-19"},
        {},
        {"d"},
    )
    assert value == "20260919"


def test_format_date_writes_the_iso_form():
    value = evaluate(
        parse_rule("format_date(d, 'YYYY-MM-DD')"),
        {"d": "2026-09-19"},
        {},
        {"d"},
    )
    assert value == "2026-09-19"


def test_format_date_passes_a_missing_date_through_as_none():
    assert evaluate(parse_rule("format_date(d, 'YYYYMMDD')"), {}, {}, {"d"}) is None


def test_an_unknown_pattern_is_refused_when_the_rule_is_parsed():
    """An allowlist, not free strftime.

    A free pattern in a configuration file is a typo nobody sees until a pass
    carries it, and `%` sequences in a YAML file that also feeds a ConfigParser
    elsewhere are a class of surprise this project has already paid for.
    """
    with pytest.raises(RuleError, match="YYYYMMDD"):
        parse_rule("format_date(d, '%Y%m%d')")


def test_format_date_is_refused_on_something_that_is_not_a_date(tmp_path):
    text = """
views:
  v:
    fields:
      name: [STRING, TEXT]
    payloads:
      p:
        kinds: [STRING, NFC]
        rule: format_date(name, 'YYYYMMDD')
"""
    with pytest.raises(ConfigError, match="date"):
        validate_config(load_config(write(tmp_path, text)))


# --- the catalogue --------------------------------------------------------------


def test_a_payload_appears_in_the_catalogue_as_a_computed_entry(tmp_path):
    from edutap.data_provider.catalogue import catalogue_for

    config = load_config(write(tmp_path, MENSAPASS))
    entry = next(e for e in catalogue_for(config, "mensapass") if e.key == "nfc_payload")
    assert entry.derived is True
    assert FieldKind.NFC in entry.kinds


# --- over HTTP ------------------------------------------------------------------


class _FakeRepository:
    def __init__(self, row):
        self._row = row

    async def person_view(self, person_uid, view_type):
        return self._row if person_uid == "a@lmu.de" else None


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A live app serving one person, configured with both rounds."""
    from fastapi.testclient import TestClient

    from edutap.data_provider.api.app import create_app
    from edutap.data_provider.api.dependencies import get_provider_config, get_repository

    path = write(tmp_path, MENSAPASS)
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_DATABASE_URL", "postgresql+asyncpg://u:p@h/db")
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_CONFIG_PATH", str(path))
    monkeypatch.setenv("EDUTAP_DATA_PROVIDER_API_TOKEN", "test-token")
    app = create_app()
    app.dependency_overrides[get_provider_config] = lambda: load_config(path)
    app.dependency_overrides[get_repository] = lambda: _FakeRepository(
        {"stwm_role": "student", "role_valid_until": "2027-03-31"}
    )
    return TestClient(app)


def _post(client, fields):
    return client.post(
        "/lookup",
        json={"person_uid": "a@lmu.de", "view_type": "mensapass", "fields": fields},
        headers={"Authorization": "Bearer test-token"},
    )


def test_the_service_answers_a_payload_that_reads_a_derived_field(client):
    """The route runs both rounds, in order, for a request that asks only for round two.

    `pass_valid_until` is not requested here. It still has to be computed,
    because the payload reads it -- that is the behaviour the round exists for.
    """
    import datetime

    response = _post(client, ["nfc_payload"])
    assert response.status_code == 200

    today = datetime.date.today()
    expected = (
        f"stwm.de:lmu.de:student:{(today + datetime.timedelta(days=7)):%Y%m%d}@{today:%Y%m%d}"
    )
    assert response.json() == {"nfc_payload": expected}


def test_a_payload_and_its_input_can_be_requested_together(client):
    response = _post(client, ["nfc_payload", "pass_valid_until", "stwm_role"])
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"nfc_payload", "pass_valid_until", "stwm_role"}
    # The date inside the payload is the same one the derived field reports --
    # one computation, not two that could drift.
    assert body["pass_valid_until"].replace("-", "") in body["nfc_payload"]


def test_a_payload_is_offered_by_the_catalogue_endpoint(client):
    response = client.get(
        "/catalogue",
        params={"view_type": "mensapass"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    entry = next(e for e in response.json() if e["key"] == "nfc_payload")
    assert entry["derived"] is True
    assert "NFC" in entry["kinds"]
