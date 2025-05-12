from celery import Celery
from celery import Task
from flask import Flask
from flask import render_template


def create_app() -> Flask:
    """
Creates a new Flask application instance with Celery configuration and blueprint registration.

Returns:
    A fully configured Flask application instance.
"""
    app = Flask(__name__)
    app.config.from_mapping(
        CELERY=dict(
            broker_url="redis://localhost",
            result_backend="redis://localhost",
            task_ignore_result=True,
        ),
    )
    app.config.from_prefixed_env()
    celery_init_app(app)

    @app.route("/")
    def index() -> str:
        """
Returns an HTML template rendered from 'index.html' using the `render_template` function.

Args:
    None

Returns:
    str: The rendered HTML content of the 'index.html' template.
"""
        return render_template("index.html")

    from . import views

    app.register_blueprint(views.bp)
    return app


def celery_init_app(app: Flask) -> Celery:
    """
Initialize the Celery application for a Flask application.

This function sets up the Celery application with the provided Flask application.
It configures the Celery application from the Flask application's configuration,
sets default settings, and registers the Celery application as an extension of the Flask application.

Args:
    app (Flask): The Flask application to initialize the Celery application for.

Returns:
    Celery: The initialized Celery application.
"""
    class FlaskTask(Task):
        def __call__(self, *args: object, **kwargs: object) -> object:
            """
Call the run method of the current instance within an application context.

This function is a special method that allows instances to be called like functions.
It sets up an application context and then calls the run method on the instance,
passing any provided arguments and keyword arguments to it.

Args:
    *args (object): Variable number of positional arguments to pass to the run method.
    **kwargs (object): Variable number of keyword arguments to pass to the run method.

Returns:
    object: The result of calling the run method on the instance with the provided arguments and keyword arguments.
"""
            with app.app_context():
                return self.run(*args, **kwargs)

    celery_app = Celery(app.name, task_cls=FlaskTask)
    celery_app.config_from_object(app.config["CELERY"])
    celery_app.set_default()
    app.extensions["celery"] = celery_app
    return celery_app
