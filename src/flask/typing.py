from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:  
    from _typeshed.wsgi import WSGIApplication  
    from werkzeug.datastructures import Headers  
    from werkzeug.sansio.response import Response  


ResponseValue = t.Union[
    "Response",
    str,
    bytes,
    list[t.Any],
# Only dict is actually accepted, but Mapping allows for TypedDict.
    
    t.Mapping[str, t.Any],
    t.Iterator[str],
    t.Iterator[bytes],
]



HeaderValue = t.Union[str, list[str], tuple[str, ...]]


HeadersValue = t.Union[
    "Headers",
    t.Mapping[str, HeaderValue],
    t.Sequence[tuple[str, HeaderValue]],
]


ResponseReturnValue = t.Union[
    ResponseValue,
    tuple[ResponseValue, HeadersValue],
    tuple[ResponseValue, int],
    tuple[ResponseValue, int, HeadersValue],
    "WSGIApplication",
]




ResponseClass = t.TypeVar("ResponseClass", bound="Response")

AppOrBlueprintKey = t.Optional[str]  
AfterRequestCallable = t.Union[
    t.Callable[[ResponseClass], ResponseClass],
    t.Callable[[ResponseClass], t.Awaitable[ResponseClass]],
]
BeforeFirstRequestCallable = t.Union[
    t.Callable[[], None], t.Callable[[], t.Awaitable[None]]
]
BeforeRequestCallable = t.Union[
    t.Callable[[], t.Optional[ResponseReturnValue]],
    t.Callable[[], t.Awaitable[t.Optional[ResponseReturnValue]]],
]
ShellContextProcessorCallable = t.Callable[[], dict[str, t.Any]]
TeardownCallable = t.Union[
    t.Callable[[t.Optional[BaseException]], None],
    t.Callable[[t.Optional[BaseException]], t.Awaitable[None]],
]
TemplateContextProcessorCallable = t.Union[
    t.Callable[[], dict[str, t.Any]],
    t.Callable[[], t.Awaitable[dict[str, t.Any]]],
]
TemplateFilterCallable = t.Callable[..., t.Any]
TemplateGlobalCallable = t.Callable[..., t.Any]
TemplateTestCallable = t.Callable[..., bool]
URLDefaultCallable = t.Callable[[str, dict[str, t.Any]], None]
URLValuePreprocessorCallable = t.Callable[
    [t.Optional[str], t.Optional[dict[str, t.Any]]], None
]







ErrorHandlerCallable = t.Union[
    t.Callable[[t.Any], ResponseReturnValue],
    t.Callable[[t.Any], t.Awaitable[ResponseReturnValue]],
]

RouteCallable = t.Union[
    t.Callable[..., ResponseReturnValue],
    t.Callable[..., t.Awaitable[ResponseReturnValue]],
]
