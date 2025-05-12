from __future__ import annotations

import json as _json
import typing as t

from jinja2.utils import htmlsafe_json_dumps as _jinja_htmlsafe_dumps

from ..globals import current_app
from .provider import _default

if t.TYPE_CHECKING:  # pragma: no cover
    from ..app import Flask
    from ..wrappers import Response


class JSONEncoder(_json.JSONEncoder):
    """The default JSON encoder. Handles extra types compared to the
    built-in :class:`json.JSONEncoder`.

    -   :class:`datetime.datetime` and :class:`datetime.date` are
        serialized to :rfc:`822` strings. This is the same as the HTTP
        date format.
    -   :class:`decimal.Decimal` is serialized to a string.
    -   :class:`uuid.UUID` is serialized to a string.
    -   :class:`dataclasses.dataclass` is passed to
        :func:`dataclasses.asdict`.
    -   :class:`~markupsafe.Markup` (or any object with a ``__html__``
        method) will call the ``__html__`` method to get a string.

    Assign a subclass of this to :attr:`flask.Flask.json_encoder` or
    :attr:`flask.Blueprint.json_encoder` to override the default.

    .. deprecated:: 2.2
        Will be removed in Flask 2.3. Use ``app.json`` instead.
    """

    def __init__(self, **kwargs) -> None:
        import warnings

        warnings.warn(
            "'JSONEncoder' is deprecated and will be removed in"
            " Flask 2.3. Use 'Flask.json' to provide an alternate"
            " JSON implementation instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        super().__init__(**kwargs)

    def default(self, o: t.Any) -> t.Any:
        return _default(o)


class JSONDecoder(_json.JSONDecoder):
    """The default JSON decoder.

    This does not change any behavior from the built-in
    :class:`json.JSONDecoder`.

    Assign a subclass of this to :attr:`flask.Flask.json_decoder` or
    :attr:`flask.Blueprint.json_decoder` to override the default.

    .. deprecated:: 2.2
        Will be removed in Flask 2.3. Use ``app.json`` instead.
    """

    def __init__(self, **kwargs) -> None:
        import warnings

        warnings.warn(
            "'JSONDecoder' is deprecated and will be removed in"
            " Flask 2.3. Use 'Flask.json' to provide an alternate"
            " JSON implementation instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        super().__init__(**kwargs)


def dumps(obj: t.Any, *, app: Flask | None = None, **kwargs: t.Any) -> str:
    if app is not None:
        import warnings

        warnings.warn(
            "The 'app' parameter is deprecated and will be removed in"
            " Flask 2.3. Call 'app.json.dumps' directly instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    else:
        app = current_app

    if app:
        return app.json.dumps(obj, **kwargs)

    kwargs.setdefault("default", _default)
    return _json.dumps(obj, **kwargs)


def dump(
    obj: t.Any, fp: t.IO[str], *, app: Flask | None = None, **kwargs: t.Any
) -> None:
    if app is not None:
        import warnings

        warnings.warn(
            "The 'app' parameter is deprecated and will be removed in"
            " Flask 2.3. Call 'app.json.dump' directly instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    else:
        app = current_app

    if app:
        app.json.dump(obj, fp, **kwargs)
    else:
        kwargs.setdefault("default", _default)
        _json.dump(obj, fp, **kwargs)


def loads(s: str | bytes, *, app: Flask | None = None, **kwargs: t.Any) -> t.Any:
    if app is not None:
        import warnings

        warnings.warn(
            "The 'app' parameter is deprecated and will be removed in"
            " Flask 2.3. Call 'app.json.loads' directly instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    else:
        app = current_app

    if app:
        return app.json.loads(s, **kwargs)

    return _json.loads(s, **kwargs)


def load(fp: t.IO[t.AnyStr], *, app: Flask | None = None, **kwargs: t.Any) -> t.Any:
    if app is not None:
        import warnings

        warnings.warn(
            "The 'app' parameter is deprecated and will be removed in"
            " Flask 2.3. Call 'app.json.load' directly instead.",
            DeprecationWarning,
            stacklevel=2,
        )
    else:
        app = current_app

    if app:
        return app.json.load(fp, **kwargs)

    return _json.load(fp, **kwargs)


def htmlsafe_dumps(obj: t.Any, **kwargs: t.Any) -> str:
    import warnings

    warnings.warn(
        "'htmlsafe_dumps' is deprecated and will be removed in Flask"
        " 2.3. Use 'jinja2.utils.htmlsafe_json_dumps' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return _jinja_htmlsafe_dumps(obj, dumps=dumps, **kwargs)


def htmlsafe_dump(obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None:
    import warnings

    warnings.warn(
        "'htmlsafe_dump' is deprecated and will be removed in Flask"
        " 2.3. Use 'jinja2.utils.htmlsafe_json_dumps' instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    fp.write(htmlsafe_dumps(obj, **kwargs))


def jsonify(*args: t.Any, **kwargs: t.Any) -> Response:
    return current_app.json.response(*args, **kwargs)

