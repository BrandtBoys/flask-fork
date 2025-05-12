import functools
import inspect
import logging
import os
import sys
import typing as t
import weakref
from datetime import timedelta
from itertools import chain
from threading import Lock
from types import TracebackType

from werkzeug.datastructures import Headers
from werkzeug.datastructures import ImmutableDict
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.exceptions import HTTPException
from werkzeug.exceptions import InternalServerError
from werkzeug.local import ContextVar
from werkzeug.routing import BuildError
from werkzeug.routing import Map
from werkzeug.routing import MapAdapter
from werkzeug.routing import RequestRedirect
from werkzeug.routing import RoutingException
from werkzeug.routing import Rule
from werkzeug.wrappers import Response as BaseResponse

from . import cli
from . import json
from .config import Config
from .config import ConfigAttribute
from .ctx import _AppCtxGlobals
from .ctx import AppContext
from .ctx import RequestContext
from .globals import _request_ctx_stack
from .globals import g
from .globals import request
from .globals import session
from .helpers import _split_blueprint_path
from .helpers import get_debug_flag
from .helpers import get_env
from .helpers import get_flashed_messages
from .helpers import get_load_dotenv
from .helpers import locked_cached_property
from .helpers import url_for
from .json import jsonify
from .logging import create_logger
from .scaffold import _endpoint_from_view_func
from .scaffold import _sentinel
from .scaffold import find_package
from .scaffold import Scaffold
from .scaffold import setupmethod
from .sessions import SecureCookieSessionInterface
from .signals import appcontext_tearing_down
from .signals import got_request_exception
from .signals import request_finished
from .signals import request_started
from .signals import request_tearing_down
from .templating import DispatchingJinjaLoader
from .templating import Environment
from .typing import AfterRequestCallable
from .typing import BeforeFirstRequestCallable
from .typing import BeforeRequestCallable
from .typing import ResponseReturnValue
from .typing import TeardownCallable
from .typing import TemplateContextProcessorCallable
from .typing import TemplateFilterCallable
from .typing import TemplateGlobalCallable
from .typing import TemplateTestCallable
from .typing import URLDefaultCallable
from .typing import URLValuePreprocessorCallable
from .wrappers import Request
from .wrappers import Response

if t.TYPE_CHECKING:
    import typing_extensions as te
    from .blueprints import Blueprint
    from .testing import FlaskClient
    from .testing import FlaskCliRunner
    from .typing import ErrorHandlerCallable

if sys.version_info >= (3, 8):
    iscoroutinefunction = inspect.iscoroutinefunction
else:

    def iscoroutinefunction(func: t.Any) -> bool:
        while inspect.ismethod(func):
            func = func.__func__

        while isinstance(func, functools.partial):
            func = func.func

        return inspect.iscoroutinefunction(func)


def _make_timedelta(value: t.Optional[timedelta]) -> t.Optional[timedelta]:
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

    #: The secure cookie uses this for the name of the session cookie.
    #:
    #: This attribute can also be configured from the config with the
    #: ``SESSION_COOKIE_NAME`` configuration key.  Defaults to ``'session'``
    session_cookie_name = ConfigAttribute("SESSION_COOKIE_NAME")

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

    #: A :class:`~datetime.timedelta` or number of seconds which is used
    #: as the default ``max_age`` for :func:`send_file`. The default is
    #: ``None``, which tells the browser to use conditional requests
    #: instead of a timed cache.
    #:
    #: Configured with the :data:`SEND_FILE_MAX_AGE_DEFAULT`
    #: configuration key.
    #:
    #: .. versionchanged:: 2.0
    #:     Defaults to ``None`` instead of 12 hours.
    send_file_max_age_default = ConfigAttribute(
        "SEND_FILE_MAX_AGE_DEFAULT", get_converter=_make_timedelta
    )

    #: Enable this if you want to use the X-Sendfile feature.  Keep in
    #: mind that the server has to support this.  This only affects files
    #: sent with the :func:`send_file` method.
    #:
    #: .. versionadded:: 0.2
    #:
    #: This attribute can also be configured from the config with the
    #: ``USE_X_SENDFILE`` configuration key.  Defaults to ``False``.
    use_x_sendfile = ConfigAttribute("USE_X_SENDFILE")

    #: The JSON encoder class to use.  Defaults to :class:`~flask.json.JSONEncoder`.
    #:
    #: .. versionadded:: 0.10
    json_encoder = json.JSONEncoder

    #: The JSON decoder class to use.  Defaults to :class:`~flask.json.JSONDecoder`.
    #:
    #: .. versionadded:: 0.10
    json_decoder = json.JSONDecoder

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
            "ENV": None,
            "DEBUG": None,
            "TESTING": False,
            "PROPAGATE_EXCEPTIONS": None,
            "PRESERVE_CONTEXT_ON_EXCEPTION": None,
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
            "JSON_AS_ASCII": True,
            "JSON_SORT_KEYS": True,
            "JSONIFY_PRETTYPRINT_REGULAR": False,
            "JSONIFY_MIMETYPE": "application/json",
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

    #: the test client that is used with when `test_client` is used.
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
    session_interface = SecureCookieSessionInterface()

    def __init__(
        self,
        import_name: str,
        static_url_path: t.Optional[str] = None,
        static_folder: t.Optional[t.Union[str, os.PathLike]] = "static",
        static_host: t.Optional[str] = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: t.Optional[str] = "templates",
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

        #: A list of functions that are called when :meth:`url_for` raises a
        #: :exc:`~werkzeug.routing.BuildError`.  Each function registered here
        #: is called with `error`, `endpoint` and `values`.  If a function
        #: returns ``None`` or raises a :exc:`BuildError` the next function is
        #: tried.
        #:
        #: .. versionadded:: 0.9
        self.url_build_error_handlers: t.List[
            t.Callable[[Exception, str, dict], str]
        ] = []

        #: A list of functions that will be called at the beginning of the
        #: first request to this instance. To register a function, use the
        #: :meth:`before_first_request` decorator.
        #:
        #: .. versionadded:: 0.8
        self.before_first_request_funcs: t.List[BeforeFirstRequestCallable] = []

        #: A list of functions that are called when the application context
        #: is destroyed.  Since the application context is also torn down
        #: if the request ends this is the place to store code that disconnects
        #: from databases.
        #:
        #: .. versionadded:: 0.9
        self.teardown_appcontext_funcs: t.List[TeardownCallable] = []

        #: A list of shell context processor functions that should be run
        #: when a shell context is created.
        #:
        #: .. versionadded:: 0.11
        self.shell_context_processors: t.List[t.Callable[[], t.Dict[str, t.Any]]] = []

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
        self._before_request_lock = Lock()

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

    def _is_setup_finished(self) -> bool:
        return self.debug and self._got_first_request

    @locked_cached_property
    def name(self) -> str:  # type: ignore
        if self.import_name == "__main__":
            fn = getattr(sys.modules["__main__"], "__file__", None)
            if fn is None:
                return "__main__"
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @property
    def propagate_exceptions(self) -> bool:
        rv = self.config["PROPAGATE_EXCEPTIONS"]
        if rv is not None:
            return rv
        return self.testing or self.debug

    @property
    def preserve_context_on_exception(self) -> bool:
        rv = self.config["PRESERVE_CONTEXT_ON_EXCEPTION"]
        if rv is not None:
            return rv
        return self.debug

    @locked_cached_property
    def logger(self) -> logging.Logger:
        return create_logger(self)

    @locked_cached_property
    def jinja_env(self) -> Environment:
        return self.create_jinja_environment()

    @property
    def got_first_request(self) -> bool:
        return self._got_first_request

    def make_config(self, instance_relative: bool = False) -> Config:
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["ENV"] = get_env()
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def auto_find_instance_path(self) -> str:
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, "instance")
        return os.path.join(prefix, "var", f"{self.name}-instance")

    def open_instance_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr]:
        return open(os.path.join(self.instance_path, resource), mode)

    @property
    def templates_auto_reload(self) -> bool:
        rv = self.config["TEMPLATES_AUTO_RELOAD"]
        return rv if rv is not None else self.debug

    @templates_auto_reload.setter
    def templates_auto_reload(self, value: bool) -> None:
        self.config["TEMPLATES_AUTO_RELOAD"] = value

    def create_jinja_environment(self) -> Environment:
        options = dict(self.jinja_options)

        if "autoescape" not in options:
            options["autoescape"] = self.select_jinja_autoescape

        if "auto_reload" not in options:
            options["auto_reload"] = self.templates_auto_reload

        rv = self.jinja_environment(self, **options)
        rv.globals.update(
            url_for=url_for,
            get_flashed_messages=get_flashed_messages,
            config=self.config,
            # request, session and g are normally added with the
            # context processor for efficiency reasons but for imported
            # templates we also want the proxies in there.
            request=request,
            session=session,
            g=g,
        )
        rv.policies["json.dumps_function"] = json.dumps
        return rv

    def create_global_jinja_loader(self) -> DispatchingJinjaLoader:
        return DispatchingJinjaLoader(self)

    def select_jinja_autoescape(self, filename: str) -> bool:
        if filename is None:
            return True
        return filename.endswith((".html", ".htm", ".xml", ".xhtml"))

    def update_template_context(self, context: dict) -> None:
        funcs: t.Iterable[
            TemplateContextProcessorCallable
        ] = self.template_context_processors[None]
        reqctx = _request_ctx_stack.top
        if reqctx is not None:
            for bp in request.blueprints:
                if bp in self.template_context_processors:
                    funcs = chain(funcs, self.template_context_processors[bp])
        orig_ctx = context.copy()
        for func in funcs:
            context.update(func())
        # make sure the original values win.  This makes it possible to
        # easier add new variables in context processors without breaking
        # existing views.
        context.update(orig_ctx)

    def make_shell_context(self) -> dict:
        rv = {"app": self, "g": g}
        for processor in self.shell_context_processors:
            rv.update(processor())
        return rv

    #: What environment the app is running in. Flask and extensions may
    #: enable behaviors based on the environment, such as enabling debug
    #: mode. This maps to the :data:`ENV` config key. This is set by the
    #: :envvar:`FLASK_ENV` environment variable and may not behave as
    #: expected if set in code.
    #:
    #: **Do not enable development when deploying in production.**
    #:
    #: Default: ``'production'``
    env = ConfigAttribute("ENV")

    @property
    def debug(self) -> bool:
        return self.config["DEBUG"]

    @debug.setter
    def debug(self, value: bool) -> None:
        self.config["DEBUG"] = value
        self.jinja_env.auto_reload = self.templates_auto_reload

    def run(
        self,
        host: t.Optional[str] = None,
        port: t.Optional[int] = None,
        debug: t.Optional[bool] = None,
        load_dotenv: bool = True,
        **options: t.Any,
    ) -> None:
        # Change this into a no-op if the server is invoked from the
        # command line. Have a look at cli.py for more information.
        if os.environ.get("FLASK_RUN_FROM_CLI") == "true":
            from .debughelpers import explain_ignored_app_run

            explain_ignored_app_run()
            return

        if get_load_dotenv(load_dotenv):
            cli.load_dotenv()

            # if set, let env vars override previous values
            if "FLASK_ENV" in os.environ:
                self.env = get_env()
                self.debug = get_debug_flag()
            elif "FLASK_DEBUG" in os.environ:
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

        cli.show_server_banner(self.env, self.debug, self.name, False)

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
            from .testing import FlaskClient as cls  # type: ignore
        return cls(  # type: ignore
            self, self.response_class, use_cookies=use_cookies, **kwargs
        )

    def test_cli_runner(self, **kwargs: t.Any) -> "FlaskCliRunner":
        cls = self.test_cli_runner_class

        if cls is None:
            from .testing import FlaskCliRunner as cls  # type: ignore

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
        view_func: t.Optional[t.Callable] = None,
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
    ) -> t.Callable[[TemplateFilterCallable], TemplateFilterCallable]:

        def decorator(f: TemplateFilterCallable) -> TemplateFilterCallable:
            self.add_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_filter(
        self, f: TemplateFilterCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.filters[name or f.__name__] = f

    @setupmethod
    def template_test(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[TemplateTestCallable], TemplateTestCallable]:

        def decorator(f: TemplateTestCallable) -> TemplateTestCallable:
            self.add_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_test(
        self, f: TemplateTestCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.tests[name or f.__name__] = f

    @setupmethod
    def template_global(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[TemplateGlobalCallable], TemplateGlobalCallable]:

        def decorator(f: TemplateGlobalCallable) -> TemplateGlobalCallable:
            self.add_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_global(
        self, f: TemplateGlobalCallable, name: t.Optional[str] = None
    ) -> None:
        self.jinja_env.globals[name or f.__name__] = f

    @setupmethod
    def before_first_request(
        self, f: BeforeFirstRequestCallable
    ) -> BeforeFirstRequestCallable:
        self.before_first_request_funcs.append(f)
        return f

    @setupmethod
    def teardown_appcontext(self, f: TeardownCallable) -> TeardownCallable:
        self.teardown_appcontext_funcs.append(f)
        return f

    @setupmethod
    def shell_context_processor(self, f: t.Callable) -> t.Callable:
        self.shell_context_processors.append(f)
        return f

    def _find_error_handler(
        self, e: Exception
    ) -> t.Optional["ErrorHandlerCallable[Exception]"]:
        exc_class, code = self._get_exc_class_and_code(type(e))

        for c in [code, None] if code is not None else [None]:
            for name in chain(request.blueprints, [None]):
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
    ) -> t.Union[HTTPException, ResponseReturnValue]:
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
    ) -> t.Union[HTTPException, ResponseReturnValue]:
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

        if self.propagate_exceptions:
            # Re-raise if called with an active exception, otherwise
            # raise the passed in exception.
            if exc_info[1] is e:
                raise

            raise e

        self.log_exception(exc_info)
        server_error: t.Union[InternalServerError, ResponseReturnValue]
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
            or request.method in ("GET", "HEAD", "OPTIONS")
        ):
            raise request.routing_exception  # type: ignore

        from .debughelpers import FormDataRoutingRedirect

        raise FormDataRoutingRedirect(request)

    def dispatch_request(self) -> ResponseReturnValue:
        req = _request_ctx_stack.top.request
        if req.routing_exception is not None:
            self.raise_routing_exception(req)
        rule = req.url_rule
        # if we provide automatic options for this URL and the
        # request came with the OPTIONS method, reply automatically
        if (
            getattr(rule, "provide_automatic_options", False)
            and req.method == "OPTIONS"
        ):
            return self.make_default_options_response()
        # otherwise dispatch to the handler for that endpoint
        return self.ensure_sync(self.view_functions[rule.endpoint])(**req.view_args)

    def full_dispatch_request(self) -> Response:
        self.try_trigger_before_first_request_functions()
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
        rv: t.Union[ResponseReturnValue, HTTPException],
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

    def try_trigger_before_first_request_functions(self) -> None:
        if self._got_first_request:
            return
        with self._before_request_lock:
            if self._got_first_request:
                return
            for func in self.before_first_request_funcs:
                self.ensure_sync(func)()
            self._got_first_request = True

    def make_default_options_response(self) -> Response:
        adapter = _request_ctx_stack.top.url_adapter
        methods = adapter.allowed_methods()
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
            )

        # Check that Werkzeug isn't using its fallback ContextVar class.
        if ContextVar.__module__ == "werkzeug.local":
            raise RuntimeError(
                "Async cannot be used with this combination of Python "
                "and Greenlet versions."
            )

        return asgiref_async_to_sync(func)

    def make_response(self, rv: ResponseReturnValue) -> Response:

        status = headers = None

        # unpack tuple returns
        if isinstance(rv, tuple):
            len_rv = len(rv)

            # a 3-tuple is unpacked directly
            if len_rv == 3:
                rv, status, headers = rv
            # decide if a 2-tuple has status or headers
            elif len_rv == 2:
                if isinstance(rv[1], (Headers, dict, tuple, list)):
                    rv, headers = rv
                else:
                    rv, status = rv
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
            if isinstance(rv, (str, bytes, bytearray)):
                # let the response class set the status and headers instead of
                # waiting to do it manually, so that the class can handle any
                # special logic
                rv = self.response_class(rv, status=status, headers=headers)
                status = headers = None
            elif isinstance(rv, dict):
                rv = jsonify(rv)
            elif isinstance(rv, BaseResponse) or callable(rv):
                # evaluate a WSGI callable, or coerce a different response
                # class to the correct type
                try:
                    rv = self.response_class.force_type(rv, request.environ)  # type: ignore  # noqa: B950
                except TypeError as e:
                    raise TypeError(
                        f"{e}\nThe view function did not return a valid"
                        " response. The return type must be a string,"
                        " dict, tuple, Response instance, or WSGI"
                        f" callable, but it was a {type(rv).__name__}."
                    ).with_traceback(sys.exc_info()[2])
            else:
                raise TypeError(
                    "The view function did not return a valid"
                    " response. The return type must be a string,"
                    " dict, tuple, Response instance, or WSGI"
                    f" callable, but it was a {type(rv).__name__}."
                )

        rv = t.cast(Response, rv)
        # prefer the status if it was provided
        if status is not None:
            if isinstance(status, (str, bytes, bytearray)):
                rv.status = status  # type: ignore
            else:
                rv.status_code = status

        # extend existing headers with provided headers
        if headers:
            rv.headers.update(headers)

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
        funcs: t.Iterable[URLDefaultCallable] = self.url_default_functions[None]

        if "." in endpoint:
            # This is called by url_for, which can be called outside a
            # request, can't use request.blueprints.
            bps = _split_blueprint_path(endpoint.rpartition(".")[0])
            bp_funcs = chain.from_iterable(self.url_default_functions[bp] for bp in bps)
            funcs = chain(funcs, bp_funcs)

        for func in funcs:
            func(endpoint, values)

    def handle_url_build_error(
        self, error: Exception, endpoint: str, values: dict
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

    def preprocess_request(self) -> t.Optional[ResponseReturnValue]:

        funcs: t.Iterable[URLValuePreprocessorCallable] = self.url_value_preprocessors[
            None
        ]
        for bp in request.blueprints:
            if bp in self.url_value_preprocessors:
                funcs = chain(funcs, self.url_value_preprocessors[bp])
        for func in funcs:
            func(request.endpoint, request.view_args)

        funcs: t.Iterable[BeforeRequestCallable] = self.before_request_funcs[None]
        for bp in request.blueprints:
            if bp in self.before_request_funcs:
                funcs = chain(funcs, self.before_request_funcs[bp])
        for func in funcs:
            rv = self.ensure_sync(func)()
            if rv is not None:
                return rv

        return None

    def process_response(self, response: Response) -> Response:
        ctx = _request_ctx_stack.top
        funcs: t.Iterable[AfterRequestCallable] = ctx._after_request_functions
        for bp in request.blueprints:
            if bp in self.after_request_funcs:
                funcs = chain(funcs, reversed(self.after_request_funcs[bp]))
        if None in self.after_request_funcs:
            funcs = chain(funcs, reversed(self.after_request_funcs[None]))
        for handler in funcs:
            response = self.ensure_sync(handler)(response)
        if not self.session_interface.is_null_session(ctx.session):
            self.session_interface.save_session(self, ctx.session, response)
        return response

    def do_teardown_request(
        self, exc: t.Optional[BaseException] = _sentinel  # type: ignore
    ) -> None:
        if exc is _sentinel:
            exc = sys.exc_info()[1]
        funcs: t.Iterable[TeardownCallable] = reversed(
            self.teardown_request_funcs[None]
        )
        for bp in request.blueprints:
            if bp in self.teardown_request_funcs:
                funcs = chain(funcs, reversed(self.teardown_request_funcs[bp]))
        for func in funcs:
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
            if self.should_ignore_error(error):
                error = None
            ctx.auto_pop(error)

    def __call__(self, environ: dict, start_response: t.Callable) -> t.Any:
        return self.wsgi_app(environ, start_response)

