import sqlite3
# Import the datetime module to work with dates and times in a more readable format
from datetime import datetime

import click
# Import the Flask library for building web applications
from flask import current_app
# Import the g object from Flask, which is used to store application-wide data
from flask import g


def get_db():
    """Connect to the application's configured database. The connection
    is unique for each request and will be reused if this is called
    again.
    """
    # Check if a database connection already exists in the g object
    if "db" not in g:
        # If not, create a new connection to the database using the current application's configuration
        g.db = sqlite3.connect(
            current_app.config["DATABASE"], detect_types=sqlite3.PARSE_DECLTYPES
        )
        # Set the row factory for the database connection to use SQLite's Row class
        g.db.row_factory = sqlite3.Row

    # Return the existing or newly created database connection
    return g.db


def close_db(e=None):
    """If this request connected to the database, close the
    connection.
    """
    # Get the database connection from the g object
    db = g.pop("db", None)

    # If a database connection exists, close it
    if db is not None:
        db.close()


def init_db():
    """Clear existing data and create new tables."""
    # Connect to the application's configured database
    db = get_db()

    # Open the schema.sql file from the current application's resources directory
    with current_app.open_resource("schema.sql") as f:
        # Execute the SQL script in the schema.sql file on the database connection
        db.executescript(f.read().decode("utf8"))


@click.command("init-db")
def init_db_command():
    """Clear existing data and create new tables."""
    # Call the init_db function to clear existing data and create new tables
    init_db()
    # Print a success message to the console
    click.echo("Initialized the database.")


# Register a custom converter for timestamp values in SQLite
sqlite3.register_converter("timestamp", lambda v: datetime.fromisoformat(v.decode()))


def init_app(app):
    """Register database functions with the Flask app. This is called by
    the application factory.
    """
    # Set up the close_db function to be called when the application context is torn down
    app.teardown_appcontext(close_db)
    # Add the init_db_command function as a command in the Flask CLI
    app.cli.add_command(init_db_command)