"""
line_notify.py

LINE Messaging API を使った push通知の送信モジュール。
LINE Notify は2025年3月31日にサービス終了済みのため、後継の
Messaging API（チャネルアクセストークン + userId）を利用する。

必要な環境変数:
  LINE_CHANNEL_ACCESS_TOKEN … LINE Developersコンソールで発行した長期トークン
  LINE_USER_ID              … 通知を送りたいuserId。複数人に送る場合はカンマ区切りで
                               複数指定可能（例: "Uaaa...,Ubbb...,Uccc..."）
                               ※ LINE_BROADCAST=true の場合は不要
  LINE_BROADCAST            … "true" にすると、userIdを個別に集めなくても
                               公式アカウントを友だち追加した人全員に自動で届く
                               （broadcast API使用。無料プランの月200通枠は
                               「友だち人数 × 送信回数」で消費される点に注意）

セットアップ手順は README.md を参照。
"""

import os
from typing import Optional

import requests

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_MULTICAST_URL = "https://api.line.me/v2/bot/message/multicast"
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"


class LineNotifyError(Exception):
    pass


def send_line_message(
    text: str,
    channel_access_token: Optional[str] = None,
    user_id: Optional[str] = None,
    broadcast: Optional[bool] = None,
) -> None:
    """LINE Messaging API でテキストメッセージを送信する。

    - broadcast=True（またはLINE_BROADCAST=true）の場合: userIdの指定は不要で、
      公式アカウントを友だち追加している全員に届く（broadcast API）。
      新しく友だち追加した人も、userIdを取得する作業なしで自動的に対象になる。
    - それ以外: user_id（またはLINE_USER_ID環境変数）をカンマ区切りで複数指定でき、
      その場合は指定した相手だけに同じメッセージを送る（push / multicast API）。
    """
    token = channel_access_token or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise LineNotifyError(
            "LINE_CHANNEL_ACCESS_TOKEN が設定されていません。"
            "GitHub Secrets またはローカルの環境変数を確認してください。"
        )

    use_broadcast = broadcast if broadcast is not None else (
        os.environ.get("LINE_BROADCAST", "false").lower() == "true"
    )

    # LINEのテキストメッセージは1通あたり5000文字まで
    text = text[:4900]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    if use_broadcast:
        url = LINE_BROADCAST_URL
        payload = {"messages": [{"type": "text", "text": text}]}
    else:
        raw_ids = user_id or os.environ.get("LINE_USER_ID")
        if not raw_ids:
            raise LineNotifyError(
                "LINE_USER_ID が設定されていません（LINE_BROADCAST=true にする場合は不要）。"
            )
        to_ids = [i.strip() for i in raw_ids.split(",") if i.strip()]
        if not to_ids:
            raise LineNotifyError("LINE_USER_ID が空です。")

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
