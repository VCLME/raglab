import psycopg

from raglab.db.session import register_vector_if_available


def test_register_vector_if_available_ignores_missing_extension(monkeypatch):
    def fake_register_vector(_connection):
        raise psycopg.ProgrammingError("vector type not found in the database")

    monkeypatch.setattr("raglab.db.session.register_vector", fake_register_vector)

    register_vector_if_available(object())


def test_register_vector_if_available_reraises_other_programming_errors(monkeypatch):
    def fake_register_vector(_connection):
        raise psycopg.ProgrammingError("other database error")

    monkeypatch.setattr("raglab.db.session.register_vector", fake_register_vector)

    try:
        register_vector_if_available(object())
    except psycopg.ProgrammingError as exc:
        assert "other database error" in str(exc)
    else:
        raise AssertionError("Expected ProgrammingError to be re-raised")
