"""pytest: main import before migrate would fail — run alembic at module load."""

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

_test_db_dir = tempfile.mkdtemp(prefix="mail-ci-")
_test_db_path = Path(_test_db_dir) / "mail_test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path.as_posix()}"

for _key, _value in {
    "SMTP_HOST": "localhost",
    "SMTP_USER": "ci_user",
    "SMTP_PASS": "ci_pass",
    "MAIL_FROM": "ci@example.com",
    "USER_SERVICE_URL": "http://localhost:8000",
    "NEWS_DATA_SERVICE_URL": "http://localhost:8004",
}.items():
    os.environ.setdefault(_key, _value)

_alembic_cfg = Config(str(_SERVICE_DIR / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")
