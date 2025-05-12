import os
import pkgutil
import socket
import sys
import typing as t
import warnings
from datetime import datetime
from datetime import timedelta
from functools import lru_cache
from functools import update_wrapper
from threading import RLock

import werkzeug.utils
from werkzeug.exceptions import NotFound
from werkzeug.routing import BuildError
from werkzeug.urls import url_quote

from .globals import _app_ctx_stack
from .globals import _request_ctx_stack
from .globals import current_app
from .globals import request
from .globals import session
from .signals import message_flashed

if t.TYPE_CHECKING:
    from .wrappers import Response


def get_env() -> str:
    return os.environ.get("FLASK_ENV") or "production"


def get_debug_flag() -> bool:
    val = os.environ.get("FLASK_DEBUG")

    if not val:
        return get_env() == "development"

    return val.lower() not in ("0", "false", "no")


def get_load_dotenv(default: bool = True) -> bool:
    val = os.environ.get("FLASK_SKIP_DOTENV")

    if not val:
        return default

    return val.lower() in ("0", "false", "no")


def stream_with_context(
    generator_or_function: t.Union[
        t.Iterator[t.AnyStr], t.Callable[..., t.Iterator[t.AnyStr]]
    ]
) -> t.Iterator[t.AnyStr]:
    try:
        gen = iter(generator_or_function)  # type: ignore
    except TypeError:

        def decorator(*args: t.Any, **kwargs: t.Any) -> t.Any:
            gen = generator_or_function(*args, **kwargs)  # type: ignore
            return stream_with_context(gen)

        return update_wrapper(decorator, generator_or_function)  # type: ignore

    def generator() -> t.Generator:
        ctx = _request_ctx_stack.top
        if ctx is None:
            raise RuntimeError(
                "Attempted to stream with context but "
                "there was no context in the first place to keep around."
            )
        with ctx:
            # Dummy sentinel.  Has to be inside the context block or we're
            # not actually keeping the context around.
            yield None

            # The try/finally is here so that if someone passes a WSGI level
            # iterator in we're still running the cleanup logic.  Generators
            # don't need that because they are closed on their destruction
            # automatically.
            try:
                yield from gen
            finally:
                if hasattr(gen, "close"):
                    gen.close()  # type: ignore

    # The trick is to start the generator.  Then the code execution runs until
    # the first dummy None is yielded at which point the context was already
    # pushed.  This item is discarded.  Then when the iteration continues the
    # real generator is executed.
    wrapped_g = generator()
    next(wrapped_g)
    return wrapped_g


def make_response(*args: t.Any) -> "Response":
    if not args:
        return current_app.response_class()
    if len(args) == 1:
        args = args[0]
    return current_app.make_response(args)


def url_for(endpoint: str, **values: t.Any) -> str:
    appctx = _app_ctx_stack.top
    reqctx = _request_ctx_stack.top

    if appctx is None:
        raise RuntimeError(
            "Attempted to generate a URL without the application context being"
            " pushed. This has to be executed when application context is"
            " available."
        )

    # If request specific information is available we have some extra
    # features that support "relative" URLs.
    if reqctx is not None:
        url_adapter = reqctx.url_adapter
        blueprint_name = request.blueprint

        if endpoint[:1] == ".":
            if blueprint_name is not None:
                endpoint = f"{blueprint_name}{endpoint}"
            else:
                endpoint = endpoint[1:]

        external = values.pop("_external", False)

    # Otherwise go with the url adapter from the appctx and make
    # the URLs external by default.
    else:
        url_adapter = appctx.url_adapter

        if url_adapter is None:
            raise RuntimeError(
                "Application was not able to create a URL adapter for request"
                " independent URL generation. You might be able to fix this by"
                " setting the SERVER_NAME config variable."
            )

        external = values.pop("_external", True)

    anchor = values.pop("_anchor", None)
    method = values.pop("_method", None)
    scheme = values.pop("_scheme", None)
    appctx.app.inject_url_defaults(endpoint, values)

    # This is not the best way to deal with this but currently the
    # underlying Werkzeug router does not support overriding the scheme on
    # a per build call basis.
    old_scheme = None
    if scheme is not None:
        if not external:
            raise ValueError("When specifying _scheme, _external must be True")
        old_scheme = url_adapter.url_scheme
        url_adapter.url_scheme = scheme

    try:
        try:
            rv = url_adapter.build(
                endpoint, values, method=method, force_external=external
            )
        finally:
            if old_scheme is not None:
                url_adapter.url_scheme = old_scheme
    except BuildError as error:
        # We need to inject the values again so that the app callback can
        # deal with that sort of stuff.
        values["_external"] = external
        values["_anchor"] = anchor
        values["_method"] = method
        values["_scheme"] = scheme
        return appctx.app.handle_url_build_error(error, endpoint, values)

    if anchor is not None:
        rv += f"#{url_quote(anchor)}"
    return rv


def get_template_attribute(template_name: str, attribute: str) -> t.Any:
    return getattr(current_app.jinja_env.get_template(template_name).module, attribute)


def flash(message: str, category: str = "message") -> None:
    # Original implementation:
    #
    #     session.setdefault('_flashes', []).append((category, message))
    #
    # This assumed that changes made to mutable structures in the session are
    # always in sync with the session object, which is not true for session
    # implementations that use external storage for keeping their keys/values.
    flashes = session.get("_flashes", [])
    flashes.append((category, message))
    session["_flashes"] = flashes
    message_flashed.send(
        current_app._get_current_object(),  # type: ignore
        message=message,
        category=category,
    )


def get_flashed_messages(
    with_categories: bool = False, category_filter: t.Iterable[str] = ()
) -> t.Union[t.List[str], t.List[t.Tuple[str, str]]]:
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = (
            session.pop("_flashes") if "_flashes" in session else []
        )
    if category_filter:
        flashes = list(filter(lambda f: f[0] in category_filter, flashes))
    if not with_categories:
        return [x[1] for x in flashes]
    return flashes


def _prepare_send_file_kwargs(
    download_name: t.Optional[str] = None,
    attachment_filename: t.Optional[str] = None,
    etag: t.Optional[t.Union[bool, str]] = None,
    add_etags: t.Optional[t.Union[bool]] = None,
    max_age: t.Optional[
        t.Union[int, t.Callable[[t.Optional[str]], t.Optional[int]]]
    ] = None,
    cache_timeout: t.Optional[int] = None,
    **kwargs: t.Any,
) -> t.Dict[str, t.Any]:
    if attachment_filename is not None:
        warnings.warn(
            "The 'attachment_filename' parameter has been renamed to"
            " 'download_name'. The old name will be removed in Flask"
            " 2.1.",
            DeprecationWarning,
            stacklevel=3,
        )
        download_name = attachment_filename

    if cache_timeout is not None:
        warnings.warn(
            "The 'cache_timeout' parameter has been renamed to"
            " 'max_age'. The old name will be removed in Flask 2.1.",
            DeprecationWarning,
            stacklevel=3,
        )
        max_age = cache_timeout

    if add_etags is not None:
        warnings.warn(
            "The 'add_etags' parameter has been renamed to 'etag'. The"
            " old name will be removed in Flask 2.1.",
            DeprecationWarning,
            stacklevel=3,
        )
        etag = add_etags

    if max_age is None:
        max_age = current_app.get_send_file_max_age

    kwargs.update(
        environ=request.environ,
        download_name=download_name,
        etag=etag,
        max_age=max_age,
        use_x_sendfile=current_app.use_x_sendfile,
        response_class=current_app.response_class,
        _root_path=current_app.root_path,  # type: ignore
    )
    return kwargs


def send_file(
    path_or_file: t.Union[os.PathLike, str, t.BinaryIO],
    mimetype: t.Optional[str] = None,
    as_attachment: bool = False,
    download_name: t.Optional[str] = None,
    attachment_filename: t.Optional[str] = None,
    conditional: bool = True,
    etag: t.Union[bool, str] = True,
    add_etags: t.Optional[bool] = None,
    last_modified: t.Optional[t.Union[datetime, int, float]] = None,
    max_age: t.Optional[
        t.Union[int, t.Callable[[t.Optional[str]], t.Optional[int]]]
    ] = None,
    cache_timeout: t.Optional[int] = None,
):
    return werkzeug.utils.send_file(
        **_prepare_send_file_kwargs(
            path_or_file=path_or_file,
            environ=request.environ,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=download_name,
            attachment_filename=attachment_filename,
            conditional=conditional,
            etag=etag,
            add_etags=add_etags,
            last_modified=last_modified,
            max_age=max_age,
            cache_timeout=cache_timeout,
        )
    )


def safe_join(directory: str, *pathnames: str) -> str:
    warnings.warn(
        "'flask.helpers.safe_join' is deprecated and will be removed in"
        " Flask 2.1. Use 'werkzeug.utils.safe_join' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    path = werkzeug.utils.safe_join(directory, *pathnames)

    if path is None:
        raise NotFound()

    return path


def send_from_directory(
    directory: t.Union[os.PathLike, str],
    path: t.Union[os.PathLike, str],
    filename: t.Optional[str] = None,
    **kwargs: t.Any,
) -> "Response":
    if filename is not None:
        warnings.warn(
            "The 'filename' parameter has been renamed to 'path'. The"
            " old name will be removed in Flask 2.1.",
            DeprecationWarning,
            stacklevel=2,
        )
        path = filename

    return werkzeug.utils.send_from_directory(  # type: ignore
        directory, path, **_prepare_send_file_kwargs(**kwargs)
    )


def get_root_path(import_name: str) -> str:
    # Module already imported and has a file attribute. Use that first.
    mod = sys.modules.get(import_name)

    if mod is not None and hasattr(mod, "__file__"):
        return os.path.dirname(os.path.abspath(mod.__file__))

    # Next attempt: check the loader.
    loader = pkgutil.get_loader(import_name)

    # Loader does not exist or we're referring to an unloaded main
    # module or a main module without path (interactive sessions), go
    # with the current working directory.
    if loader is None or import_name == "__main__":
        return os.getcwd()

    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name)  # type: ignore
    else:
        # Fall back to imports.
        __import__(import_name)
        mod = sys.modules[import_name]
        filepath = getattr(mod, "__file__", None)

        # If we don't have a file path it might be because it is a
        # namespace package. In this case pick the root path from the
        # first module that is contained in the package.
        if filepath is None:
            raise RuntimeError(
                "No root path can be found for the provided module"
                f" {import_name!r}. This can happen because the module"
                " came from an import hook that does not provide file"
                " name information or because it's a namespace package."
                " In this case the root path needs to be explicitly"
                " provided."
            )

    # filepath is import_name.py for a module, or __init__.py for a package.
    return os.path.dirname(os.path.abspath(filepath))


class locked_cached_property(werkzeug.utils.cached_property):
    """A :func:`property` that is only evaluated once. Like
    :class:`werkzeug.utils.cached_property` except access uses a lock
    for thread safety.

    .. versionchanged:: 2.0
        Inherits from Werkzeug's ``cached_property`` (and ``property``).
    """

    def __init__(
        self,
        fget: t.Callable[[t.Any], t.Any],
        name: t.Optional[str] = None,
        doc: t.Optional[str] = None,
    ) -> None:
        super().__init__(fget, name=name, doc=doc)
        self.lock = RLock()

    def __get__(self, obj: object, type: type = None) -> t.Any:  # type: ignore
        if obj is None:
            return self

        with self.lock:
            return super().__get__(obj, type=type)

    def __set__(self, obj: object, value: t.Any) -> None:
        with self.lock:
            super().__set__(obj, value)

    def __delete__(self, obj: object) -> None:
        with self.lock:
            super().__delete__(obj)


def total_seconds(td: timedelta) -> int:
    warnings.warn(
        "'total_seconds' is deprecated and will be removed in Flask"
        " 2.1. Use 'timedelta.total_seconds' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return td.days * 60 * 60 * 24 + td.seconds


def is_ip(value: str) -> bool:
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            socket.inet_pton(family, value)
        except OSError:
            pass
        else:
            return True

    return False


@lru_cache(maxsize=None)
def _split_blueprint_path(name: str) -> t.List[str]:
    out: t.List[str] = [name]

    if "." in name:
        out.extend(_split_blueprint_path(name.rpartition(".")[0]))

    return out

