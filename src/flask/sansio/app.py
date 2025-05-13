from __future__ import annotations

import logging
import os
import sys
import typing as t
from datetime import timedelta
from itertools import chain

from werkzeug.exceptions import Aborter
from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import BadRequestKeyError
from werkzeug.routing import BuildError
from werkzeug.routing import Map
from werkzeug.routing import Rule
from werkzeug.sansio.response import Response
from werkzeug.utils import cached_property
from werkzeug.utils import redirect as _wz_redirect

from .. import typing as ft
from ..config import Config
from ..config import ConfigAttribute
from ..ctx import _AppCtxGlobals
from ..helpers import _split_blueprint_path
from ..helpers import get_debug_flag
from ..json.provider import DefaultJSONProvider
from ..json.provider import JSONProvider
from ..logging import create_logger
from ..templating import DispatchingJinjaLoader
from ..templating import Environment
from .scaffold import _endpoint_from_view_func
from .scaffold import find_package
from .scaffold import Scaffold
from .scaffold import setupmethod

if t.TYPE_CHECKING:  # pragma: no cover
    from werkzeug.wrappers import Response as BaseResponse
    from .blueprints import Blueprint
    from ..testing import FlaskClient
    from ..testing import FlaskCliRunner

T_shell_context_processor = t.TypeVar(
    "T_shell_context_processor", bound=ft.ShellContextProcessorCallable
)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_filter = t.TypeVar("T_template_filter", bound=ft.TemplateFilterCallable)
T_template_global = t.TypeVar("T_template_global", bound=ft.TemplateGlobalCallable)
T_template_test = t.TypeVar("T_template_test", bound=ft.TemplateTestCallable)


def _make_timedelta(value: timedelta | int | None) -> timedelta | None:
    if value is None or isinstance(value, timedelta):
        return value

    return timedelta(seconds=value)


class App(Scaffold):
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

    json_provider_class: type[JSONProvider] = DefaultJSONProvider
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
    test_client_class: type[FlaskClient] | None = None

    #: The :class:`~click.testing.CliRunner` subclass, by default
    #: :class:`~flask.testing.FlaskCliRunner` that is used by
    #: :meth:`test_cli_runner`. Its ``__init__`` method should take a
    #: Flask app object as the first argument.
    #:
    #: .. versionadded:: 1.0
    test_cli_runner_class: type[FlaskCliRunner] | None = None

    default_config: dict
    response_class: type[Response]

    def __init__(
        self,
        import_name: str,
        static_url_path: str | None = None,
        static_folder: str | os.PathLike | None = "static",
        static_host: str | None = None,
        host_matching: bool = False,
        subdomain_matching: bool = False,
        template_folder: str | os.PathLike | None = "templates",
        instance_path: str | None = None,
        instance_relative_config: bool = False,
        root_path: str | None = None,
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
        self.url_build_error_handlers: list[
            t.Callable[[Exception, str, dict[str, t.Any]], str]
        ] = []

        #: A list of functions that are called when the application context
        #: is destroyed.  Since the application context is also torn down
        #: if the request ends this is the place to store code that disconnects
        #: from databases.
        #:
        #: .. versionadded:: 0.9
        self.teardown_appcontext_funcs: list[ft.TeardownCallable] = []

        #: A list of shell context processor functions that should be run
        #: when a shell context is created.
        #:
        #: .. versionadded:: 0.11
        self.shell_context_processors: list[ft.ShellContextProcessorCallable] = []

        #: Maps registered blueprint names to blueprint objects. The
        #: dict retains the order the blueprints were registered in.
        #: Blueprints can be registered multiple times, this dict does
        #: not track how often they were attached.
        #:
        #: .. versionadded:: 0.7
        self.blueprints: dict[str, Blueprint] = {}

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
        self.url_map = self.url_map_class(host_matching=host_matching)

        self.subdomain_matching = subdomain_matching

        # tracks internally if the application already handled at least one
        # request.
        self._got_first_request = False

        # Set the name of the Click group in case someone wants to add
        # the app's commands to another CLI tool.
        self.cli.name = self.name

    def _check_setup_finished(self, f_name: str) -> None:
        """
Raises an AssertionError if the setup method has already been called on the application.

This check is performed after the first request has been handled by the application.
If the setup method is called again, any changes made will not be applied consistently.

Parameters:
    f_name (str): The name of the setup method being checked.

Returns:
    None

Raises:
    AssertionError: If the setup method has already been called on the application.
"""
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
        """
Returns the name of the current module or the main module name if running directly.

If running directly, it attempts to retrieve the filename from the `__file__` attribute of the main module.
If successful, it returns the base filename without extension. Otherwise, it returns the main module name.

Args:
    None

Returns:
    str: The name of the current module or the main module name if running directly.
"""
        if self.import_name == "__main__":
            fn = getattr(sys.modules["__main__"], "__file__", None)
            if fn is None:
                return "__main__"
            return os.path.splitext(os.path.basename(fn))[0]
        return self.import_name

    @cached_property
    def logger(self) -> logging.Logger:
        """
Returns an instance of the Logger class.

This method is used to initialize and return a new logger object. The logger object is created using the `create_logger` function, which takes the current object (`self`) as an argument.

Args:
    self: The current object.

Returns:
    logging.Logger: An instance of the Logger class.
"""
        return create_logger(self)

    @cached_property
    def jinja_env(self) -> Environment:
        """
Returns an instance of Jinja2's Environment class.

This method is a wrapper around `create_jinja_environment` and provides a more Pythonic interface for creating a new Jinja environment. The returned environment can be used to compile templates, render templates with data, and perform other template-related tasks.

Note: This method does not create a new environment instance; it simply delegates the creation to the underlying `create_jinja_environment` method.
"""
        return self.create_jinja_environment()

    def create_jinja_environment(self) -> Environment:
        raise NotImplementedError()

    def make_config(self, instance_relative: bool = False) -> Config:
        """
Creates a configuration object based on the provided parameters.

Args:
    instance_relative (bool): If True, uses the instance's path instead of the root path. Defaults to False.

Returns:
    Config: A configuration object with the specified settings.
"""
        root_path = self.root_path
        if instance_relative:
            root_path = self.instance_path
        defaults = dict(self.default_config)
        defaults["DEBUG"] = get_debug_flag()
        return self.config_class(root_path, defaults)

    def make_aborter(self) -> Aborter:
        """
Creates an instance of the Aborter class.

Returns:
    Aborter: An instance of the Aborter class.
"""
        return self.aborter_class()

    def auto_find_instance_path(self) -> str:
        prefix, package_path = find_package(self.import_name)
        if prefix is None:
            return os.path.join(package_path, "instance")
        return os.path.join(prefix, "var", f"{self.name}-instance")

        """
Opens an instance resource file.

Args:
    - `resource` (str): The path to the resource file.
    - `mode` (str, optional): The mode in which to open the file. Defaults to "rb".

Returns:
    A file object opened at the specified location with the given mode.

Raises:
    FileNotFoundError: If the instance_path does not exist or the resource is not found.
"""
        """
Creates a Jinja environment with custom options and updates its globals.

This method creates a new Jinja environment based on the provided options.
It also updates the environment's globals dictionary to include necessary functions
and variables for use in templates.

Args:
    self: The object instance that owns this method.

Returns:
    Environment: A newly created Jinja environment with custom options and updated globals.
"""
    def create_global_jinja_loader(self) -> DispatchingJinjaLoader:
        """
Creates and returns a global Jinja loader instance.

This method is used to initialize the global Jinja loader, which is then used throughout the application.
It takes no arguments and returns an instance of `DispatchingJinjaLoader`, which is responsible for dispatching template rendering tasks.

Returns:
    DispatchingJinjaLoader: A global Jinja loader instance.
"""
        return DispatchingJinjaLoader(self)

    def select_jinja_autoescape(self, filename: str) -> bool:
        """
Selects whether a Jinja autoescape should be applied to a given file.

Args:
    filename (str): The name of the file to check.

Returns:
    bool: True if the file should have autoescape applied, False otherwise.
"""
        if filename is None:
            return True
        return filename.endswith((".html", ".htm", ".xml", ".xhtml", ".svg"))

        """
Updates the template context with additional information.

This function is used to extend the context passed to a template, allowing
for dynamic rendering of templates outside of a request context. It first
checks if a request object is available and adds any blueprint names from
it to the list of names to process. Then it iterates over this list,
applying any context processors that have been registered for each name.

The original context is preserved and updated with the new values after all
context processors have been applied.

Args:
    context (dict): The initial template context.

Returns:
    None
"""
        """
Returns a dictionary representing the shell context.

This function combines the application object (`self`) with the global object (`g`), 
and then updates it with the results of each processor function in `self.shell_context_processors`.

Args:
    None

Returns:
    dict: The constructed shell context.
"""
    @property
    def debug(self) -> bool:
        """
Returns whether the debug mode is enabled based on the configuration.

Args:
    None

Returns:
    bool: True if debug mode is enabled, False otherwise
"""
        return self.config["DEBUG"]

    @debug.setter
    def debug(self, value: bool) -> None:
        """
    Sets the debug mode for the application.

    Args:
        value (bool): A boolean indicating whether to enable or disable debug mode.
    
    Returns:
        None
    
    Note:
        This function modifies the configuration of the application. It also affects the behavior of the Jinja templating engine if TEMPLATES_AUTO_RELOAD is not set.
"""
        self.config["DEBUG"] = value

        if self.config["TEMPLATES_AUTO_RELOAD"] is None:
            self.jinja_env.auto_reload = value

        """
Returns a test client instance for the application.

Args:
    use_cookies (bool): Whether to include cookies in the request. Defaults to True.
    **kwargs: Additional keyword arguments to pass to the FlaskClient constructor.

Returns:
    FlaskClient: A test client instance for the application.
"""
        """
Returns an instance of `FlaskCliRunner` initialized with the provided keyword arguments.

Args:
    **kwargs (t.Any): Keyword arguments to be passed to the `FlaskCliRunner` constructor.

Returns:
    FlaskCliRunner: An instance of `FlaskCliRunner`.

Raises:
    None
"""
    @setupmethod
    def register_blueprint(self, blueprint: Blueprint, **options: t.Any) -> None:
        """
Registers a blueprint with the current application.

Args:
    - blueprint (Blueprint): The blueprint to be registered.
    - **options (t.Any): Optional keyword arguments to be passed to the `register` method of the blueprint.

Returns:
    None
"""
        blueprint.register(self, options)

    def iter_blueprints(self) -> t.ValuesView[Blueprint]:
        """
Returns an iterator over the blueprint values.

This method provides a view of all blueprints in the system, allowing for efficient iteration and access to their attributes. The returned iterator is a `ValuesView` object, which supports various methods for filtering and manipulating the results.

Args:
    None

Returns:
    t.ValuesView[Blueprint]: An iterator over the blueprint values.
"""
        return self.blueprints.values()

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
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
        self, name: str | None = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:

        def decorator(f: T_template_filter) -> T_template_filter:
            """
Adds a template filter to the current context.

This function is a decorator that takes a template filter as an argument and adds it to the current context.
The added filter will be accessible under the specified `name` parameter.

Args:
    f (T_template_filter): The template filter to add to the context.

Returns:
    T_template_filter: The original filter, now decorated with the added functionality.

Raises:
    ValueError: If the name is not a valid identifier.
"""
            self.add_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_filter(
        self, f: ft.TemplateFilterCallable, name: str | None = None
    ) -> None:
        """
Adds a template filter to the Jinja environment.

Args:
    f (ft.TemplateFilterCallable): The filter function to add.
    name (str, optional): The name of the filter. If None, uses the function's __name__. Defaults to None.

Returns:
    None
"""
        self.jinja_env.filters[name or f.__name__] = f

    @setupmethod
    def template_test(
        self, name: str | None = None
    ) -> t.Callable[[T_template_test], T_template_test]:

       """
Template Test Decorator.

This function returns a decorator that can be used to wrap a template test function.
The wrapped function will have its `name` attribute set by the `template_test` function.

Args:
    f (Callable[[T_template_test], T_template_test]): The function to be decorated.
    name (str | None, optional): The name of the template test. Defaults to None.

Returns:
    Callable[[T_template_test], T_template_test]: The decorated function.
"""
        def decorator(f: T_template_test) -> T_template_test:
            self.add_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_test(
        self, f: ft.TemplateTestCallable, name: str | None = None
    ) -> None:
        """
Adds a template test to the Jinja environment.

Args:
    - `f`: A callable representing the template test.
    - `name` (optional): The name of the test. If not provided, it defaults to the function's name.

Returns:
    None
"""
        self.jinja_env.tests[name or f.__name__] = f

    @setupmethod
    def template_global(
        self, name: str | None = None
    ) -> t.Callable[[T_template_global], T_template_global]:

       """
Template Global Decorator

This function is used to create a template global decorator. It takes a function `f` as an argument and returns the same function wrapped with the `add_template_global` method.

The `name` parameter can be provided to specify the name of the template global. If not specified, it defaults to None.

Args:
    f (T_template_global): The function to be decorated.
    name (str | None, optional): The name of the template global. Defaults to None.

Returns:
    T_template_global: The decorated function.
"""
        def decorator(f: T_template_global) -> T_template_global:
            """
Decorates a function to add it as a template global.

Args:
    f (T_template_global): The function to be decorated.

Returns:
    T_template_global: The decorated function.
"""
            self.add_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_template_global(
        self, f: ft.TemplateGlobalCallable, name: str | None = None
    ) -> None:
        """
Adds a template global to the Jinja environment.

This method allows you to add a callable as a global variable in the Jinja environment.
The callable can be used in templates using the `{{ }}` syntax, and its name will be used as the key for the global variable.

Args:
    f (ft.TemplateGlobalCallable): The callable to add as a global variable.
    name (str | None, optional): The name of the global variable. If not provided, the name of the callable will be used. Defaults to None.

Returns:
    None
"""
        self.jinja_env.globals[name or f.__name__] = f

    @setupmethod
    def teardown_appcontext(self, f: T_teardown) -> T_teardown:
        """
Adds a teardown function to the list of teardown functions and returns the original function.

Args:
    f (T_teardown): The teardown function to be added.

Returns:
    T_teardown: The original teardown function.
"""
        self.teardown_appcontext_funcs.append(f)
        return f

    @setupmethod
    def shell_context_processor(
        self, f: T_shell_context_processor
    ) -> T_shell_context_processor:
        """
Processors for shell context.

This function is used to register a shell context processor. The processor will be executed when the shell context is processed.

Args:
    f (T_shell_context_processor): The processor to be registered.

Returns:
    T_shell_context_processor: The original processor, which has been appended to the list of shell context processors.
"""
        self.shell_context_processors.append(f)
        return f

    def _find_error_handler(
        self, e: Exception, blueprints: list[str]
    ) -> ft.ErrorHandlerCallable | None:
        """
Finds the error handler for a given exception.

This function iterates through the blueprint handlers and class-specific handlers to find a matching error handler.
If no match is found, it returns `None`.

Args:
    e (Exception): The exception for which to find an error handler.

Returns:
    ft.ErrorHandlerCallable | None: The error handler for the given exception, or `None` if no match is found.
"""
        exc_class, code = self._get_exc_class_and_code(type(e))
        names = (*blueprints, None)

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

    def trap_http_exception(self, e: Exception) -> bool:
        """
Traps HTTP exceptions based on configuration settings.

This function determines whether to trap an HTTP exception or not. It checks the `TRAP_HTTP_EXCEPTIONS` setting in the application's configuration.
If this setting is enabled, the function returns True, indicating that the exception should be trapped.

Additionally, if `TRAP_BAD_REQUEST_ERRORS` is set to None and the application is in debug mode, key errors are also trapped.

Finally, if `TRAP_BAD_REQUEST_ERRORS` is enabled, only bad request exceptions are trapped. Otherwise, no exceptions are trapped.

Args:
    e (Exception): The exception to check.

Returns:
    bool: True if the exception should be trapped, False otherwise.
"""
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

    def should_ignore_error(self, error: BaseException | None) -> bool:
        return False

    def redirect(self, location: str, code: int = 302) -> BaseResponse:
        return _wz_redirect(
            location, code=code, Response=self.response_class  # type: ignore[arg-type]
        """
Handles exceptions raised during request processing.

Raises an exception if propagation is enabled and the current exception
is different from the one passed in. Otherwise, re-raises the original
exception. If no error handler is found, logs the exception and returns a
server error response.

Args:
    e (Exception): The exception to be handled.

Returns:
    Response: A server error response.
"""
        """
Logs an exception with the provided error information.

Args:
    - `self`: The instance of the class that this method belongs to.
    - `exc_info`: A tuple containing the type, value, and traceback of the exception. Can be a single value if only one is available (e.g., for sys.exc_info()).

Returns:
    None
"""
        )
        """
Dispatches the full request and handles any exceptions that may occur.

This method initiates the request dispatching process, ensuring that all necessary steps are taken to fulfill the user's request.
It also catches any exceptions that may be raised during this process and handles them accordingly.

Returns:
    Response: The response object after successful request dispatching or exception handling.

Raises:
    Exception: If an error occurs during request dispatching or exception handling.
"""
        """
Finalizes a request by processing the response and sending a signal to indicate that the request has finished.

Args:
    rv (ft.ResponseReturnValue | HTTPException): The response value or exception to be finalized.
    from_error_handler (bool, optional): Whether this is being called from an error handler. Defaults to False.

Returns:
    Response: The finalized response object.

Raises:
    Exception: If the request finalizing fails and `from_error_handler` is False.
"""
        """
Returns a default options response for the current request.

This method creates a new response object with the allowed HTTP methods from the URL adapter.
The `allow` attribute of the response is updated to include these methods, allowing the client to specify which methods are supported by the server.

Args:
    None

Returns:
    Response: A new response object with the default options configuration.
"""
        """
Determines whether an exception should be ignored.

Args:
    error (BaseException | None): The exception to check. Can be None for no exception.
Returns:
    bool: True if the exception should be ignored, False otherwise.
"""
        """
Ensures that a provided function is synchronous by converting it to a synchronous function if it's a coroutine.

Args:
    func (t.Callable): The function to be ensured as synchronous.

Returns:
    t.Callable: The synchronous version of the input function, or the original function if it's already synchronous.
"""
        """
Converts an asynchronous function to a synchronous one.

This function takes an asynchronous callable and returns a new function that can be called synchronously.
It uses the `asgiref.sync.async_to_sync` function from Flask, which is only available when Flask is installed with the 'async' extra.

If the required import fails, it raises a RuntimeError indicating that Flask needs to be installed with the 'async' extra.

Args:
    func: The asynchronous function to convert.

Returns:
    A new synchronous function wrapping the original asynchronous one.
"""
        """
Redirects to a specified URL with an optional HTTP status code.

Args:
    location (str): The URL to redirect to.
    code (int, optional): The HTTP status code. Defaults to 302.

Returns:
    BaseResponse: A response object containing the redirect URL and status code.
"""
        """
Creates a URL adapter for the current request.

If `subdomain_matching` is disabled, uses the default subdomain in all cases.
Otherwise, does not use a subdomain. The adapter binds to the environment,
server name, and other configuration settings from the application's config.

Returns:
    MapAdapter | None: A bound URL map adapter or None if no adapter can be created.
"""

    def inject_url_defaults(self, endpoint: str, values: dict) -> None:
        names: t.Iterable[str | None] = (None,)

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
        self, error: BuildError, endpoint: str, values: dict[str, t.Any]
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

        """
Preprocesses the request by applying URL value preprocessors and before request functions.

This method iterates over the blueprint names in reverse order, applying any URL value preprocessors to each endpoint.
It then checks for any before request functions associated with the current blueprint and executes them if present.

If a before request function returns a non-None response, it is returned immediately. Otherwise, the method proceeds to check the next blueprint.

Returns:
    ft.ResponseReturnValue | None: The result of the last executed before request function, or None if no such function was found.
"""
        """
Processes the given response by executing any after-request functions and saving the session.

Args:
    response (Response): The response to be processed.

Returns:
    Response: The processed response.
"""
        """
Tear down the application context.

This function is called after the application context has been torn down. It ensures that any teardown functions are executed in a synchronous manner and sends an event to notify other parts of the application that the context is being torn down.

Args:
    exc (BaseException | None): The exception that caused the tear down, or None if no exception was raised.
        Defaults to `_sentinel` which will be replaced with the actual exception if present.

Returns:
    None
"""
        """
Returns an instance of `AppContext` initialized with the current object.

Args:
    None

Returns:
    AppContext: An instance of `AppContext` initialized with the current object.
"""
        """
Returns a new instance of RequestContext with the given environment.

Args:
    environ (dict): The current HTTP environment.

Returns:
    RequestContext: A new instance of RequestContext.
"""
        """
Tests the creation of a request context using an `EnvironBuilder`.

This function creates an instance of `EnvironBuilder` with the provided arguments,
uses it to create an environment, and then attempts to create a request context
using that environment. The `finally` block ensures the `EnvironBuilder` is properly
closed after use.

Args:
    *args: Variable number of positional arguments to pass to the `EnvironBuilder`.
    **kwargs: Keyword arguments to pass to the `EnvironBuilder`.

Returns:
    A `RequestContext` object representing the created request context.
Raises:
    Exception: If an error occurs while creating the request context.
"""
        """
WSGI Application Function

This function serves as the entry point for the WSGI application. It takes in an environment dictionary and a start response callable, 
and returns any response object generated by the application.

The function first creates a request context using `self.request_context(environ)`. It then attempts to execute the full dispatch of the request,
handling any exceptions that may occur during this process. If an exception is caught, it will be handled and propagated up the call stack.
Finally, the response object is returned to the caller.

Note: This function should not be called directly by users of the application. Instead, it should be used as part of a larger WSGI server or framework.
"""
        """
    Calls the WSGI application with the provided environment and response callback.

    Args:
        environ (dict): The HTTP request environment.
        start_response (t.Callable): A callable that takes a status code and headers as arguments.

    Returns:
        t.Any: The result of calling the WSGI application.

    Note:
        This method is part of the WSGI protocol and is used to call the WSGI application with the provided environment and response callback.
"""