"""
line_notify.py

LINE Messaging API を使った push通知の送信モジュール。
LINE Notify は2025年3月31日にサービス終了済みのため、後継の
Messaging API（チャネルアクセストークン + userId）を利用する。

必要な環境変数:
  LINE_CHANNEL_ACCESS_TOKEN … LINE Developersコンソールで発行した長期トークン
  LINE_USER_ID              … 通知を送りたい自分のuserId

セットアップ手順は README.md を参照。
"""

import os
from typing import Optional

import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotifyError(Exception):
    pass


def send_line_message(text: str, channel_access_token: Optional[str] = None, user_id: Optional[str] = None) -> None:
    """LINE Messaging API でテキストメッセージをpush送信する。"""
    token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    to_id = user_id or os.environ.get("LINE_USER_ID")

    if not token or not to_id:
        raise LineNotifyError(
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が設定されていません。"
            "GitHub Secrets またはローカルの環境変数を確認してください。"
        )

    # LINEのテキストメッセージは1通あたり5000文字まで
    text = text[:4900]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": to_id,
        "messages": [{"type": "text", "text": text}],
    }

    resp = requests.post(LINE_PUSH_URL, headers=headers, json=payload, timeout=15)
    if resp.status_code != 200:
        raise LineNotifyError(f"LINE通知に失敗しました: {resp.status_code} {resp.text}")


def build_rough_race_message(race: dict) -> str:
    """検出結果の1レース分をLINEメッセージ用テキストに整形する。"""
    return (
        f"🔥 荒れそうなレース検知\n"
        f"{race['venue']} {race['race_no']}R（締切 {race['deadline']}）\n"
        f"判定: {race['status']}（score {race['score']}）\n"
        f"理由: {race['reasons']}\n"
        f"1号艇展示タイム: {race['b1_ex']} / 最速展示タイム: {race['best_ex']}"
    )
