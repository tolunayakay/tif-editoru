"""GitHub sürümlerinden yeni program sürümü denetimi.

Yalnızca ``v`` ile başlayan etiketler (ör. ``v1.2.0``) program sürümü sayılır; taslak ve
ön sürümler ile ``tesseract-…`` gibi yardımcı sürümler yok sayılır. Hiçbir şey indirilmez
ya da kurulmaz; yeni sürüm varsa kullanıcıya sürüm sayfası gösterilir.
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass

from . import GITHUB_URL, __version__
from .tess_install import _ssl_context


@dataclass
class Release:
    version: str
    url: str
    notes: str


def _parse(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def api_url() -> str:
    owner_repo = GITHUB_URL.rstrip("/").split("github.com/", 1)[1]
    return f"https://api.github.com/repos/{owner_repo}/releases?per_page=30"


def latest_release(timeout: int = 15) -> Release | None:
    req = urllib.request.Request(api_url(), headers={"User-Agent": "UyapTifViewer",
                                                     "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        data = json.load(resp)
    best: Release | None = None
    for r in data:
        tag = r.get("tag_name") or ""
        if r.get("draft") or r.get("prerelease") or not re.fullmatch(r"v\d+(\.\d+)*", tag):
            continue
        if best is None or _parse(tag) > _parse(best.version):
            best = Release(tag.lstrip("v"), r.get("html_url") or GITHUB_URL, (r.get("body") or "").strip())
    return best


def check_for_update() -> Release | None:
    """Kurulu sürümden yeni bir sürüm varsa onu döndürür."""
    r = latest_release()
    if r is not None and _parse(r.version) > _parse(__version__):
        return r
    return None
