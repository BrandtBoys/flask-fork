# -*- coding: utf-8 -*-
"""
    Flask Tests
    ~~~~~~~~~~~

    Tests Flask itself.  The majority of Flask is already tested
    as part of Werkzeug.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
from __future__ import with_statement
import flask
import unittest
import tempfile


class ContextTestCase(unittest.TestCase):

    def test_context_binding(self):
        app = flask.Flask(__name__)
        @app.route('/')
        def index():
            """
Returns a personalized greeting message.

This function takes advantage of Flask's request object to access query parameters.
It expects the 'name' parameter to be passed in the URL as a query string.

Args:
    None

Returns:
    str: A personalized greeting message.

Example:
    flask.run(app, host='localhost', port=5000)
    >>> app.index()
    'Hello World!'
"""
            return 'Hello %s!' % flask.request.args['name']
        @app.route('/meh')
        def meh():
            """
Returns the URL of the current request.

This function is a simple wrapper around Flask's `request` object, providing direct access to the URL of the incoming request. It can be used in various contexts, such as logging or redirecting users to different pages based on their location.

Args:
    None

Returns:
    str: The URL of the current request.
"""
            return flask.request.url

        with app.test_request_context('/?name=World'):
            assert index() == 'Hello World!'
        with app.test_request_context('/meh'):
            assert meh() == 'http://localhost/meh'

    def test_request_dispatching(self):
        """
Tests the request dispatching behavior of Flask's route handlers.

This test suite verifies that different HTTP methods are dispatched to their respective handlers.
It checks for correct status codes, allowed methods, and response data.

- `c.get('/')` should return a response with method 'GET'.
- `c.post('/')` should return a response with status code 405 (Method Not Allowed) and allowed methods ['GET', 'HEAD'].
- `c.head('/')` should return a response with status code 200 and no data.
- `c.post('/more')` should return a response with method 'POST'.
- `c.get('/more')` should return a response with method 'GET'.
- `c.delete('/more')` should return a response with status code 405 (Method Not Allowed) and allowed methods ['GET', 'HEAD', 'POST'].
"""
        app = flask.Flask(__name__)
        @app.route('/')
        def index():
            """
Returns the HTTP method of the current request.

Args:
    None

Returns:
    str: The HTTP method (e.g., 'GET', 'POST', etc.)

Raises:
    None

Example:
    >>> app.index()
    'GET'
"""
            return flask.request.method
        @app.route('/more', methods=['GET', 'POST'])
        def more():
            """
Returns the HTTP method of the current request.

Args:
    None

Returns:
    str: The HTTP method (e.g. 'GET', 'POST', etc.)

Raises:
    None

Example:
    >>> from your_module import more
    >>> print(more())  # prints the HTTP method of the current request
"""
            return flask.request.method

        c = app.test_client()
        assert c.get('/').data == 'GET'
        rv = c.post('/')
        assert rv.status_code == 405
        assert sorted(rv.allow) == ['GET', 'HEAD']
        rv = c.head('/')
        assert rv.status_code == 200
        assert not rv.data # head truncates
        assert c.post('/more').data == 'POST'
        assert c.get('/more').data == 'GET'
        rv = c.delete('/more')
        assert rv.status_code == 405
        assert sorted(rv.allow) == ['GET', 'HEAD', 'POST']

    def test_session(self):
        """
Tests the functionality of a Flask application's session.

This test case verifies that the `test_session` method correctly sets and retrieves values from the session using a Flask test client.

- It creates a new Flask application instance.
- Sets a secret key for the application.
- Defines two routes: `/set` to set a value in the session, and `/get` to retrieve a value from the session.
- Uses a test client to simulate a POST request to `/set` with a value of '42', and verifies that the response is 'value set'.
- Uses the same test client to simulate a GET request to `/get`, and verifies that the response is '42'.

Note: This test case assumes that the Flask session is properly configured and initialized before running this test.
"""
        app = flask.Flask(__name__)
        app.secret_key = 'testkey'
        @app.route('/set', methods=['POST'])
        def set():
            """
Sets the value in the Flask session.

This function takes no arguments and modifies the `value` key in the Flask session.
It retrieves the `value` from the request form data and assigns it to the session.
Returns a success message indicating that the value has been set. 

Args:
    None

Returns:
    str: A success message
"""
            flask.session['value'] = flask.request.form['value']
            return 'value set'
        @app.route('/get')
        def get():
            """
Returns the value from the Flask session dictionary. 

    Args:
        None

    Returns:
        The value stored in the Flask session dictionary.

    Raises:
        KeyError: If the 'value' key is not found in the session dictionary.
"""
            return flask.session['value']

        c = app.test_client()
        assert c.post('/set', data={'value': '42'}).data == 'value set'
        assert c.get('/get').data == '42'

    def test_url_generation(self):
        app = flask.Flask(__name__)
        @app.route('/hello/<name>', methods=['POST'])
        def hello():
            pass
        with app.test_request_context():
            assert flask.url_for('hello', name='test x') == '/hello/test%20x'


if __name__ == '__main__':
    unittest.main()
