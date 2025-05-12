import os
import pkgutil
import socket
import sys
import typing as t
from datetime import datetime
from functools import lru_cache
from functools import update_wrapper
from threading import RLock

import werkzeug.utils
from werkzeug.exceptions import abort as _wz_abort
from werkzeug.utils import redirect as _wz_redirect

from .globals import _cv_request
from .globals import current_app
from .globals import request
from .globals import request_ctx
from .globals import session
from .signals import message_flashed

if t.TYPE_CHECKING:  # pragma: no cover
    from werkzeug.wrappers import Response as BaseResponse
    from .wrappers import Response
    import typing_extensions as te


def get_env() -> str:
    import warnings

    warnings.warn(
        "'FLASK_ENV' and 'get_env' are deprecated and will be removed"
        " in Flask 2.3. Use 'FLASK_DEBUG' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return os.environ.get("FLASK_ENV") or "production"


def get_debug_flag() -> bool:
    val = os.environ.get("FLASK_DEBUG")

    if not val:
        env = os.environ.get("FLASK_ENV")

        if env is not None:
            print(
                "'FLASK_ENV' is deprecated and will not be used in"
                " Flask 2.3. Use 'FLASK_DEBUG' instead.",
                file=sys.stderr,
            )
            return env == "development"

        return False

    return val.lower() not in {"0", "false", "no"}


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
        ctx = _cv_request.get(None)
        if ctx is None:
            raise RuntimeError(
                "'stream_with_context' can only be used when a request"
                " context is active, such as in a view function."
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
                    gen.close()

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
    return current_app.make_response(args)  # type: ignore


def url_for(
    endpoint: str,
    *,
    _anchor: t.Optional[str] = None,
    _method: t.Optional[str] = None,
    _scheme: t.Optional[str] = None,
    _external: t.Optional[bool] = None,
    **values: t.Any,
) -> str:
    return current_app.url_for(
        endpoint,
        _anchor=_anchor,
        _method=_method,
        _scheme=_scheme,
        _external=_external,
        **values,
    )


def redirect(
    location: str, code: int = 302, Response: t.Optional[t.Type["BaseResponse"]] = None
) -> "BaseResponse":
    if current_app:
        return current_app.redirect(location, code=code)

    return _wz_redirect(location, code=code, Response=Response)


def abort(
    code: t.Union[int, "BaseResponse"], *args: t.Any, **kwargs: t.Any
) -> "te.NoReturn":
    if current_app:
        current_app.aborter(code, *args, **kwargs)

    _wz_abort(code, *args, **kwargs)


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
    flashes = request_ctx.flashes
    if flashes is None:
        flashes = session.pop("_flashes") if "_flashes" in session else []
        request_ctx.flashes = flashes
    if category_filter:
        flashes = list(filter(lambda f: f[0] in category_filter, flashes))
    if not with_categories:
        return [x[1] for x in flashes]
    return flashes


def _prepare_send_file_kwargs(**kwargs: t.Any) -> t.Dict[str, t.Any]:
    if kwargs.get("max_age") is None:
        kwargs["max_age"] = current_app.get_send_file_max_age

    kwargs.update(
        environ=request.environ,
        use_x_sendfile=current_app.config["USE_X_SENDFILE"],
        response_class=current_app.response_class,
        _root_path=current_app.root_path,  # type: ignore
    )
    return kwargs


def send_file(
    path_or_file: t.Union[os.PathLike, str, t.BinaryIO],
    mimetype: t.Optional[str] = None,
    as_attachment: bool = False,
    download_name: t.Optional[str] = None,
    conditional: bool = True,
    etag: t.Union[bool, str] = True,
    last_modified: t.Optional[t.Union[datetime, int, float]] = None,
    max_age: t.Optional[
        t.Union[int, t.Callable[[t.Optional[str]], t.Optional[int]]]
    ] = None,
) -> "Response":
    return werkzeug.utils.send_file(  # type: ignore[return-value]
        **_prepare_send_file_kwargs(
            path_or_file=path_or_file,
            environ=request.environ,
            mimetype=mimetype,
            as_attachment=as_attachment,
            download_name=download_name,
            conditional=conditional,
            etag=etag,
            last_modified=last_modified,
            max_age=max_age,
        )
    )


def send_from_directory(
    directory: t.Union[os.PathLike, str],
    path: t.Union[os.PathLike, str],
    **kwargs: t.Any,
) -> "Response":
    return werkzeug.utils.send_from_directory(  # type: ignore[return-value]
        directory, path, **_prepare_send_file_kwargs(**kwargs)
    )


def get_root_path(import_name: str) -> str:
    # Module already imported and has a file attribute. Use that first.
    mod = sys.modules.get(import_name)

    if mod is not None and hasattr(mod, "__file__") and mod.__file__ is not None:
        return os.path.dirname(os.path.abspath(mod.__file__))

    # Next attempt: check the loader.
    loader = pkgutil.get_loader(import_name)

    # Loader does not exist or we're referring to an unloaded main
    # module or a main module without path (interactive sessions), go
    # with the current working directory.
    if loader is None or import_name == "__main__":
        return os.getcwd()

    if hasattr(loader, "get_filename"):
        filepath = loader.get_filename(import_name)
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

