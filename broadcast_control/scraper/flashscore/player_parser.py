from __future__ import annotations


def parse_player_from_match(driver, result: dict, match_url: str, **kwargs) -> dict:
    from main import parse_player_from_match as legacy_parse_player_from_match

    return legacy_parse_player_from_match(driver, result, match_url, **kwargs)

