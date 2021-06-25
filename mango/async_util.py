import asyncio
import logging
from asyncio import Task
from typing import List


async def run_until_first_completed(logger: logging.Logger, tasks: List[Task]):
    # wait until the first task completes
    done, pending = await asyncio.wait(
        tasks,
        return_when=asyncio.FIRST_COMPLETED
    )
    # cancel all remaining tasks
    for task in pending:
        task.cancel()
    # log all relevant exceptions
    pending = tasks  # We should log exceptions of all tasks
    while len(pending) > 0:
        done, pending = await asyncio.wait(
            tasks,
            return_when=asyncio.FIRST_COMPLETED
        )
        # Give info about the cancelled tasks
        for task in done:
            # noinspection PyBroadException
            try:
                await task
            except asyncio.CancelledError:
                logger.info(f'Task was cancelled: {task.get_name()} / {task.get_coro()}')
            except Exception:
                logger.exception(f'Task {task.get_name()} / {task.get_coro()} has raised exception')
