# -*- coding: utf-8 -*-
"""
    flask
    ~~~~~

    A microframework based on Werkzeug.  It's extensively documented
    and follows best practice patterns.

    :copyright: (c) 2010 by Armin Ronacher.
    :license: BSD, see LICENSE for more details.
"""
import os
import sys
import pkg_resources
from threading import local
from contextlib import contextmanager
from jinja2 import Environment, PackageLoader
from werkzeug import Request as RequestBase, Response as ResponseBase, \
     LocalStack, LocalProxy, create_environ, cached_property
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, InternalServerError
from werkzeug.contrib.securecookie import SecureCookie

# utilities we import from Werkzeug and Jinja2 that are unused
# in the module but are exported as public interface.
from werkzeug import abort, redirect
from jinja2 import Markup, escape


class Request(RequestBase):
    """The request object used by default in flask.  Remembers the
    matched endpoint and view arguments.

    It is what ends up as :class:`~flask.request`.  If you want to replace
    the request object used you can subclass this and set
    :attr:`~flask.Flask.request_class` to your subclass.
    """

    def __init__(self, environ):
        """
Initialize a new instance of the class.

Parameters:
    environ (object): The environment object passed to the parent class's constructor.

Raises:
    None

Attributes:
    endpoint (str): The endpoint URL for this request.
    view_args (dict): A dictionary of view arguments for this request.
"""
        RequestBase.__init__(self, environ)
        self.endpoint = None
        self.view_args = None


class Response(ResponseBase):
    """The response object that is used by default in flask.  Works like the
    response object from Werkzeug but is set to have a HTML mimetype by
    default.  Quite often you don't have to create this object yourself because
    :meth:`~flask.Flask.make_response` will take care of that for you.

    If you want to replace the response object used you can subclass this and
    set :attr:`~flask.Flask.request_class` to your subclass.
    """
    default_mimetype = 'text/html'


class _RequestGlobals(object):
    pass


class _RequestContext(object):
    """The request context contains all request relevant information.  It is
    created at the beginning of the request and pushed to the
    `_request_ctx_stack` and removed at the end of it.  It will create the
    URL adapter and request object for the WSGI environment provided.
    """

    def __init__(self, app, environ):
        self.app = app
        self.url_adapter = app.url_map.bind_to_environ(environ)
        self.request = app.request_class(environ)
        self.session = app.open_session(self.request)
        self.g = _RequestGlobals()
        self.flashes = None


def url_for(endpoint, **values):
    return _request_ctx_stack.top.url_adapter.build(endpoint, values)


def flash(message):
    session['_flashes'] = (session.get('_flashes', [])) + [message]


def get_flashed_messages():
    flashes = _request_ctx_stack.top.flashes
    if flashes is None:
        _request_ctx_stack.top.flashes = flashes = \
            session.pop('_flashes', [])
    return flashes


def render_template(template_name, **context):
    """
Render a template with the given context.

Args:
    template_name (str): The name of the template to be rendered.
    **context: A dictionary containing variables to be passed to the template.

Returns:
    str: The rendered HTML content of the template.

Raises:
    None
"""
    current_app.update_template_context(context)
    return current_app.jinja_env.get_template(template_name).render(context)


def render_template_string(source, **context):
    """
Render a Jinja template string with given context.

This function takes a source template string and a dictionary of context variables.
It updates the application's template context with the provided variables,
and then renders the template using the `Jinja` environment from the current application.

Args:
    source (str): The Jinja template string to render.
    **context: A dictionary of variables to pass to the template.

Returns:
    str: The rendered template string.

Raises:
    None
"""
    current_app.update_template_context(context)
    return current_app.jinja_env.from_string(source).render(context)


def _default_template_ctx_processor():
    """
Processes default template context with request, session and group information.

This function retrieves the topmost request context from the `_request_ctx_stack` and returns a dictionary containing the request, session, and group attributes.

Returns:
    dict: A dictionary containing the request, session, and group attributes.
"""
reqctx = _request_ctx_stack.top
    return dict(
        request=reqctx.request,
        session=reqctx.session,
        g=reqctx.g
    )


class Flask(object):
    """The flask object implements a WSGI application and acts as the central
    object.  It is passed the name of the module or package of the
    application.  Once it is created it will act as a central registry for
    the view functions, the URL rules, template configuration and much more.

    The name of the package is used to resolve resources from inside the
    package or the folder the module is contained in depending on if the
    package parameter resolves to an actual python package (a folder with
    an `__init__.py` file inside) or a standard module (just a `.py` file).

    For more information about resource loading, see :func:`open_resource`.

    Usually you create a :class:`Flask` instance in your main module or
    in the `__init__.py` file of your package like this::

        from flask import Flask
        app = Flask(__name__)
    """

    #: the class that is used for request objects.  See :class:`~flask.request`
    #: for more information.
    request_class = Request

    #: the class that is used for response objects.  See
    #: :class:`~flask.Response` for more information.
    response_class = Response

    #: path for the static files.  If you don't want to use static files
    #: you can set this value to `None` in which case no URL rule is added
    #: and the development server will no longer serve any static files.
    static_path = '/static'

    #: if a secret key is set, cryptographic components can use this to
    #: sign cookies and other things.  Set this to a complex random value
    #: when you want to use the secure cookie for instance.
    secret_key = None

    #: The secure cookie uses this for the name of the session cookie
    session_cookie_name = 'session'

    #: options that are passed directly to the Jinja2 environment
    jinja_options = dict(
        autoescape=True,
        extensions=['jinja2.ext.autoescape', 'jinja2.ext.with_']
    )

    def __init__(self, package_name):
        #: the debug flag.  Set this to `True` to enable debugging of
        #: the application.  In debug mode the debugger will kick in
        #: when an unhandled exception ocurrs and the integrated server
        #: will automatically reload the application if changes in the
        #: code are detected.
        self.debug = False

        #: the name of the package or module.  Do not change this once
        #: it was set by the constructor.
        self.package_name = package_name

        #: a dictionary of all view functions registered.  The keys will
        #: be function names which are also used to generate URLs and
        #: the values are the function objects themselves.
        #: to register a view function, use the :meth:`route` decorator.
        self.view_functions = {}

        #: a dictionary of all registered error handlers.  The key is
        #: be the error code as integer, the value the function that
        #: should handle that error.
        #: To register a error handler, use the :meth:`errorhandler`
        #: decorator.
        self.error_handlers = {}

        #: a list of functions that should be called at the beginning
        #: of the request before request dispatching kicks in.  This
        #: can for example be used to open database connections or
        #: getting hold of the currently logged in user.
        #: To register a function here, use the :meth:`request_init`
        #: decorator.
        self.request_init_funcs = []

        #: a list of functions that are called at the end of the
        #: request.  Tha function is passed the current response
        #: object and modify it in place or replace it.
        #: To register a function here use the :meth:`request_shtdown`
        #: decorator.
        self.request_shutdown_funcs = []

        #: a list of functions that are called without arguments
        #: to populate the template context.  Each returns a dictionary
        #: that the template context is updated with.
        #: To register a function here, use the :meth:`context_processor`
        #: decorator.
        self.template_context_processors = [_default_template_ctx_processor]

        self.url_map = Map()

        if self.static_path is not None:
            self.url_map.add(Rule(self.static_path + '/<filename>',
                                  build_only=True, endpoint='static'))

        #: the Jinja2 environment.  It is created from the
        #: :attr:`jinja_options` and the loader that is returned
        #: by the :meth:`create_jinja_loader` function.
        self.jinja_env = Environment(loader=self.create_jinja_loader(),
                                     **self.jinja_options)
        self.jinja_env.globals.update(
            url_for=url_for,
            get_flashed_messages=get_flashed_messages
        )

    def create_jinja_loader(self):
        return PackageLoader(self.package_name)

    def update_template_context(self, context):
        """
Updates the template context with information from the request and session.

Args:
    context (dict): The dictionary to update with the new context values.

Returns:
    None

Raises:
    AttributeError: If _request_ctx_stack is not available or top is not a Request object.
"""

        reqctx = _request_ctx_stack.top
        for func in self.template_context_processors:
            context.update(func())

    def run(self, host='localhost', port=5000, **options):
        from werkzeug import run_simple
        if 'debug' in options:
            self.debug = options.pop('debug')
        if self.static_path is not None:
            options['static_files'] = {
                self.static_path:   (self.package_name, 'static')
            }
        options.setdefault('use_reloader', self.debug)
        options.setdefault('use_debugger', self.debug)
        return run_simple(host, port, self, **options)

    def test_client(self):
        """
Returns a Werkzeug HTTP client instance for testing purposes.

The client is configured to use cookies and is tied to the provided `self` object and response class. This allows for seamless integration with the test framework's request and response objects.

Args:
    self (object): The object being tested.
    self.response_class (class): The response class used by the test framework.

Returns:
    Client: A Werkzeug HTTP client instance.
"""
        from werkzeug import Client
        return Client(self, self.response_class, use_cookies=True)

    def open_resource(self, resource):
        return pkg_resources.resource_stream(self.package_name, resource)

    def open_session(self, request):
        key = self.secret_key
        if key is not None:
            return SecureCookie.load_cookie(request, self.session_cookie_name,
                                            secret_key=key)

    def save_session(self, session, response):
        if session is not None:
            session.save_cookie(response, self.session_cookie_name)

    def add_url_rule(self, rule, endpoint, **options):
        options['endpoint'] = endpoint
        options.setdefault('methods', ('GET',))
        self.url_map.add(Rule(rule, **options))

    def route(self, rule, **options):
        """
Route a URL pattern to a view function.

This function is used to map a URL rule to a specific view function. It can be used as a decorator to register the view function with the application.

Args:
    rule (str): The URL rule to match.
    **options: Additional options for the URL rule, such as the HTTP method.

Returns:
    A decorator function that registers the view function with the application.

Example:
    @app.route('/users', methods=['GET'])
    def get_users():
        # View function code here
        pass

Note:
    This function is typically used in a web framework to map URL patterns to view functions.
"""
        def decorator(f):
            self.add_url_rule(rule, f.__name__, **options)
            self.view_functions[f.__name__] = f
            return f
        return decorator

    def errorhandler(self, code):
        def decorator(f):
            self.error_handlers[code] = f
            return f
        return decorator

    def request_init(self, f):
        self.request_init_funcs.append(f)
        return f

    def request_shutdown(self, f):
        """
Adds a shutdown function to the list of requested shutdown functions.

Args:
    f (function): The shutdown function to be added.

Returns:
    function: The original shutdown function passed in, with no changes made.
"""
self.request_shutdown_funcs.append(f)
        return f

    def context_processor(self, f):
        """
Processors for the template context.

This function adds a processor to the list of template context processors.
It is used to inject data into the template context.

Args:
    f (function): The processor function to be added.

Returns:
    function: The original processor function, which has been appended to the list of template context processors.
"""
self.template_context_processors.append(f)
        return f

    def match_request(self):
        rv = _request_ctx_stack.top.url_adapter.match()
        request.endpoint, request.view_args = rv
        return rv

    def dispatch_request(self):
        try:
            endpoint, values = self.match_request()
            return self.view_functions[endpoint](**values)
        except HTTPException, e:
            handler = self.error_handlers.get(e.code)
            if handler is None:
                return e
            return handler(e)
        except Exception, e:
            handler = self.error_handlers.get(500)
            if self.debug or handler is None:
                raise
            return handler(e)

    def make_response(self, rv):
        if isinstance(rv, self.response_class):
            return rv
        if isinstance(rv, basestring):
            return self.response_class(rv)
        if isinstance(rv, tuple):
            return self.response_class(*rv)
        return self.response_class.force_type(rv, request.environ)

    def preprocess_request(self):
        for func in self.request_init_funcs:
            rv = func()
            if rv is not None:
                return rv

    def process_response(self, response):
        session = _request_ctx_stack.top.session
        if session is not None:
            self.save_session(session, response)
        for handler in self.request_shutdown_funcs:
            response = handler(response)
        return response

    def wsgi_app(self, environ, start_response):
        """
WSGI Application Function

This function serves as the entry point for a WSGI-compliant web application.
It processes incoming requests and returns a response to be sent back to the client.

Parameters:
    environ (dict): The environment dictionary containing information about the request.
    start_response (str): A callable that takes the status code and headers as arguments.

Returns:
    response: An object representing the response to be sent back to the client.

Notes:
    This function uses a request context manager to ensure proper cleanup of resources.
    It preprocesses the request, dispatches it if necessary, makes a response, processes it,
    and finally returns the response to the WSGI server.
"""
        with self.request_context(environ):
            rv = self.preprocess_request()
            if rv is None:
                rv = self.dispatch_request()
            response = self.make_response(rv)
            response = self.process_response(response)
            return response(environ, start_response)

    @contextmanager
    def request_context(self, environ):
        _request_ctx_stack.push(_RequestContext(self, environ))
        try:
            yield
        finally:
            _request_ctx_stack.pop()

    def test_request_context(self, *args, **kwargs):
        """
Tests the request context by creating a mock environment and passing it to the `request_context` method.

Args:
    *args: Variable length argument list of arguments to be passed to `create_environ`.
    **kwargs: Arbitrary keyword arguments to be passed to `create_environ`.

Returns:
    The result of calling `self.request_context` with the created mock environment.
"""
        return self.request_context(create_environ(*args, **kwargs))

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)


# context locals
_request_ctx_stack = LocalStack()
current_app = LocalProxy(lambda: _request_ctx_stack.top.app)
request = LocalProxy(lambda: _request_ctx_stack.top.request)
session = LocalProxy(lambda: _request_ctx_stack.top.session)
g = LocalProxy(lambda: _request_ctx_stack.top.g)
