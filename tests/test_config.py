import pytest

from edutap.data_provider.config import ConfigError, load_config
from edutap.data_provider.vocabulary import FieldKind

CONFIG = """
constants:
  open_ended: 9999-12-31

views:
  full_view:
    description: Complete record
    fields:
      surname: [STRING, TEXT]
      mail: [STRING, TEXT, LINK]
  mensapass:
    fields:
      display_name: [STRING, TEXT]
    derived:
      pass_valid_until:
        kinds: [STRING, TEXT, DATETIME]
        rule: add_days(today(), 7)
"""


def write(tmp_path, text):
    path = tmp_path / "views.yaml"
    path.write_text(text)
    return path


def test_loads_views_and_fields(tmp_path):
    config = load_config(write(tmp_path, CONFIG))
    assert sorted(config.views) == ["full_view", "mensapass"]
    assert config.views["full_view"].fields["mail"].kinds == [
        FieldKind.STRING,
        FieldKind.TEXT,
        FieldKind.LINK,
    ]


def test_loads_a_derived_field_with_its_rule(tmp_path):
    config = load_config(write(tmp_path, CONFIG))
    derived = config.views["mensapass"].derived["pass_valid_until"]
    assert derived.rule == "add_days(today(), 7)"
    assert FieldKind.DATETIME in derived.kinds


def test_constants_keep_their_yaml_types(tmp_path):
    import datetime

    config = load_config(write(tmp_path, CONFIG))
    assert config.constants["open_ended"] == datetime.date(9999, 12, 31)


def test_unknown_kind_is_fatal(tmp_path):
    text = CONFIG.replace("[STRING, TEXT, LINK]", "[STRING, MAGIC]")
    with pytest.raises(ConfigError, match="MAGIC"):
        load_config(write(tmp_path, text))


def test_a_derived_name_colliding_with_a_field_is_fatal(tmp_path):
    text = CONFIG.replace("      display_name: [STRING, TEXT]", "      pass_valid_until: [STRING]")
    with pytest.raises(ConfigError, match="pass_valid_until"):
        load_config(write(tmp_path, text))


def test_a_view_without_fields_or_derived_is_fatal(tmp_path):
    with pytest.raises(ConfigError, match="empty"):
        load_config(write(tmp_path, "views:\n  ghost: {}\n"))


def test_a_missing_file_is_fatal(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_dotted_or_nested_field_names_are_rejected(tmp_path):
    text = CONFIG.replace("      surname: [STRING, TEXT]", "      person.surname: [STRING]")
    with pytest.raises(ConfigError, match="flat"):
        load_config(write(tmp_path, text))


def test_malformed_yaml_is_fatal(tmp_path):
    text = "views:\n  full_view:\n    fields: [unbalanced\n"
    with pytest.raises(ConfigError, match="views.yaml"):
        load_config(write(tmp_path, text))


def test_a_duplicate_view_name_is_fatal(tmp_path):
    """A copy-pasted view block must not silently win over the first one.

    `yaml.safe_load` keeps the last of two identically named keys, so the service
    would start happily and serve a definition nobody meant to deploy.
    """
    text = (
        CONFIG
        + """
  mensapass:
    fields:
      display_name: [STRING]
"""
    )
    with pytest.raises(ConfigError, match="mensapass"):
        load_config(write(tmp_path, text))


def test_a_duplicate_field_name_inside_a_view_is_fatal(tmp_path):
    """The same silent overwrite one level down is just as wrong."""
    text = CONFIG.replace(
        "      mail: [STRING, TEXT, LINK]",
        "      mail: [STRING, TEXT, LINK]\n      surname: [STRING]",
    )
    with pytest.raises(ConfigError, match="surname"):
        load_config(write(tmp_path, text))


def test_a_duplicate_constant_is_fatal(tmp_path):
    text = CONFIG.replace(
        "  open_ended: 9999-12-31",
        "  open_ended: 9999-12-31\n  open_ended: 2000-01-01",
    )
    with pytest.raises(ConfigError, match="open_ended"):
        load_config(write(tmp_path, text))


def test_the_duplicate_message_points_at_the_file(tmp_path):
    """Whoever edits the YAML needs the file and the key, not a parser trace."""
    text = (
        CONFIG
        + """
  mensapass:
    fields:
      display_name: [STRING]
"""
    )
    with pytest.raises(ConfigError) as error:
        load_config(write(tmp_path, text))
    message = str(error.value)
    assert "views.yaml" in message
    assert "mensapass" in message
    assert "duplicate" in message.lower()


def test_fields_accept_the_long_mapping_form(tmp_path):
    text = CONFIG.replace(
        "      surname: [STRING, TEXT]",
        "      surname:\n        kinds: [STRING, TEXT]\n        description: Family name",
    )
    config = load_config(write(tmp_path, text))
    surname = config.views["full_view"].fields["surname"]
    assert surname.kinds == [FieldKind.STRING, FieldKind.TEXT]
    assert surname.description == "Family name"


MERGE_CONFIG = """
constants:
  open_ended: 9999-12-31

defaults: &defaults
  description: Inherited description
  fields:
    surname: [STRING, TEXT]

views:
  mensapass:
    <<: *defaults
    description: Explicit description
"""


def test_a_merge_key_is_resolved_and_the_explicit_value_wins(tmp_path):
    """`<<: *anchor` is valid YAML and must keep working alongside the check.

    The duplicate-key check scans the mapping the author wrote. A merge key is the
    one construct where the same name legitimately appears twice — once inherited,
    once overridden — and YAML says the explicit one wins.
    """
    config = load_config(write(tmp_path, MERGE_CONFIG))
    view = config.views["mensapass"]
    assert view.description == "Explicit description"
    assert view.fields["surname"].kinds == [FieldKind.STRING, FieldKind.TEXT]


def test_two_merge_keys_in_one_mapping_are_not_a_duplicate(tmp_path):
    """`<<` is not a key: repeating it merges both anchors, it does not clash."""
    text = """
base_one: &one
  fields:
    surname: [STRING]
base_two: &two
  derived:
    pass_valid_until:
      kinds: [STRING]
      rule: today()

views:
  mensapass:
    <<: *one
    <<: *two
"""
    config = load_config(write(tmp_path, text))
    view = config.views["mensapass"]
    assert "surname" in view.fields
    assert "pass_valid_until" in view.derived


def test_a_genuine_duplicate_next_to_a_merge_key_is_still_fatal(tmp_path):
    """Merging must not buy an author an exemption from the check."""
    text = MERGE_CONFIG.replace(
        "    description: Explicit description",
        "    description: Explicit description\n    description: And again",
    )
    with pytest.raises(ConfigError, match="description"):
        load_config(write(tmp_path, text))


def test_a_duplicate_inside_the_merged_mapping_is_fatal(tmp_path):
    """The anchored mapping is a mapping of the document like any other.

    It is checked where it is written, so the error names the definition site rather
    than every place that merges it.
    """
    text = MERGE_CONFIG.replace(
        "    surname: [STRING, TEXT]",
        "    surname: [STRING, TEXT]\n    surname: [TEXT]",
    )
    with pytest.raises(ConfigError, match="surname"):
        load_config(write(tmp_path, text))


def test_a_duplicate_in_an_anchor_written_at_the_merge_site_is_fatal(tmp_path):
    """The shape that hides from a naive check: an anchor with no other binding.

    PyYAML descends into a merge source by calling `flatten_mapping` on it, never
    `construct_mapping`. A mapping reached only that way would therefore skip the
    duplicate scan, and its repeated key would be resolved by the plain
    last-one-wins rule — silently changing which fields the view exposes.
    """
    text = """
views:
  mensapass:
    <<: &defaults
      description: Inherited
      fields:
        surname: [STRING]
      fields:
        surname: [STRING]
        mail: [STRING, LINK]
    description: Explicit
"""
    with pytest.raises(ConfigError, match="fields"):
        load_config(write(tmp_path, text))


def test_a_duplicate_in_a_sequence_of_merged_anchors_is_fatal(tmp_path):
    """`<<: [*one, *two]` is the other spelling of a merge and gets the same check."""
    text = """
views:
  mensapass:
    <<: [&one {fields: {surname: [STRING]}, fields: {mail: [STRING]}}]
    description: Explicit
"""
    with pytest.raises(ConfigError, match="fields"):
        load_config(write(tmp_path, text))


def test_a_duplicate_in_a_merge_nested_inside_a_merge_is_fatal(tmp_path):
    """Merges nest, so the check has to follow them all the way down."""
    text = """
views:
  mensapass:
    <<: &outer
      <<: &inner
        fields: {surname: [STRING]}
        fields: {mail: [STRING]}
      description: Inherited
    description: Explicit
"""
    with pytest.raises(ConfigError, match="fields"):
        load_config(write(tmp_path, text))


def test_an_anchor_reused_after_its_own_merge_still_loads(tmp_path):
    """Two levels of defaults is ordinary, and must not be read as a duplicate.

    `flatten_mapping` rewrites a node in place, and PyYAML resolves every alias to
    one shared node. Looking at a merge source a second time would therefore see the
    already merged content, where the inherited key and its deliberate override sit
    side by side — and would reject this correct document. Each node is examined
    once, on the visit that still sees it as written.
    """
    text = """
views:
  base: &base
    fields:
      surname: [STRING]
      mail: [STRING]

  extended: &extended
    <<: *base
    fields:
      surname: [STRING, TEXT]

  mensapass:
    <<: *extended
    description: Explicit
"""
    config = load_config(write(tmp_path, text))
    assert config.views["mensapass"].description == "Explicit"
    assert config.views["mensapass"].fields["surname"].kinds == [
        FieldKind.STRING,
        FieldKind.TEXT,
    ]


def test_the_same_anchor_merged_into_two_views_still_loads(tmp_path):
    """One shared set of defaults, used twice — the point of an anchor."""
    text = """
defaults:
  inherited: &inherited
    fields:
      surname: [STRING]
  shared: &shared
    <<: *inherited
    fields:
      surname: [STRING, TEXT]

views:
  mensapass:
    <<: *shared
    description: Canteen
  esc:
    <<: *shared
    description: Student card
"""
    config = load_config(write(tmp_path, text))
    assert sorted(config.views) == ["esc", "mensapass"]
    assert config.views["esc"].fields["surname"].kinds == [FieldKind.STRING, FieldKind.TEXT]


def test_a_duplicate_inside_an_anchor_merged_twice_is_still_fatal(tmp_path):
    """Being reused must not launder a duplicate: the first visit catches it."""
    text = """
defaults:
  shared: &shared
    fields: {surname: [STRING]}
    fields: {mail: [STRING]}

views:
  mensapass:
    <<: *shared
    description: Canteen
  esc:
    <<: *shared
    description: Student card
"""
    with pytest.raises(ConfigError, match="fields"):
        load_config(write(tmp_path, text))


def test_two_anchors_defining_one_key_follow_yaml_precedence(tmp_path):
    """Not a duplicate: this is inheritance, and YAML decides who wins.

    `<<: [*one, *two]` takes the key from the earlier source, and an explicit key
    beats any merged one. Refusing this would make the sequence form useless, which
    is the whole reason it exists. The check refuses one mapping naming a key twice
    *in the file*; it does not arbitrate between two anchors that each name it once.
    """
    text = """
defaults:
  public: &public
    surname: [STRING]
    mail: [STRING, LINK]
  internal: &internal
    surname: [STRING, TEXT]

views:
  directory:
    description: Public listing
    fields:
      <<: [*public, *internal]
"""
    config = load_config(write(tmp_path, text))
    fields = config.views["directory"].fields
    assert fields["surname"].kinds == [FieldKind.STRING]
    assert "mail" in fields
