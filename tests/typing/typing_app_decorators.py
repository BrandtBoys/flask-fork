from __future__ import annotations

from flask import Flask
from flask import Response

app = Flask(__name__)


@app.after_request
def after_sync(response: Response) -> Response:
    return Response()


@app.after_request
async def after_async(response: Response) -> Response:
    return Response()


@app.before_request
def before_sync() -> None:
    ...


@app.before_request
async def before_async() -> None:
    ...


@app.teardown_appcontext
def teardown_sync(exc: BaseException | None) -> None:
    """
Teardowns synchronization after an exception.

This function is called when an exception occurs during a sync operation. It ensures that any ongoing synchronization operations are properly cleaned up to prevent resource leaks or other issues.

Args:
    exc (BaseException | None): The exception that occurred during the sync operation, or None if no exception occurred.
"""
    ...


@app.teardown_appcontext
async def teardown_async(exc: BaseException | None) -> None:
    ...
