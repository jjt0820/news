"""pytest: mock boto3 S3 client for news-fetcher-service."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(_SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVICE_DIR))


@pytest.fixture(autouse=True)
def _mock_boto3_s3_client():
    mock_client = MagicMock()
    with patch("boto3.client", return_value=mock_client):
        yield mock_client
