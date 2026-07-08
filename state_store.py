"""
state_store.py

GitHub Actionsはcron起動のたびに新しいコンテナで実行されるため、
「同じレースを何度も通知してしまう」問題を防ぐには状態をファイルに
永続化する必要がある。本モジュールは notified_races.json に
「その日どのレースを通知済みか」を記録し、日付が変わったら自動的に
リセットする。

また daily_summary.json には、閾値未満も含めてその日スキャンで
検出されたレースを蓄積する（「当日の検出履歴」表示用）。

いずれのファイルもワークフロー側（.github/workflows/rough_race_notify.yml）で
git commit & push されることで、次回実行時・ダッシュボード表示時にも引き継がれる。
"""

import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "notified_races.json")
DAILY_SUMMARY_FILE = os.path.join(os.path.dirname(__file__), "daily_summary.json")
PREVIEW_STATE_FILE = os.path.join(os.path.dirname(__file__), "daily_preview_sent.json")


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


# --- 当日の検出履歴（daily_summary.json） --------------------------------

def _empty_daily_summary(date_hd: str) -> dict:
    return {"date": date_hd, "races": {}}


def load_daily_summary(date_hd: str) -> dict:
    if not os.path.exists(DAILY_SUMMARY_FILE):
        return _empty_daily_summary(date_hd)
    try:
        with open(DAILY_SUMMARY_FILE, "r", encoding="utf-8") as f:
            summary = json.load(f)
    except (json.JSONDecodeError, OSError):
        return _empty_daily_summary(date_hd)

    if summary.get("date") != date_hd:
        return _empty_daily_summary(date_hd)
    summary.setdefault("races", {})
    return summary


def save_daily_summary(summary: dict) -> None:
    with open(DAILY_SUMMARY_FILE, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)


def upsert_daily_race(summary: dict, date_hd: str, race: dict) -> None:
    """
    そのレースの検出結果を記録する。同じレースが複数回スキャンされた場合は
    スコアが高い方（＝より荒れ感が強く出た時点の情報）で上書きする。
    """
    key = race_key(date_hd, race)
    existing = summary["races"].get(key)
    if existing is None or race.get("score", 0) >= existing.get("score", 0):
        summary["races"][key] = race


def daily_races_sorted(summary: dict) -> list:
    return sorted(summary.get("races", {}).values(), key=lambda r: r.get("score", 0), reverse=True)


# --- 事前予想の日次LINE通知の重複送信防止（daily_preview_sent.json） -------

def already_sent_preview(date_hd: str) -> bool:
    if not os.path.exists(PREVIEW_STATE_FILE):
        return False
    try:
        with open(PREVIEW_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False
    return state.get("date") == date_hd


def mark_preview_sent(date_hd: str) -> None:
    with open(PREVIEW_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"date": date_hd}, f, ensure_ascii=False, indent=2)
