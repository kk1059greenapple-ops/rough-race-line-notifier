"""
line_notify.py

LINE Messaging API を使った push通知の送信モジュール。
LINE Notify は2025年3月31日にサービス終了済みのため、後継の
Messaging API（チャネルアクセストークン + userId）を利用する。

必要な環境変数:
  LINE_CHANNEL_ACCESS_TOKEN … LINE Developersコンソールで発行した長期トークン
  LINE_USER_ID              … 通知を送りたいuserId。複数人に送る場合はカンマ区切りで
                               複数指定可能（例: "Uaaa...,Ubbb...,Uccc..."）

セットアップ手順は README.md を参照。
"""

import os
from typing import Optional

import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_MULTICAST_URL = "https://api.line.me/v2/bot/message/multicast"


class LineNotifyError(Exception):
    pass


def send_line_message(text: str, channel_access_token: Optional[str] = None, user_id: Optional[str] = None) -> None:
    """LINE Messaging API でテキストメッセージをpush送信する。

    user_id（またはLINE_USER_ID環境変数）はカンマ区切りで複数指定でき、
    その場合は複数の相手に同じメッセージを送る（multicast API使用）。
    """
    token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    raw_ids = user_id or os.environ.get("LINE_USER_ID")

    if not token or not raw_ids:
        raise LineNotifyError(
            "LINE_CHANNEL_ACCESS_TOKEN / LINE_USER_ID が設定されていません。"
            "GitHub Secrets またはローカルの環境変数を確認してください。"
        )

    to_ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
    if not to_ids:
        raise LineNotifyError("LINE_USER_ID が空です。")

    # LINEのテキストメッセージは1通あたり5000文字まで
    text = text[:4900]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    if len(to_ids) == 1:
        url = LINE_PUSH_URL
        payload = {"to": to_ids[0], "messages": [{"type": "text", "text": text}]}
    else:
        # multicastは1回のAPI呼び出しで最大500人まで送信可能
        url = LINE_MULTICAST_URL
        payload = {"to": to_ids, "messages": [{"type": "text", "text": text}]}

    resp = requests.post(url, headers=headers, json=payload, timeout=15)
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


def build_daily_preview_message(races: list, date_hd: str) -> str:
    """
    事前予想モード（出走表ベース）の結果をまとめた、その日の朝に送る
    ダイジェストメッセージを組み立てる。races はスコア降順を想定。
    """
    date_label = f"{date_hd[0:4]}/{date_hd[4:6]}/{date_hd[6:8]}" if len(date_hd) == 8 else date_hd
    lines = [f"🌅 本日({date_label})の荒れそうなレース予想", ""]
    for race in races:
        lines.append(
            f"【{race['venue']} {race['race_no']}R】{race['status']}（score {race['score']}）\n"
            f"　{race['reasons']}"
        )
    lines.append("")
    lines.append("※出走表データ（全国勝率・モーター成績・今節成績等）に基づく事前予想です。展示タイムは未反映。")
    return "\n".join(lines)
