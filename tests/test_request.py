from __future__ import annotations

from flask import Flask
from flask import Request
from flask import request
from flask.testing import FlaskClient


def test_max_content_length(app: Flask, client: FlaskClient) -> None:
    """
Tests the maximum content length configuration for a Flask application.

This test case verifies that when the maximum content length is set to 50, 
a POST request with a file larger than this limit will return an error response.
It also checks if the error handler correctly returns "42" in such cases.

Args:
    app (Flask): The Flask application instance.
    client (FlaskClient): The client instance used for making HTTP requests.

Returns:
    None
"""
    app.config["MAX_CONTENT_LENGTH"] = 50

    @app.post("/")
    def index():
        """
Raises an AssertionError when attempting to access the 'myfile' key in the request form.

Note: This function is likely intended to demonstrate a security vulnerability or test for a specific error condition.
"""
        request.form["myfile"]
        AssertionError()

    @app.errorhandler(413)
    def catcher(error):
        """
Catcher Function

This function takes an error as input and returns a predefined value.

Args:
    error (any): The input error to be caught.

Returns:
    str: A predefined string '42' indicating that the error has been caught.
"""
        return "42"

    rv = client.post("/", data={"myfile": "foo" * 50})
    assert rv.data == b"42"


def test_limit_config(app: Flask):
    """
Tests the configuration of the `Request` object in relation to Flask's application context.

This function tests how the `max_content_length`, `max_form_memory_size`, and `max_form_parts`
attributes of the `Request` object are affected by the presence or absence of an application context.
It also checks that overriding these attributes outside of an app context still applies when an app
context is later established.

Args:
    app (Flask): The Flask application instance to test with.

Returns:
    None
"""
    app.config["MAX_CONTENT_LENGTH"] = 100
    app.config["MAX_FORM_MEMORY_SIZE"] = 50
    app.config["MAX_FORM_PARTS"] = 3
    r = Request({})

    # no app context, use Werkzeug defaults
    assert r.max_content_length is None
    assert r.max_form_memory_size == 500_000
    assert r.max_form_parts == 1_000

    # in app context, use config
    with app.app_context():
        assert r.max_content_length == 100
        assert r.max_form_memory_size == 50
        assert r.max_form_parts == 3

    # regardless of app context, use override
    r.max_content_length = 90
    r.max_form_memory_size = 30
    r.max_form_parts = 4

    assert r.max_content_length == 90
    assert r.max_form_memory_size == 30
    assert r.max_form_parts == 4

    with app.app_context():
        assert r.max_content_length == 90
        assert r.max_form_memory_size == 30
        assert r.max_form_parts == 4
