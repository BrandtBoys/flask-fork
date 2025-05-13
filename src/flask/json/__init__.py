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
    """
Dumps the provided object to a file stream.

This function is used to serialize and dump objects to a file. It supports both Flask's `current_app.json` and the standard `_json` library for dumping objects.

Args:
    obj (t.Any): The object to be dumped.
    fp (t.IO[str]): The file stream where the object will be written.
    **kwargs (t.Any): Additional keyword arguments to be passed to the dump function. If `current_app` is not set, these arguments are used to configure the dumping process.

Returns:
    None
"""
    if current_app:
        current_app.json.dump(obj, fp, **kwargs)
    else:
        kwargs.setdefault("default", _default)
        _json.dump(obj, fp, **kwargs)


def loads(s: str | bytes, **kwargs: t.Any) -> t.Any:
    """
Loads JSON data from a string or bytes object.

This function is used to parse JSON data from various sources. It can handle both strings and bytes objects as input.
The `current_app` variable is used to determine the context in which this function is being called. If it exists, 
it will use its `json.loads` method to parse the data. Otherwise, it will fall back to a generic `_json.loads` method.

Args:
    s (str | bytes): The JSON data to be loaded.
    **kwargs: Additional keyword arguments to be passed to the parsing function.

Returns:
    t.Any: The parsed JSON data.

Raises:
    None
"""
    if current_app:
        return current_app.json.loads(s, **kwargs)

    return _json.loads(s, **kwargs)


def load(fp: t.IO[t.AnyStr], **kwargs: t.Any) -> t.Any:
    """
Loads JSON data from a file.

This function takes an open file object `fp` and optional keyword arguments `**kwargs`.
If the `current_app` context is available, it will use its `json.load()` method to load the data.
Otherwise, it falls back to using `_json.load()`.

Args:
    fp (IO[AnyStr]): The file object containing the JSON data.
    **kwargs: Optional keyword arguments to pass to the loading function.

Returns:
    Any: The loaded JSON data.
"""
    if current_app:
        return current_app.json.load(fp, **kwargs)

    return _json.load(fp, **kwargs)


def jsonify(*args: t.Any, **kwargs: t.Any) -> Response:
    return current_app.json.response(*args, **kwargs)
