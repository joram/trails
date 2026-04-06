from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Waypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float
    lng: float
    alt: Optional[float] = None


class TrailStats(BaseModel):
    """Key/value stats from source sites; keys are not fixed across trails."""

    model_config = ConfigDict(extra="allow")


class TrailFile(BaseModel):
    """Serialized trail record in ``trails/data/.../*.json``."""

    model_config = ConfigDict(extra="forbid")

    center_geohash: Optional[str] = None
    center_lat: Optional[float] = None
    center_lng: Optional[float] = None
    description: str = ""
    directions: str = ""
    geohash: Optional[str] = None
    nearest_peak_geohash: Optional[str] = None
    photos: List[str] = Field(default_factory=list)
    source_url: str = ""
    stats: TrailStats = Field(default_factory=TrailStats)
    title: str
    trail_id: str
    waypoints: Optional[List[List[Waypoint]]] = None

    @field_validator("trail_id", mode="before")
    @classmethod
    def _coerce_trail_id(cls, v: object) -> str:
        if v is None:
            raise TypeError("trail_id is required")
        return str(v)


class PeakRecord(BaseModel):
    """One GNDB-style peak entry from ``peaks.json``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    title: str = Field(alias="Geographical Name")
    lat: float = Field(alias="Latitude")
    lng: float = Field(alias="Longitude")
    geohash: str
