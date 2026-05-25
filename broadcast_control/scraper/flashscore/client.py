from __future__ import annotations


def get_driver():
    from main import get_driver as legacy_get_driver

    return legacy_get_driver()


def close_consent(driver) -> None:
    from main import close_consent as legacy_close_consent

    legacy_close_consent(driver)

