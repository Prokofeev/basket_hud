from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    updated_at: str = Field(default_factory=utc_now)
    source: str = "broadcast-control"
    generation: int = 0


class ConfigState(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    urls: list[str] = Field(default_factory=list)
    update_frequency: int = 8
    stream_port: int = 8081
    strict_match_players_only: bool = True
    dump_player_candidates: bool = True
    auto_switch_match_url: bool = True
    overlay_screen: str = "team_stats"
    meta: AppMeta = Field(default_factory=lambda: AppMeta(schema_version=1, source="config"), alias="_meta")


class TeamState(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = ""
    abbr: str = ""
    logo: str = ""
    total: str = ""
    q1: str = ""
    q2: str = ""
    q3: str = ""
    q4: str = ""
    ot: str = ""
    FG: str = ""
    threeP: str = Field(default="", alias="3P")
    FT: str = ""
    REB: str = ""
    AST: str = ""
    TOV: str = ""
    PF: str = ""
    players: list[dict[str, Any]] = Field(default_factory=list)


class ResultState(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    status: str = "scheduled"
    screen: str = "team_stats"
    quarter: str = ""
    time: str = ""
    home: TeamState = Field(default_factory=TeamState)
    away: TeamState = Field(default_factory=TeamState)
    meta: AppMeta = Field(default_factory=lambda: AppMeta(schema_version=1, source="result"), alias="_meta")


class PlayerState(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = 2
    visible: bool = False
    mode: str = "hidden"
    updated_at: str = Field(default_factory=utc_now)
    source: str = "broadcast-control"
    team_side: str = ""
    match_key: str = ""
    name: str = ""
    number: str = ""
    position: str = ""
    team: str = ""
    photo: str = ""
    photo_source: str = ""
    photo_status: str = ""
    stats: dict[str, Any] = Field(default_factory=dict)
    meta: AppMeta = Field(default_factory=lambda: AppMeta(schema_version=2, source="player"), alias="_meta")


class GraphicState(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: int = 1
    phase: Literal[
        "idle",
        "draft_dirty",
        "preview_ready",
        "armed",
        "taking",
        "on_air_synced",
        "emergency_hidden",
    ] = "idle"
    selected_layer: str = "player_card"
    armed: bool = False
    emergency_hidden: bool = False
    player: PlayerState = Field(default_factory=PlayerState)
    result: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    updated_at: str = Field(default_factory=utc_now)
    meta: AppMeta = Field(default_factory=lambda: AppMeta(schema_version=1, source="graphic-state"), alias="_meta")


class StateEnvelope(BaseModel):
    model_config = ConfigDict(extra="allow")

    live_state: GraphicState = Field(default_factory=GraphicState)
    preview_state: GraphicState = Field(default_factory=GraphicState)
    last_good_state: GraphicState = Field(default_factory=GraphicState)
