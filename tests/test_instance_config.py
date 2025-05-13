import os

import pytest

import flask


def test_explicit_instance_paths(modules_tmp_path):
    """
Tests the Flask application's instance path.

This function tests that a ValueError is raised when an absolute instance path
is not provided, and that the instance path can be correctly set using an
absolute path.

Args:
    modules_tmp_path (str): The temporary path to the modules.

Returns:
    None

Raises:
    ValueError: If the instance path is not absolute.
"""
    with pytest.raises(ValueError, match=".*must be absolute"):
        flask.Flask(__name__, instance_path="instance")

    app = flask.Flask(__name__, instance_path=os.fspath(modules_tmp_path))
    assert app.instance_path == os.fspath(modules_tmp_path)


def test_uninstalled_module_paths(modules_tmp_path, purge_module):
    """
Tests the behavior of an uninstalled module by creating a temporary configuration file and purging the module.

Args:
    modules_tmp_path (Path): The path to the temporary modules directory.
    purge_module (function): A function that takes a module name as input and removes it from the system.

Returns:
    None

Raises:
    AssertionError: If the instance path of the Flask app does not match the expected value.
"""
    (modules_tmp_path / "config_module_app.py").write_text(
        "import os\n"
        "import flask\n"
        "here = os.path.abspath(os.path.dirname(__file__))\n"
        "app = flask.Flask(__name__)\n"
    )
    purge_module("config_module_app")

    from config_module_app import app

    assert app.instance_path == os.fspath(modules_tmp_path / "instance")


def test_uninstalled_package_paths(modules_tmp_path, purge_module):
    """
Tests the paths of an uninstalled package.

This function creates a temporary Flask application in the provided
`modules_tmp_path`, writes an `__init__.py` file to it, and then purges
the module. It then imports the app and asserts that its instance path
matches the expected value.

Parameters:
    modules_tmp_path (Path): The base directory for the test.
    purge_module (function): A function to remove a module from the system.

Returns:
    None

Raises:
    AssertionError: If the instance path of the app does not match the expected value.
"""
    app = modules_tmp_path / "config_package_app"
    app.mkdir()
    (app / "__init__.py").write_text(
        "import os\n"
        "import flask\n"
        "here = os.path.abspath(os.path.dirname(__file__))\n"
        "app = flask.Flask(__name__)\n"
    )
    purge_module("config_package_app")

    from config_package_app import app

    assert app.instance_path == os.fspath(modules_tmp_path / "instance")


def test_uninstalled_namespace_paths(tmp_path, monkeypatch, purge_module):
    """
Test that the instance path of a Flask application is correctly set when the namespace package is uninstalled.

This test creates two namespaces, one for each package being tested. It then purges the modules from these namespaces and asserts that the instance path of the second package's application is correct.

Args:
    tmp_path (pathlib.Path): A temporary directory used to create project directories.
    monkeypatch (MonkeyPatch): A MonkeyPatch object used to modify the sys.path.
    purge_module (function): A function used to purge modules from a namespace.

Returns:
    None
"""
    def create_namespace(package):
        project = tmp_path / f"project-{package}"
        monkeypatch.syspath_prepend(os.fspath(project))
        ns = project / "namespace" / package
        ns.mkdir(parents=True)
        (ns / "__init__.py").write_text("import flask\napp = flask.Flask(__name__)\n")
        return project

    _ = create_namespace("package1")
    project2 = create_namespace("package2")
    purge_module("namespace.package2")
    purge_module("namespace")

    from namespace.package2 import app

    assert app.instance_path == os.fspath(project2 / "instance")


def test_installed_module_paths(
    modules_tmp_path, modules_tmp_path_prefix, purge_module, site_packages, limit_loader
):
    """
Test function to verify installed module paths.

This function tests the installation of a Flask application in a temporary directory.
It creates a `site_app.py` file with a basic Flask app, purges any existing instance,
and then asserts that the instance path matches the expected value.

Parameters:
    modules_tmp_path (str): The path to the temporary directory for module files.
    modules_tmp_path_prefix (str): The prefix for the temporary directory.
    purge_module (function): A function to purge a module from the site-packages.
    site_packages (str): The path to the site-packages directory.
    limit_loader (int): An optional parameter to limit the loader.

Returns:
    None
"""
    (site_packages / "site_app.py").write_text(
        "import flask\napp = flask.Flask(__name__)\n"
    )
    purge_module("site_app")

    from site_app import app

    assert app.instance_path == os.fspath(
        modules_tmp_path / "var" / "site_app-instance"
    )


def test_installed_package_paths(
    limit_loader, modules_tmp_path, modules_tmp_path_prefix, purge_module, monkeypatch
):
    """
Test function to verify the installation of a package.

This function tests the installation of a Flask application in a temporary directory.
It creates a temporary directory, installs a Flask application, and then verifies that
the instance path is correctly set.

Parameters:
limit_loader (bool): Whether to limit the loader.
modules_tmp_path (Path): The path to the modules tmp directory.
modules_tmp_path_prefix (str): The prefix for the modules tmp path.
purge_module (str): The module to purge.
monkeypatch (object): A monkey patch object.

Returns:
None
"""
    installed_path = modules_tmp_path / "path"
    installed_path.mkdir()
    monkeypatch.syspath_prepend(installed_path)

    app = installed_path / "installed_package"
    app.mkdir()
    (app / "__init__.py").write_text("import flask\napp = flask.Flask(__name__)\n")
    purge_module("installed_package")

    from installed_package import app

    assert app.instance_path == os.fspath(
        modules_tmp_path / "var" / "installed_package-instance"
    )


def test_prefix_package_paths(
    limit_loader, modules_tmp_path, modules_tmp_path_prefix, purge_module, site_packages
):
    """
Test prefix package paths.

This function tests the behavior of a package when its path is prefixed.
It creates a temporary directory, installs a Flask app into it, and then
purges the original module. It then imports the package again to verify that
the instance path has been correctly updated.

Parameters:
    limit_loader (bool): Whether to limit the loader.
    modules_tmp_path (Path): The path to the temporary modules directory.
    modules_tmp_path_prefix (str): The prefix for the temporary modules path.
    purge_module (str): The module to purge.
    site_packages (Path): The path to the site-packages directory.

Returns:
    None
"""
    app = site_packages / "site_package"
    app.mkdir()
    (app / "__init__.py").write_text("import flask\napp = flask.Flask(__name__)\n")
    purge_module("site_package")

    import site_package

    assert site_package.app.instance_path == os.fspath(
        modules_tmp_path / "var" / "site_package-instance"
    )
