"""Runtime localization loaded from editable JSON files."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class Localization:
    DEFAULT_LANGUAGE = "ru"

    def __init__(self, language_dir: Path | None = None) -> None:
        self._language_dir = language_dir
        self.languages: dict[str, dict[str, Any]] = {}
        self.language_code = self.DEFAULT_LANGUAGE
        self.reload()

    def _directories(self) -> list[Path]:
        if self._language_dir is not None:
            return [self._language_dir]
        root = Path(__file__).resolve().parents[2]
        directories = [root / "assets" / "lang"]
        executable_directory = Path(sys.executable).resolve().parent / "assets" / "lang"
        if executable_directory not in directories:
            directories.insert(0, executable_directory)
        return directories

    @staticmethod
    def _valid_language(data: Any) -> bool:
        metadata = data.get("language") if isinstance(data, dict) else None
        return isinstance(metadata, dict) and isinstance(metadata.get("code"), str) and \
            isinstance(metadata.get("name"), str) and bool(metadata["code"].strip()) and bool(metadata["name"].strip())

    def reload(self) -> None:
        languages: dict[str, dict[str, Any]] = {}
        for directory in self._directories():
            if not directory.is_dir():
                continue
            for path in directory.glob("*.json"):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if self._valid_language(data) and data["language"]["code"] == path.stem:
                    languages.setdefault(data["language"]["code"], data)
        self.languages = languages
        if self.language_code not in languages:
            self.language_code = self.DEFAULT_LANGUAGE

    def available_languages(self) -> dict[str, str]:
        return {code: data["language"]["name"] for code, data in self.languages.items()}

    def set_language(self, code: str) -> str:
        self.language_code = code if code in self.languages else self.DEFAULT_LANGUAGE
        return self.language_code

    @staticmethod
    def _value(data: dict[str, Any], key: str) -> str | None:
        value: Any = data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value if isinstance(value, str) else None

    def tr(self, key: str, **kwargs: Any) -> str:
        value = self._value(self.languages.get(self.language_code, {}), key)
        if value is None:
            value = self._value(self.languages.get(self.DEFAULT_LANGUAGE, {}), key)
        if value is None:
            return key
        try:
            return value.format(**kwargs)
        except (KeyError, ValueError):
            return value


localization = Localization()


def tr(key: str, **kwargs: Any) -> str:
    return localization.tr(key, **kwargs)
