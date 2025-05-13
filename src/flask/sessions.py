from __future__ import annotations

import hashlib
import typing as t
from collections.abc import MutableMapping
from datetime import datetime
from datetime import timezone

from itsdangerous import BadSignature
from itsdangerous import URLSafeTimedSerializer
from werkzeug.datastructures import CallbackDict

from .json.tag import TaggedJSONSerializer

if t.TYPE_CHECKING:  # pragma: no cover
    from .app import Flask
    from .wrappers import Request, Response


class SessionMixin(MutableMapping):
    """Expands a basic dictionary with session attributes."""

    @property
    def permanent(self) -> bool:
        return self.get("_permanent", False)

    @permanent.setter
    def permanent(self, value: bool) -> None:
        self["_permanent"] = bool(value)

    #: Some implementations can detect whether a session is newly
    #: created, but that is not guaranteed. Use with caution. The mixin
    # default is hard-coded ``False``.
    new = False

    #: Some implementations can detect changes to the session and set
    #: this when that happens. The mixin default is hard coded to
    #: ``True``.
    modified = True

    #: Some implementations can detect when session data is read or
    #: written and set this when that happens. The mixin default is hard
    #: coded to ``True``.
    accessed = True


class SecureCookieSession(CallbackDict, SessionMixin):
    """Base class for sessions based on signed cookies.

    This session backend will set the :attr:`modified` and
    :attr:`accessed` attributes. It cannot reliably track whether a
    session is new (vs. empty), so :attr:`new` remains hard coded to
    ``False``.
    """

    #: When data is changed, this is set to ``True``. Only the session
    #: dictionary itself is tracked; if the session contains mutable
    #: data (for example a nested dict) then this must be set to
    #: ``True`` manually when modifying that data. The session cookie
    #: will only be written to the response if this is ``True``.
    modified = False

    #: When data is read or written, this is set to ``True``. Used by
    # :class:`.SecureCookieSessionInterface` to add a ``Vary: Cookie``
    #: header, which allows caching proxies to cache different pages for
    #: different users.
    accessed = False

    def __init__(self, initial: t.Any = None) -> None:
        def on_update(self) -> None:
            self.modified = True
            self.accessed = True

        super().__init__(initial, on_update)

    def __getitem__(self, key: str) -> t.Any:
        self.accessed = True
        return super().__getitem__(key)

    def get(self, key: str, default: t.Any = None) -> t.Any:
        self.accessed = True
        return super().get(key, default)

    def setdefault(self, key: str, default: t.Any = None) -> t.Any:
        self.accessed = True
        return super().setdefault(key, default)


class NullSession(SecureCookieSession):
    """Class used to generate nicer error messages if sessions are not
    available.  Will still allow read-only access to the empty session
    but fail on setting.
    """

    def _fail(self, *args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise RuntimeError(
            "The session is unavailable because no secret "
            "key was set.  Set the secret_key on the "
            "application to something unique and secret."
        )

    __setitem__ = __delitem__ = clear = pop = popitem = update = setdefault = _fail  # type: ignore # noqa: B950
    del _fail


class SessionInterface:
    """The basic interface you have to implement in order to replace the
    default session interface which uses werkzeug's securecookie
    implementation.  The only methods you have to implement are
    :meth:`open_session` and :meth:`save_session`, the others have
    useful defaults which you don't need to change.

    The session object returned by the :meth:`open_session` method has to
    provide a dictionary like interface plus the properties and methods
    from the :class:`SessionMixin`.  We recommend just subclassing a dict
    and adding that mixin::

        class Session(dict, SessionMixin):
            pass

    If :meth:`open_session` returns ``None`` Flask will call into
    :meth:`make_null_session` to create a session that acts as replacement
    if the session support cannot work because some requirement is not
    fulfilled.  The default :class:`NullSession` class that is created
    will complain that the secret key was not set.

    To replace the session interface on an application all you have to do
    is to assign :attr:`flask.Flask.session_interface`::

        app = Flask(__name__)
        app.session_interface = MySessionInterface()

    Multiple requests with the same session may be sent and handled
    concurrently. When implementing a new session interface, consider
    whether reads or writes to the backing store must be synchronized.
    There is no guarantee on the order in which the session for each
    request is opened or saved, it will occur in the order that requests
    begin and end processing.

    .. versionadded:: 0.8
    """

    #: :meth:`make_null_session` will look here for the class that should
    #: be created when a null session is requested.  Likewise the
    #: :meth:`is_null_session` method will perform a typecheck against
    #: this type.
    null_session_class = NullSession

    #: A flag that indicates if the session interface is pickle based.
    #: This can be used by Flask extensions to make a decision in regards
    #: to how to deal with the session object.
    #:
    #: .. versionadded:: 0.10
    pickle_based = False

    def make_null_session(self, app: Flask) -> NullSession:
        """
Creates and returns a null session instance for the given Flask application.

Args:
    app (Flask): The Flask application instance.

Returns:
    NullSession: A null session instance.
"""
        return self.null_session_class()

    def is_null_session(self, obj: object) -> bool:
        return isinstance(obj, self.null_session_class)

    def get_cookie_name(self, app: Flask) -> str:
        """
Returns the name of the cookie used to store session data in a Flask application.

Args:
    app (Flask): The Flask application instance.

Returns:
    str: The name of the session cookie.
"""
        return app.config["SESSION_COOKIE_NAME"]

    def get_cookie_domain(self, app: Flask) -> str | None:
        rv = app.config["SESSION_COOKIE_DOMAIN"]
        return rv if rv else None

    def get_cookie_path(self, app: Flask) -> str:
        """
Returns the path of the cookie used by a Flask application.

If 'SESSION_COOKIE_PATH' is set in the application's configuration,
its value will be returned. Otherwise, the value of
'APPLICATION_ROOT' will be used as a fallback.

Args:
    app (Flask): The Flask application instance.

Returns:
    str: The path of the cookie.
"""
        return app.config["SESSION_COOKIE_PATH"] or app.config["APPLICATION_ROOT"]

    def get_cookie_httponly(self, app: Flask) -> bool:
        """
Returns whether the session cookie is set to be HTTP-only in the given Flask application.

Args:
    app (Flask): The Flask application instance.

Returns:
    bool: True if the session cookie is HTTP-only, False otherwise.
"""
        return app.config["SESSION_COOKIE_HTTPONLY"]

    def get_cookie_secure(self, app: Flask) -> bool:
        """
Returns whether the session cookie is secure.

This method checks if the `SESSION_COOKIE_SECURE` configuration variable
is set to True in the Flask application's configuration. If it is, the
session cookie will be transmitted over a secure protocol (HTTPS).

Args:
    app: The Flask application instance.

Returns:
    bool: Whether the session cookie is secure.
"""
        return app.config["SESSION_COOKIE_SECURE"]

    def get_cookie_samesite(self, app: Flask) -> str:
        """
Returns the value of the `SESSION_COOKIE_SAMESITE` configuration option from the provided Flask application.

Args:
    app (Flask): The Flask application instance.

Returns:
    str: The value of the `SESSION_COOKIE_SAMESITE` configuration option.
"""
        return app.config["SESSION_COOKIE_SAMESITE"]

    def get_expiration_time(self, app: Flask, session: SessionMixin) -> datetime | None:
        """
Returns the expiration time of a Flask session.

If the session is permanent, returns the current UTC time plus the permanent session lifetime.
Otherwise, returns None.

Args:
    self: The instance of the class that this method belongs to (not used in this implementation).
    app: A Flask application object.
    session: A SessionMixin object representing the session.

Returns:
    datetime: The expiration time of the session, or None if the session is not permanent.
"""
        if session.permanent:
            return datetime.now(timezone.utc) + app.permanent_session_lifetime
        return None

    def should_set_cookie(self, app: Flask, session: SessionMixin) -> bool:

        return session.modified or (
            session.permanent and app.config["SESSION_REFRESH_EACH_REQUEST"]
        )

    def open_session(self, app: Flask, request: Request) -> SessionMixin | None:
        """
Opens a new session for the given Flask application and request.

Args:
    - `app`: The Flask application instance.
    - `request`: The HTTP request object.

Returns:
    An optional SessionMixin object, indicating whether a session was successfully opened. If not implemented by subclasses, raises NotImplementedError.

Raises:
    NotImplementedError: If the method is not implemented by subclasses.
"""
        raise NotImplementedError()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        """
Saves a session.

This method is intended to be overridden by subclasses. It takes in the Flask application,
the session object, and the response object as parameters. The implementation of this
method should be provided by the subclass.

Parameters:
app (Flask): The Flask application instance.
session (SessionMixin): The session object.
response (Response): The response object.

Returns:
None

Raises:
NotImplementedError: This method is intended to be overridden and should not be called directly.
"""
        raise NotImplementedError()


session_json_serializer = TaggedJSONSerializer()


class SecureCookieSessionInterface(SessionInterface):
    """The default session interface that stores sessions in signed cookies
    through the :mod:`itsdangerous` module.
    """

    #: the salt that should be applied on top of the secret key for the
    #: signing of cookie based sessions.
    salt = "cookie-session"
    #: the hash function to use for the signature.  The default is sha1
    digest_method = staticmethod(hashlib.sha1)
    #: the name of the itsdangerous supported key derivation.  The default
    #: is hmac.
    key_derivation = "hmac"
    #: A python serializer for the payload.  The default is a compact
    #: JSON derived serializer with support for some extra Python types
    #: such as datetime objects or tuples.
    serializer = session_json_serializer
    session_class = SecureCookieSession

    def get_signing_serializer(self, app: Flask) -> URLSafeTimedSerializer | None:
        """
Returns a signing serializer for the provided Flask application.

If the application's secret key is not set, returns None. Otherwise, creates a
URLSafeTimedSerializer instance with the secret key and additional configuration
from the application's settings.

Args:
    app (Flask): The Flask application to generate the serializer for.
Returns:
    URLSafeTimedSerializer: The generated signing serializer, or None if the
        application's secret key is not set.
"""
        if not app.secret_key:
            return None
        signer_kwargs = dict(
            key_derivation=self.key_derivation, digest_method=self.digest_method
        )
        return URLSafeTimedSerializer(
            app.secret_key,
            salt=self.salt,
            serializer=self.serializer,
            signer_kwargs=signer_kwargs,
        )

    def open_session(self, app: Flask, request: Request) -> SecureCookieSession | None:
        """
Opens a new session for the given Flask application and request.

Args:
    app (Flask): The Flask application instance.
    request (Request): The HTTP request object.

Returns:
    t.Optional[SecureCookieSession]: The opened session, or None if creation fails.
"""
        s = self.get_signing_serializer(app)
        if s is None:
            return None
        val = request.cookies.get(self.get_cookie_name(app))
        if not val:
            return self.session_class()
        max_age = int(app.permanent_session_lifetime.total_seconds())
        try:
            data = s.loads(val, max_age=max_age)
            return self.session_class(data)
        except BadSignature:
            return self.session_class()

    def save_session(
        self, app: Flask, session: SessionMixin, response: Response
    ) -> None:
        """
Saves a session cookie to the client's browser.

This method sets a session cookie based on the provided `app`, `session`, and `response` objects.
It determines the necessary cookie attributes (name, domain, path, secure, samesite, httponly) using
the `get_cookie_name`, `get_cookie_domain`, `get_cookie_path`, `get_cookie_secure`, 
`get_cookie_samesite`, and `get_cookie_httponly` methods.

Parameters:
app (Flask): The Flask application instance.
session (SessionMixin): The session object being saved.
response (Response): The HTTP response object.

Returns:
None
"""
        name = self.get_cookie_name(app)
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        secure = self.get_cookie_secure(app)
        samesite = self.get_cookie_samesite(app)
        httponly = self.get_cookie_httponly(app)

        # Add a "Vary: Cookie" header if the session was accessed at all.
        if session.accessed:
            response.vary.add("Cookie")

        # If the session is modified to be empty, remove the cookie.
        # If the session is empty, return without setting the cookie.
        if not session:
            if session.modified:
                response.delete_cookie(
                    name,
                    domain=domain,
                    path=path,
                    secure=secure,
                    samesite=samesite,
                    httponly=httponly,
                )
                response.vary.add("Cookie")

            return

        if not self.should_set_cookie(app, session):
            return

        expires = self.get_expiration_time(app, session)
        val = self.get_signing_serializer(app).dumps(dict(session))  # type: ignore
        response.set_cookie(
            name,
            val,  # type: ignore
            expires=expires,
            httponly=httponly,
            domain=domain,
            path=path,
            secure=secure,
            samesite=samesite,
        )
        response.vary.add("Cookie")
