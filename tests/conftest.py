import os
import pkgutil
import sys

import pytest
from _pytest import monkeypatch

from flask import Flask
from flask.globals import request_ctx


@pytest.fixture(scope="session", autouse=True)
def _standard_os_environ():
    mp = monkeypatch.MonkeyPatch()
    out = (
        (os.environ, "FLASK_ENV_FILE", monkeypatch.notset),
        (os.environ, "FLASK_APP", monkeypatch.notset),
        (os.environ, "FLASK_DEBUG", monkeypatch.notset),
        (os.environ, "FLASK_RUN_FROM_CLI", monkeypatch.notset),
        (os.environ, "WERKZEUG_RUN_MAIN", monkeypatch.notset),
    )

    for _, key, value in out:
        if value is monkeypatch.notset:
            mp.delenv(key, False)
        else:
            mp.setenv(key, value)

    yield out
    mp.undo()


@pytest.fixture(autouse=True)
def _reset_os_environ(monkeypatch, _standard_os_environ):
    monkeypatch._setitem.extend(_standard_os_environ)


@pytest.fixture
def app():
    app = Flask("flask_test", root_path=os.path.dirname(__file__))
    app.config.update(
        TESTING=True,
        SECRET_KEY="test key",
    )
    return app


@pytest.fixture
def app_ctx(app):
    with app.app_context() as ctx:
        yield ctx


@pytest.fixture
def req_ctx(app):
    with app.test_request_context() as ctx:
        yield ctx


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def test_apps(monkeypatch):
    monkeypatch.syspath_prepend(os.path.join(os.path.dirname(__file__), "test_apps"))
    original_modules = set(sys.modules.keys())

    yield

    # Remove any imports cached during the test. Otherwise "import app"
    # will work in the next test even though it's no longer on the path.
    for key in sys.modules.keys() - original_modules:
        sys.modules.pop(key)


@pytest.fixture(autouse=True)
def leak_detector():
    yield

    # make sure we're not leaking a request context since we are
    # testing flask internally in debug mode in a few cases
    leaks = []
    while request_ctx:
        leaks.append(request_ctx._get_current_object())
        request_ctx.pop()

    assert leaks == []


@pytest.fixture(params=(True, False))
def limit_loader(request, monkeypatch):
    if not request.param:
        return

    class LimitedLoader:
        def __init__(self, loader):
            self.loader = loader

        def __getattr__(self, name):
            if name in {"archive", "get_filename"}:
                raise AttributeError(f"Mocking a loader which does not have {name!r}.")
            return getattr(self.loader, name)

    old_get_loader = pkgutil.get_loader

    def get_loader(*args, **kwargs):
        return LimitedLoader(old_get_loader(*args, **kwargs))

    monkeypatch.setattr(pkgutil, "get_loader", get_loader)


@pytest.fixture
def modules_tmp_path(tmp_path, monkeypatch):
    rv = tmp_path / "modules_tmp"
    rv.mkdir()
    monkeypatch.syspath_prepend(os.fspath(rv))
    return rv


@pytest.fixture
def modules_tmp_path_prefix(modules_tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", os.fspath(modules_tmp_path))
    return modules_tmp_path


@pytest.fixture
def site_packages(modules_tmp_path, monkeypatch):
    py_dir = f"python{sys.version_info.major}.{sys.version_info.minor}"
    rv = modules_tmp_path / "lib" / py_dir / "site-packages"
    rv.mkdir(parents=True)
    monkeypatch.syspath_prepend(os.fspath(rv))
    return rv


@pytest.fixture
def purge_module(request):
    def inner(name):
        request.addfinalizer(lambda: sys.modules.pop(name, None))

    return inner
