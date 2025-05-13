import functools
import inspect
import logging
import os
import sys
import typing as t
import weakref
from collections.abc import Iterator as _abc_Iterator
from datetime import timedelta
from itertools import chain
from types import TracebackType

import click
from werkzeug.datastructures import Headers
from werkzeug.datastructures import ImmutableDict
from werkzeug.exceptions import Aborter
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import InternalServerError
from werkzeug.routing import BuildError
from werkzeug.routing import Map
from werkzeug.routing import MapAdapter
from werkzeug.routing import RequestRedirect
from werkzeug.routing import RoutingException
from werkzeug.routing import Rule
from werkzeug.serving import is_running_from_reloader
from werkzeug.urls import url_quote
from werkzeug.utils import cached_property
from werkzeug.utils import redirect as _wz_redirect
from werkzeug.wrappers import Response as BaseResponse

from . import cli
from . import typing as ft
from .config import Config
from .config import ConfigAttribute
from .ctx import _AppCtxGlobals
from .ctx import AppContext
from .ctx import RequestContext
from .globals import _cv_app
from .globals import _cv_request
from .globals import g
from .globals import request
from .globals import request_ctx
from .globals import session
from .helpers import _split_blueprint_path
from .helpers import get_debug_flag
from .helpers import get_flashed_messages
from .helpers import get_load_dotenv
from .json.provider import DefaultJSONProvider
from .json.provider import JSONProvider
from .logging import create_logger
from .scaffold import _endpoint_from_view_func
from .scaffold import _sentinel
from .scaffold import find_package
from .scaffold import Scaffold
from .scaffold import setupmethod
from .sessions import SecureCookieSessionInterface
from .sessions import SessionInterface
from .signals import appcontext_tearing_down
from .signals import got_request_exception
from .signals import request_finished
from .signals import request_started
from .signals import request_tearing_down
from .templating import DispatchingJinjaLoader
from .templating import Environment
from .wrappers import Request
from .wrappers import Response

if t.TYPE_CHECKING:  # pragma: no cover
    import typing_extensions as te
    from .blueprints import Blueprint
    from .testing import FlaskClient
    from .testing import FlaskCliRunner

T_shell_context_processor = t.TypeVar(
    "T_shell_context_processor", bound=ft.ShellContextProcessorCallable
)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_filter = t.TypeVar("T_template_filter", bound=ft.TemplateFilterCallable)
T_template_global = t.TypeVar("T_template_global", bound=ft.TemplateGlobalCallable)
T_template_test = t.TypeVar("T_template_test", bound=ft.TemplateTestCallable)

if sys.version_info >= (3, 8):
    iscoroutinefunction = inspect.iscoroutinefunction
else:

    def iscoroutinefunction(func: t.Any) -> bool:
        while inspect.ismethod(func):
            func = func.__func__

        while isinstance(func, functools.partial):
            func = func.func

        return inspect.iscoroutinefunction(func)


def _make_timedelta(value: t.Union[timedelta, int, None]) -> t.Optional[timedelta]:
    if value is None or isinstance(value, timedelta):
        return value

    return timedelta(seconds=value)


class Flask(Scaffold):
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an :file:`__init__.py` file inside) or a standard module (just a ``.py`` file).

    For more information about resource loading, see :func:`open_resource`.

    Usually you create a :class:`Flask` instance in your main module or
    in the :file:`__init__.py` file of your package like this::

        from flask import Flask
        app = Flask(__name__)

    .. admonition:: About the First Parameter

        The idea of the first parameter is to give Flask an idea of what
        belongs to your application.  This name is used to find resources
        on the filesystem, can be used by extensions to improve debugging
        information and a lot more.

        So it's important what you provide there.  If you are using a single
        module, `__name__` is always the correct value.  If you however are
        using a package, it's usually recommended to hardcode the name of
        your package there.

        For example if your application is defined in :file:`yourapplication/app.py`
        you should create it with one of the two versions below::

            app = Flask('yourapplication')
            app = Flask(__name__.split('.')[0])

        Why is that?  The application will work even with `__name__`, thanks
        to how resources are looked up.  However it will make debugging more
        painful.  Certain extensions can make assumptions based on the
        import name of your application.  For example the Flask-SQLAlchemy
        extension will look for the code in your application that triggered
        an SQL query in debug mode.  If the import name is not properly set
        up, that debugging information is lost.  (For example it would only
        pick up SQL queries in `yourapplication.app` and not
        `yourapplication.views.frontend`)

    .. versionadded:: 0.7
       The `static_url_path`, `static_folder`, and `template_folder`
       parameters were added.

    .. versionadded:: 0.8
       The `instance_path` and `instance_relative_config` parameters were
       added.

    .. versionadded:: 0.11
       The `root_path` parameter was added.

    .. versionadded:: 1.0
       The ``host_matching`` and ``static_host`` parameters were added.

    .. versionadded:: 1.0
       The ``subdomain_matching`` parameter was added. Subdomain
       matching needs to be enabled manually now. Setting
       :data:`SERVER_NAME` does not implicitly enable it.

    :param import_name: the name of the application package
    :param static_url_path: can be used to specify a different path for the
                            static files on the web.  Defaults to the name
                            of the `static_folder` folder.
    :param static_folder: The folder with static files that is served at
        ``static_url_path``. Relative to the application ``root_path``
        or an absolute path. Defaults to ``'static'``.
    :param static_host: the host to use when adding the static route.
        Defaults to None. Required when using ``host_matching=True``
        with a ``static_folder`` configured.
    :param host_matching: set ``url_map.host_matching`` attribute.
        Defaults to False.
    :param subdomain_matching: consider the subdomain relative to
        :data:`SERVER_NAME` when matching routes. Defaults to False.
    :param template_folder: the folder that contains the templates that should
                            be used by the application.  Defaults to
                            ``'templates'`` folder in the root path of the
                            application.
    :param instance_path: An alternative instance path for the application.
                          By default the folder ``'instance'`` next to the
                          package or module is assumed to be the instance
                          path.
    :param instance_relative_config: if set to ``True`` relative filenames
                                     for loading the config are assumed to
                                     be relative to the instance path instead
                                     of the application root.
    :param root_path: The path to the root of the application files.
        This should only be set manually when it can't be detected
        automatically, such as for namespace packages.
    """

    #: The class that is used for request objects.  See :class:`~flask.Request`
    #: for more information.
    request_class = Request

    #: The class that is used for response objects.  See
    #: :class:`~flask.Response` for more information.
    response_class = Response

    #: The class of the object assigned to :attr:`aborter`, created by
    #: :meth:`create_aborter`. That object is called by
    #: :func:`flask.abort` to raise HTTP errors, and can be
    #: called directly as well.
    #:
    #: Defaults to :class:`werkzeug.exceptions.Aborter`.
    #:
    #: .. versionadded:: 2.2
    aborter_class = Aborter

    #: The class that is used for the Jinja environment.
    #:
    #: .. versionadded:: 0.11
    jinja_environment = Environment

    #: The class that is used for the :data:`~flask.g` instance.
    #:
    #: Example use cases for a custom class:
    #:
    #: 1. Store arbitrary attributes on flask.g.
    #: 2. Add a property for lazy per-request database connectors.
    #: 3. Return None instead of AttributeError on unexpected attributes.
    #: 4. Raise exception if an unexpected attr is set, a "controlled" flask.g.
    #:
    #: In Flask 0.9 this property was called `request_globals_class` but it
    #: was changed in 0.10 to :attr:`app_ctx_globals_class` because the
    #: flask.g object is now application context scoped.
    #:
    #: .. versionadded:: 0.10
    app_ctx_globals_class = _AppCtxGlobals

    #: The class that is used for the ``config`` attribute of this app.
    #: Defaults to :class:`~flask.Config`.
    #:
    #: Example use cases for a custom class:
    #:
    #: 1. Default values for certain config options.
    #: 2. Access to config values through attributes in addition to keys.
    #:
    #: .. versionadded:: 0.11
    config_class = Config

    #: The testing flag.  Set this to ``True`` to enable the test mode of
    #: Flask extensions (and in the future probably also Flask itself).
    #: For example this might activate test helpers that have an
    #: additional runtime cost which should not be enabled by default.
    #:
    #: If this is enabled and PROPAGATE_EXCEPTIONS is not changed from the
    #: default it's implicitly enabled.
    #:
    #: This attribute can also be configured from the config with the
    #: ``TESTING`` configuration key.  Defaults to ``False``.
    testing = ConfigAttribute("TESTING")

    #: If a secret key is set, cryptographic components can use this to
    #: sign cookies and other things. Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    #:
    #: This attribute can also be configured from the config with the
    #: :data:`SECRET_KEY` configuration key. Defaults to ``None``.
    secret_key = ConfigAttribute("SECRET_KEY")

        """
Returns the name of the session cookie.

This method is deprecated and will be removed in Flask 2.3. Instead, use
`app.config['SESSION_COOKIE_NAME']`.

Args:
    None

Returns:
    str: The name of the session cookie.
"""
        """
Deprecation Notice:

The `session_cookie_name` method is deprecated and will be removed in Flask 2.3.
Use the 'SESSION_COOKIE_NAME' configuration option in 'app.config' instead.

Parameters:
value (str): The new session cookie name.

Returns:
None
"""
    #: A :class:`~datetime.timedelta` which is used to set the expiration
    #: date of a permanent session.  The default is 31 days which makes a
    #: permanent session survive for roughly one month.
    #:
    #: This attribute can also be configured from the config with the
    #: ``PERMANENT_SESSION_LIFETIME`` configuration key.  Defaults to
    #: ``timedelta(days=31)``
    permanent_session_lifetime = ConfigAttribute(
        "PERMANENT_SESSION_LIFETIME", get_converter=_make_timedelta
    )

        """
Deprecation Notice:

The `send_file_max_age_default` method is deprecated and will be removed in Flask 2.3.
Use 'SEND_FILE_MAX_AGE_DEFAULT' in 'app.config' instead.

Returns:
    Optional[timedelta]: The maximum age for sending files, or None if not set.

Raises:
    DeprecationWarning: If the deprecated method is called.

Note:
This function is only available for backwards compatibility and should not be used in new code.
"""
        """
Deprecation Notice:

The `send_file_max_age_default` method is deprecated and will be removed in Flask 2.3.
Use 'SEND_FILE_MAX_AGE_DEFAULT' in 'app.config' instead.

Parameters:
    value (Union[int, timedelta, None]): The maximum age of sent files in seconds.
        If int, the value is used directly as a number of seconds.
        If timedelta, the value is converted to seconds.
        If None, no default is set.

Returns:
    None
"""
        """
Deprecation Notice:

The `use_x_sendfile` method is deprecated and will be removed in Flask 2.3.
Instead, use the 'USE_X_SENDFILE' configuration option in the application's
configuration dictionary.

Returns:
    bool: The value of the 'USE_X_SENDFILE' configuration option.

Raises:
    DeprecationWarning: If the 'use_x_sendfile' method is called.
"""
        """
Returns the JSON encoder class for this application.

This method is deprecated in favor of customizing 'app.json_provider_class' or 'app.json'.
The `DeprecationWarning` will be raised when calling this function.
 
Args:
    None
 
Returns:
    t.Type[json.JSONEncoder]: The JSON encoder class.
"""
        """
Deprecation Warning: `json_encoder` is deprecated and will be removed in Flask 2.3.
Customize `json_provider_class` or `json` instead.

Args:
    value (t.Type[json.JSONEncoder]): The new JSON encoder class to use.

Returns:
    None
"""
        """
Returns the JSON decoder class.

This function returns the JSON decoder class used by the application. It is deprecated in favor of customizing 'app.json_provider_class' or 'app.json'. 

Parameters:
    None

Returns:
    t.Type[json.JSONDecoder]: The JSON decoder class.

Raises:
    DeprecationWarning: If 'app.json_decoder' is called, it will raise a deprecation warning.
"""
        """
Decodes JSON data using the provided decoder.

This function is deprecated in Flask 2.3 and will be removed.
Instead, customize `app.json_provider_class` or `app.json`.

Args:
    value (t.Type[json.JSONDecoder]): The JSON decoder to use.

Returns:
    None
"""
    json_provider_class: t.Type[JSONProvider] = DefaultJSONProvider
    """A subclass of :class:`~flask.json.provider.JSONProvider`. An
    instance is created and assigned to :attr:`app.json` when creating
    the app.

    The default, :class:`~flask.json.provider.DefaultJSONProvider`, uses
    Python's built-in :mod:`json` library. A different provider can use
    a different JSON library.

    .. versionadded:: 2.2
    """

    #: Options that are passed to the Jinja environment in
    #: :meth:`create_jinja_environment`. Changing these options after
    #: the environment is created (accessing :attr:`jinja_env`) will
    #: have no effect.
    #:
    #: .. versionchanged:: 1.1.0
    #:     This is a ``dict`` instead of an ``ImmutableDict`` to allow
    #:     easier configuration.
    #:
    jinja_options: dict = {}

    #: Default configuration parameters.
    default_config = ImmutableDict(
        {
            "DEBUG": None,
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": None,
            "SECRET_KEY": None,
            "PERMANENT_SESSION_LIFETIME": timedelta(days=31),
            "USE_X_SENDFILE": False,
            "SERVER_NAME": None,
            "APPLICATION_ROOT": "/",
            "SESSION_COOKIE_NAME": "session",
            "SESSION_COOKIE_DOMAIN": None,
            "SESSION_COOKIE_PATH": None,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": False,
            "SESSION_COOKIE_SAMESITE": None,
            "SESSION_REFRESH_EACH_REQUEST": True,
            "MAX_CONTENT_LENGTH": None,
            "SEND_FILE_MAX_AGE_DEFAULT": None,
            "TRAP_BAD_REQUEST_ERRORS": None,
            "TRAP_HTTP_EXCEPTIONS": False,
            "EXPLAIN_TEMPLATE_LOADING": False,
            "PREFERRED_URL_SCHEME": "http",
            "TEMPLATES_AUTO_RELOAD": None,
            "MAX_COOKIE_SIZE": 4093,
        }
    )

    #: The rule object to use for URL rules created.  This is used by
    #: :meth:`add_url_rule`.  Defaults to :class:`werkzeug.routing.Rule`.
    #:
    #: .. versionadded:: 0.7
    url_rule_class = Rule

    #: The map object to use for storing the URL rules and routing
    #: configuration parameters. Defaults to :class:`werkzeug.routing.Map`.
    #:
    #: .. versionadded:: 1.1.0
    url_map_class = Map

    #: The :meth:`test_client` method creates an instance of this test
    #: client class. Defaults to :class:`~flask.testing.FlaskClient`.
    #:
    #: .. versionadded:: 0.7
    test_client_class: t.Optional[t.Type["FlaskClient"]] = None

    #: The :class:`~click.testing.CliRunner` subclass, by default
    #: :class:`~flask.testing.FlaskCliRunner` that is used by
    #: :meth:`test_cli_runner`. Its ``__init__`` method should take a
    #: Flask app object as the first argument.
    #:
    #: .. versionadded:: 1.0
    test_cli_runner_class: t.Optional[t.Type["FlaskCliRunner"]] = None

    #: the session interface to use.  By default an instance of
    #: :class:`~flask.sessions.SecureCookieSessionInterface` is used here.
    #:
    #: .. versionadded:: 0.8
    session_interface: SessionInterface = SecureCookieSessionInterface()

    def __init__(
        self,
        import_name: str,
        static_url_path: t.Optional[str] = None,
        static_folder: t.Optional[t.Union[str, os.PathLike]] = "static",
        static_host: t.Optional[str] = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: t.Optional[t.Union[str, os.PathLike]] = "templates",
        instance_path: t.Optional[str] = None,
        instance_relative_config: bool = False,
        root_path: t.Optional[str] = None,
    ):
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        if instance_path is None:
            instance_path = self.auto_find_instance_path()
        elif not os.path.isabs(instance_path):
            raise ValueError(
                "If an instance path is provided it must be absolute."
                " A relative path was given instead."
            )

        #: Holds the path to the instance folder.
        #:
        #: .. versionadded:: 0.8
        self.instance_path = instance_path

        #: The configuration dictionary as :class:`Config`.  This behaves
        #: exactly like a regular dictionary but supports additional methods
        #: to load a config from files.
        self.config = self.make_config(instance_relative_config)

        #: An instance of :attr:`aborter_class` created by
        #: :meth:`make_aborter`. This is called by :func:`flask.abort`
        #: to raise HTTP errors, and can be called directly as well.
        #:
        #: .. versionadded:: 2.2
        #:     Moved from ``flask.abort``, which calls this object.
        self.aborter = self.make_aborter()

        self.json: JSONProvider = self.json_provider_class(self)
        """Provides access to JSON methods. Functions in ``flask.json``
        will call methods on this provider when the application context
        is active. Used for handling JSON requests and responses.

        An instance of :attr:`json_provider_class`. Can be customized by
        changing that attribute on a subclass, or by assigning to this
        attribute afterwards.

        The default, :class:`~flask.json.provider.DefaultJSONProvider`,
        uses Python's built-in :mod:`json` library. A different provider
        can use a different JSON library.

        .. versionadded:: 2.2
        """

        #: A list of functions that are called by
        #: :meth:`handle_url_build_error` when :meth:`.url_for` raises a
        #: :exc:`~werkzeug.routing.BuildError`. Each function is called
        #: with ``error``, ``endpoint`` and ``values``. If a function
        #: returns ``None`` or raises a ``BuildError``, it is skipped.
        #: Otherwise, its return value is returned by ``url_for``.
        #:
        #: .. versionadded:: 0.9
        self.url_build_error_handlers: t.List[
            t.Callable[[Exception, str, t.Dict[str, t.Any]], str]
        ] = []

        #: A list of functions that are called when the application context
        #: is destroyed.  Since the application context is also torn down
        #: if the request ends this is the place to store code that disconnects
        #: from databases.
        #:
        #: .. versionadded:: 0.9
        self.teardown_appcontext_funcs: t.List[ft.TeardownCallable] = []

        #: A list of shell context processor functions that should be run
        #: when a shell context is created.
        #:
        #: .. versionadded:: 0.11
        self.shell_context_processors: t.List[ft.ShellContextProcessorCallable] = []

        #: Maps registered blueprint names to blueprint objects. The
        #: dict retains the order the blueprints were registered in.
        #: Blueprints can be registered multiple times, this dict does
        #: not track how often they were attached.
        #:
        #: .. versionadded:: 0.7
        self.blueprints: t.Dict[str, "Blueprint"] = {}

        #: a place where extensions can store application specific state.  For
        #: example this is where an extension could store database engines and
        #: similar things.
        #:
        #: The key must match the name of the extension module. For example in
        #: case of a "Flask-Foo" extension in `flask_foo`, the key would be
        #: ``'foo'``.
        #:
        #: .. versionadded:: 0.7
        self.extensions: dict = {}

        #: The :class:`~werkzeug.routing.Map` for this instance.  You can use
        #: this to change the routing converters after the class was created
        #: but before any routes are connected.  Example::
        #:
        #:    from werkzeug.routing import BaseConverter
        #:
        #:    class ListConverter(BaseConverter):
        #:        def to_python(self, value):
        #:            return value.split(',')
        #:        def to_url(self, values):
        #:            return ','.join(super(ListConverter, self).to_url(value)
        #:                            for value in values)
        #:
        #:    app = Flask(__name__)
        #:    app.url_map.converters['list'] = ListConverter
        self.url_map = self.url_map_class()

        self.url_map.host_matching = host_matching
        self.subdomain_matching = subdomain_matching

        # tracks internally if the application already handled at least one
        # request.
        self._got_first_request = False

        # Add a static route using the provided static_url_path, static_host,
        # and static_folder if there is a configured static_folder.
        # Note we do this without checking if static_folder exists.
        # For one, it might be created while the server is running (e.g. during
        # development). Also, Google App Engine stores static files somewhere
        if self.has_static_folder:
            assert (
                bool(static_host) == host_matching
            ), "Invalid static_host/host_matching combination"
            # Use a weakref to avoid creating a reference cycle between the app
            # and the view function (see #3761).
            self_ref = weakref.ref(self)
            self.add_url_rule(
                f"{self.static_url_path}/<path:filename>",
                endpoint="static",
                host=static_host,
                view_func=lambda **kw: self_ref().send_static_file(**kw),  # type: ignore # noqa: B950
            )

        # Set the name of the Click group in case someone wants to add
        # the app's commands to another CLI tool.
        self.cli.name = self.name

    def _check_setup_finished(self, f_name: str) -> None:
        if self._got_first_request:
            raise AssertionError(
                f"The setup method '{f_name}' can no longer be called"
                " on the application. It has already handled its first"
                " request, any changes will not be applied"
                " consistently.\n"
                "Make sure all imports, decorators, functions, etc."
                " needed to set up the application are done before"
                " running it."
            )

    @cached_property
    def name(self) -> str:  # type: ignore
        if self.import_name == "__main__":
            fn = getattr(sys.modules["__main__"], "__file__", None)
            if fn is None:
                return "__main__"
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @cached_property
    def logger(self) -> logging.Logger:
        return create_logger(self)

    @cached_property
    def jinja_env(self) -> Environment:
        return self.create_jinja_environment()

    @property
    def got_first_request(self) -> bool:
        """
Propagates exceptions to the application's context.

This function checks the value of `PROPAGATE_EXCEPTIONS` in the Flask configuration.
If it exists, its value is returned. Otherwise, the function returns whether the application is running in testing or debug mode.

Deprecation Warning: This method is deprecated and will be removed in Flask 2.3. It's recommended to use a different approach for exception propagation.

Args:
    None

Returns:
    bool: Whether exceptions should be propagated to the application's context.
"""
        import warnings

        warnings.warn(
            "'got_first_request' is deprecated and will be removed in Flask 2.4.",
            DeprecationWarning,
            stacklevel=2,
        )
        """
Deprecation Notice: `got_first_request` is deprecated and will be removed in Flask 2.4.

Returns:
    bool: Whether the first request has been received.

Raises:
    DeprecationWarning: If the function is called, indicating that it should not be used.
"""
        return self._got_first_request

    def make_config(self, instance_relative: bool = False) -> Config:
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def make_aborter(self) -> Aborter:
        return self.aborter_class()

    def auto_find_instance_path(self) -> str:
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, "instance")
        return os.path.join(prefix, "var", f"{self.name}-instance")

    def open_instance_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr]:
        return open(os.path.join(self.instance_path, resource), mode)
        """
Returns the value of `TEMPLATES_AUTO_RELOAD` from the application configuration.

If `TEMPLATES_AUTO_RELOAD` is set, its value is returned. Otherwise, the value of `debug` is used as a fallback.

Deprecated since Flask 2.3 in favor of using `TEMPLATES_AUTO_RELOAD` in `app.config`.

Args:
    None

Returns:
    bool: The value of `TEMPLATES_AUTO_RELOAD` or `debug` if not set.
"""

    def create_jinja_environment(self) -> Environment:
        options = dict(self.jinja_options)

        if "autoescape" not in options:
            options["autoescape"] = self.select_jinja_autoescape

        if "auto_reload" not in options:
            auto_reload = self.config["TEMPLATES_AUTO_RELOAD"]

            if auto_reload is None:
                auto_reload = self.debug

            options["auto_reload"] = auto_reload

        rv = self.jinja_environment(self, **options)
        rv.globals.update(
            url_for=self.url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,
            # request, session and g are normally added with the
            # context processor for efficiency reasons but for imported
            # templates we also want the proxies in there.
            request=request,
            session=session,
            g=g,
        )
        rv.policies["json.dumps_function"] = self.json.dumps
        return rv

    def create_global_jinja_loader(self) -> DispatchingJinjaLoader:
        return DispatchingJinjaLoader(self)

    def select_jinja_autoescape(self, filename: str) -> bool:
        if filename is None:
            return True
        return filename.endswith((".html", ".htm", ".xml", ".xhtml", ".svg"))

    def update_template_context(self, context: dict) -> None:
        names: t.Iterable[t.Optional[str]] = (None,)

        # A template may be rendered outside a request context.
        if request:
            names = chain(names, reversed(request.blueprints))

        # The values passed to render_template take precedence. Keep a
        # copy to re-apply after all context functions.
        orig_ctx = context.copy()

        for name in names:
            if name in self.template_context_processors:
                for func in self.template_context_processors[name]:
                    context.update(func())

        context.update(orig_ctx)

    def make_shell_context(self) -> dict:
        rv = {"app": self, "g": g}
        for processor in self.shell_context_processors:
            rv.update(processor())
        return rv
        """
Returns the environment variable as a string.

Deprecation Warning: This method is deprecated and will be removed in Flask 2.3.
Use `app.debug` instead.

Args:
    None

Returns:
    str: The environment variable value.

Raises:
    DeprecationWarning: If the 'app.env' method is called.
"""
        """
Deprecation Warning: `env` method is deprecated and will be removed in Flask 2.3.
Use `debug` attribute instead.

Args:
    value (str): The environment variable to set.

Returns:
    None
"""

    @property
    def debug(self) -> bool:
        return self.config["DEBUG"]

    @debug.setter
    def debug(self, value: bool) -> None:
        self.config["DEBUG"] = value

        if self.config["TEMPLATES_AUTO_RELOAD"] is None:
            self.jinja_env.auto_reload = value

    def run(
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        debug: t.Optional[bool] = None,
        load_dotenv: bool = True,
        **options: t.Any,
    ) -> None:
        # Ignore this call so that it doesn't start another server if
        # the 'flask run' command is used.
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            if not is_running_from_reloader():
                click.secho(
                    " * Ignoring a call to 'app.run()' that would block"
                    " the current 'flask' CLI command.\n"
                    "   Only call 'app.run()' in an 'if __name__ =="
                    ' "__main__"\' guard.',
                    fg="red",
                )

            return

        if get_load_dotenv(load_dotenv):
            cli.load_dotenv()

            # if set, env var overrides existing value
            if "FLASK_DEBUG" in os.environ:
                self.debug = get_debug_flag()

        # debug passed to method overrides all other sources
        if debug is not None:
            self.debug = bool(debug)

        server_name = self.config.get("SERVER_NAME")
        sn_host = sn_port = None

        if server_name:
            sn_host, _, sn_port = server_name.partition(":")

        if not host:
            if sn_host:
                host = sn_host
            else:
                host = "127.0.0.1"

        if port or port == 0:
            port = int(port)
        elif sn_port:
            port = int(sn_port)
        else:
            port = 5000

        options.setdefault("use_reloader", self.debug)
        options.setdefault("use_debugger", self.debug)
        options.setdefault("threaded", True)

        cli.show_server_banner(self.debug, self.name)

        from werkzeug.serving import run_simple

        try:
            run_simple(t.cast(str, host), port, self, **options)
        finally:
            # reset the first request information if the development server
            # reset normally.  This makes it possible to restart the server
            # without reloader and that stuff from an interactive shell.
            self._got_first_request = False

    def test_client(self, use_cookies: bool = True, **kwargs: t.Any) -> "FlaskClient":
        cls = self.test_client_class
        if cls is None:
            from .testing import FlaskClient as cls
        return cls(  # type: ignore
            self, self.response_class, use_cookies=use_cookies, **kwargs
        )

    def test_cli_runner(self, **kwargs: t.Any) -> "FlaskCliRunner":
        cls = self.test_cli_runner_class

        if cls is None:
            from .testing import FlaskCliRunner as cls

        return cls(self, **kwargs)  # type: ignore

    @setupmethod
    def register_blueprint(self, blueprint: "Blueprint", **options: t.Any) -> None:
        blueprint.register(self, options)

    def iter_blueprints(self) -> t.ValuesView["Blueprint"]:
        return self.blueprints.values()

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: t.Optional[str] = None,
        view_func: t.Optional[ft.RouteCallable] = None,
        provide_automatic_options: t.Optional[bool] = None,
        **options: t.Any,
    ) -> None:
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)  # type: ignore
        options["endpoint"] = endpoint
        methods = options.pop("methods", None)

        # if the methods are not given and the view_func object knows its
        # methods we can use that instead.  If neither exists, we go with
        # a tuple of only ``GET`` as default.
        if methods is None:
            methods = getattr(view_func, "methods", None) or ("GET",)
        if isinstance(methods, str):
            raise TypeError(
                "Allowed methods must be a list of strings, for"
                ' example: @app.route(..., methods=["POST"])'
            )
        methods = {item.upper() for item in methods}

        # Methods that should always be added
        required_methods = set(getattr(view_func, "required_methods", ()))

        # starting with Flask 0.8 the view_func object can disable and
        # force-enable the automatic options handling.
        if provide_automatic_options is None:
            provide_automatic_options = getattr(
                view_func, "provide_automatic_options", None
            )

        if provide_automatic_options is None:
            if "OPTIONS" not in methods:
                provide_automatic_options = True
                required_methods.add("OPTIONS")
            else:
                provide_automatic_options = False

        # Add the required methods now.
        methods |= required_methods

        rule = self.url_rule_class(rule, methods=methods, **options)
        rule.provide_automatic_options = provide_automatic_options  # type: ignore

        self.url_map.add(rule)
        if view_func is not None:
            old_func = self.view_functions.get(endpoint)
            if old_func is not None and old_func != view_func:
                raise AssertionError(
                    "View function mapping is overwriting an existing"
                    f" endpoint function: {endpoint}"
                )
            self.view_functions[endpoint] = view_func

    @setupmethod
    def template_filter(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:

        def decorator(f: T_template_filter) -> T_template_filter:
            self.add_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_filter(
        self, f: ft.TemplateFilterCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.filters[name or f.__name__] = f

    @setupmethod
    def template_test(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_test], T_template_test]:

        def decorator(f: T_template_test) -> T_template_test:
            self.add_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_test(
        self, f: ft.TemplateTestCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.tests[name or f.__name__] = f

    @setupmethod
    def template_global(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_global], T_template_global]:

        def decorator(f: T_template_global) -> T_template_global:
            self.add_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_global(
        self, f: ft.TemplateGlobalCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.globals[name or f.__name__] = f
        """
Deprecation Warning: before_first_request function is deprecated and will be removed in Flask 2.3.
 
   To avoid deprecation warnings, run setup code while creating the application instead.

   Parameters:
       f (T_before_first_request): The function to be executed before the first request.

   Returns:
       T_before_first_request: The input function for appending to self.before_first_request_funcs.

   Note:
       This function is deprecated and should not be used in new applications. Instead, run setup code while creating the application.
"""

    @setupmethod
    def teardown_appcontext(self, f: T_teardown) -> T_teardown:
        self.teardown_appcontext_funcs.append(f)
        return f

    @setupmethod
    def shell_context_processor(
        self, f: T_shell_context_processor
    ) -> T_shell_context_processor:
        self.shell_context_processors.append(f)
        return f

    def _find_error_handler(self, e: Exception) -> t.Optional[ft.ErrorHandlerCallable]:
        exc_class, code = self._get_exc_class_and_code(type(e))
        names = (*request.blueprints, None)

        for c in (code, None) if code is not None else (None,):
            for name in names:
                handler_map = self.error_handler_spec[name][c]

                if not handler_map:
                    continue

                for cls in exc_class.__mro__:
                    handler = handler_map.get(cls)

                    if handler is not None:
                        return handler
        return None

    def handle_http_exception(
        self, e: HTTPException
    ) -> t.Union[HTTPException, ft.ResponseReturnValue]:
        # Proxy exceptions don't have error codes.  We want to always return
        # those unchanged as errors
        if e.code is None:
            return e

        # RoutingExceptions are used internally to trigger routing
        # actions, such as slash redirects raising RequestRedirect. They
        # are not raised or handled in user code.
        if isinstance(e, RoutingException):
            return e

        handler = self._find_error_handler(e)
        if handler is None:
            return e
        return self.ensure_sync(handler)(e)

    def trap_http_exception(self, e: Exception) -> bool:
        if self.config["TRAP_HTTP_EXCEPTIONS"]:
            return True

        trap_bad_request = self.config["TRAP_BAD_REQUEST_ERRORS"]

        # if unset, trap key errors in debug mode
        if (
            trap_bad_request is None
            and self.debug
            and isinstance(e, BadRequestKeyError)
        ):
            return True

        if trap_bad_request:
            return isinstance(e, BadRequest)

        return False

    def handle_user_exception(
        self, e: Exception
    ) -> t.Union[HTTPException, ft.ResponseReturnValue]:
        if isinstance(e, BadRequestKeyError) and (
            self.debug or self.config["TRAP_BAD_REQUEST_ERRORS"]
        ):
            e.show_exception = True

        if isinstance(e, HTTPException) and not self.trap_http_exception(e):
            return self.handle_http_exception(e)

        handler = self._find_error_handler(e)

        if handler is None:
            raise

        return self.ensure_sync(handler)(e)

    def handle_exception(self, e: Exception) -> Response:
        exc_info = sys.exc_info()
        got_request_exception.send(self, exception=e)
        propagate = self.config["PROPAGATE_EXCEPTIONS"]

        if propagate is None:
            propagate = self.testing or self.debug

        if propagate:
            # Re-raise if called with an active exception, otherwise
            # raise the passed in exception.
            if exc_info[1] is e:
                raise

            raise e

        self.log_exception(exc_info)
        server_error: t.Union[InternalServerError, ft.ResponseReturnValue]
        server_error = InternalServerError(original_exception=e)
        handler = self._find_error_handler(server_error)

        if handler is not None:
            server_error = self.ensure_sync(handler)(server_error)

        return self.finalize_request(server_error, from_error_handler=True)

    def log_exception(
        self,
        exc_info: t.Union[
            t.Tuple[type, BaseException, TracebackType], t.Tuple[None, None, None]
        ],
    ) -> None:
        self.logger.error(
            f"Exception on {request.path} [{request.method}]", exc_info=exc_info
        )

    def raise_routing_exception(self, request: Request) -> "te.NoReturn":
        if (
            not self.debug
            or not isinstance(request.routing_exception, RequestRedirect)
            or request.routing_exception.code in {307, 308}
            or request.method in {"GET", "HEAD", "OPTIONS"}
        ):
            raise request.routing_exception  # type: ignore

        from .debughelpers import FormDataRoutingRedirect

        raise FormDataRoutingRedirect(request)

    def dispatch_request(self) -> ft.ResponseReturnValue:
        req = request_ctx.request
        if req.routing_exception is not None:
            self.raise_routing_exception(req)
        rule: Rule = req.url_rule  # type: ignore[assignment]
        # if we provide automatic options for this URL and the
        # request came with the OPTIONS method, reply automatically
        if (
            getattr(rule, "provide_automatic_options", False)
            and req.method == "OPTIONS"
        ):
            return self.make_default_options_response()
        # otherwise dispatch to the handler for that endpoint
        view_args: t.Dict[str, t.Any] = req.view_args  # type: ignore[assignment]
        return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)

    def full_dispatch_request(self) -> Response:
        """
Dispatches the full request, including running before_first_request functions and handling exceptions.

This method is deprecated in favor of a more efficient implementation. It should not be used in new code.

Parameters
self : object
    The instance of the class that this method belongs to.

Returns
Response
    The response from the dispatching process.
"""
        self._got_first_request = True

        try:
            request_started.send(self)
            rv = self.preprocess_request()
            if rv is None:
                rv = self.dispatch_request()
        except Exception as e:
            rv = self.handle_user_exception(e)
        return self.finalize_request(rv)

    def finalize_request(
        self,
        rv: t.Union[ft.ResponseReturnValue, HTTPException],
        from_error_handler: bool = False,
    ) -> Response:
        response = self.make_response(rv)
        try:
            response = self.process_response(response)
            request_finished.send(self, response=response)
        except Exception:
            if not from_error_handler:
                raise
            self.logger.exception(
                "Request finalizing failed with an error while handling an error"
            )
        return response

    def make_default_options_response(self) -> Response:
        adapter = request_ctx.url_adapter
        methods = adapter.allowed_methods()  # type: ignore[union-attr]
        rv = self.response_class()
        rv.allow.update(methods)
        return rv

    def should_ignore_error(self, error: t.Optional[BaseException]) -> bool:
        return False

    def ensure_sync(self, func: t.Callable) -> t.Callable:
        if iscoroutinefunction(func):
            return self.async_to_sync(func)

        return func

    def async_to_sync(
        self, func: t.Callable[..., t.Coroutine]
    ) -> t.Callable[..., t.Any]:
        try:
            from asgiref.sync import async_to_sync as asgiref_async_to_sync
        except ImportError:
            raise RuntimeError(
                "Install Flask with the 'async' extra in order to use async views."
            ) from None

        return asgiref_async_to_sync(func)

    def url_for(
        self,
        endpoint: str,
        *,
        _anchor: t.Optional[str] = None,
        _method: t.Optional[str] = None,
        _scheme: t.Optional[str] = None,
        _external: t.Optional[bool] = None,
        **values: t.Any,
    ) -> str:
        req_ctx = _cv_request.get(None)

        if req_ctx is not None:
            url_adapter = req_ctx.url_adapter
            blueprint_name = req_ctx.request.blueprint

            # If the endpoint starts with "." and the request matches a
            # blueprint, the endpoint is relative to the blueprint.
            if endpoint[:1] == ".":
                if blueprint_name is not None:
                    endpoint = f"{blueprint_name}{endpoint}"
                else:
                    endpoint = endpoint[1:]

            # When in a request, generate a URL without scheme and
            # domain by default, unless a scheme is given.
            if _external is None:
                _external = _scheme is not None
        else:
            app_ctx = _cv_app.get(None)

            # If called by helpers.url_for, an app context is active,
            # use its url_adapter. Otherwise, app.url_for was called
            # directly, build an adapter.
            if app_ctx is not None:
                url_adapter = app_ctx.url_adapter
            else:
                url_adapter = self.create_url_adapter(None)

            if url_adapter is None:
                raise RuntimeError(
                    "Unable to build URLs outside an active request"
                    " without 'SERVER_NAME' configured. Also configure"
                    " 'APPLICATION_ROOT' and 'PREFERRED_URL_SCHEME' as"
                    " needed."
                )

            # When outside a request, generate a URL with scheme and
            # domain by default.
            if _external is None:
                _external = True

        # It is an error to set _scheme when _external=False, in order
        # to avoid accidental insecure URLs.
        if _scheme is not None and not _external:
            raise ValueError("When specifying '_scheme', '_external' must be True.")

        self.inject_url_defaults(endpoint, values)

        try:
            rv = url_adapter.build(  # type: ignore[union-attr]
                endpoint,
                values,
                method=_method,
                url_scheme=_scheme,
                force_external=_external,
            )
        except BuildError as error:
            values.update(
                _anchor=_anchor, _method=_method, _scheme=_scheme, _external=_external
            )
            return self.handle_url_build_error(error, endpoint, values)

        if _anchor is not None:
            rv = f"{rv}#{url_quote(_anchor)}"

        return rv

    def redirect(self, location: str, code: int = 302) -> BaseResponse:
        return _wz_redirect(location, code=code, Response=self.response_class)

    def make_response(self, rv: ft.ResponseReturnValue) -> Response:

        status = headers = None

        # unpack tuple returns
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # a 3-tuple is unpacked directly
            if len_rv == 3:
                rv, status, headers = rv  # type: ignore[misc]
            # decide if a 2-tuple has status or headers
            elif len_rv == 2:
                if isinstance(rv[1], (Headers, dict, tuple, list)):
                    rv, headers = rv
                else:
                    rv, status = rv  # type: ignore[assignment,misc]
            # other sized tuples are not allowed
            else:
                raise TypeError(
                    "The view function did not return a valid response tuple."
                    " The tuple must have the form (body, status, headers),"
                    " (body, status), or (body, headers)."
                )

        # the body must not be None
        if rv is None:
            raise TypeError(
                f"The view function for {request.endpoint!r} did not"
                " return a valid response. The function either returned"
                " None or ended without a return statement."
            )

        # make sure the body is an instance of the response class
        if not isinstance(rv, self.response_class):
            if isinstance(rv, (str, bytes, bytearray)) or isinstance(rv, _abc_Iterator):
                # let the response class set the status and headers instead of
                # waiting to do it manually, so that the class can handle any
                # special logic
                rv = self.response_class(
                    rv,
                    status=status,
                    headers=headers,  # type: ignore[arg-type]
                )
                status = headers = None
            elif isinstance(rv, (dict, list)):
                rv = self.json.response(rv)
            elif isinstance(rv, BaseResponse) or callable(rv):
                # evaluate a WSGI callable, or coerce a different response
                # class to the correct type
                try:
                    rv = self.response_class.force_type(
                        rv, request.environ  # type: ignore[arg-type]
                    )
                except TypeError as e:
                    raise TypeError(
                        f"{e}\nThe view function did not return a valid"
                        " response. The return type must be a string,"
                        " dict, list, tuple with headers or status,"
                        " Response instance, or WSGI callable, but it"
                        f" was a {type(rv).__name__}."
                    ).with_traceback(sys.exc_info()[2]) from None
            else:
                raise TypeError(
                    "The view function did not return a valid"
                    " response. The return type must be a string,"
                    " dict, list, tuple with headers or status,"
                    " Response instance, or WSGI callable, but it was a"
                    f" {type(rv).__name__}."
                )

        rv = t.cast(Response, rv)
        # prefer the status if it was provided
        if status is not None:
            if isinstance(status, (str, bytes, bytearray)):
                rv.status = status
            else:
                rv.status_code = status

        # extend existing headers with provided headers
        if headers:
            rv.headers.update(headers)  # type: ignore[arg-type]

        return rv

    def create_url_adapter(
        self, request: t.Optional[Request]
    ) -> t.Optional[MapAdapter]:
        if request is not None:
            # If subdomain matching is disabled (the default), use the
            # default subdomain in all cases. This should be the default
            # in Werkzeug but it currently does not have that feature.
            if not self.subdomain_matching:
                subdomain = self.url_map.default_subdomain or None
            else:
                subdomain = None

            return self.url_map.bind_to_environ(
                request.environ,
                server_name=self.config["SERVER_NAME"],
                subdomain=subdomain,
            )
        # We need at the very least the server name to be set for this
        # to work.
        if self.config["SERVER_NAME"] is not None:
            return self.url_map.bind(
                self.config["SERVER_NAME"],
                script_name=self.config["APPLICATION_ROOT"],
                url_scheme=self.config["PREFERRED_URL_SCHEME"],
            )

        return None

    def inject_url_defaults(self, endpoint: str, values: dict) -> None:
        names: t.Iterable[t.Optional[str]] = (None,)

        # url_for may be called outside a request context, parse the
        # passed endpoint instead of using request.blueprints.
        if "." in endpoint:
            names = chain(
                names, reversed(_split_blueprint_path(endpoint.rpartition(".")[0]))
            )

        for name in names:
            if name in self.url_default_functions:
                for func in self.url_default_functions[name]:
                    func(endpoint, values)

    def handle_url_build_error(
        self, error: BuildError, endpoint: str, values: t.Dict[str, t.Any]
    ) -> str:
        for handler in self.url_build_error_handlers:
            try:
                rv = handler(error, endpoint, values)
            except BuildError as e:
                # make error available outside except block
                error = e
            else:
                if rv is not None:
                    return rv

        # Re-raise if called with an active exception, otherwise raise
        # the passed in exception.
        if error is sys.exc_info()[1]:
            raise

        raise error

    def preprocess_request(self) -> t.Optional[ft.ResponseReturnValue]:
        names = (None, *reversed(request.blueprints))

        for name in names:
            if name in self.url_value_preprocessors:
                for url_func in self.url_value_preprocessors[name]:
                    url_func(request.endpoint, request.view_args)

        for name in names:
            if name in self.before_request_funcs:
                for before_func in self.before_request_funcs[name]:
                    rv = self.ensure_sync(before_func)()

                    if rv is not None:
                        return rv

        return None

    def process_response(self, response: Response) -> Response:
        ctx = request_ctx._get_current_object()  # type: ignore[attr-defined]

        for func in ctx._after_request_functions:
            response = self.ensure_sync(func)(response)

        for name in chain(request.blueprints, (None,)):
            if name in self.after_request_funcs:
                for func in reversed(self.after_request_funcs[name]):
                    response = self.ensure_sync(func)(response)

        if not self.session_interface.is_null_session(ctx.session):
            self.session_interface.save_session(self, ctx.session, response)

        return response

    def do_teardown_request(
        self, exc: t.Optional[BaseException] = _sentinel  # type: ignore
    ) -> None:
        if exc is _sentinel:
            exc = sys.exc_info()[1]

        for name in chain(request.blueprints, (None,)):
            if name in self.teardown_request_funcs:
                for func in reversed(self.teardown_request_funcs[name]):
                    self.ensure_sync(func)(exc)

        request_tearing_down.send(self, exc=exc)

    def do_teardown_appcontext(
        self, exc: t.Optional[BaseException] = _sentinel  # type: ignore
    ) -> None:
        if exc is _sentinel:
            exc = sys.exc_info()[1]

        for func in reversed(self.teardown_appcontext_funcs):
            self.ensure_sync(func)(exc)

        appcontext_tearing_down.send(self, exc=exc)

    def app_context(self) -> AppContext:
        return AppContext(self)

    def request_context(self, environ: dict) -> RequestContext:
        return RequestContext(self, environ)

    def test_request_context(self, *args: t.Any, **kwargs: t.Any) -> RequestContext:
        from .testing import EnvironBuilder

        builder = EnvironBuilder(self, *args, **kwargs)

        try:
            return self.request_context(builder.get_environ())
        finally:
            builder.close()

    def wsgi_app(self, environ: dict, start_response: t.Callable) -> t.Any:
        ctx = self.request_context(environ)
        error: t.Optional[BaseException] = None
        try:
            try:
                ctx.push()
                response = self.full_dispatch_request()
            except Exception as e:
                error = e
                response = self.handle_exception(e)
            except:  # noqa: B001
                error = sys.exc_info()[1]
                raise
            return response(environ, start_response)
        finally:
            if "werkzeug.debug.preserve_context" in environ:
                environ["werkzeug.debug.preserve_context"](_cv_app.get())
                environ["werkzeug.debug.preserve_context"](_cv_request.get())

            if error is not None and self.should_ignore_error(error):
                error = None

            ctx.pop(error)

    def __call__(self, environ: dict, start_response: t.Callable) -> t.Any:
        return self.wsgi_app(environ, start_response)
