"""Utilities for handling scheduling poll date-times safely."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

UTC = ZoneInfo("UTC")


def _ensure_roundtrip(local_dt: datetime, zone: ZoneInfo) -> None:
    """Ensure that a localized datetime survives a UTC round-trip.

    The timezone transitions occurring during DST changes can result in
    "missing" hours (spring forward) or duplicate hours (fall back).  To ensure
    that we never interpret a non-existent time, the localized datetime is
    converted to UTC and back to the original timezone.  If the resulting wall
    time differs, the original value did not represent a real instant in that
    timezone.
    """
    utc_dt = local_dt.astimezone(UTC)
    roundtrip_dt = utc_dt.astimezone(zone)
    if (
        roundtrip_dt.date() != local_dt.date()
        or roundtrip_dt.hour != local_dt.hour
        or roundtrip_dt.minute != local_dt.minute
        or roundtrip_dt.fold != local_dt.fold
    ):
        raise ValueError("The selected local time does not exist in the given timezone.")


class PollSlot(BaseModel):
    """Representation of a single poll option."""

    date: date
    time: time
    timezone: str = Field(..., description="IANA timezone identifier")
    fold: int = Field(0, description="Select the second occurrence when an hour repeats")

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ValueError(f"Unknown timezone '{value}'") from exc
        return value

    @field_validator("fold")
    @classmethod
    def _validate_fold(cls, value: int) -> int:
        if value not in (0, 1):
            raise ValueError("fold must be either 0 or 1")
        return value

    def localized_datetime(self) -> datetime:
        """Return the timezone aware datetime represented by this slot.

        The conversion is performed in a single place so every caller (event
        creation, notification generation, etc.) shares the exact same logic.
        This eliminates subtle discrepancies that previously occurred when
        different call sites used slightly different conversion methods.
        """

        zone = ZoneInfo(self.timezone)
        naive = datetime.combine(self.date, self.time.replace(second=0, microsecond=0))
        localized = naive.replace(tzinfo=zone, fold=self.fold)
        _ensure_roundtrip(localized, zone)
        return localized


class NormalizedSlot(BaseModel):
    """Normalized representation of a poll slot."""

    utc: datetime
    local: datetime
    fold: int

    model_config = ConfigDict()

    @field_serializer("utc", "local")
    def _serialize_datetime(self, value: datetime) -> str:  # pragma: no cover - serialization helper
        return value.isoformat()


class PollSelection(BaseModel):
    """A chosen start and end slot for scheduling."""

    start: PollSlot
    end: PollSlot

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PollNormalizationResponse(BaseModel):
    """Response payload returned to the client after normalization."""

    timezone: str
    start: NormalizedSlot
    end: NormalizedSlot

    model_config = ConfigDict(str_strip_whitespace=True)


def normalize_slot(slot: PollSlot) -> NormalizedSlot:
    """Normalize a single poll slot into local and UTC representations."""

    local_dt = slot.localized_datetime()
    utc_dt = local_dt.astimezone(UTC)
    return NormalizedSlot(utc=utc_dt, local=local_dt, fold=local_dt.fold)


def normalize_selection(selection: PollSelection) -> PollNormalizationResponse:
    """Normalize a selected start/end pair, validating the overall interval."""

    if selection.start.timezone != selection.end.timezone:
        raise ValueError("Start and end timezones must match.")

    start_normalized = normalize_slot(selection.start)
    end_normalized = normalize_slot(selection.end)

    if end_normalized.utc <= start_normalized.utc:
        raise ValueError("End time must be after start time.")

    return PollNormalizationResponse(
        timezone=selection.start.timezone,
        start=start_normalized,
        end=end_normalized,
    )
