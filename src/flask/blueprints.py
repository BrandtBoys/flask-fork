from __future__ import annotations

import os
import typing as t
from datetime import timedelta

from .globals import current_app
from .helpers import send_from_directory
from .sansio.blueprints import Blueprint as SansioBlueprint
from .sansio.blueprints import BlueprintSetupState as BlueprintSetupState  # noqa

if t.TYPE_CHECKING:  # pragma: no cover
    from .wrappers import Response


class Blueprint(SansioBlueprint):
    def get_send_file_max_age(self, filename: str | None) -> int | None:
        """
Returns the maximum age in seconds for sending files.

If `filename` is provided, it will be used to retrieve the default send file max age from the application configuration.
Otherwise, the default value will be returned.

Args:
    filename (str | None): The name of the file to use for retrieving the default send file max age. Defaults to None.

Returns:
    int | None: The maximum age in seconds for sending files, or None if no default is set.
"""
        value = current_app.config["SEND_FILE_MAX_AGE_DEFAULT"]

        if value is None:
            return None

        if isinstance(value, timedelta):
            return int(value.total_seconds())

        return value

    def send_static_file(self, filename: str) -> Response:
        """
Sends a static file from the configured static folder.

This method is used to serve static files. It checks if the `static_folder` attribute has been set and raises a RuntimeError if not.
It then calls `get_send_file_max_age` to determine the maximum age for the file, which is necessary for blueprints to work correctly.
Finally, it uses `send_from_directory` to send the file from the static folder.

Args:
    filename (str): The name of the file to be sent.

Returns:
    Response: A response object containing the sent file.

Raises:
    RuntimeError: If 'static_folder' is not set.
"""
        if not self.has_static_folder:
            raise RuntimeError("'static_folder' must be set to serve static_files.")

        # send_file only knows to call get_send_file_max_age on the app,
        # call it here so it works for blueprints too.
        max_age = self.get_send_file_max_age(filename)
        return send_from_directory(
            t.cast(str, self.static_folder), filename, max_age=max_age
        )

    def open_resource(self, resource: str, mode: str = "rb") -> t.IO[t.AnyStr]:
        """
Opens a resource file.

Args:
    resource (str): The path to the resource file.
    mode (str, optional): The mode in which to open the file. Defaults to "rb". Supported modes are "r", "rt", and "rb".

Returns:
    t.IO[t.AnyStr]: A file object opened in the specified mode.

Raises:
    ValueError: If an unsupported mode is provided.
"""
        if mode not in {"r", "rt", "rb"}:
            raise ValueError("Resources can only be opened for reading.")

        return open(os.path.join(self.root_path, resource), mode)
