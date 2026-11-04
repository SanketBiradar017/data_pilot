import logging


def setup_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    for noisy in ("matplotlib", "PIL", "httpcore", "httpx", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
