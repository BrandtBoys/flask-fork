import decimal
import io
import json as _json
import typing as t
import uuid
import warnings
from datetime import date

from jinja2.utils import htmlsafe_json_dumps as _jinja_htmlsafe_dumps
from werkzeug.http import http_date

from ..globals import current_app
from ..globals import request

if t.TYPE_CHECKING:
    from ..app import Flask
    from ..wrappers import Response

try:
    import dataclasses
except ImportError:
    # Python < 3.7
    dataclasses = None  # type: ignore


class JSONEncoder(_json.JSONEncoder):
    """The default JSON encoder. Handles extra types compared to the
    built-in :class:`json.JSONEncoder`.

    -   :class:`datetime.datetime` and :class:`datetime.date` are
        serialized to :rfc:`822` strings. This is the same as the HTTP
        date format.
    -   :class:`uuid.UUID` is serialized to a string.
    -   :class:`dataclasses.dataclass` is passed to
        :func:`dataclasses.asdict`.
    -   :class:`~markupsafe.Markup` (or any object with a ``__html__``
        method) will call the ``__html__`` method to get a string.

    Assign a subclass of this to :attr:`flask.Flask.json_encoder` or
    :attr:`flask.Blueprint.json_encoder` to override the default.
    """

    def default(self, o: t.Any) -> t.Any:
        if isinstance(o, date):
            return http_date(o)
        if isinstance(o, (decimal.Decimal, uuid.UUID)):
            return str(o)
        if dataclasses and dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if hasattr(o, "__html__"):
            return str(o.__html__())
        return super().default(o)


class JSONDecoder(_json.JSONDecoder):
    """The default JSON decoder.

    This does not change any behavior from the built-in
    :class:`json.JSONDecoder`.

    Assign a subclass of this to :attr:`flask.Flask.json_decoder` or
    :attr:`flask.Blueprint.json_decoder` to override the default.
    """


def _dump_arg_defaults(
    kwargs: t.Dict[str, t.Any], app: t.Optional["Flask"] = None
) -> None:
    if app is None:
        app = current_app

    if app:
        cls = app.json_encoder
        bp = app.blueprints.get(request.blueprint) if request else None  # type: ignore
        if bp is not None and bp.json_encoder is not None:
            cls = bp.json_encoder

        kwargs.setdefault("cls", cls)
        kwargs.setdefault("ensure_ascii", app.config["JSON_AS_ASCII"])
        kwargs.setdefault("sort_keys", app.config["JSON_SORT_KEYS"])
    else:
        kwargs.setdefault("sort_keys", True)
        kwargs.setdefault("cls", JSONEncoder)


def _load_arg_defaults(
    kwargs: t.Dict[str, t.Any], app: t.Optional["Flask"] = None
) -> None:
    if app is None:
        app = current_app

    if app:
        cls = app.json_decoder
        bp = app.blueprints.get(request.blueprint) if request else None  # type: ignore
        if bp is not None and bp.json_decoder is not None:
            cls = bp.json_decoder

        kwargs.setdefault("cls", cls)
    else:
        kwargs.setdefault("cls", JSONDecoder)


def dumps(obj: t.Any, app: t.Optional["Flask"] = None, **kwargs: t.Any) -> str:
    _dump_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)
    rv = _json.dumps(obj, **kwargs)

    if encoding is not None:
        warnings.warn(
            "'encoding' is deprecated and will be removed in Flask 2.1.",
            DeprecationWarning,
            stacklevel=2,
        )

        if isinstance(rv, str):
            return rv.encode(encoding)  # type: ignore

    return rv


def dump(
    obj: t.Any, fp: t.IO[str], app: t.Optional["Flask"] = None, **kwargs: t.Any
) -> None:
    _dump_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)
    show_warning = encoding is not None

    try:
        fp.write("")
    except TypeError:
        show_warning = True
        fp = io.TextIOWrapper(fp, encoding or "utf-8")  # type: ignore

    if show_warning:
        warnings.warn(
            "Writing to a binary file, and the 'encoding' argument, is"
            " deprecated and will be removed in Flask 2.1.",
            DeprecationWarning,
            stacklevel=2,
        )

    _json.dump(obj, fp, **kwargs)


def loads(s: str, app: t.Optional["Flask"] = None, **kwargs: t.Any) -> t.Any:
    _load_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)

    if encoding is not None:
        warnings.warn(
            "'encoding' is deprecated and will be removed in Flask 2.1."
            " The data must be a string or UTF-8 bytes.",
            DeprecationWarning,
            stacklevel=2,
        )

        if isinstance(s, bytes):
            s = s.decode(encoding)

    return _json.loads(s, **kwargs)


def load(fp: t.IO[str], app: t.Optional["Flask"] = None, **kwargs: t.Any) -> t.Any:
    _load_arg_defaults(kwargs, app=app)
    encoding = kwargs.pop("encoding", None)

    if encoding is not None:
        warnings.warn(
            "'encoding' is deprecated and will be removed in Flask 2.1."
            " The file must be text mode, or binary mode with UTF-8"
            " bytes.",
            DeprecationWarning,
            stacklevel=2,
        )

        if isinstance(fp.read(0), bytes):
            fp = io.TextIOWrapper(fp, encoding)  # type: ignore

    return _json.load(fp, **kwargs)


def htmlsafe_dumps(obj: t.Any, **kwargs: t.Any) -> str:
    return _jinja_htmlsafe_dumps(obj, dumps=dumps, **kwargs)


def htmlsafe_dump(obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None:
    fp.write(htmlsafe_dumps(obj, **kwargs))


def jsonify(*args: t.Any, **kwargs: t.Any) -> "Response":
    indent = None
    separators = (",", ":")

    if current_app.config["JSONIFY_PRETTYPRINT_REGULAR"] or current_app.debug:
        indent = 2
        separators = (", ", ": ")

    if args and kwargs:
        raise TypeError("jsonify() behavior undefined when passed both args and kwargs")
    elif len(args) == 1:  # single args are passed directly to dumps()
        data = args[0]
    else:
        data = args or kwargs

    return current_app.response_class(
        f"{dumps(data, indent=indent, separators=separators)}\n",
        mimetype=current_app.config["JSONIFY_MIMETYPE"],
    )

