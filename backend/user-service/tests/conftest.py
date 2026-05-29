"""pytest: main import 전에 테스트 DB 마이그레이션을 최우선 적용."""

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

_test_db_dir = tempfile.mkdtemp(prefix="user-ci-")
_test_db_path = Path(_test_db_dir) / "user_test.sqlite"
os.environ["DATABASE_URL"] = f"sqlite:///{_test_db_path.as_posix()}"

_alembic_cfg = Config(str(_SERVICE_DIR / "alembic.ini"))
command.upgrade(_alembic_cfg, "head")
