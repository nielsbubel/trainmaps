"""Validated, stable identifiers for source lines and mapped geometries."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


LINE_ID_PATTERN = r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$"
NETWORK_ID_PATTERN = LINE_ID_PATTERN


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceAlias(StrictModel):
    netz: str = Field(min_length=1, max_length=200)
    line: str = Field(min_length=1, max_length=200)


class GeometryReference(StrictModel):
    source: Literal["basemap.de"] = "basemap.de"
    source_layer: Literal["Verkehrslinie"] = "Verkehrslinie"
    source_class: Literal["S-Bahn"] = "S-Bahn"
    fallback_classes: list[Literal["Eisenbahn", "Personenverkehr", "Gleis"]] = Field(
        default_factory=list, max_length=3
    )
    status: Literal["pending", "mapped", "verified"] = "pending"
    reference: str | None = Field(default=None, min_length=1, max_length=300)
    version: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def mapped_geometry_has_reference(self):
        if self.status != "pending" and (not self.reference or not self.version):
            raise ValueError("Mapped or verified geometry requires reference and version")
        return self


class LineDefinition(StrictModel):
    revision: int = Field(ge=1, le=2_147_483_647)
    network_id: str = Field(pattern=NETWORK_ID_PATTERN, min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    source_aliases: list[SourceAlias] = Field(min_length=1, max_length=100)
    geometry: GeometryReference = Field(default_factory=GeometryReference)
    active: bool = True
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def aliases_are_unique(self):
        aliases = {(alias.netz, alias.line) for alias in self.source_aliases}
        if len(aliases) != len(self.source_aliases):
            raise ValueError("source_aliases contains duplicate netz/line pairs")
        return self


class LineRecord(LineDefinition):
    line_id: str = Field(pattern=LINE_ID_PATTERN, min_length=1, max_length=120)
    updated_at: str


class LineList(StrictModel):
    total: int
    offset: int
    next_offset: int | None
    values: list[LineRecord]
