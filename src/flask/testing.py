import typing as t
from contextlib import contextmanager
from contextlib import ExitStack
from copy import copy
from types import TracebackType
from urllib.parse import urlsplit

import werkzeug.test
from click.testing import CliRunner
from werkzeug.test import Client
from werkzeug.wrappers import Request as BaseRequest

from .cli import ScriptInfo
from .sessions import SessionMixin

if t.TYPE_CHECKING:  # pragma: no cover
    from werkzeug.test import TestResponse

    from .app import Flask


class EnvironBuilder(werkzeug.test.EnvironBuilder):
    """An :class:`~werkzeug.test.EnvironBuilder`, that takes defaults from the
    application.

    :param app: The Flask application to configure the environment from.
    :param path: URL path being requested.
    :param base_url: Base URL where the app is being served, which
        ``path`` is relative to. If not given, built from
        :data:`PREFERRED_URL_SCHEME`, ``subdomain``,
        :data:`SERVER_NAME`, and :data:`APPLICATION_ROOT`.
    :param subdomain: Subdomain name to append to :data:`SERVER_NAME`.
    :param url_scheme: Scheme to use instead of
        :data:`PREFERRED_URL_SCHEME`.
    :param json: If given, this is serialized as JSON and passed as
        ``data``. Also defaults ``content_type`` to
        ``application/json``.
    :param args: other positional arguments passed to
        :class:`~werkzeug.test.EnvironBuilder`.
    :param kwargs: other keyword arguments passed to
        :class:`~werkzeug.test.EnvironBuilder`.
    """

    def __init__(
        self,
        app: "Flask",
        path: str = "/",
        base_url: t.Optional[str] = None,
        subdomain: t.Optional[str] = None,
        url_scheme: t.Optional[str] = None,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        """
Initialize the application.

This method is called when an instance of this class is created. It takes in various parameters to configure the application's URL structure.

Parameters:
app (Flask): The Flask application instance.
path (str): The root path of the application. Defaults to "/".
base_url (Optional[str]): The base URL of the application. If provided, subdomain and url_scheme cannot be used. Defaults to None.
subdomain (Optional[str]): The subdomain of the application. If provided with a base_url, it will override the base_url. Defaults to None.
url_scheme (Optional[str]): The scheme of the URL. If not provided, it will use the preferred scheme from the Flask configuration. Defaults to None.

Returns:
None
"""
        assert not (base_url or subdomain or url_scheme) or (
            base_url is not None
        ) != bool(
            subdomain or url_scheme
        ), 'Cannot pass "subdomain" or "url_scheme" with "base_url".'

        if base_url is None:
            http_host = app.config.get("SERVER_NAME") or "localhost"
            app_root = app.config["APPLICATION_ROOT"]

            if subdomain:
                http_host = f"{subdomain}.{http_host}"

            if url_scheme is None:
                url_scheme = app.config["PREFERRED_URL_SCHEME"]

            url = urlsplit(path)
            base_url = (
                f"{url.scheme or url_scheme}://{url.netloc or http_host}"
                f"/{app_root.lstrip('/')}"
            )
            path = url.path

            if url.query:
                sep = b"?" if isinstance(url.query, bytes) else "?"
                path += sep + url.query

        self.app = app
        super().__init__(path, base_url, *args, **kwargs)

    def json_dumps(self, obj: t.Any, **kwargs: t.Any) -> str:  # type: ignore
        return self.app.json.dumps(obj, **kwargs)


class FlaskClient(Client):
    """Works like a regular Werkzeug test client but has knowledge about
    Flask's contexts to defer the cleanup of the request context until
    the end of a ``with`` block. For general information about how to
    use this class refer to :class:`werkzeug.test.Client`.

    .. versionchanged:: 0.12
       `app.test_client()` includes preset default environment, which can be
       set after instantiation of the `app.test_client()` object in
       `client.environ_base`.

    Basic usage is outlined in the :doc:`/testing` chapter.
    """

    application: "Flask"

    def __init__(self, *args: t.Any, **kwargs: t.Any) -> None:
        super().__init__(*args, **kwargs)
        self.preserve_context = False
        self._new_contexts: t.List[t.ContextManager[t.Any]] = []
        self._context_stack = ExitStack()
        self.environ_base = {
            "REMOTE_ADDR": "127.0.0.1",
            "HTTP_USER_AGENT": f"werkzeug/{werkzeug.__version__}",
        }

    @contextmanager
    def session_transaction(
        self, *args: t.Any, **kwargs: t.Any
    ) -> t.Generator[SessionMixin, None, None]:
        """
Yield a session object for the current test request context.
        # new cookie interface for Werkzeug >= 2.3
        cookie_storage = self._cookies if hasattr(self, "_cookies") else self.cookie_jar

This function is used to create and manage sessions for testing purposes.
It checks if cookies are enabled, sets up the WSGI context, opens a new session,
and saves it after use. If the session backend fails to open a session, a
RuntimeError is raised.

Args:
    *args: Variable length argument list containing any arguments passed to the test request context.
    **kwargs: Keyworded arguments for the test request context.

Returns:
    A generator yielding SessionMixin objects.
"""
        if cookie_storage is None:
            raise TypeError(
                "Cookies are disabled. Create a client with 'use_cookies=True'."
            )

        app = self.application
        ctx = app.test_request_context(*args, **kwargs)

        if hasattr(self, "_add_cookies_to_wsgi"):
            self._add_cookies_to_wsgi(ctx.request.environ)
        else:
            self.cookie_jar.inject_wsgi(ctx.request.environ)  # type: ignore[union-attr]

        with ctx:
            sess = app.session_interface.open_session(app, ctx.request)

        if sess is None:
            raise RuntimeError("Session backend did not open a session.")

        yield sess
        resp = app.response_class()

        if app.session_interface.is_null_session(sess):
            return

        with ctx:
            app.session_interface.save_session(app, sess, resp)

        if hasattr(self, "_update_cookies_from_response"):
            try:
                # Werkzeug>=2.3.3
                self._update_cookies_from_response(
                    ctx.request.host.partition(":")[0],
                    ctx.request.path,
                    resp.headers.getlist("Set-Cookie"),
                )
            except TypeError:
                # Werkzeug>=2.3.0,<2.3.3
                self._update_cookies_from_response(  # type: ignore[call-arg]
                    ctx.request.host.partition(":")[0],
                    resp.headers.getlist("Set-Cookie"),  # type: ignore[arg-type]
                )
        else:
            # Werkzeug<2.3.0
            self.cookie_jar.extract_wsgi(  # type: ignore[union-attr]
                ctx.request.environ, resp.headers
            )

    def _copy_environ(self, other):
        out = {**self.environ_base, **other}

        if self.preserve_context:
            out["werkzeug.debug.preserve_context"] = self._new_contexts.append

        return out

    def _request_from_builder_args(self, args, kwargs):
        kwargs["environ_base"] = self._copy_environ(kwargs.get("environ_base", {}))
        builder = EnvironBuilder(self.application, *args, **kwargs)

        try:
            return builder.get_request()
        finally:
            builder.close()

    def open(
        self,
        *args: t.Any,
        buffered: bool = False,
        follow_redirects: bool = False,
        **kwargs: t.Any,
    ) -> "TestResponse":
        """
Opens a new test request.

This method is used to create a new test request, which can be used to simulate HTTP requests and responses.
It takes several keyword arguments that control the behavior of the request:

- `buffered`: If True, the response will be buffered. Otherwise, it will be sent immediately.
- `follow_redirects`: If True, redirects will be followed.

If no request is provided, one will be created from the given arguments and keyword arguments.

Returns:
    TestResponse: The response object for the test request.

Raises:
    ValueError: If the request cannot be created from the given arguments and keyword arguments.
"""
        if args and isinstance(
            args[0], (werkzeug.test.EnvironBuilder, dict, BaseRequest)
        ):
            if isinstance(args[0], werkzeug.test.EnvironBuilder):
                builder = copy(args[0])
                builder.environ_base = self._copy_environ(builder.environ_base or {})
                request = builder.get_request()
            elif isinstance(args[0], dict):
                request = EnvironBuilder.from_environ(
                    args[0], app=self.application, environ_base=self._copy_environ({})
                ).get_request()
            else:
                # isinstance(args[0], BaseRequest)
                request = copy(args[0])
                request.environ = self._copy_environ(request.environ)
        else:
            # request is None
            request = self._request_from_builder_args(args, kwargs)

        # Pop any previously preserved contexts. This prevents contexts
        # from being preserved across redirects or multiple requests
        # within a single block.
        self._context_stack.close()

        response = super().open(
            request,
            buffered=buffered,
            follow_redirects=follow_redirects,
        )
        response.json_module = self.application.json  # type: ignore[assignment]

        # Re-push contexts that were preserved during the request.
        while self._new_contexts:
            cm = self._new_contexts.pop()
            self._context_stack.enter_context(cm)

        return response

    def __enter__(self) -> "FlaskClient":
        """
Enters the context of a Flask client.

This method is used to create a new context for the Flask client. It sets the `preserve_context` attribute to `True`, 
indicating that subsequent invocations will preserve the current context. If an attempt is made to nest client invocations, 
a RuntimeError is raised.

Returns:
    The instance of the FlaskClient class, allowing for method chaining.
    
Raises:
    RuntimeError: If an attempt is made to nest client invocations.
"""
        if self.preserve_context:
            raise RuntimeError("Cannot nest client invocations")
        self.preserve_context = True
        return self

    def __exit__(
        self,
        exc_type: t.Optional[type],
        exc_value: t.Optional[BaseException],
        tb: t.Optional[TracebackType],
    ) -> None:
        """
Closes the context stack and sets preserve_context to False.

This method is called when the exception handling context is exited. It ensures that the context is properly cleaned up by closing the context stack, which helps prevent resource leaks. The `preserve_context` flag is also set to False to indicate that the current context should not be preserved for future use.

Args:
    exc_type (type): The type of the exception that was raised.
    exc_value (BaseException): The value of the exception that was raised.
    tb (TracebackType): The traceback object associated with the exception.

Returns:
    None
"""
        self.preserve_context = False
        self._context_stack.close()


class FlaskCliRunner(CliRunner):
    """A :class:`~click.testing.CliRunner` for testing a Flask app's
    CLI commands. Typically created using
    :meth:`~flask.Flask.test_cli_runner`. See :ref:`testing-cli`.
    """

    def __init__(self, app: "Flask", **kwargs: t.Any) -> None:
        """
Initialize a new instance of the class.

Args:
    app (Flask): The Flask application instance.
    **kwargs (t.Any): Additional keyword arguments to pass to the superclass's __init__ method.

Returns:
    None
"""
        self.app = app
        super().__init__(**kwargs)

    def invoke(  # type: ignore
        self, cli: t.Any = None, args: t.Any = None, **kwargs: t.Any
    ) -> t.Any:
        if cli is None:
            cli = self.app.cli  # type: ignore

        if "obj" not in kwargs:
            kwargs["obj"] = ScriptInfo(create_app=lambda: self.app)

        return super().invoke(cli, args, **kwargs)
