import pytest
from sqlalchemy import text

from edutap.data_provider.repository import Repository

pytestmark = pytest.mark.integration


async def insert_view(session_factory, person_uid, view_type, data):
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO person_view (person_uid, view_type, data) "
                r"VALUES (:uid, :view, :data\:\:jsonb)"
            ),
            {"uid": person_uid, "view": view_type, "data": data},
        )
        await session.commit()


async def test_reads_the_payload_of_one_view(session_factory):
    await insert_view(session_factory, "a@lmu.de", "full_view", '{"surname": "Doe"}')
    repository = Repository(session_factory)
    assert await repository.person_view("a@lmu.de", "full_view") == {"surname": "Doe"}


async def test_an_absent_row_is_none(session_factory):
    repository = Repository(session_factory)
    assert await repository.person_view("nobody@lmu.de", "full_view") is None


async def test_view_types_do_not_leak_into_each_other(session_factory):
    await insert_view(session_factory, "a@lmu.de", "full_view", '{"surname": "Doe"}')
    await insert_view(session_factory, "a@lmu.de", "mensapass", '{"display_name": "A. Doe"}')
    repository = Repository(session_factory)
    assert await repository.person_view("a@lmu.de", "mensapass") == {"display_name": "A. Doe"}


async def test_the_pass_state_table_accepts_a_google_style_identifier(session_factory):
    """The schema must hold what a provider actually issues, prefix and all."""
    async with session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO pass_state (pass_id, person_uid, wallet_type, state, pass_template) "
                "VALUES ('3388000000022195611.mensapass-a-lmu-de', 'a@lmu.de', "
                "'GOOGLE_ST', 'ACTIVE', 'mensapass')"
            )
        )
        await session.commit()
        stored = await session.execute(
            text("SELECT pass_id, pass_template_variant FROM pass_state")
        )
    assert stored.one() == ("3388000000022195611.mensapass-a-lmu-de", None)


async def test_the_repository_never_writes(session_factory):
    import inspect

    from edutap.data_provider import repository as module

    source = inspect.getsource(module)
    for statement in ("INSERT", "UPDATE ", "DELETE", "session.add", "commit()"):
        assert statement not in source, f"{statement} in a read-only service"
