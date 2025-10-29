from __future__ import annotations

import sys
from pathlib import Path

import asyncio
import os
import types

import pytest

LIB_PATH = Path(__file__).resolve().parents[1] / "ex_app" / "lib"
if str(LIB_PATH) not in sys.path:
    sys.path.insert(0, str(LIB_PATH))

os.environ.setdefault("APP_ID", "flow")
os.environ.setdefault("APP_SECRET", "test-secret")
os.environ.setdefault("NEXTCLOUD_URL", "http://localhost")
os.environ.setdefault("APP_PORT", "0")
os.environ.setdefault("APP_HOST", "127.0.0.1")
PERSISTENT_DIR = (Path(__file__).parent / "_tmp").resolve()
os.environ.setdefault("APP_PERSISTENT_STORAGE", str(PERSISTENT_DIR))
PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)

if "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class _PlaceholderClient:  # pragma: no cover - defensive stub
        def __init__(self, *args, **kwargs) -> None:  # noqa: D401
            raise RuntimeError("httpx is unavailable in the unit test environment.")

    def _raise_httpx_usage(*args, **kwargs):  # pragma: no cover - defensive stub
        raise RuntimeError("httpx network calls are unsupported in tests.")

    fake_httpx.AsyncClient = _PlaceholderClient
    fake_httpx.Client = _PlaceholderClient
    fake_httpx.post = fake_httpx.get = fake_httpx.put = fake_httpx.delete = _raise_httpx_usage  # type: ignore
    sys.modules["httpx"] = fake_httpx

import main  # type: ignore  # pylint: disable=import-error
import scheduling_poll  # type: ignore  # pylint: disable=import-error
from fastapi import HTTPException


def test_normalize_selection_handles_fall_back():
    selection = scheduling_poll.PollSelection(
        start={
            "date": "2024-11-03",
            "time": "01:30",
            "timezone": "America/New_York",
            "fold": 1,
        },
        end={
            "date": "2024-11-03",
            "time": "02:30",
            "timezone": "America/New_York",
        },
    )

    response = scheduling_poll.normalize_selection(selection)

    assert response.start.fold == 1
    assert response.start.local.isoformat() == "2024-11-03T01:30:00-05:00"
    assert response.start.utc.isoformat() == "2024-11-03T06:30:00+00:00"
    assert response.end.utc.isoformat() == "2024-11-03T07:30:00+00:00"


def test_normalize_selection_rejects_nonexistent_time():
    selection = scheduling_poll.PollSelection(
        start={
            "date": "2024-03-10",
            "time": "02:30",
            "timezone": "America/New_York",
        },
        end={
            "date": "2024-03-10",
            "time": "03:30",
            "timezone": "America/New_York",
        },
    )

    with pytest.raises(ValueError) as exc:
        scheduling_poll.normalize_selection(selection)

    assert "does not exist" in str(exc.value)


def test_normalize_selection_requires_shared_timezone():
    selection = scheduling_poll.PollSelection(
        start={
            "date": "2024-11-03",
            "time": "01:30",
            "timezone": "America/New_York",
        },
        end={
            "date": "2024-11-03",
            "time": "02:30",
            "timezone": "Europe/Berlin",
        },
    )

    with pytest.raises(ValueError) as exc:
        scheduling_poll.normalize_selection(selection)

    assert "timezones must match" in str(exc.value)


def test_route_wrapper_surfaces_validation_error():
    selection = scheduling_poll.PollSelection(
        start={
            "date": "2024-03-10",
            "time": "02:30",
            "timezone": "America/New_York",
        },
        end={
            "date": "2024-03-10",
            "time": "03:30",
            "timezone": "America/New_York",
        },
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.normalize_scheduling_poll(selection))

    assert exc.value.status_code == 400
    assert "does not exist" in exc.value.detail
