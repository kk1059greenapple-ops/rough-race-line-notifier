"""
state_store.py

GitHub Actionsはcron起動のたびに新しいコンテナで実行されるため、
「同じレースを何度も通知してしまう」問題を防ぐには状態をファイルに
永続化する必要がある。本モジュールは notified_races.json に
「その日どのレースを通知済みか」を記録し、日付が変わったら自動的に
リセットする。

ファイルはワークフロー側（.github/workflows/rough_race_notify.yml）で
git commit & push されることで、次回実行時にも引き継がれる。
"""

import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "notified_races.json")


def _empty_state(date_hd: str) -> dict:
    return {"date": date_hd, "notified": []}


def load_state(date_hd: str) -> dict:
    if not os.path.exists(STATE_FILE):
        return _empty_state(date_hd)
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_state(date_hd)

    if state.get("date") != date_hd:
        # 日付が変わっていたらリセット
        return _empty_state(date_hd)
    state.setdefault("notified", [])
    return state


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def race_key(date_hd: str, race: dict) -> str:
    return f"{date_hd}_{race['venue']}_{race['race_no']}R"


def is_notified(state: dict, key: str) -> bool:
    return key in state["notified"]


def mark_notified(state: dict, key: str) -> None:
    state["notified"].append(key)
