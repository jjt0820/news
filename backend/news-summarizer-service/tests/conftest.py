"""pytest: run alembic before main import (summarized_news schema)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config

_SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))

_test_db_dir = tempfile.mkdtemp(prefix="summarizer-ci-")
_test_db_path = Path(_test_db_dir) / "news_test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path.as_posix()}"
os.environ.setdefault("GEMINI_API_KEY", "ci-placeholder-not-used-for-summarize-endpoint")

_alembic_cfg = Config(str(_SERVICE_DIR / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")
