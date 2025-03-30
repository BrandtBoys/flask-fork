import sqlite3
# Import the datetime module to handle date and time conversions
from datetime import datetime

import click
# Import the Flask application object from the flask module
from flask import current_app
from flask import g


def get_db():
    """Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    # Check if a database connection already exists in the 'g' object
    if "db" not in g:
        # Connect to the database using the configuration from the Flask app
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        # Set the row factory to use SQLite's Row class for better data access
        g.db.row_factory = sqlite3.Row

    return g.db


def close_db(e=None):
    """If this request connected to the database, close the
    connection.
    """
    db = g.pop("db", None)

    # If a database connection exists, close it
    if db is not None:
        db.close()


def init_db():
    """Clear existing data and create new tables."""
    # Get the current database connection
    db = get_db()

    # Open the schema.sql file from the Flask app's resources directory
    with current_app.open_resource("schema.sql") as f:
        # Execute the SQL script in the schema.sql file to create or modify tables
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
def init_db_command():
    """Clear existing data and create new tables."""
    # Call the init_db function to clear existing data and create new tables
    init_db()
    # Print a success message indicating that the database has been initialized
    click.echo("Initialized the database.")


# Register a custom converter for timestamp values, which converts them to datetime objects
sqlite3.register_converter("timestamp", lambda v: datetime.fromisoformat(v.decode()))


def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    # Set up the close_db function as a teardown handler for the Flask app's context
    app.teardown_appcontext(close_db)
    # Add the init_db_command to the Flask app's CLI (command-line interface)
    app.cli.add_command(init_db_command)