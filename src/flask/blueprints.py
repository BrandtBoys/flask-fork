import json
import os
import typing as t
from collections import defaultdict
from functools import update_wrapper

from . import typing as ft
from .scaffold import _endpoint_from_view_func
from .scaffold import _sentinel
from .scaffold import Scaffold
from .scaffold import setupmethod

if t.TYPE_CHECKING:  # pragma: no cover
    from .app import Flask

DeferredSetupFunction = t.Callable[["BlueprintSetupState"], t.Callable]
T_after_request = t.TypeVar("T_after_request", bound=ft.AfterRequestCallable)
T_before_first_request = t.TypeVar(
    "T_before_first_request", bound=ft.BeforeFirstRequestCallable
)
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
        blueprint: "Blueprint",
        app: "Flask",
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
        endpoint: t.Optional[str] = None,
        view_func: t.Optional[t.Callable] = None,
        **options: t.Any,
    ) -> None:
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

    _json_encoder: t.Union[t.Type[json.JSONEncoder], None] = None
    _json_decoder: t.Union[t.Type[json.JSONDecoder], None] = None

    @property
    def json_encoder(
        self,
    ) -> t.Union[t.Type[json.JSONEncoder], None]:
        """
Returns the JSON encoder class, deprecation warning if applicable.

This function is deprecated and will be removed in Flask 2.3. It's recommended to customize 'app.json_provider_class' or 'app.json' instead.

Args:
    None

Returns:
    t.Union[t.Type[json.JSONEncoder], None]: The JSON encoder class or None.
"""
        import warnings

        warnings.warn(
            "'bp.json_encoder' is deprecated and will be removed in Flask 2.3."
            " Customize 'app.json_provider_class' or 'app.json' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._json_encoder

    @json_encoder.setter
    def json_encoder(self, value: t.Union[t.Type[json.JSONEncoder], None]) -> None:
        """
Deprecation Warning: json_encoder function is deprecated and will be removed in Flask 2.3.
 
To customize the JSON encoding behavior, use either 'app.json_provider_class' or 'app.json' instead.

Args:
    value (Union[Type[JSONEncoder], None]): The JSON encoder class to use. Defaults to None.

Returns:
    None
"""
        import warnings

        warnings.warn(
            "'bp.json_encoder' is deprecated and will be removed in Flask 2.3."
            " Customize 'app.json_provider_class' or 'app.json' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._json_encoder = value

    @property
    def json_decoder(
        self,
    ) -> t.Union[t.Type[json.JSONDecoder], None]:
        import warnings

        warnings.warn(
            "'bp.json_decoder' is deprecated and will be removed in Flask 2.3."
            " Customize 'app.json_provider_class' or 'app.json' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self._json_decoder

    @json_decoder.setter
    def json_decoder(self, value: t.Union[t.Type[json.JSONDecoder], None]) -> None:
        """
Decodes JSON values.

This function is deprecated and will be removed in Flask 2.3.
Instead, customize `app.json_provider_class` or `app.json`.

Args:
    value (t.Union[t.Type[json.JSONDecoder], None]): The JSON decoder to use.

Returns:
    None
"""
        import warnings

        warnings.warn(
            "'bp.json_decoder' is deprecated and will be removed in Flask 2.3."
            " Customize 'app.json_provider_class' or 'app.json' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._json_decoder = value

    def __init__(
        self,
        name: str,
        import_name: str,
        static_folder: t.Optional[t.Union[str, os.PathLike]] = None,
        static_url_path: t.Optional[str] = None,
        template_folder: t.Optional[t.Union[str, os.PathLike]] = None,
        url_prefix: t.Optional[str] = None,
        subdomain: t.Optional[str] = None,
        url_defaults: t.Optional[dict] = None,
        root_path: t.Optional[str] = None,
        cli_group: t.Optional[str] = _sentinel,  # type: ignore
    ):
        """
Initialize a new instance of the class.

Parameters:
    name (str): The name of the application or module.
    import_name (str): The import name of the application or module.
    static_folder (t.Optional[t.Union[str, os.PathLike]], optional): The path to the static folder. Defaults to None.
    static_url_path (t.Optional[str], optional): The URL path for static files. Defaults to None.
    template_folder (t.Optional[t.Union[str, os.PathLike]], optional): The path to the template folder. Defaults to None.
    url_prefix (t.Optional[str], optional): The prefix for URLs. Defaults to None.
    subdomain (t.Optional[str], optional): The subdomain for URLs. Defaults to None.
    url_defaults (t.Optional[dict], optional): Default values for URL parameters. Defaults to None.
    root_path (t.Optional[str], optional): The root path of the application or module. Defaults to None.
    cli_group (t.Optional[str], optional): The CLI group name. Defaults to _sentinel.

Raises:
    ValueError: If 'name' is empty or contains a dot '.' character.

Attributes:
    name (str): The name of the application or module.
    url_prefix (str): The prefix for URLs.
    subdomain (str): The subdomain for URLs.
    deferred_functions (list): A list of deferred functions.
    url_values_defaults (dict): Default values for URL parameters.
    cli_group (str): The CLI group name.
    _blueprints (list): A list of blueprints and their configurations.
"""
        super().__init__(
            import_name=import_name,
            static_folder=static_folder,
            static_url_path=static_url_path,
            template_folder=template_folder,
            root_path=root_path,
        )

        if "." in name:
            raise ValueError("'name' may not contain a dot '.' character.")

        self.name = name
        self.url_prefix = url_prefix
        self.subdomain = subdomain
        self.deferred_functions: t.List[DeferredSetupFunction] = []

        if url_defaults is None:
            url_defaults = {}

        self.url_values_defaults = url_defaults
        self.cli_group = cli_group
        self._blueprints: t.List[t.Tuple["Blueprint", dict]] = []

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
            import warnings

            warnings.warn(
                f"The setup method '{f_name}' can no longer be called on"
                f" the blueprint '{self.name}'. It has already been"
                " registered at least once, any changes will not be"
                " applied consistently.\n"
                "Make sure all imports, decorators, functions, etc."
                " needed to set up the blueprint are done before"
                " registering it.\n"
                "This warning will become an exception in Flask 2.3.",
                UserWarning,
                stacklevel=3,
            )

    @setupmethod
    def record(self, func: t.Callable) -> None:
        self.deferred_functions.append(func)

    @setupmethod
    def record_once(self, func: t.Callable) -> None:

        def wrapper(state: BlueprintSetupState) -> None:
            if state.first_registration:
                func(state)

        self.record(update_wrapper(wrapper, func))

    def make_setup_state(
        self, app: "Flask", options: dict, first_registration: bool = False
    ) -> BlueprintSetupState:
        return BlueprintSetupState(self, app, options, first_registration)

    @setupmethod
    def register_blueprint(self, blueprint: "Blueprint", **options: t.Any) -> None:
        if blueprint is self:
            raise ValueError("Cannot register a blueprint on itself")
        self._blueprints.append((blueprint, options))

    def register(self, app: "Flask", options: dict) -> None:
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
                view_func=self.send_static_file,
                endpoint="static",
            )

        # Merge blueprint data into parent.
        if first_bp_registration or first_name_registration:

            def extend(bp_dict, parent_dict):
                for key, values in bp_dict.items():
                    key = name if key is None else f"{name}.{key}"
                    parent_dict[key].extend(values)

            for key, value in self.error_handler_spec.items():
                key = name if key is None else f"{name}.{key}"
                value = defaultdict(
                    dict,
                    {
                        code: {
                            exc_class: func for exc_class, func in code_values.items()
                        }
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

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: t.Optional[str] = None,
        view_func: t.Optional[ft.RouteCallable] = None,
        provide_automatic_options: t.Optional[bool] = None,
        **options: t.Any,
    ) -> None:
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
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_filter], T_template_filter]:

        def decorator(f: T_template_filter) -> T_template_filter:
            self.add_app_template_filter(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_filter(
        self, f: ft.TemplateFilterCallable, name: t.Optional[str] = None
    ) -> None:

        def register_template(state: BlueprintSetupState) -> None:
            state.app.jinja_env.filters[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def app_template_test(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_test], T_template_test]:

        def decorator(f: T_template_test) -> T_template_test:
            self.add_app_template_test(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_test(
        self, f: ft.TemplateTestCallable, name: t.Optional[str] = None
    ) -> None:

        def register_template(state: BlueprintSetupState) -> None:
            state.app.jinja_env.tests[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def app_template_global(
        self, name: t.Optional[str] = None
    ) -> t.Callable[[T_template_global], T_template_global]:

        def decorator(f: T_template_global) -> T_template_global:
            self.add_app_template_global(f, name=name)
            return f

        return decorator

    @setupmethod
    def add_app_template_global(
        self, f: ft.TemplateGlobalCallable, name: t.Optional[str] = None
    ) -> None:

        def register_template(state: BlueprintSetupState) -> None:
            state.app.jinja_env.globals[name or f.__name__] = f

        self.record_once(register_template)

    @setupmethod
    def before_app_request(self, f: T_before_request) -> T_before_request:
        self.record_once(
            lambda s: s.app.before_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def before_app_first_request(
        self, f: T_before_first_request
    ) -> T_before_first_request:
        """
Deprecation Notice:

The `before_app_first_request` function is deprecated and will be removed in Flask 2.3.
Use the `record_once` method instead to run setup code when registering a blueprint.

Parameters:
f (T_before_first_request): The function to register for before first request.

Returns:
T_before_first_request: The registered function.

Raises:
DeprecationWarning: If the function is deprecated and should be replaced with `record_once`.
"""
        import warnings

        warnings.warn(
            "'before_app_first_request' is deprecated and will be"
            " removed in Flask 2.3. Use 'record_once' instead to run"
            " setup code when registering the blueprint.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.record_once(lambda s: s.app.before_first_request_funcs.append(f))
        return f

    @setupmethod
    def after_app_request(self, f: T_after_request) -> T_after_request:
        self.record_once(
            lambda s: s.app.after_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def teardown_app_request(self, f: T_teardown) -> T_teardown:
        self.record_once(
            lambda s: s.app.teardown_request_funcs.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_context_processor(
        self, f: T_template_context_processor
    ) -> T_template_context_processor:
        self.record_once(
            lambda s: s.app.template_context_processors.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_errorhandler(
        self, code: t.Union[t.Type[Exception], int]
    ) -> t.Callable[[T_error_handler], T_error_handler]:

        def decorator(f: T_error_handler) -> T_error_handler:
            self.record_once(lambda s: s.app.errorhandler(code)(f))
            return f

        return decorator

    @setupmethod
    def app_url_value_preprocessor(
        self, f: T_url_value_preprocessor
    ) -> T_url_value_preprocessor:
        self.record_once(
            lambda s: s.app.url_value_preprocessors.setdefault(None, []).append(f)
        )
        return f

    @setupmethod
    def app_url_defaults(self, f: T_url_defaults) -> T_url_defaults:
        self.record_once(
            lambda s: s.app.url_default_functions.setdefault(None, []).append(f)
        )
        return f
