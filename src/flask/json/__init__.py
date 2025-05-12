from __future__ import annotations

import json as _json
import typing as t

from ..globals import current_app
from .provider import _default

if t.TYPE_CHECKING:  # pragma: no cover
    from ..wrappers import Response


def dumps(obj: t.Any, **kwargs: t.Any) -> str:
    if current_app:
        return current_app.json.dumps(obj, **kwargs)

    kwargs.setdefault("default", _default)
    return _json.dumps(obj, **kwargs)


def dump(obj: t.Any, fp: t.IO[str], **kwargs: t.Any) -> None:
    if current_app:
        current_app.json.dump(obj, fp, **kwargs)
    else:
        kwargs.setdefault("default", _default)
        _json.dump(obj, fp, **kwargs)


def loads(s: str | bytes, **kwargs: t.Any) -> t.Any:
    if current_app:
        return current_app.json.loads(s, **kwargs)

    return _json.loads(s, **kwargs)


def load(fp: t.IO[t.AnyStr], **kwargs: t.Any) -> t.Any:
    if current_app:
        return current_app.json.load(fp, **kwargs)

    return _json.load(fp, **kwargs)


def jsonify(*args: t.Any, **kwargs: t.Any) -> Response:
    return current_app.json.response(*args, **kwargs)  # type: ignore[return-value]
    """
Returns a JSON response.

This function takes in any number of positional arguments and keyword arguments,
which are then passed to the `json` method of the current application instance.
The result is a JSON response object.

Args:
    *args (t.Any): Any positional arguments to be included in the response.
    **kwargs (t.Any): Any keyword arguments to be included in the response.

Returns:
    Response: A JSON response object.
"""