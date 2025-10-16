from app.core.database import _sqlite_connect_args


def test_sqlite_connect_args_returns_thread_check_flag():
    assert _sqlite_connect_args("sqlite:///foo.db") == {"check_same_thread": False}


def test_non_sqlite_connect_args_returns_empty_dict():
    assert _sqlite_connect_args("postgresql://example") == {}
