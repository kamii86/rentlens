import logging


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "time=%(asctime)s level=%(levelname)s logger=%(name)s message=%(message)s"
        ),
    )
