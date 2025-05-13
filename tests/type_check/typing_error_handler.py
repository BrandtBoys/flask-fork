from __future__ import annotations

from http import HTTPStatus

from werkzeug.exceptions import BadRequest
from werkzeug.exceptions import NotFound

from flask import Flask

app = Flask(__name__)


@app.errorhandler(400)
@app.errorhandler(HTTPStatus.BAD_REQUEST)
@app.errorhandler(BadRequest)
def handle_400(e: BadRequest) -> str:
    """
Handles 400 Bad Request exceptions by returning an empty string.

Args:
    e (BadRequest): The exception object containing information about the bad request.

Returns:
    str: An empty string indicating that the request was not processed.
"""
    return ""


@app.errorhandler(ValueError)
def handle_custom(e: ValueError) -> str:
    """
Handles custom exceptions by returning an empty string.

Args:
    e (ValueError): The exception to be handled.

Returns:
    str: An empty string.
"""
    return ""


@app.errorhandler(ValueError)
def handle_accept_base(e: Exception) -> str:
    """
Handles an exception raised during base acceptance.

Args:
    e (Exception): The exception object that was raised.

Returns:
    str: An empty string indicating successful handling of the exception.
"""
    return ""


@app.errorhandler(BadRequest)
@app.errorhandler(404)
def handle_multiple(e: BadRequest | NotFound) -> str:
    """
Handles exceptions raised by API endpoints.

This function takes an exception object of type `BadRequest` or `NotFound` and returns a string response.
If no exception is provided, it returns an empty string.

Args:
    e (BadRequest | NotFound): The exception to be handled.

Returns:
    str: A string representation of the error response.
"""
    return ""
