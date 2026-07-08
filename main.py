"""
main.py

「荒れるレース」自動検出 → LINE通知 の実行エントリーポイント。
GitHub Actionsから数分おきに起動される想定（.github/workflows/rough_race_notify.yml）。

処理の流れ:
  1. rough_race_scanner で全会場を巡回し、締切間際のレースを収集・スコアリング
  2. 展示タイムが公表済みの結果を daily_summary.json に蓄積（当日の検出履歴）
  3. スコアが閾値以上（デフォルト: score >= 50 = "大波乱気配🔥"）のレースを抽出
  4. state_store で当日通知済みのレースを除外（重複通知防止）
  5. 未通知の新規該当レースがあればLINEにpush通知し、通知済みとして記録
"""

import asyncio
import os
import sys

from rough_race_scanner import find_rough_races_today
from line_notify import send_line_message, build_rough_race_message, LineNotifyError
from state_store import (
    load_state, save_state, race_key, is_notified, mark_notified,
    load_daily_summary, save_daily_summary, upsert_daily_race,
)

# 通知を送るスコアの閾値。デフォルトは「大波乱気配🔥」ライン。
# 環境変数 ROUGH_SCORE_THRESHOLD で上書き可能（例: 20 にすると「波乱含み」も拾う）
SCORE_THRESHOLD = int(os.environ.get("ROUGH_SCORE_THRESHOLD", "50"))

# 対象日。省略時は当日（JST）。GitHub Actionsから TARGET_DATE=YYYYMMDD で指定可能。
TARGET_DATE = os.environ.get("TARGET_DATE") or None

DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"


def main() -> int:
    results, date_hd, status = asyncio.run(find_rough_races_today(TARGET_DATE))

    if status != "ok":
        print(f"[INFO] 対象レースなし（status={status}）")
        return 0

    # 展示タイムが公表済みの結果は、閾値未満も含めて当日の検出履歴に記録する
    recordable = [r for r in results if r.get("status") != "データ収集中"]
    if recordable:
        summary = load_daily_summary(date_hd)
        for race in recordable:
            upsert_daily_race(summary, date_hd, race)
        save_daily_summary(summary)

    candidates = [r for r in results if r["score"] >= SCORE_THRESHOLD]
    if not candidates:
        print(f"[INFO] 閾値({SCORE_THRESHOLD})以上のレースなし。取得件数={len(results)}")
        return 0

    state = load_state(date_hd)
    sent = 0
    errors = 0

    for race in candidates:
        key = race_key(date_hd, race)
        if is_notified(state, key):
            continue

        message = build_rough_race_message(race)
        print(f"[NOTIFY] {key} score={race['score']} status={race['status']}")

        if DRY_RUN:
            print(message)
        else:
            try:
                send_line_message(message)
            except LineNotifyError as e:
                print(f"[ERROR] {key} の通知に失敗: {e}", file=sys.stderr)
                errors += 1
                continue

        mark_notified(state, key)
        sent += 1

    save_state(state)
    print(f"[DONE] 新規通知={sent}件 / 失敗={errors}件 / 検出総数={len(results)}件")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
