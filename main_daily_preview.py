"""
main_daily_preview.py

「事前予想モード」の日次ダイジェストをLINEに送るエントリーポイント。
GitHub Actionsから1日1回、朝に起動される想定
（.github/workflows/daily_preview_notify.yml）。

main.py（直前情報ベースの随時通知）とは別の通知系統。
1日1回だけ送るため、同日中に複数回起動された場合は
daily_preview_sent.json を見て2通目以降をスキップする
（workflow_dispatchでの手動再実行時に FORCE_RESEND=true を渡せば強制再送可能）。
"""

import asyncio
import os
import sys

from racelist_scanner import scan_all_races_today
from line_notify import send_line_message, build_daily_preview_message, LineNotifyError
from state_store import already_sent_preview, mark_preview_sent

# 通知対象とするスコアの閾値。デフォルトは「波乱注意🔥」ライン。
PRE_RACE_SCORE_THRESHOLD = int(os.environ.get("PRE_RACE_SCORE_THRESHOLD", "45"))

# ダイジェストに載せる最大件数（LINEの1通あたり文字数制限対策）
TOP_N = int(os.environ.get("PRE_RACE_TOP_N", "10"))

TARGET_DATE = os.environ.get("TARGET_DATE") or None
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
FORCE_RESEND = os.environ.get("FORCE_RESEND", "false").lower() == "true"


def main() -> int:
    results, date_hd, status = asyncio.run(scan_all_races_today(TARGET_DATE))

    if status != "ok":
        print(f"[INFO] 本日の開催情報を取得できませんでした（status={status}）")
        return 0

    if not FORCE_RESEND and already_sent_preview(date_hd):
        print(f"[INFO] 本日({date_hd})分は送信済みのためスキップします。")
        return 0

    candidates = [r for r in results if r["score"] >= PRE_RACE_SCORE_THRESHOLD][:TOP_N]
    if not candidates:
        print(f"[INFO] 閾値({PRE_RACE_SCORE_THRESHOLD})以上のレースなし。取得件数={len(results)}")
        # 該当なしでも「送信済み」として扱い、1日1回だけの実行に留める
        mark_preview_sent(date_hd)
        return 0

    message = build_daily_preview_message(candidates, date_hd)
    print(message)

    if DRY_RUN:
        print(f"[DRY_RUN] {len(candidates)}件を送信予定（実際には送信しません）")
    else:
        try:
            send_line_message(message)
        except LineNotifyError as e:
            print(f"[ERROR] 送信に失敗: {e}", file=sys.stderr)
            return 1

    mark_preview_sent(date_hd)
    print(f"[DONE] 事前予想 {len(candidates)}件を通知（取得総数={len(results)}件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
