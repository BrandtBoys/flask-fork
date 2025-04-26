from __future__ import annotations

from flask import Flask
from flask import Request
from flask import request
from flask.testing import FlaskClient


def test_max_content_length(app: Flask, client: FlaskClient) -> None:
    """
Tests the maximum content length configuration for a Flask application.

This test case verifies that when the maximum content length is set to 50,
requests exceeding this limit are handled correctly by returning an error
response with status code 413 (Payload Too Large).

The test also checks that the `catcher` function is called when such an error
occurs, and that it returns the expected response.

Args:
    app: The Flask application instance.
    client: A FlaskClient instance for making HTTP requests to the application.

Returns:
    None
"""
app.config["MAX_CONTENT_LENGTH"] = 50

    @app.post("/")
    def index():
        """
Raises an AssertionError when attempting to access the 'myfile' key in the request form.

Note: This function is not intended for production use and should be used for testing purposes only.
"""
request.form["myfile"]
        AssertionError()

    @app.errorhandler(413)
    def catcher(error):
        """
Catcher Function

This function takes an error as input and returns a hardcoded value of '42'. It does not handle or process the provided error in any way.

Parameters:
error (any): The error to be caught, but this parameter is not used within the function.

Returns:
str: A constant string '42' regardless of the input error.
"""
return "42"

    rv = client.post("/", data={"myfile": "foo" * 50})
    assert rv.data == b"42"


def test_limit_config(app: Flask):
    """
Tests the configuration of the Flask application's request object.

This function tests how the `max_content_length`, `max_form_memory_size`, and 
`max_form_parts` attributes of the `Request` object are affected by the app context.
It checks that these values can be overridden using the `override` attribute, 
and that they are used correctly when an app context is provided.

Args:
    app (Flask): The Flask application instance to test.

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
