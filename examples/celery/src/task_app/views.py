from celery.result import AsyncResult
from flask import Blueprint
from flask import request

from . import tasks

bp = Blueprint("tasks", __name__, url_prefix="/tasks")


@bp.get("/result/<id>")
def result(id: str) -> dict[str, object]:
    """
Returns a dictionary containing the status and result of an asynchronous operation.

Args:
    id (str): The ID of the asynchronous operation.

Returns:
    dict[str, object]: A dictionary with the following keys:
        - "ready": A boolean indicating whether the operation is ready.
        - "successful": A boolean indicating whether the operation was successful. If not ready, this will be None.
        - "value": The result of the operation if it's ready; otherwise, the result itself.

Raises:
    TypeError: If the input ID is not a string.
"""

    result = AsyncResult(id)
    ready = result.ready()
    return {
        "ready": ready,
        "successful": result.successful() if ready else None,
        "value": result.get() if ready else result.result,
    }


@bp.post("/add")
def add() -> dict[str, object]:
    a = request.form.get("a", type=int)
    b = request.form.get("b", type=int)
    result = tasks.add.delay(a, b)
    return {"result_id": result.id}


@bp.post("/block")
def block() -> dict[str, object]:
    """
Blocks the execution of a task and returns its ID.

This function uses Celery's `delay` method to execute a task asynchronously.
The returned dictionary contains the ID of the executed task.

Args:
    None

Returns:
    dict[str, object]: A dictionary containing the result ID of the blocked task.

Raises:
    None
"""
    result = tasks.block.delay()
    return {"result_id": result.id}


@bp.post("/process")
def process() -> dict[str, object]:
    """
Processes a task and returns the ID of the delayed job.
    result = tasks.process.delay(total=request.form.get("total", type=int))
    return {"result_id": result.id}

This function takes no arguments and returns a dictionary containing the ID of the delayed job.
The delay is set to the total value provided in the request form, defaulting to 0 if not specified.

Returns:
    dict[str, object]: A dictionary containing the result_id of the delayed job.
"""