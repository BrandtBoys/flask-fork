import importlib.util
import os
import pkgutil
import sys
import typing as t
from collections import defaultdict
from functools import update_wrapper
from json import JSONDecoder
from json import JSONEncoder

from jinja2 import FileSystemLoader
from werkzeug.exceptions import default_exceptions
from werkzeug.exceptions import HTTPException

from .cli import AppGroup
from .globals import current_app
from .helpers import get_root_path
from .helpers import locked_cached_property
from .helpers import send_from_directory
from .templating import _default_template_ctx_processor
from .typing import AfterRequestCallable
from .typing import AppOrBlueprintKey
from .typing import BeforeRequestCallable
from .typing import GenericException
from .typing import TeardownCallable
from .typing import TemplateContextProcessorCallable
from .typing import URLDefaultCallable
from .typing import URLValuePreprocessorCallable

if t.TYPE_CHECKING:
    from .wrappers import Response
    from .typing import ErrorHandlerCallable

# a singleton sentinel value for parameter defaults
_sentinel = object()

F = t.TypeVar("F", bound=t.Callable[..., t.Any])


def setupmethod(f: F) -> F:

    def wrapper_func(self, *args: t.Any, **kwargs: t.Any) -> t.Any:
        if self._is_setup_finished():
            raise AssertionError(
                "A setup function was called after the first request "
                "was handled. This usually indicates a bug in the"
                " application where a module was not imported and"
                " decorators or other functionality was called too"
                " late.\nTo fix this make sure to import all your view"
                " modules, database models, and everything related at a"
                " central place before the application starts serving"
                " requests."
            )
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
    _static_folder: t.Optional[str] = None
    _static_url_path: t.Optional[str] = None

    #: JSON encoder class used by :func:`flask.json.dumps`. If a
    #: blueprint sets this, it will be used instead of the app's value.
    json_encoder: t.Optional[t.Type[JSONEncoder]] = None

    #: JSON decoder class used by :func:`flask.json.loads`. If a
    #: blueprint sets this, it will be used instead of the app's value.
    json_decoder: t.Optional[t.Type[JSONDecoder]] = None

    def __init__(
        self,
        import_name: str,
        static_folder: t.Optional[t.Union[str, os.PathLike]] = None,
        static_url_path: t.Optional[str] = None,
        template_folder: t.Optional[str] = None,
        root_path: t.Optional[str] = None,
    ):
        #: The name of the package or module that this object belongs
        #: to. Do not change this once it is set by the constructor.
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
        self.view_functions: t.Dict[str, t.Callable] = {}

        #: A data structure of registered error handlers, in the format
        #: ``{scope: {code: {class: handler}}}```. The ``scope`` key is
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
        self.error_handler_spec: t.Dict[
            AppOrBlueprintKey,
            t.Dict[
                t.Optional[int],
                t.Dict[t.Type[Exception], "ErrorHandlerCallable[Exception]"],
            ],
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
        self.before_request_funcs: t.Dict[
            AppOrBlueprintKey, t.List[BeforeRequestCallable]
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
        self.after_request_funcs: t.Dict[
            AppOrBlueprintKey, t.List[AfterRequestCallable]
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
        self.teardown_request_funcs: t.Dict[
            AppOrBlueprintKey, t.List[TeardownCallable]
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
        self.template_context_processors: t.Dict[
            AppOrBlueprintKey, t.List[TemplateContextProcessorCallable]
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
        self.url_value_preprocessors: t.Dict[
            AppOrBlueprintKey,
            t.List[URLValuePreprocessorCallable],
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
        self.url_default_functions: t.Dict[
            AppOrBlueprintKey, t.List[URLDefaultCallable]
        ] = defaultdict(list)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"

    def _is_setup_finished(self) -> bool:
        raise NotImplementedError

    @property
    def static_folder(self) -> t.Optional[str]:
        if self._static_folder is not None:
            return os.path.join(self.root_path, self._static_folder)
        else:
            return None

    @static_folder.setter
    def static_folder(self, value: t.Optional[t.Union[str, os.PathLike]]) -> None:
        if value is not None:
            value = os.fspath(value).rstrip(r"\/")

        self._static_folder = value

    @property
    def has_static_folder(self) -> bool:
        return self.static_folder is not None

    @property
    def static_url_path(self) -> t.Optional[str]:
        if self._static_url_path is not None:
            return self._static_url_path

        if self.static_folder is not None:
            basename = os.path.basename(self.static_folder)
            return f"/{basename}".rstrip("/")

        return None

    @static_url_path.setter
    def static_url_path(self, value: t.Optional[str]) -> None:
        if value is not None:
            value = value.rstrip("/")

        self._static_url_path = value

    def get_send_file_max_age(self, filename: t.Optional[str]) -> t.Optional[int]:
        value = current_app.send_file_max_age_default

        if value is None:
            return None

        return int(value.total_seconds())

    def send_static_file(self, filename: str) -> "Response":
        if not self.has_static_folder:
            raise RuntimeError("'static_folder' must be set to serve static_files.")

        # send_file only knows to call get_send_file_max_age on the app,
        # call it here so it works for blueprints too.
        max_age = self.get_send_file_max_age(filename)
        return send_from_directory(
            t.cast(str, self.static_folder), filename, max_age=max_age
        )

    @locked_cached_property
    def jinja_loader(self) -> t.Optional[FileSystemLoader]:
        if self.template_folder is not None:
            return FileSystemLoader(os.path.join(self.root_path, self.template_folder))
        else:
            return None

    def open_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr]:
        if mode not in {"r", "rt", "rb"}:
            raise ValueError("Resources can only be opened for reading.")

        return open(os.path.join(self.root_path, resource), mode)

    def _method_route(self, method: str, rule: str, options: dict) -> t.Callable:
        if "methods" in options:
            raise TypeError("Use the 'route' decorator to use the 'methods' argument.")

        return self.route(rule, methods=[method], **options)

    def get(self, rule: str, **options: t.Any) -> t.Callable:
        return self._method_route("GET", rule, options)

    def post(self, rule: str, **options: t.Any) -> t.Callable:
        return self._method_route("POST", rule, options)

    def put(self, rule: str, **options: t.Any) -> t.Callable:
        return self._method_route("PUT", rule, options)

    def delete(self, rule: str, **options: t.Any) -> t.Callable:
        return self._method_route("DELETE", rule, options)

    def patch(self, rule: str, **options: t.Any) -> t.Callable:
        return self._method_route("PATCH", rule, options)

    def route(self, rule: str, **options: t.Any) -> t.Callable:

        def decorator(f: t.Callable) -> t.Callable:
            endpoint = options.pop("endpoint", None)
            self.add_url_rule(rule, endpoint, f, **options)
            return f

        return decorator

    @setupmethod
    def add_url_rule(
        self,
        rule: str,
        endpoint: t.Optional[str] = None,
        view_func: t.Optional[t.Callable] = None,
        provide_automatic_options: t.Optional[bool] = None,
        **options: t.Any,
    ) -> None:
        raise NotImplementedError

    def endpoint(self, endpoint: str) -> t.Callable:

        def decorator(f):
            self.view_functions[endpoint] = f
            return f

        return decorator

    @setupmethod
    def before_request(self, f: BeforeRequestCallable) -> BeforeRequestCallable:
        self.before_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def after_request(self, f: AfterRequestCallable) -> AfterRequestCallable:
        self.after_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def teardown_request(self, f: TeardownCallable) -> TeardownCallable:
        self.teardown_request_funcs.setdefault(None, []).append(f)
        return f

    @setupmethod
    def context_processor(
        self, f: TemplateContextProcessorCallable
    ) -> TemplateContextProcessorCallable:
        self.template_context_processors[None].append(f)
        return f

    @setupmethod
    def url_value_preprocessor(
        self, f: URLValuePreprocessorCallable
    ) -> URLValuePreprocessorCallable:
        self.url_value_preprocessors[None].append(f)
        return f

    @setupmethod
    def url_defaults(self, f: URLDefaultCallable) -> URLDefaultCallable:
        self.url_default_functions[None].append(f)
        return f

    @setupmethod
    def errorhandler(
        self, code_or_exception: t.Union[t.Type[GenericException], int]
    ) -> t.Callable[
        ["ErrorHandlerCallable[GenericException]"],
        "ErrorHandlerCallable[GenericException]",
    ]:

        def decorator(
            f: "ErrorHandlerCallable[GenericException]",
        ) -> "ErrorHandlerCallable[GenericException]":
            self.register_error_handler(code_or_exception, f)
            return f

        return decorator

    @setupmethod
    def register_error_handler(
        self,
        code_or_exception: t.Union[t.Type[GenericException], int],
        f: "ErrorHandlerCallable[GenericException]",
    ) -> None:
        if isinstance(code_or_exception, HTTPException):  # old broken behavior
            raise ValueError(
                "Tried to register a handler for an exception instance"
                f" {code_or_exception!r}. Handlers can only be"
                " registered for exception classes or HTTP error codes."
            )

        try:
            exc_class, code = self._get_exc_class_and_code(code_or_exception)
        except KeyError:
            raise KeyError(
                f"'{code_or_exception}' is not a recognized HTTP error"
                " code. Use a subclass of HTTPException with that code"
                " instead."
            )

        self.error_handler_spec[None][code][exc_class] = t.cast(
            "ErrorHandlerCallable[Exception]", f
        )

    @staticmethod
    def _get_exc_class_and_code(
        exc_class_or_code: t.Union[t.Type[Exception], int]
    ) -> t.Tuple[t.Type[Exception], t.Optional[int]]:
        exc_class: t.Type[Exception]
        if isinstance(exc_class_or_code, int):
            exc_class = default_exceptions[exc_class_or_code]
        else:
            exc_class = exc_class_or_code

        assert issubclass(
            exc_class, Exception
        ), "Custom exceptions must be subclasses of Exception."

        if issubclass(exc_class, HTTPException):
            return exc_class, exc_class.code
        else:
            return exc_class, None


def _endpoint_from_view_func(view_func: t.Callable) -> str:
    assert view_func is not None, "expected view func if endpoint is not provided."
    return view_func.__name__


def _matching_loader_thinks_module_is_package(loader, mod_name):
    # Use loader.is_package if it's available.
    if hasattr(loader, "is_package"):
        return loader.is_package(mod_name)

    cls = type(loader)

    # NamespaceLoader doesn't implement is_package, but all names it
    # loads must be packages.
    if cls.__module__ == "_frozen_importlib" and cls.__name__ == "NamespaceLoader":
        return True

    # Otherwise we need to fail with an error that explains what went
    # wrong.
    raise AttributeError(
        f"'{cls.__name__}.is_package()' must be implemented for PEP 302"
        f" import hooks."
    )


def _find_package_path(root_mod_name):
    try:
        spec = importlib.util.find_spec(root_mod_name)

        if spec is None:
            raise ValueError("not found")
    # ImportError: the machinery told us it does not exist
    # ValueError:
    #    - the module name was invalid
    #    - the module name is __main__
    #    - *we* raised `ValueError` due to `spec` being `None`
    except (ImportError, ValueError):
        pass  # handled below
    else:
        # namespace package
        if spec.origin in {"namespace", None}:
            return os.path.dirname(next(iter(spec.submodule_search_locations)))
        # a package (with __init__.py)
        elif spec.submodule_search_locations:
            return os.path.dirname(os.path.dirname(spec.origin))
        # just a normal module
        else:
            return os.path.dirname(spec.origin)

    # we were unable to find the `package_path` using PEP 451 loaders
    loader = pkgutil.get_loader(root_mod_name)

    if loader is None or root_mod_name == "__main__":
        # import name is not found, or interactive/main module
        return os.getcwd()

    if hasattr(loader, "get_filename"):
        filename = loader.get_filename(root_mod_name)
    elif hasattr(loader, "archive"):
        # zipimporter's loader.archive points to the .egg or .zip file.
        filename = loader.archive
    else:
        # At least one loader is missing both get_filename and archive:
        # Google App Engine's HardenedModulesHook, use __file__.
        filename = importlib.import_module(root_mod_name).__file__

    package_path = os.path.abspath(os.path.dirname(filename))

    # If the imported name is a package, filename is currently pointing
    # to the root of the package, need to get the current directory.
    if _matching_loader_thinks_module_is_package(loader, root_mod_name):
        package_path = os.path.dirname(package_path)

    return package_path


def find_package(import_name: str):
    root_mod_name, _, _ = import_name.partition(".")
    package_path = _find_package_path(root_mod_name)
    py_prefix = os.path.abspath(sys.prefix)

    # installed to the system
    if package_path.startswith(py_prefix):
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
