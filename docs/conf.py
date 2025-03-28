import packaging.version
from pallets_sphinx_themes import get_version
from pallets_sphinx_themes import ProjectLink

# Define project metadata
project = "Flask"
copyright = "2010 Pallets"
author = "Pallets"

# Get the version of Flask from the theme's configuration
release, version = get_version("Flask")

# Set default role for code blocks to display as code
default_role = "code"

# List of extensions used by Sphinx for this project
extensions = [
    # Autodoc extension for automatically generating documentation for classes and functions
    "sphinx.ext.autodoc",
    # Extlinks extension for creating links to external resources
    "sphinx.ext.extlinks",
    # Intersphinx extension for linking between different Sphinx projects
    "sphinx.ext.intersphinx",
    # Logcabinet extension for displaying log messages in the documentation
    "sphinxcontrib.log_cabinet",
    # Tabs extension for creating tabbed documentation
    "sphinx_tabs.tabs",
    # Pallets Sphinx theme for customizing the look and feel of the documentation
    "pallets_sphinx_themes",
]

# Configure autodoc to display member variables in source order
autodoc_member_order = "bysource"

# Enable type hints for autodoc
autodoc_typehints = "description"

# Preserve default values when generating documentation
autodoc_preserve_defaults = True

# Define custom links for issues and pull requests
extlinks = {
    # Link to the issue tracker on GitHub
    "issue": ("https://github.com/pallets/flask/issues/%s", "#%s"),
    # Link to the pull request on GitHub
    "pr": ("https://github.com/pallets/flask/pull/%s", "#%s"),
}

# Map between Sphinx project names and their corresponding documentation URLs
intersphinx_mapping = {
    # Python documentation URL
    "python": ("https://docs.python.org/3/", None),
    # Werkzeug documentation URL
    "werkzeug": ("https://werkzeug.palletsprojects.com/", None),
    # Click documentation URL
    "click": ("https://click.palletsprojects.com/", None),
    # Jinja documentation URL
    "jinja": ("https://jinja.palletsprojects.com/", None),
    # Itsdangerous documentation URL
    "itsdangerous": ("https://itsdangerous.palletsprojects.com/", None),
    # SQLAlchemy documentation URL
    "sqlalchemy": ("https://docs.sqlalchemy.org/", None),
    # WTForms documentation URL
    "wtforms": ("https://wtforms.readthedocs.io/", None),
    # Blinker documentation URL
    "blinker": ("https://blinker.readthedocs.io/", None),
}

# Set the theme for the documentation to Flask
html_theme = "flask"

# Configure the index sidebar logo to be hidden
html_theme_options = {"index_sidebar_logo": False}

# Define a context dictionary for HTML templates
html_context = {
    # List of project links to display in the navigation bar
    "project_links": [
        ProjectLink("Donate", "https://palletsprojects.com/donate"),
        ProjectLink("PyPI Releases", "https://pypi.org/project/Flask/"),
        ProjectLink("Source Code", "https://github.com/pallets/flask/"),
        ProjectLink("Issue Tracker", "https://github.com/pallets/flask/issues/"),
        ProjectLink("Chat", "https://discord.gg/pallets"),
    ]
}

# Define sidebar templates for HTML pages
html_sidebars = {
    # Template for the main page
    "**": "sidebar.html",
}

# Set the title of the documentation to include the version number
html_title = f"Flask Documentation ({version})"

# Hide the source link in the documentation
html_show_sourcelink = False

# Define a function to generate GitHub links
def github_link(name, rawtext, text, lineno, inliner, options=None, content=None):
    # Get the app configuration from the document settings
    app = inliner.document.settings.env.app
    
    # Get the release version from the app configuration
    release = app.config.release
    
    # Define the base URL for GitHub links
    base_url = "https://github.com/pallets/flask/tree/"
    
    # Check if the text ends with a closing angle bracket
    if text.endswith(">"):
        words, text = text[:-1].rsplit("<", 1)
        words = words.strip()
    else:
        words = None
    
    # Determine the URL based on whether the release is a development version
    if packaging.version.parse(release).is_devrelease:
        url = f"{base_url}main/{text}"
    else:
        url = f"{base_url}{release}/{text}"
    
    # If no words were specified, use the full URL as the reference
    if words is None:
        words = url
    
    # Create a reference node for the link
    from docutils.nodes import reference
    from docutils.parsers.rst.roles import set_classes

    options = options or {}
    set_classes(options)
    node = reference(rawtext, words, refuri=url, **options)
    
    # Return the list of nodes to be rendered as a link
    return [node], []

# Define a setup function for Sphinx
def setup(app):
    app.add_role("gh", github_link)