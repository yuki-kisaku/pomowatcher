"""OS共通の設定値とJSON保存。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path


BGM_VOLUME_DEFAULT = 50
BGM_VOLUME_MIN = 0
BGM_VOLUME_MAX = 125
BGM_VOLUME_STEP = 10
NOTIFY_VOLUME_DEFAULT = 90
NOTIFY_VOLUME_MAX = 200


def normalize_volume(
    value: object,
    *,
    default: int = BGM_VOLUME_DEFAULT,
    minimum: int = BGM_VOLUME_MIN,
    maximum: int = BGM_VOLUME_MAX,
) -> int:
    try:
        volume = int(value)
    except (TypeError, ValueError):
        return default
    if not minimum <= volume <= maximum:
        return default
    return volume


def normalize_notify_volume(value: object) -> int:
    return normalize_volume(
        value,
        default=NOTIFY_VOLUME_DEFAULT,
        maximum=NOTIFY_VOLUME_MAX,
    )


@dataclass
class AppSettings:
    bgm_muted: bool = False
    bgm_volume: int = BGM_VOLUME_DEFAULT
    notify_volume: int = NOTIFY_VOLUME_DEFAULT


class SettingsStore:
    """保存先の違いを隠し、同じ設定形式を読み書きする。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSettings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            data = {}
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("設定を読み込めません。初期値で続行します: %s", exc)
            data = {}
        return AppSettings(
            bgm_muted=data.get("bgm_muted") is True,
            bgm_volume=normalize_volume(data.get("bgm_volume")),
            notify_volume=normalize_notify_volume(data.get("notify_volume")),
        )

    def save(self, settings: AppSettings) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = self.path.with_suffix(".tmp")
            payload = asdict(settings)
            payload["bgm_volume"] = normalize_volume(payload["bgm_volume"])
            payload["notify_volume"] = normalize_notify_volume(payload["notify_volume"])
            temporary_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary_path.replace(self.path)
        except OSError as exc:
            logging.warning("設定を保存できません: %s", exc)
