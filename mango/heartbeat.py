from pathlib import Path
import logging

LOGGER = logging.getLogger()


def heartbeat(filepath: str) -> None:
    """
    Creates a file with filepath, including the dir path.
    If file exists, it overwrites it.
    """
    try:
        Path(filepath).touch(mode=0o666, exist_ok=True)
    except PermissionError as e:
        LOGGER.warning('Not allowed to write to %s, %s', filepath, e)


def heartbeat_init(filepath: str) -> None:
    """
    If heartbeat directory does not exists it creates it.
    Run heartbeat (touch the file) of the specified location.
    """
    heartbeat_dir = Path(filepath).parent
    heartbeat_dir.mkdir(exist_ok=True, parents=True)

    heartbeat(filepath)
