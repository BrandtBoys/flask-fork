from __future__ import annotations

import errno
import json
import os
import types
import typing as t

from werkzeug.utils import import_string

if t.TYPE_CHECKING:
    import typing_extensions as te

    from .sansio.app import App


T = t.TypeVar("T")


class ConfigAttribute(t.Generic[T]):
    """Makes an attribute forward to the config"""

    def __init__(
        self, name: str, get_converter: t.Callable[[t.Any], T] | None = None
    ) -> None:
        """
Initialize a new instance of the class.

Args:
    - **name (str)**: The name of the converter.
    - **get_converter (t.Callable[[t.Any], T] | None, optional)**: A function that converts any type to the target type. Defaults to None.

Returns:
    None
"""
        self.__name__ = name
        self.get_converter = get_converter

    @t.overload
    def __get__(self, obj: None, owner: None) -> te.Self:
        ...

    @t.overload
    def __get__(self, obj: App, owner: type[App]) -> T:
        """
Gets an attribute from an instance of the class.

This method is used to implement property access in Python. It allows you to define a getter function for a property and use it with the `@property` decorator.

Args:
    self (object): The instance of the class.
    obj (App, optional): The object that owns this attribute. Defaults to None.
    owner (type[App], optional): The type of the App class. Defaults to None.

Returns:
    T: The value of the attribute.
"""
        ...

    def __get__(self, obj: App | None, owner: type[App] | None = None) -> T | te.Self:
        """
Gets the configuration value for this descriptor.

If `obj` is provided, it must be an instance of `App`. The method returns
the configuration value associated with the name of this descriptor. If a
converter function is set on this descriptor, it will be applied to the
configuration value before being returned.

Args:
    obj: An instance of App (optional)
    owner: The type of the App instance (optional)

Returns:
    T | te.Self: The configuration value or self if no object was provided.
"""
        if obj is None:
            return self

        rv = obj.config[self.__name__]

        if self.get_converter is not None:
            rv = self.get_converter(rv)

        return rv  # type: ignore[no-any-return]

    def __set__(self, obj: App, value: t.Any) -> None:
        """
Sets a configuration attribute on an object.

This method is used to set a configuration attribute on an object. The attribute name is determined by the `__name__` attribute of the current instance, and its value is stored in the `config` dictionary of the object's parent class (`App`). 

Args:
    obj (App): The object that owns this configuration attribute.
    value (t.Any): The new value for the configuration attribute.

Returns:
    None
"""
        obj.config[self.__name__] = value


class Config(dict):  # type: ignore[type-arg]
    """Works exactly like a dict but provides ways to fill it from files
    or special dictionaries.  There are two common patterns to populate the
    config.

    Either you can fill the config from a config file::

        app.config.from_pyfile('yourconfig.cfg')

    Or alternatively you can define the configuration options in the
    module that calls :meth:`from_object` or provide an import path to
    a module that should be loaded.  It is also possible to tell it to
    use the same module and with that provide the configuration values
    just before the call::

        DEBUG = True
        SECRET_KEY = 'development key'
        app.config.from_object(__name__)

    In both cases (loading from any Python file or loading from modules),
    only uppercase keys are added to the config.  This makes it possible to use
    lowercase values in the config file for temporary values that are not added
    to the config or to define the config keys in the same file that implements
    the application.

    Probably the most interesting way to load configurations is from an
    environment variable pointing to a file::

        app.config.from_envvar('YOURAPPLICATION_SETTINGS')

    In this case before launching the application you have to set this
    environment variable to the file you want to use.  On Linux and OS X
    use the export statement::

        export YOURAPPLICATION_SETTINGS='/path/to/config/file'

    On windows use `set` instead.

    :param root_path: path to which files are read relative from.  When the
                      config object is created by the application, this is
                      the application's :attr:`~flask.Flask.root_path`.
    :param defaults: an optional dictionary of default values
    """

    def __init__(
        self,
        root_path: str | os.PathLike[str],
        defaults: dict[str, t.Any] | None = None,
    ) -> None:
        """
Initialize the documentation assistant.

### Parameters

- **root_path**: The root path of the documentation. Can be a string or an os.PathLike object.
- **defaults**: An optional dictionary of default values to use for initialization. Defaults to None.

### Returns

None
"""
        super().__init__(defaults or {})
        self.root_path = root_path

    def from_envvar(self, variable_name: str, silent: bool = False) -> bool:
        rv = os.environ.get(variable_name)
        if not rv:
            if silent:
                return False
            raise RuntimeError(
                f"The environment variable {variable_name!r} is not set"
                " and as such configuration could not be loaded. Set"
                " this variable and make it point to a configuration"
                " file"
            )
        return self.from_pyfile(rv, silent=silent)

    def from_prefixed_env(
        self, prefix: str = "FLASK", *, loads: t.Callable[[str], t.Any] = json.loads
    ) -> bool:
        prefix = f"{prefix}_"
        len_prefix = len(prefix)

        for key in sorted(os.environ):
            if not key.startswith(prefix):
                continue

            value = os.environ[key]

            try:
                value = loads(value)
            except Exception:
                # Keep the value as a string if loading failed.
                pass

            # Change to key.removeprefix(prefix) on Python >= 3.9.
            key = key[len_prefix:]

            if "__" not in key:
                # A non-nested key, set directly.
                self[key] = value
                continue

            # Traverse nested dictionaries with keys separated by "__".
            current = self
            *parts, tail = key.split("__")

            for part in parts:
                # If an intermediate dict does not exist, create it.
                if part not in current:
                    current[part] = {}

                current = current[part]

            current[tail] = value

        return True

    def from_pyfile(
        self, filename: str | os.PathLike[str], silent: bool = False
    ) -> bool:
        """
Loads a configuration from a Python file.

This function reads the contents of a specified Python file, executes it as a module,
and then calls `from_object` on the resulting object. If the file does not exist or
cannot be executed for some reason, an error is raised.

Args:
    filename (str | os.PathLike[str]): The path to the configuration file.
    silent (bool): If True, returns False if the file cannot be loaded without raising an exception. Defaults to False.

Returns:
    bool: Whether the configuration was successfully loaded.
"""
        filename = os.path.join(self.root_path, filename)
        d = types.ModuleType("config")
        d.__file__ = filename
        try:
            with open(filename, mode="rb") as config_file:
                exec(compile(config_file.read(), filename, "exec"), d.__dict__)
        except OSError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR, errno.ENOTDIR):
                return False
            e.strerror = f"Unable to load configuration file ({e.strerror})"
            raise
        self.from_object(d)
        return True

    def from_object(self, obj: object | str) -> None:
        if isinstance(obj, str):
            obj = import_string(obj)
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def from_file(
        self,
        filename: str | os.PathLike[str],
        load: t.Callable[[t.IO[t.Any]], t.Mapping[str, t.Any]],
        silent: bool = False,
        text: bool = True,
    ) -> bool:
        """
Loads a configuration file from disk.

This method attempts to open the specified file and load its contents using the provided
`load` function. If successful, it returns `True`. Otherwise, it raises an exception with a
customized error message if silent mode is enabled or returns `False`.

Args:
    filename (str | os.PathLike[str]): The path to the configuration file.
    load (t.Callable[[t.IO[t.Any]], t.Mapping[str, t.Any]]): A function that takes an IO object and returns a mapping of key-value pairs.
    silent (bool, optional): If True, exceptions are caught silently. Defaults to False.
    text (bool, optional): Specifies whether the file should be opened in text mode (True) or binary mode (False). Defaults to True.

Returns:
    bool: Whether the configuration was loaded successfully.
Raises:
    OSError: If an error occurs while loading the configuration file.
"""
        filename = os.path.join(self.root_path, filename)

        try:
            with open(filename, "r" if text else "rb") as f:
                obj = load(f)
        except OSError as e:
            if silent and e.errno in (errno.ENOENT, errno.EISDIR):
                return False

            e.strerror = f"Unable to load configuration file ({e.strerror})"
            raise

        return self.from_mapping(obj)

    def from_mapping(
        self, mapping: t.Mapping[str, t.Any] | None = None, **kwargs: t.Any
    ) -> bool:
        mappings: dict[str, t.Any] = {}
        if mapping is not None:
            mappings.update(mapping)
        mappings.update(kwargs)
        for key, value in mappings.items():
            if key.isupper():
                self[key] = value
        return True

    def get_namespace(
        self, namespace: str, lowercase: bool = True, trim_namespace: bool = True
    ) -> dict[str, t.Any]:
        rv = {}
        for k, v in self.items():
            if not k.startswith(namespace):
                continue
            if trim_namespace:
                key = k[len(namespace) :]
            else:
                key = k
            if lowercase:
                key = key.lower()
            rv[key] = v
        return rv

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {dict.__repr__(self)}>"
