import errno
import json
import os
import types
import typing as t

from werkzeug.utils import import_string


class ConfigAttribute:
    """Makes an attribute forward to the config"""

    def __init__(self, name: str, get_converter: t.Optional[t.Callable] = None) -> None:
        self.__name__ = name
        self.get_converter = get_converter

    def __get__(self, obj: t.Any, owner: t.Any = None) -> t.Any:
        if obj is None:
            return self
        rv = obj.config[self.__name__]
        if self.get_converter is not None:
            rv = self.get_converter(rv)
        return rv

    def __set__(self, obj: t.Any, value: t.Any) -> None:
        obj.config[self.__name__] = value


class Config(dict):
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

    def __init__(self, root_path: str, defaults: t.Optional[dict] = None) -> None:
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

    def from_pyfile(self, filename: str, silent: bool = False) -> bool:
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

    def from_object(self, obj: t.Union[object, str]) -> None:
        if isinstance(obj, str):
            obj = import_string(obj)
        for key in dir(obj):
            if key.isupper():
                self[key] = getattr(obj, key)

    def from_file(
        self,
        filename: str,
        load: t.Callable[[t.IO[t.Any]], t.Mapping],
        silent: bool = False,
        text: bool = True,
    ) -> bool:
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
        self, mapping: t.Optional[t.Mapping[str, t.Any]] = None, **kwargs: t.Any
    ) -> bool:
        mappings: t.Dict[str, t.Any] = {}
        if mapping is not None:
            mappings.update(mapping)
        mappings.update(kwargs)
        for key, value in mappings.items():
            if key.isupper():
                self[key] = value
        return True

    def get_namespace(
        self, namespace: str, lowercase: bool = True, trim_namespace: bool = True
    ) -> t.Dict[str, t.Any]:
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
