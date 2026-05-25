from __future__ import annotations


def download_nba_headshot(person_id: str) -> str:
    from main import download_nba_headshot as legacy_download_nba_headshot

    return legacy_download_nba_headshot(person_id)

