import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
article_id_var: ContextVar[str | None] = ContextVar("article_id", default=None)
stage_var: ContextVar[str | None] = ContextVar("stage", default=None)
run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)

_CONTEXT = {
    "request_id": request_id_var,
    "article_id": article_id_var,
    "stage": stage_var,
    "run_id": run_id_var,
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, var in _CONTEXT.items():
            if (value := var.get()) is not None:
                out[key] = value
        extra = getattr(record, "extra", None)
        if isinstance(extra, dict):
            out.update(extra)
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    for noisy in ("httpx", "apscheduler", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
