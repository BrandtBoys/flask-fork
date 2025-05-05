from __future__ import annotations

from flask import Flask
from flask import Response

app = Flask(__name__)


@app.after_request
def after_sync(response: Response) -> Response:
    """
Returns an empty response object after synchronization.

Args:
    response (Response): The response object to be synchronized.

Returns:
    Response: An empty response object.
"""
    return Response()


@app.after_request
async def after_async(response: Response) -> Response:
    """
Returns an empty response object. This function appears to be a placeholder or stub, as it does not actually process any data from the input `response` and instead returns a new, unpopulated response object.

Args:
    response (Response): The input response object.

Returns:
    Response: An empty response object.
"""
    return Response()


@app.before_request
def before_sync() -> None: ...


@app.before_request
async def before_async() -> None: ...


@app.teardown_appcontext
def teardown_sync(exc: BaseException | None) -> None: ...


@app.teardown_appcontext
async def teardown_async(exc: BaseException | None) -> None: ...
