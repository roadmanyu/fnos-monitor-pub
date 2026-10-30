"""Apprise 推送。"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def send_apprise(urls: list[str], title: str, body: str) -> bool:
    if not urls:
        return False
    try:
        import apprise

        apobj = apprise.Apprise()
        for u in urls:
            if not apobj.add(u):
                log.warning("invalid apprise url (skipped)")
        ok = apobj.notify(title=title, body=body)
        return bool(ok)
    except Exception as e:
        log.warning("apprise notify failed: %s", e)
        return False
