from __future__ import annotations

import os
import typing as t
from collections import defaultdict
from functools import update_wrapper

from .. import typing as ft
from .scaffold import _endpoint_from_view_func
from .scaffold import _sentinel
from .scaffold import Scaffold
from .scaffold import setupmethod

if t.TYPE_CHECKING:  # pragma: no cover
    from .app import App

DeferredSetupFunction = t.Callable[["BlueprintSetupState"], t.Callable]
T_after_request = t.TypeVar("T_after_request", bound=ft.AfterRequestCallable)
T_before_request = t.TypeVar("T_before_request", bound=ft.BeforeRequestCallable)
T_error_handler = t.TypeVar("T_error_handler", bound=ft.ErrorHandlerCallable)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_context_processor = t.TypeVar(
    "T_template_context_processor", bound=ft.TemplateContextProcessorCallable
)
T_template_filter = t.TypeVar("T_template_filter", bound=ft.TemplateFilterCallable)
T_template_global = t.TypeVar("T_template_global", bound=ft.TemplateGlobalCallable)
T_template_test = t.TypeVar("T_template_test", bound=ft.TemplateTestCallable)
T_url_defaults = t.TypeVar("T_url_defaults", bound=ft.URLDefaultCallable)
T_url_value_preprocessor = t.TypeVar(
    "T_url_value_preprocessor", bound=ft.URLValuePreprocessorCallable
)


class BlueprintSetupState:
    """Temporary holder object for registering a blueprint with the
    application.  An instance of this class is created by the
    :meth:`~flask.Blueprint.make_setup_state` method and later passed
    to all register callback functions.
    """

    def __init__(
        self,
        blueprint: Blueprint,
        app: App,
        options: t.Any,
        first_registration: bool,
    ) -> None:
        #: a reference to the current application
        self.app = app

        #: a reference to the blueprint that created this setup state.
        self.blueprint = blueprint

        #: a dictionary with all options that were passed to the
        #: :meth:`~flask.Flask.register_blueprint` method.
        self.options = options

        #: as blueprints can be registered multiple times with the
        #: application and not everything wants to be registered
        #: multiple times on it, this attribute can be used to figure
        #: out if the blueprint was registered in the past already.
        self.first_registration = first_registration

        subdomain = self.options.get("subdomain")
        if subdomain is None:
            subdomain = self.blueprint.subdomain

        #: The subdomain that the blueprint should be active for, ``None``
        #: otherwise.
        self.subdomain = subdomain

        url_prefix = self.options.get("url_prefix")
        if url_prefix is None:
            url_prefix = self.blueprint.url_prefix
        #: The prefix that should be used for all URLs defined on the
        #: blueprint.
        self.url_prefix = url_prefix

        self.name = self.options.get("name", blueprint.name)
        self.name_prefix = self.options.get("name_prefix", "")

        #: A dictionary with URL defaults that is added to each and every
        #: URL that was defined with the blueprint.
        self.url_defaults = dict(self.blueprint.url_values_defaults)
        self.url_defaults.update(self.options.get("url_defaults", ()))

    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: t.Callable | None = None,
        **options: t.Any,
    ) -> None:
        """
Adds a URL rule to the application.

Parameters:
    rule (str): The URL pattern.
    endpoint (str | None, optional): The endpoint name. Defaults to None.
    view_func (t.Callable | None, optional): The view function. Defaults to None.
    **options (t.Any): Additional options for the URL rule.

Returns:
    None
"""
        if self.url_prefix is not None:
            if rule:
                rule = "/".join((self.url_prefix.rstrip("/"), rule.lstrip("/")))
            else:
                rule = self.url_prefix
        options.setdefault("subdomain", self.subdomain)
        if endpoint is None:
            endpoint = _endpoint_from_view_func(view_func)  # type: ignore
        defaults = self.url_defaults
        if "defaults" in options:
            defaults = dict(defaults, **options.pop("defaults"))

        self.app.add_url_rule(
            rule,
            f"{self.name_prefix}.{self.name}.{endpoint}".lstrip("."),
            view_func,
            defaults=defaults,
            **options,
        )


class Blueprint(Scaffold):
    """Represents a blueprint, a collection of routes and other
    app-related functions that can be registered on a real application
    later.

    A blueprint is an object that allows defining application functions
    without requiring an application object ahead of time. It uses the
    same decorators as :class:`~flask.Flask`, but defers the need for an
    application by recording them for later registration.

    Decorating a function with a blueprint creates a deferred function
    that is called with :class:`~flask.blueprints.BlueprintSetupState`
    when the blueprint is registered on an application.

    See :doc:`/blueprints` for more information.

    :param name: The name of the blueprint. Will be prepended to each
        endpoint name.
    :param import_name: The name of the blueprint package, usually
        ``__name__``. This helps locate the ``root_path`` for the
        blueprint.
    :param static_folder: A folder with static files that should be
        served by the blueprint's static route. The path is relative to
        the blueprint's root path. Blueprint static files are disabled
        by default.
    :param static_url_path: The url to serve static files from.
        Defaults to ``static_folder``. If the blueprint does not have
        a ``url_prefix``, the app's static route will take precedence,
        and the blueprint's static files won't be accessible.
    :param template_folder: A folder with templates that should be added
        to the app's template search path. The path is relative to the
        blueprint's root path. Blueprint templates are disabled by
        default. Blueprint templates have a lower precedence than those
        in the app's templates folder.
    :param url_prefix: A path to prepend to all of the blueprint's URLs,
        to make them distinct from the rest of the app's routes.
    :param subdomain: A subdomain that blueprint routes will match on by
        default.
    :param url_defaults: A dict of default values that blueprint routes
        will receive by default.
    :param root_path: By default, the blueprint will automatically set
        this based on ``import_name``. In certain situations this
        automatic detection can fail, so the path can be specified
        manually instead.

    .. versionchanged:: 1.1.0
        Blueprints have a ``cli`` group to register nested CLI commands.
        The ``cli_group`` parameter controls the name of the group under
        the ``flask`` command.

    .. versionadded:: 0.7
    """

    _got_registered_once = False

    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder: str | os.PathLike | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike | None = None,
        url_prefix: str | None = None,
        subdomain: str | None = None,
        url_defaults: dict | None = None,
        root_path: str | None = None,
        cli_group: str | None = _sentinel,  # type: ignore
    ):
        """
Initialize a Flask Blueprint.

This function initializes a new Flask Blueprint with the given parameters. It sets up the blueprint's metadata and configuration options.

Parameters:
    name (str): The name of the blueprint.
    import_name (str): The import name of the blueprint.
    static_folder (str | os.PathLike | None, optional): The folder containing static files. Defaults to None.
    static_url_path (str | None, optional): The URL path for static files. Defaults to None.
    template_folder (str | os.PathLike | None, optional): The folder containing templates. Defaults to None.
    url_prefix (str | None, optional): The prefix for URLs. Defaults to None.
    subdomain (str | None, optional): The subdomain for the blueprint. Defaults to None.
    url_defaults (dict | None, optional): Default values for URL parameters. Defaults to None.
    root_path (str | None, optional): The root path of the blueprint. Defaults to None.
    cli_group (str | None, optional): The CLI group for the blueprint. Defaults to _sentinel.

Raises:
    ValueError: If 'name' is empty or contains a dot '.' character.

Attributes:
    name (str): The name of the blueprint.
    url_prefix (str): The prefix for URLs.
    subdomain (str): The subdomain for the blueprint.
    deferred_functions (list[DeferredSetupFunction]): A list of deferred setup functions.
    url_values_defaults (dict): Default values for URL parameters.
    cli_group (str): The CLI group for the blueprint.
    _blueprints (list[tuple[Blueprint, dict]]): A list of blueprints and their configurations.

"""
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        if not name:
            raise ValueError("'name' may not be empty.")

        if "." in name:
            raise ValueError("'name' may not contain a dot '.' character.")

        self.name = name
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.deferred_functions: list[DeferredSetupFunction] = []

        if url_defaults is None:
            url_defaults = {}

        self.url_values_defaults = url_defaults
        self.cli_group = cli_group
        self._blueprints: list[tuple[Blueprint, dict]] = []

    def _check_setup_finished(self, f_name: str) -> None:
        """
Raises an AssertionError if the setup method has already been registered.

If the setup method has been called at least once, this function will raise
an AssertionError with a message indicating that further calls to the setup
method will not be applied consistently. This is intended to prevent changes
to imports, decorators, functions, etc. from being made after registration.

Args:
    f_name (str): The name of the setup method that was called.

Raises:
    AssertionError: If the setup method has already been registered.
"""
        if self._got_registered_once:
            raise AssertionError(
                f"The setup method '{f_name}' can no longer be called on the blueprint"
                f" '{self.name}'. It has already been registered at least once, any"
                " changes will not be applied consistently.\n"
                "Make sure all imports, decorators, functions, etc. needed to set up"
                " the blueprint are done before registering it."
            )

    @setupmethod
    def record(self, func: t.Callable) -> None:
        self.deferred_functions.append(func)

    @setupmethod
    def record_once(self, func: t.Callable) -> None:

       """
Records a function to be executed once during the first registration of a blueprint.

This method is used to register a function that should only be executed during the initial setup of a blueprint.
The function will be called when the blueprint's first registration occurs.

Args:
    func (t.Callable): The function to be recorded and executed.

Returns:
    None
"""
        def wrapper(state: BlueprintSetupState) -> None:
            """
Wrapper function to handle first registration of users.

This function checks if the user has registered for the first time and calls the `func` function with the provided `state` object if so.

Args:
    state (BlueprintSetupState): The current state of the application setup.

Returns:
    None
"""
            if state.first_registration:
                func(state)

        self.record(update_wrapper(wrapper, func))

    def make_setup_state(
        self, app: App, options: dict, first_registration: bool = False
    ) -> BlueprintSetupState:
        """
Creates a new setup state for the given application.

Args:
    - `app`: The Flask application instance.
    - `options`: A dictionary of configuration options.
    - `first_registration` (optional): Whether this is the first registration. Defaults to False.

Returns:
    A BlueprintSetupState object representing the created setup state.

Raises:
    None
"""
        return BlueprintSetupState(self, app, options, first_registration)

    @setupmethod
    def register_blueprint(self, blueprint: Blueprint, **options: t.Any) -> None:
        """
Registers a blueprint with the current instance.

Args:
    - blueprint (Blueprint): The blueprint to be registered.
    - **options (t.Any): Optional keyword arguments for the blueprint registration.

Raises:
    ValueError: If the provided blueprint is the same as the current instance.

Returns:
    None
"""
        if blueprint is self:
            raise ValueError("Cannot register a blueprint on itself")
        self._blueprints.append((blueprint, options))

    def register(self, app: App, options: dict) -> None:
        name_prefix = options.get("name_prefix", "")
        self_name = options.get("name", self.name)
        name = f"{name_prefix}.{self_name}".lstrip(".")

        if name in app.blueprints:
            bp_desc = "this" if app.blueprints[name] is self else "a different"
            existing_at = f" '{name}'" if self_name != name else ""

            raise ValueError(
                f"The name '{self_name}' is already registered for"
                f" {bp_desc} blueprint{existing_at}. Use 'name=' to"
                f" provide a unique name."
            )

        first_bp_registration = not any(bp is self for bp in app.blueprints.values())
        first_name_registration = name not in app.blueprints

        app.blueprints[name] = self
        self._got_registered_once = True
        state = self.make_setup_state(app, options, first_bp_registration)

        if self.has_static_folder:
            state.add_url_rule(
                f"{self.static_url_path}/<path:filename>",
                view_func=self.send_static_file,  # type: ignore[attr-defined]
                endpoint="static",
            )

        # Merge blueprint data into parent.
        if first_bp_registration or first_name_registration:
            self._merge_blueprint_funcs(app, name)
                """
Extends a dictionary with another dictionary's values.

This function takes two dictionaries as input: `bp_dict` and `parent_dict`. It iterates over the items in `bp_dict`, 
constructs new keys by appending the current key to the parent dictionary's name if it exists, and extends the 
values of the corresponding item in `parent_dict`.

Args:
    bp_dict (dict): The dictionary containing values to be extended.
    parent_dict (dict): The dictionary whose values will be extended.

Returns:
    None
"""

        for deferred in self.deferred_functions:
            deferred(state)

        cli_resolved_group = options.get("cli_group", self.cli_group)

        if self.cli.commands:
            if cli_resolved_group is None:
                app.cli.commands.update(self.cli.commands)
            elif cli_resolved_group is _sentinel:
                self.cli.name = name
                app.cli.add_command(self.cli)
            else:
                self.cli.name = cli_resolved_group
                app.cli.add_command(self.cli)

        for blueprint, bp_options in self._blueprints:
            bp_options = bp_options.copy()
            bp_url_prefix = bp_options.get("url_prefix")
            bp_subdomain = bp_options.get("subdomain")

            if bp_subdomain is None:
                bp_subdomain = blueprint.subdomain

            if state.subdomain is not None and bp_subdomain is not None:
                bp_options["subdomain"] = bp_subdomain + "." + state.subdomain
            elif bp_subdomain is not None:
                bp_options["subdomain"] = bp_subdomain
            elif state.subdomain is not None:
                bp_options["subdomain"] = state.subdomain

            if bp_url_prefix is None:
                bp_url_prefix = blueprint.url_prefix

            if state.url_prefix is not None and bp_url_prefix is not None:
                bp_options["url_prefix"] = (
                    state.url_prefix.rstrip("/") + "/" + bp_url_prefix.lstrip("/")
                )
            elif bp_url_prefix is not None:
                bp_options["url_prefix"] = bp_url_prefix
            elif state.url_prefix is not None:
                bp_options["url_prefix"] = state.url_prefix

            bp_options["name_prefix"] = name
            blueprint.register(app, bp_options)

    def _merge_blueprint_funcs(self, app: App, name: str) -> None:
        def extend(bp_dict, parent_dict):
            for key, values in bp_dict.items():
                key = name if key is None else f"{name}.{key}"
                parent_dict[key].extend(values)

        for key, value in self.error_handler_spec.items():
            key = name if key is None else f"{name}.{key}"
            value = defaultdict(
                dict,
                {
                    code: {exc_class: func for exc_class, func in code_values.items()}
                    for code, code_values in value.items()
                },
            )
            app.error_handler_spec[key] = value

        for endpoint, func in self.view_functions.items():
            app.view_functions[endpoint] = func

        extend(self.before_request_funcs, app.before_request_funcs)
        extend(self.after_request_funcs, app.after_request_funcs)
        extend(
            self.teardown_request_funcs,
            app.teardown_request_funcs,
        )
        extend(self.url_default_functions, app.url_default_functions)
        extend(self.url_value_preprocessors, app.url_value_preprocessors)
        extend(self.template_context_processors, app.template_context_processors)

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        """
Adds a URL rule to the application.

This method is used to register a new route for the application. It takes in several parameters:

- `rule`: The path of the URL rule.
- `endpoint`: The name of the endpoint associated with this URL rule (optional).
- `view_func`: The view function that will handle requests to this URL rule (optional).
- `provide_automatic_options`: A boolean indicating whether to provide automatic options for this URL rule (optional).
- `**options`: Any additional keyword arguments to pass to the `add_url_rule` method of the view function.

If either the `endpoint` or `view_func.__name__` contains a dot ('.'), a ValueError is raised. The `record` method is then called with a closure that adds this URL rule to the application.

Returns:
    None
"""
        if endpoint and "." in endpoint:
            raise ValueError("'endpoint' may not contain a dot '.' character.")

        if view_func and hasattr(view_func, "__name__") and "." in view_func.__name__:
            raise ValueError("'view_func' name may not contain a dot '.' character.")

        self.record(
            lambda s: s.add_url_rule(
                rule,
                endpoint,
                view_func,
                provide_automatic_options=provide_automatic_options,
                **options,
            )
        )

    @setupmethod
    def app_template_filter(
        self, name: str | None = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:

        def decorator(f: T_template_filter) -> T_template_filter:
            self.add_app_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_filter(
        self, f: ft.TemplateFilterCallable, name: str | None = None
    ) -> None:

       """
Adds a template filter to the application's Jinja environment.

This function registers a new template filter with the given name, which can be used in templates to perform custom operations. If no name is provided, the filter will be registered under its original name (i.e., the name of the `f` function).

Args:
    f: A callable that implements the template filter functionality.
    name: The name under which the filter should be registered (optional). Defaults to None.

Returns:
    None
"""
        def register_template(state: BlueprintSetupState) -> None:
            """
Registers a Jinja2 filter with the given application state.

Args:
    state (BlueprintSetupState): The application state to modify.

Returns:
    None
"""
            state.app.jinja_env.filters[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def app_template_test(
        self, name: str | None = None
    ) -> t.Callable[[T_template_test], T_template_test]:

       """
Decorates a function with the `app_template_test` metadata.

This decorator adds an application template test to the decorated function.
It takes an optional `name` parameter to specify the test name.

Args:
    f (Callable): The function to be decorated.
    name (str, optional): The name of the test. Defaults to None.

Returns:
    Callable: The decorated function with added metadata.
"""
        def decorator(f: T_template_test) -> T_template_test:
            """
Decorates a test function with an application template test.

This function takes a test function `f` as input and adds it to the list of 
application template tests. The decorated function is then returned.

Args:
    f (T_template_test): The test function to be decorated.

Returns:
    T_template_test: The decorated test function.
"""
            self.add_app_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_test(
        self, f: ft.TemplateTestCallable, name: str | None = None
    ) -> None:

       """
Adds a template test to the application's Jinja environment.

This function registers a template test with the given name (defaulting to the test function's name if not provided).

Args:
    f (ft.TemplateTestCallable): The test function to register.
    name (str | None, optional): The name of the test. Defaults to None.

Returns:
    None
"""
        def register_template(state: BlueprintSetupState) -> None:
            """
Registers a Jinja template test in the application's setup state.

Args:
    state (BlueprintSetupState): The current state of the application's setup.
    
Returns:
    None: This function does not return any value. It modifies the provided BlueprintSetupState object directly.
"""
            state.app.jinja_env.tests[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def app_template_global(
        self, name: str | None = None
    ) -> t.Callable[[T_template_global], T_template_global]:

       """
Decorates a function to make it available as an application template global.

This decorator adds the decorated function to the list of application template globals.
It is typically used in conjunction with the `add_app_template_global` method.

Args:
    name (str | None): The name under which the decorated function should be added. If None, no name will be specified.

Returns:
    T_template_global: A decorator function that adds the decorated function to the list of application template globals.
"""
        def decorator(f: T_template_global) -> T_template_global:
            """
Adds the provided function as a template global for the application.

Args:
    f (T_template_global): The function to be added as a template global.

Returns:
    T_template_global: The decorated function.
"""
            self.add_app_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_global(
        self, f: ft.TemplateGlobalCallable, name: str | None = None
    ) -> None:

       """
Adds a template global to the application.

This function registers a template global with the given name. If no name is provided, it defaults to the name of the provided callable.

Args:
    f (ft.TemplateGlobalCallable): The callable to register as a template global.
    name (str | None, optional): The name of the template global. Defaults to None.

Returns:
    None
"""
        def register_template(state: BlueprintSetupState) -> None:
            """
Registers a template as a global variable in the Jinja environment.

Args:
    state (BlueprintSetupState): The current setup state of the application.
    
Returns:
    None
    
Raises:
    TypeError: If `state` is not an instance of BlueprintSetupState.
"""
            state.app.jinja_env.globals[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def before_app_request(self, f: T_before_request) -> T_before_request:
        """
Records a function to be executed before the application request.

Args:
    f (T_before_request): The function to be recorded.

Returns:
    T_before_request: The input function with the record added.
"""
        self.record_once(
            lambda s: s.app.before_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def after_app_request(self, f: T_after_request) -> T_after_request:
        """
Records a function as an 'after-app-request' hook.

Args:
    f (T_after_request): The function to be recorded.

Returns:
    T_after_request: The input function.
"""
        self.record_once(
            lambda s: s.app.after_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def teardown_app_request(self, f: T_teardown) -> T_teardown:
        """
Records a teardown request function for the current application context.

Args:
    f (T_teardown): The teardown request function to be recorded.

Returns:
    T_teardown: The original teardown request function.
"""
        self.record_once(
            lambda s: s.app.teardown_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_context_processor(
        self, f: T_template_context_processor
    ) -> T_template_context_processor:
        """
Processes the template context for an application.

This function is used to add a new template context processor to the existing list.
It ensures that the processor is added only once by using the `record_once` method.

Args:
    f (T_template_context_processor): The template context processor to be added.

Returns:
    T_template_context_processor: The original template context processor, which has been modified in-place.
"""
        self.record_once(
            lambda s: s.app.template_context_processors.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_errorhandler(
        self, code: type[Exception] | int
    ) -> t.Callable[[T_error_handler], T_error_handler]:

       """
App Error Handler Decorator.

This function returns a decorator that can be used to handle application errors.
The decorator takes an error handling function as input and wraps it with the provided app error handler.

Args:
    code (type[Exception] | int): The type of exception or error code to use for error handling.
    f (T_error_handler): The error handling function to wrap.

Returns:
    T_error_handler: The wrapped error handling function.

Example:
    @app_errorhandler(404)
    def handle_404(f):
        # Handle 404 errors
        pass

    @app_errorhandler(Exception)
    def handle_all_errors(f):
        # Handle all exceptions
        pass
"""
        def decorator(f: T_error_handler) -> T_error_handler:
            """
Decorates a function with error handling.

This decorator records the first occurrence of an exception and uses it to update the application's error handler.

Args:
    f (function): The function to be decorated.

Returns:
    function: The decorated function.
"""
            self.record_once(lambda s: s.app.errorhandler(code)(f))
            return f

        return decorator

    @setupmethod
    def app_url_value_preprocessor(
        self, f: T_url_value_preprocessor
    ) -> T_url_value_preprocessor:
        """
Preprocesses the given URL value preprocessor and records it in the application's internal state.

Args:
    f (T_url_value_preprocessor): The URL value preprocessor to be recorded.

Returns:
    T_url_value_preprocessor: The original preprocessor, which has been marked as recorded.
"""
        self.record_once(
            lambda s: s.app.url_value_preprocessors.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_url_defaults(self, f: T_url_defaults) -> T_url_defaults:
        """
Returns a URL default function and records it in the `url_default_functions` set.

Args:
    f (T_url_defaults): The URL default function to be returned.

Returns:
    T_url_defaults: The provided URL default function.
"""
        self.record_once(
            lambda s: s.app.url_default_functions.setdefault(None, []).append(f)
        )
        return f
