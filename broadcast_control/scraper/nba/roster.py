from __future__ import annotations


def find_nba_player_id(full_name: str) -> str:
    from main import find_nba_player_id as legacy_find_nba_player_id

    return legacy_find_nba_player_id(full_name)

