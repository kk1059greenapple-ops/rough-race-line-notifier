"""
app.py — 荒れるレース検出ダッシュボード（新規独立アプリ）

既存の boat-race-app（予想アプリ）とは完全に別のアプリケーションです。
このアプリには3つのモードがあります（タブで切り替え）:

  1. 🔎 直前スキャン: 締切15分前後のレースを展示タイムから荒れ度判定（従来機能）
  2. 🌅 事前予想（全レース）: 展示タイムを待たず、出走表の全国勝率・モーター成績・
     級別から「今日のレース全体」を荒れそうな順にランキング
  3. 📋 本日の検出履歴: GitHub Actionsが自動スキャンした結果を1日分蓄積して一覧表示

バックグラウンドの自動監視・LINE通知は同リポジトリの GitHub Actions
（.github/workflows/rough_race_notify.yml が main.py を定期実行）が担当し、
このダッシュボードを開いていなくても自動で動きます。

Streamlit Community Cloud にデプロイして使うことを想定。
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import nest_asyncio
import streamlit as st

from rough_race_scanner import find_rough_races_today
from racelist_scanner import scan_all_races_today
from line_notify import send_line_message, build_rough_race_message, build_daily_preview_message, LineNotifyError
from state_store import (
    load_state, save_state, race_key, is_notified, mark_notified,
    load_daily_summary, daily_races_sorted,
)

JST = timezone(timedelta(hours=9))
nest_asyncio.apply()

st.set_page_config(page_title="荒れるレース検出ダッシュボード", page_icon="🔥", layout="wide")

# Streamlit Cloudの st.secrets をLINE通知モジュールが読む環境変数に反映
# （GitHub Actions側は Secrets を環境変数として直接渡すので、ここは
#  Streamlit Cloud上で動かす場合のみ必要な橋渡し）
# secrets.tomlが存在しない環境（ローカルで未設定の場合など）では
# st.secrets へのアクセス自体が FileNotFoundError を出すため、握りつぶして継続する。
try:
    for key in ("LINE_CHANNEL_ACCESS_TOKEN", "LINE_USER_ID"):
        if key not in os.environ and key in st.secrets:
            os.environ[key] = st.secrets[key]
except FileNotFoundError:
    pass

DEFAULT_THRESHOLD = int(os.environ.get("ROUGH_SCORE_THRESHOLD", "50"))
TODAY_JST = datetime.now(JST).strftime("%Y%m%d")

st.title("🔥 荒れるレース検出ダッシュボード")

with st.sidebar:
    st.header("設定")
    target_date = st.text_input("対象日 (YYYYMMDD)", value=TODAY_JST)
    st.divider()
    token_ok = bool(os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")) and bool(os.environ.get("LINE_USER_ID"))
    st.write("LINE連携: " + ("✅ 設定済み" if token_ok else "⚠️ 未設定（Secrets未登録）"))

tab_live, tab_preview, tab_history = st.tabs(["🔎 直前スキャン", "🌅 事前予想（全レース）", "📋 本日の検出履歴"])


# ---------------------------------------------------------------------------
# タブ1: 直前スキャン（従来の展示タイムベース判定）
# ---------------------------------------------------------------------------
with tab_live:
    st.caption(
        "全24会場を横断し、締切15分前後のレースを展示タイムから荒れ度スコアで判定します。"
        "自動LINE通知はこの画面を開いていなくても GitHub Actions が裏で動かしています。"
    )
    threshold = st.slider(
        "通知対象スコアのしきい値", min_value=0, max_value=100, value=DEFAULT_THRESHOLD, step=5, key="live_threshold"
    )
    st.caption("展示タイム差0.1秒ごとに20点。50以上=「大波乱気配🔥」目安、20〜49は「波乱含み」。")

    if "scan_results" not in st.session_state:
        st.session_state.scan_results = None
        st.session_state.scan_status = None
        st.session_state.scan_date = None

    if st.button("🔍 今すぐスキャン", type="primary", key="live_scan_btn"):
        with st.spinner("全会場を巡回中..."):
            results, date_hd, status = asyncio.run(find_rough_races_today(target_date or None))
            st.session_state.scan_results = results
            st.session_state.scan_status = status
            st.session_state.scan_date = date_hd

    results = st.session_state.scan_results
    status = st.session_state.scan_status
    date_hd = st.session_state.scan_date

    if results is None:
        st.info("「今すぐスキャン」を押すと、締切間際のレースを検索します。")
    elif status == "no_timing":
        st.warning("現在、締切15分以内（前後）のレースが見つかりませんでした。開催時間中に再度お試しください。")
    else:
        hot = [r for r in results if r["score"] >= threshold]
        st.subheader(f"検出結果: {len(results)}件中 {len(hot)}件がしきい値以上")

        state = load_state(date_hd)

        for race in sorted(results, key=lambda r: r["score"], reverse=True):
            key = race_key(date_hd, race)
            already = is_notified(state, key)
            is_hot = race["score"] >= threshold

            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 3, 2])
                with c1:
                    st.markdown(f"**{race['venue']} {race['race_no']}R**（締切 {race['deadline']}）")
                    st.markdown(f"判定: **{race['status']}**（score {race['score']}）")
                with c2:
                    st.caption(f"理由: {race['reasons']}")
                    st.caption(f"1号艇展示タイム:{race['b1_ex']} / 最速展示タイム:{race['best_ex']}")
                with c3:
                    if not is_hot:
                        st.caption("しきい値未満")
                    elif already:
                        st.caption("✅ 通知済み")
                    elif st.button("📩 LINEに送信", key=f"send_{key}"):
                        try:
                            send_line_message(build_rough_race_message(race))
                            mark_notified(state, key)
                            save_state(state)
                            st.success("送信しました")
                            st.rerun()
                        except LineNotifyError as e:
                            st.error(f"送信失敗: {e}")


# ---------------------------------------------------------------------------
# タブ2: 事前予想（出走表データによる終日ランキング）
# ---------------------------------------------------------------------------
with tab_preview:
    st.caption(
        "展示タイムを待たず、出走表の全国勝率・モーター成績・級別・フライング歴から、"
        "今日開催される全レースを「荒れそうな順」にランキングします。"
        "直前スキャンとは情報源もスコア基準も別物なので、単純比較はできません。"
    )
    st.warning("全会場・全レースの出走表を巡回するため、実行に数分かかることがあります。", icon="⏳")

    if "preview_results" not in st.session_state:
        st.session_state.preview_results = None
        st.session_state.preview_status = None

    if st.button("🌅 本日の事前予想を実行", type="primary", key="preview_scan_btn"):
        with st.spinner("全会場・全レースの出走表を巡回中...（数分かかります）"):
            p_results, p_date_hd, p_status = asyncio.run(scan_all_races_today(target_date or None))
            st.session_state.preview_results = p_results
            st.session_state.preview_status = p_status

    p_results = st.session_state.preview_results
    p_status = st.session_state.preview_status

    if p_results is None:
        st.info("「本日の事前予想を実行」を押すと、今日の全レースをランキングします。")
    elif p_status == "no_race":
        st.warning("本日の開催情報が取得できませんでした。")
    else:
        top_n = st.slider("表示件数", min_value=5, max_value=len(p_results) or 5, value=min(20, len(p_results) or 5), key="preview_topn")
        st.subheader(f"事前予想ランキング（全{len(p_results)}レース中、上位{top_n}件）")

        if st.button("📩 表示中の上位レースをLINEに送る", key="preview_send_btn"):
            try:
                send_line_message(build_daily_preview_message(p_results[:top_n], target_date or TODAY_JST))
                st.success("送信しました")
            except LineNotifyError as e:
                st.error(f"送信失敗: {e}")

        for race in p_results[:top_n]:
            with st.container(border=True):
                st.markdown(f"**{race['venue']} {race['race_no']}R** — 判定: **{race['status']}**（score {race['score']}）")
                st.caption(f"理由: {race['reasons']}")
                st.caption(
                    f"1号艇級別:{race['b1_class']} / 1号艇全国勝率:{race['b1_win']} / "
                    f"1号艇今節平均着順:{race['b1_avg_rank']}"
                )


# ---------------------------------------------------------------------------
# タブ3: 本日の検出履歴（GitHub Actionsが自動蓄積したもの）
# ---------------------------------------------------------------------------
with tab_history:
    st.caption(
        "GitHub Actionsが自動スキャンで検出した、展示タイム公表済みのレースを"
        "その日の分だけ蓄積した一覧です（このダッシュボードを開いていなくても記録されます）。"
    )
    summary = load_daily_summary(target_date or TODAY_JST)
    races = daily_races_sorted(summary)

    if not races:
        st.info(
            "まだ本日分の記録がありません。GitHub Actionsが稼働してレースを検出すると、"
            "ここに自動で蓄積されていきます。"
        )
    else:
        st.subheader(f"本日の検出履歴: {len(races)}レース")
        for race in races:
            with st.container(border=True):
                st.markdown(f"**{race['venue']} {race['race_no']}R**（締切 {race['deadline']}） — **{race['status']}**（score {race['score']}）")
                st.caption(f"理由: {race['reasons']}")
                st.caption(f"1号艇展示タイム:{race['b1_ex']} / 最速展示タイム:{race['best_ex']}")


st.divider()
st.caption(
    "このダッシュボードは検出ロジックの確認・手動送信用です。定期的な自動監視とLINE通知は "
    "GitHub Actions（.github/workflows/rough_race_notify.yml）が独立して行います。"
)
