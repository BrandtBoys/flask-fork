from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import typing as t
from collections import defaultdict
from functools import update_wrapper

from jinja2 import FileSystemLoader
from werkzeug.exceptions import default_exceptions
from werkzeug.exceptions import HTTPException
from werkzeug.utils import cached_property

from .. import typing as ft
from ..cli import AppGroup
from ..helpers import get_root_path
from ..templating import _default_template_ctx_processor

# a singleton sentinel value for parameter defaults
_sentinel = object()

F = t.TypeVar("F", bound=t.Callable[..., t.Any])
T_after_request = t.TypeVar("T_after_request", bound=ft.AfterRequestCallable)
T_before_request = t.TypeVar("T_before_request", bound=ft.BeforeRequestCallable)
T_error_handler = t.TypeVar("T_error_handler", bound=ft.ErrorHandlerCallable)
T_teardown = t.TypeVar("T_teardown", bound=ft.TeardownCallable)
T_template_context_processor = t.TypeVar(
    "T_template_context_processor", bound=ft.TemplateContextProcessorCallable
)
T_url_defaults = t.TypeVar("T_url_defaults", bound=ft.URLDefaultCallable)
T_url_value_preprocessor = t.TypeVar(
    "T_url_value_preprocessor", bound=ft.URLValuePreprocessorCallable
)
T_route = t.TypeVar("T_route", bound=ft.RouteCallable)


def setupmethod(f: F) -> F:
    """
Decorates a method with setup functionality.

This decorator sets up the method by checking if the setup process is finished
and updating the wrapper function to include the original method's metadata.

Args:
    f (function): The method to be decorated.

Returns:
    function: The decorated method.
"""
    f_name = f.__name__

    def wrapper_func(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        """
Wrapper function for a specific class method.

This function checks if the setup is finished before calling the original method.
It then calls the original method with the provided arguments and returns its result.

Args:
    self: The instance of the class that owns this method.
    *args: Variable number of positional arguments to be passed to the original method.
    **kwargs: Variable number of keyword arguments to be passed to the original method.

Returns:
    The result of the original method call.

Raises:
    None
"""
        self._check_setup_finished(f_name)
        return f(self, *args, **kwargs)

    return t.cast(F, update_wrapper(wrapper_func, f))


class Scaffold:
    """Common behavior shared between :class:`~flask.Flask` and
    :class:`~flask.blueprints.Blueprint`.

    :param import_name: The import name of the module where this object
        is defined. Usually :attr:`__name__` should be used.
    :param static_folder: Path to a folder of static files to serve.
        If this is set, a static route will be added.
    :param static_url_path: URL prefix for the static route.
    :param template_folder: Path to a folder containing template files.
        for rendering. If this is set, a Jinja loader will be added.
    :param root_path: The path that static, template, and resource files
        are relative to. Typically not set, it is discovered based on
        the ``import_name``.

    .. versionadded:: 2.0
    """

    name: str
    _static_folder: str | None = None
    _static_url_path: str | None = None

    def __init__(
        self,
        import_name: str,
        static_folder: str | os.PathLike | None = None,
        static_url_path: str | None = None,
        template_folder: str | os.PathLike | None = None,
        root_path: str | None = None,
    ):
        #: The name of the package or module that this object belongs
        #: to. Do not change this once it is set by the constructor.
        """
Initialize a Flask application.

This function initializes a new instance of the Flask class. It takes several
parameters that define the configuration and behavior of the application.

Parameters:
    import_name (str): The name of the package or module that this object belongs to.
    static_folder (str | os.PathLike | None, optional): The path to the static folder. Defaults to None.
    static_url_path (str | None, optional): The URL path for static files. Defaults to None.
    template_folder (str | os.PathLike | None, optional): The path to the templates folder. Defaults to None.
    root_path (str | None, optional): The absolute path to the package on the filesystem. Defaults to None.

Attributes:
    import_name (str): The name of the package or module that this object belongs to.
    static_folder (str | os.PathLike | None): The path to the static folder.
    static_url_path (str | None): The URL path for static files.
    template_folder (str | os.PathLike | None): The path to the templates folder.
    root_path (str | None): The absolute path to the package on the filesystem.
    cli (AppGroup): The Click command group for registering CLI commands.
    view_functions (dict[str, t.Callable]): A dictionary mapping endpoint names to view functions.
    error_handler_spec (dict[ft.AppOrBlueprintKey, dict[int | None, dict[type[Exception], ft.ErrorHandlerCallable]]]): A data structure of registered error handlers.
    before_request_funcs (dict[ft.AppOrBlueprintKey, list[ft.BeforeRequestCallable]]): A data structure of functions to call at the beginning of each request.
    after_request_funcs (dict[ft.AppOrBlueprintKey, list[ft.AfterRequestCallable]]): A data structure of functions to call at the end of each request.
    teardown_request_funcs (dict[ft.AppOrBlueprintKey, list[ft.TeardownCallable]]): A data structure of functions to call to pass extra context values when rendering templates.
    template_context_processors (dict[ft.AppOrBlueprintKey, list[ft.TemplateContextProcessorCallable]]): A data structure of functions to call to modify the keyword arguments passed to the view function.
    url_value_preprocessors (dict[ft.AppOrBlueprintKey, list[ft.URLValuePreprocessorCallable]]): A data structure of functions to call to modify the keyword arguments when generating URLs.
    url_default_functions (dict[ft.AppOrBlueprintKey, list[ft.URLDefaultCallable]]): A data structure of functions to call to modify the keyword arguments when generating URLs.

Raises:
    TypeError: If any parameter is not of the correct type.
"""
        self.import_name = import_name

        self.static_folder = static_folder  # type: ignore
        self.static_url_path = static_url_path

        #: The path to the templates folder, relative to
        #: :attr:`root_path`, to add to the template loader. ``None`` if
        #: templates should not be added.
        self.template_folder = template_folder

        if root_path is None:
            root_path = get_root_path(self.import_name)

        #: Absolute path to the package on the filesystem. Used to look
        #: up resources contained in the package.
        self.root_path = root_path

        #: The Click command group for registering CLI commands for this
        #: object. The commands are available from the ``flask`` command
        #: once the application has been discovered and blueprints have
        #: been registered.
        self.cli = AppGroup()

        #: A dictionary mapping endpoint names to view functions.
        #:
        #: To register a view function, use the :meth:`route` decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.view_functions: dict[str, t.Callable] = {}

        #: A data structure of registered error handlers, in the format
        #: ``{scope: {code: {class: handler}}}``. The ``scope`` key is
        #: the name of a blueprint the handlers are active for, or
        #: ``None`` for all requests. The ``code`` key is the HTTP
        #: status code for ``HTTPException``, or ``None`` for
        #: other exceptions. The innermost dictionary maps exception
        #: classes to handler functions.
        #:
        #: To register an error handler, use the :meth:`errorhandler`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.error_handler_spec: dict[
            ft.AppOrBlueprintKey,
            dict[int | None, dict[type[Exception], ft.ErrorHandlerCallable]],
        ] = defaultdict(lambda: defaultdict(dict))

        #: A data structure of functions to call at the beginning of
        #: each request, in the format ``{scope: [functions]}``. The
        #: ``scope`` key is the name of a blueprint the functions are
        #: active for, or ``None`` for all requests.
        #:
        #: To register a function, use the :meth:`before_request`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.before_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.BeforeRequestCallable]
        ] = defaultdict(list)

        #: A data structure of functions to call at the end of each
        #: request, in the format ``{scope: [functions]}``. The
        #: ``scope`` key is the name of a blueprint the functions are
        #: active for, or ``None`` for all requests.
        #:
        #: To register a function, use the :meth:`after_request`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.after_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.AfterRequestCallable]
        ] = defaultdict(list)

        #: A data structure of functions to call at the end of each
        #: request even if an exception is raised, in the format
        #: ``{scope: [functions]}``. The ``scope`` key is the name of a
        #: blueprint the functions are active for, or ``None`` for all
        #: requests.
        #:
        #: To register a function, use the :meth:`teardown_request`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.teardown_request_funcs: dict[
            ft.AppOrBlueprintKey, list[ft.TeardownCallable]
        ] = defaultdict(list)

        #: A data structure of functions to call to pass extra context
        #: values when rendering templates, in the format
        #: ``{scope: [functions]}``. The ``scope`` key is the name of a
        #: blueprint the functions are active for, or ``None`` for all
        #: requests.
        #:
        #: To register a function, use the :meth:`context_processor`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.template_context_processors: dict[
            ft.AppOrBlueprintKey, list[ft.TemplateContextProcessorCallable]
        ] = defaultdict(list, {None: [_default_template_ctx_processor]})

        #: A data structure of functions to call to modify the keyword
        #: arguments passed to the view function, in the format
        #: ``{scope: [functions]}``. The ``scope`` key is the name of a
        #: blueprint the functions are active for, or ``None`` for all
        #: requests.
        #:
        #: To register a function, use the
        #: :meth:`url_value_preprocessor` decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.url_value_preprocessors: dict[
            ft.AppOrBlueprintKey,
            list[ft.URLValuePreprocessorCallable],
        ] = defaultdict(list)

        #: A data structure of functions to call to modify the keyword
        #: arguments when generating URLs, in the format
        #: ``{scope: [functions]}``. The ``scope`` key is the name of a
        #: blueprint the functions are active for, or ``None`` for all
        #: requests.
        #:
        #: To register a function, use the :meth:`url_defaults`
        #: decorator.
        #:
        #: This data structure is internal. It should not be modified
        #: directly and its format may change at any time.
        self.url_default_functions: dict[
            ft.AppOrBlueprintKey, list[ft.URLDefaultCallable]
        ] = defaultdict(list)

    def __repr__(self) -> str:
        """
Returns a string representation of the object.

This method is used to provide a human-readable representation of the object, 
including its type and name. It is typically used for debugging purposes or 
when displaying objects in a user interface.

Args:
    None

Returns:
    str: A string representation of the object.
"""
        return f"<{type(self).__name__} {self.name!r}>"

    def _check_setup_finished(self, f_name: str) -> None:
        """
Raises a NotImplementedError when setup is not finished.

This method should be implemented by subclasses to check if the setup process is complete.
If the setup is not finished, it raises a NotImplementedError with an appropriate message.

Args:
    f_name (str): The name of the file being checked.

Returns:
    None
"""
        raise NotImplementedError

    @property
    def static_folder(self) -> str | None:
        """
Returns the path to the static folder. If no static folder has been set, returns None.

Args:
    None

Returns:
    str | None: The path to the static folder or None if not set.
"""
        if self._static_folder is not None:
            return os.path.join(self.root_path, self._static_folder)
        else:
            return None

    @static_folder.setter
    def static_folder(self, value: str | os.PathLike | None) -> None:
        """
Sets the path to a static folder.

This method takes a string or Path-like object representing the path to a static folder.
If the provided path is absolute, it will be normalized and any trailing slash removed.
The resulting path is then stored in the `_static_folder` attribute of the instance.

Args:
    value (str | os.PathLike | None): The path to the static folder.

Returns:
    None
"""
        if value is not None:
            value = os.fspath(value).rstrip(r"\/")

        self._static_folder = value

    @property
    def has_static_folder(self) -> bool:
        """
Returns whether the object has a static folder.

This method checks if the `static_folder` attribute of the object is not None.
It can be used to determine if the object has a static folder available for serving files. 

Args:
    None

Returns:
    bool: True if the object has a static folder, False otherwise
"""
        return self.static_folder is not None

    @property
    def static_url_path(self) -> str | None:
        """
Returns the static URL path for this object.

If a precomputed URL path exists, it returns that. Otherwise, it constructs a URL path from the `static_folder` attribute by taking the basename of the folder and appending it to the root URL.

Returns:
    str | None: The static URL path or None if no valid path can be constructed.
"""
        if self._static_url_path is not None:
            return self._static_url_path

        if self.static_folder is not None:
            basename = os.path.basename(self.static_folder)
            return f"/{basename}".rstrip("/")

        return None

    @static_url_path.setter
    def static_url_path(self, value: str | None) -> None:
        """
Returns a static URL path.

This method takes a string or None as input and returns the URL path after removing any trailing slashes. If the input is None, it sets the internal `_static_url_path` attribute to None.

Args:
    value (str | None): The URL path to be processed.

Returns:
    None
"""
        if value is not None:
            value = value.rstrip("/")

        self._static_url_path = value

        """
Returns the maximum age in seconds for sending files.

If `filename` is provided, it will be used to retrieve the default send file max age from the application configuration.
Otherwise, the default value will be returned.

Args:
    filename (str | None): The name of the file to use for retrieving the default send file max age. Defaults to None.

Returns:
    int | None: The maximum age in seconds for sending files, or None if no default is set.
"""
        """
Sends a static file from the configured static folder.

This method is used to serve static files. It checks if the `static_folder` attribute has been set and raises a RuntimeError if not.
It then calls `get_send_file_max_age` to determine the maximum age for the file, which is necessary for blueprints to work correctly.
Finally, it uses `send_from_directory` to send the file from the static folder.

Args:
    filename (str): The name of the file to be sent.

Returns:
    Response: A response object containing the sent file.

Raises:
    RuntimeError: If 'static_folder' is not set.
"""
    @cached_property
    def jinja_loader(self) -> FileSystemLoader | None:
        """
Loads a Jinja template loader based on the presence of a template folder.

Returns:
    FileSystemLoader: A Jinja template loader instance if a template folder is found.
    None: No template folder found, returns None.
"""
        if self.template_folder is not None:
            return FileSystemLoader(os.path.join(self.root_path, self.template_folder))
        else:
            return None
        """
Opens a resource file.

Args:
    resource (str): The path to the resource file.
    mode (str, optional): The mode in which to open the file. Defaults to "rb". Supported modes are "r", "rt", and "rb".

Returns:
    t.IO[t.AnyStr]: A file object opened in the specified mode.

Raises:
    ValueError: If an unsupported mode is provided.
"""

    def _method_route(
        self,
        method: str,
        rule: str,
        options: dict,
    ) -> t.Callable[[T_route], T_route]:
        """
Determine and apply a route method.

This function is used internally by the class to determine and apply a specific route method.
It takes in the method name, rule, and options as parameters. If the 'methods' key exists in the options dictionary,
it raises a TypeError indicating that the 'route' decorator should be used instead.

Args:
    self: The instance of the class.
    method (str): The name of the route method to apply.
    rule (str): The rule for which the method is applied.
    options (dict): A dictionary containing additional options for the route.

Returns:
    t.Callable[[T_route], T_route]: A callable function that applies the specified route method to a given route object.

Raises:
    TypeError: If the 'methods' key exists in the options dictionary, indicating that the 'route' decorator should be used.
"""
        if "methods" in options:
            raise TypeError("Use the 'route' decorator to use the 'methods' argument.")

        return self.route(rule, methods=[method], **options)

    @setupmethod
    def get(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
Returns a callable function for handling HTTP GET requests.

Args:
    rule (str): The route to be handled.
    **options (t.Any): Additional keyword arguments to be passed to the method.

Returns:
    t.Callable[[T_route], T_route]: A callable function that handles HTTP GET requests.
"""
        return self._method_route("GET", rule, options)

    @setupmethod
    def post(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        return self._method_route("POST", rule, options)

    @setupmethod
    def put(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
Returns a callable function for handling HTTP PUT requests.

Args:
    rule (str): The route to be handled.
    **options (t.Any): Additional keyword arguments to be passed to the underlying method.

Returns:
    t.Callable[[T_route], T_route]: A callable function that handles HTTP PUT requests for the given rule.
"""
        return self._method_route("PUT", rule, options)

    @setupmethod
    def delete(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
Deletes a route.

Args:
    rule (str): The path of the route to be deleted.
    **options (t.Any): Additional keyword arguments for the method.

Returns:
    t.Callable[[T_route], T_route]: A callable function that deletes the specified route.

Raises:
    ValueError: If the rule is not a valid path.
"""
        return self._method_route("DELETE", rule, options)

    @setupmethod
    def patch(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:
        """
Patches a route with the specified rule and options.

Args:
    rule (str): The rule to patch.
    **options (t.Any): Additional options for the route.

Returns:
    t.Callable[[T_route], T_route]: A callable that patches the route.

Raises:
    None
"""
        return self._method_route("PATCH", rule, options)

    @setupmethod
    def route(self, rule: str, **options: t.Any) -> t.Callable[[T_route], T_route]:

       """
Route a URL pattern to a view function.

This function is used to create a route for a given URL pattern. It takes in the rule of the URL and any additional options as keyword arguments. The `endpoint` option can be provided to specify an endpoint name, which will be used when adding the URL rule.

The returned decorator function can be applied to view functions to register them with this router.

Args:
    rule (str): The URL pattern to route.
    **options: t.Any: Additional options for the URL rule. Can include 'endpoint' to specify an endpoint name.

Returns:
    T_route -> T_route: A decorator function that registers a view function with this router.
"""
        def decorator(f: T_route) -> T_route:
            """
Decorates a function to register it as an endpoint.

This decorator takes a function `f` and registers it with the Flask application.
It also populates the "endpoint" key in the options dictionary if present,
and passes the remaining options to the `add_url_rule` method.

Args:
    f (function): The function to be decorated.

Returns:
    function: The original function, now registered as an endpoint.
"""
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: str | None = None,
        view_func: ft.RouteCallable | None = None,
        provide_automatic_options: bool | None = None,
        **options: t.Any,
    ) -> None:
        raise NotImplementedError

    @setupmethod
    def endpoint(self, endpoint: str) -> t.Callable[[F], F]:

       """
Endpoint Decorator Function

This function is a decorator that registers an endpoint with the provided endpoint string.
It takes in a function `f` and returns a new function that wraps the original function, 
registering it as a view function for the specified endpoint.

Args:
    endpoint (str): The endpoint to register the function under.
    f (Callable[[F], F]): The function to be registered as a view function.

Returns:
    Callable[[F], F]: A new function that wraps the original function and registers it as a view function.
"""
        def decorator(f: F) -> F:
            """
Decorates a view function with endpoint information.

This function is used to register and decorate view functions for use in the application.
It takes a view function `f` as an argument, adds it to the `view_functions` dictionary 
with the current endpoint, and then returns the original function. This allows for easy
management of view functions and their corresponding endpoints.

Args:
    f (F): The view function to be decorated.

Returns:
    F: The decorated view function.
"""
            
            self.view_functions[endpoint] = f
            return f

        return decorator

    @setupmethod
    def before_request(self, f: T_before_request) -> T_before_request:
        """
Adds a request handler function to the `before_request_funcs` set.

Args:
    f (T_before_request): The request handler function to be added.

Returns:
    T_before_request: The original request handler function.
"""
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def after_request(self, f: T_after_request) -> T_after_request:
        """
Adds a request handler function to the `after_request_funcs` set.

Args:
    f (T_after_request): The request handler function to be added.

Returns:
    T_after_request: The original request handler function.
"""
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def teardown_request(self, f: T_teardown) -> T_teardown:
        """
Adds a teardown request function to the internal list of teardown functions.

Args:
    f (T_teardown): The teardown request function to be added.

Returns:
    T_teardown: The original teardown request function.
"""
        self.teardown_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def context_processor(
        self,
        f: T_template_context_processor,
    ) -> T_template_context_processor:
        """
Processes a template context processor.

This function is used to register and manage template context processors.
It takes in a `f` parameter, which is the template context processor to be added,
and returns the same `f` after adding it to the list of registered processors.

Args:
    f (T_template_context_processor): The template context processor to be added.

Returns:
    T_template_context_processor: The original template context processor.
"""
        self.template_context_processors[None].append(f)
        return f

    @setupmethod
    def url_value_preprocessor(
        self,
        f: T_url_value_preprocessor,
    ) -> T_url_value_preprocessor:
        """
Preprocesses a URL value by appending it to the list of preprocessed values.

Args:
    f (T_url_value_preprocessor): The URL value to be preprocessed.

Returns:
    T_url_value_preprocessor: The preprocessed URL value.
"""
        self.url_value_preprocessors[None].append(f)
        return f

    @setupmethod
    def url_defaults(self, f: T_url_defaults) -> T_url_defaults:
        """
Adds a URL defaults function to the `url_default_functions` dictionary.

Args:
    f (T_url_defaults): The URL defaults function to be added.

Returns:
    T_url_defaults: The provided URL defaults function, which is then appended to the `url_default_functions` dictionary.
"""
        self.url_default_functions[None].append(f)
        return f

    @setupmethod
    def errorhandler(
        self, code_or_exception: type[Exception] | int
    ) -> t.Callable[[T_error_handler], T_error_handler]:

       """
Decorates a function to handle specific exceptions.

This function returns a decorator that registers the provided function as an error handler for the specified exception type or code. The decorated function will be called when the registered exception is raised.

Args:
    self: The instance of the class that this method belongs to.
    code_or_exception (type[Exception] | int): The type of exception or code to register the decorator for.
    f (T_error_handler): The function to decorate as an error handler.

Returns:
    T_error_handler: The decorated function.
"""
        def decorator(f: T_error_handler) -> T_error_handler:
            """
Decorates a function to register it as an error handler.

This decorator takes a function `f` that handles errors and registers it with the 
`register_error_handler` method. The decorated function is then returned.

Args:
    f (T_error_handler): The function to be registered as an error handler.

Returns:
    T_error_handler: The decorated function.
"""
            self.register_error_handler(code_or_exception, f)
            return f

        return decorator

    @setupmethod
    def register_error_handler(
        self,
        code_or_exception: type[Exception] | int,
        f: ft.ErrorHandlerCallable,
    ) -> None:
        """
Registers an error handler for a specific exception class or code.

Args:
    - `self`: The instance of the class that this method belongs to.
    - `code_or_exception`: A type hint indicating whether it's an exception class (type[Exception]) or an integer representing an HTTP status code. This parameter is used to determine which part of the error handler specification to update.
    - `f`: An instance of ft.ErrorHandlerCallable, which represents a function that will be called when an error occurs.

Returns:
    None

Raises:
    None
"""
        exc_class, code = self._get_exc_class_and_code(code_or_exception)
        self.error_handler_spec[None][code][exc_class] = f

    @staticmethod
    def _get_exc_class_and_code(
        exc_class_or_code: type[Exception] | int,
    ) -> tuple[type[Exception], int | None]:
        """
Returns the exception class and its corresponding code (if applicable) from a given exception class or code.

Args:
    exc_class_or_code: The exception class or code to retrieve. Can be an instance of Exception or an integer representing an HTTP error code.

Returns:
    A tuple containing the exception class and its code (or None if not applicable).
Raises:
    ValueError: If the provided code is not a recognized HTTP error code.
    TypeError: If the provided value is not an instance of Exception or an integer representing an HTTP error code, or if it's an instance of Exception instead of a class.
"""
        exc_class: type[Exception]

        if isinstance(exc_class_or_code, int):
            try:
                exc_class = default_exceptions[exc_class_or_code]
            except KeyError:
                raise ValueError(
                    f"'{exc_class_or_code}' is not a recognized HTTP"
                    " error code. Use a subclass of HTTPException with"
                    " that code instead."
                ) from None
        else:
            exc_class = exc_class_or_code

        if isinstance(exc_class, Exception):
            raise TypeError(
                f"{exc_class!r} is an instance, not a class. Handlers"
                " can only be registered for Exception classes or HTTP"
                " error codes."
            )

        if not issubclass(exc_class, Exception):
            raise ValueError(
                f"'{exc_class.__name__}' is not a subclass of Exception."
                " Handlers can only be registered for Exception classes"
                " or HTTP error codes."
            )

        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None


def _endpoint_from_view_func(view_func: t.Callable) -> str:
    assert view_func is not None, "expected view func if endpoint is not provided."
    return view_func.__name__


def _path_is_relative_to(path: pathlib.PurePath, base: str) -> bool:
    # Path.is_relative_to doesn't exist until Python 3.9
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _find_package_path(import_name):
    root_mod_name, _, _ = import_name.partition(".")

    try:
        root_spec = importlib.util.find_spec(root_mod_name)

        if root_spec is None:
            raise ValueError("not found")
    except (ImportError, ValueError):
        # ImportError: the machinery told us it does not exist
        # ValueError:
        #    - the module name was invalid
        #    - the module name is __main__
        #    - we raised `ValueError` due to `root_spec` being `None`
        return os.getcwd()

    if root_spec.origin in {"namespace", None}:
        # namespace package
        package_spec = importlib.util.find_spec(import_name)

        if package_spec is not None and package_spec.submodule_search_locations:
            # Pick the path in the namespace that contains the submodule.
            package_path = pathlib.Path(
                os.path.commonpath(package_spec.submodule_search_locations)
            )
            search_location = next(
                location
                for location in root_spec.submodule_search_locations
                if _path_is_relative_to(package_path, location)
            )
        else:
            # Pick the first path.
            search_location = root_spec.submodule_search_locations[0]

        return os.path.dirname(search_location)
    elif root_spec.submodule_search_locations:
        # package with __init__.py
        return os.path.dirname(os.path.dirname(root_spec.origin))
    else:
        # module
        return os.path.dirname(root_spec.origin)


def find_package(import_name: str):
    """
Find the path to a Python package.

This function takes an import name as input and returns the prefix and full path of the corresponding package.
If the package is installed system-wide, it returns the prefix and full path. If the package is installed in a virtual environment,
it returns the parent directory and full path. If the package is not installed, it returns None for both values.

Parameters:
    import_name (str): The name of the Python package to find.

Returns:
    tuple: A tuple containing the prefix and full path of the package, or None if the package is not installed.
"""
    package_path = _find_package_path(import_name)
    py_prefix = os.path.abspath(sys.prefix)

    # installed to the system
    if _path_is_relative_to(pathlib.PurePath(package_path), py_prefix):
        return py_prefix, package_path

    site_parent, site_folder = os.path.split(package_path)

    # installed to a virtualenv
    if site_folder.lower() == "site-packages":
        parent, folder = os.path.split(site_parent)

        # Windows (prefix/lib/site-packages)
        if folder.lower() == "lib":
            return parent, package_path

        # Unix (prefix/lib/pythonX.Y/site-packages)
        if os.path.basename(parent).lower() == "lib":
            return os.path.dirname(parent), package_path

        # something else (prefix/site-packages)
        return site_parent, package_path

    # not installed
    return None, package_path
