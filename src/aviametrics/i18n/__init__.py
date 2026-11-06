"""Minimal i18n: one TOML file per language, t(lang, key, **fmt)."""
import tomllib
from functools import cache
from pathlib import Path

LANGS = {"de": "Deutsch", "en": "English"}


@cache
def _load(lang: str) -> dict:
    return tomllib.loads((Path(__file__).parent / f"{lang}.toml").read_text())


def t(lang: str, key: str, **fmt) -> str:
    s = _load(lang).get(key) or _load("de").get(key, key)
    return s.format(**fmt) if fmt else s
