from __future__ import annotations


def parse_stats(driver, result: dict) -> None:
    from main import parse_stats as legacy_parse_stats

    legacy_parse_stats(driver, result)

