from __future__ import annotations

from .schemas import ConfigState, GraphicState, PlayerState, ResultState


def default_config() -> ConfigState:
    return ConfigState(
        urls=[],
        update_frequency=8,
        strict_match_players_only=True,
        dump_player_candidates=True,
        auto_switch_match_url=True,
        overlay_screen="team_stats",
    )


def default_result() -> ResultState:
    return ResultState()


def default_player() -> PlayerState:
    return PlayerState(
        stats={
            "PPG": "",
            "RPG": "",
            "APG": "",
            "STL": "",
            "BLK": "",
            "FG": "",
            "3P": "",
            "FT": "",
            "MIN": "",
            "PLUS_MINUS": "",
            "TOV": "",
            "PF": "",
        }
    )


def default_preview_state() -> GraphicState:
    return GraphicState(phase="idle", selected_layer="player_card")


def default_live_state() -> GraphicState:
    return GraphicState(phase="idle", selected_layer="player_card")
