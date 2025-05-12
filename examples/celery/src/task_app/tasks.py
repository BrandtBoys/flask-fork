import time

from celery import shared_task
from celery import Task


@shared_task(ignore_result=False)
def add(a: int, b: int) -> int:
    """
Adds two integers together.

Args:
    a (int): The first integer to be added.
    b (int): The second integer to be added.

Returns:
    int: The sum of the two input integers.

Raises:
    TypeError: If either 'a' or 'b' is not an integer.

Example:
    >>> add(3, 5)
    8
"""
    return a + b


@shared_task()
def block() -> None:
    """
Blocks the execution of the program for 5 seconds.

This function uses the `time` module's `sleep` function to pause the execution of the program for a specified amount of time. It does not return any value and is intended to be used as a blocking operation.

Args:
    None

Returns:
    None
"""
    time.sleep(5)


@shared_task(bind=True, ignore_result=False)
def process(self: Task, total: int) -> object:
    """
Process a task and update its state.

This function updates the state of a task to 'PROGRESS' with metadata indicating the current progress.
It then waits for 1 second between each update before returning the final state.

Args:
    self (Task): The task object being processed.
    total (int): The total number of steps in the process.

Returns:
    dict: A dictionary containing the final state of the task, including 'current' and 'total' values.
"""
    for i in range(total):
        self.update_state(state="PROGRESS", meta={"current": i + 1, "total": total})
        time.sleep(1)

    return {"current": total, "total": total}
