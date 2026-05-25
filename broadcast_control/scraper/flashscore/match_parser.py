from __future__ import annotations


def parse_quarter_scores(driver, result: dict) -> None:
    from main import parse_quarter_scores as legacy_parse_quarter_scores

    legacy_parse_quarter_scores(driver, result)


def scrape_match(driver, url: str, include_stats: bool = True) -> tuple[dict, dict]:
    from main import scrape as legacy_scrape

    return legacy_scrape(driver, url, include_stats=include_stats)

