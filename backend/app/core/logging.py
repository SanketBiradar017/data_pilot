import logging

from backend.app.core.secrets import RedactingFilter


def setup_logging(debug: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    for noisy in ("matplotlib", "PIL", "httpcore", "httpx", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    for h in logging.getLogger().handlers:  # filters on handlers apply to every logger's records
        if not any(isinstance(f, RedactingFilter) for f in h.filters):
            h.addFilter(RedactingFilter())
