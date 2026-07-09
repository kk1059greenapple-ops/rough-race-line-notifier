"""
rough_race_scanner.py

全24会場を横断して「締切間際（-3分〜+15分）」のレースを検出し、
公式サイトの展示タイムに加えて、一周・まわり足・直線タイム（オリジナル展示、
original_exhibition.py経由）、風速・風向・波高・安定板、出走表の選手戦績
（racelist_scanner.py経由: 級別・全国勝率・モーター2連率・フライング歴）を
総合して荒れ度スコアを算出するモジュール。

既存の app.py 内蔵の rough_race_finder.py（Streamlit UIから手動実行される版）や、
app.py 本体の calculate_dynamic_roughness() / calculate_oracle() の考え方
（会場別の荒れやすさベース値 + 各種補正の加減算）を踏襲しつつ、
GitHub Actions上で自動実行できる形に移植したもの。

このモジュールは以下の点を元のapp.pyから変更している:
- boatrace.jp公式サイトのスキャン自体はaiohttp + BeautifulSoupのみ（Playwright不要）
- オリジナル展示（一周/まわり足/直線タイム）・風速風向・波高・安定板の取得のみ、
  boaters-boatrace.com を対象にPlaywrightを使用する（公式サイトには存在しないため）
- 選手の戦績（級別・全国勝率・モーター成績・フライング歴）はboaters-boatrace.comの
  複雑なテキスト解析ではなく、公式サイトの出走表を解析する racelist_scanner.py の
  実装を再利用する（より確実で、事前予想モードと同じデータ源のため一貫性がある）
- オッズとの乖離判定（AI予想 vs 市場人気のズレ）は、オッズスクレイピングと
  選手データベースの突合が必要な別系統の重い処理のため対象外としている
- サーバー実行環境が UTC でも正しく動くよう、時刻計算をすべて JST 明示に修正
  （元のコードは datetime.now() のみでサーバーがUTCだと9時間ズレるバグがあった）
- Streamlit（st.*）依存を完全に排除し、GitHub Actions等の非対話環境で単独実行可能

このモジュールは app.py・rough_race_finder.py を一切変更せず、
新規フォルダ rough_race_notifier_app/ 配下の独立システムとして動作する。
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from original_exhibition import fetch_original_exhibition, launch_browser

JST = timezone(timedelta(hours=9))

# 過去1年間の統計ベースの会場別「荒れる度」ベース値（万舟率等、app.pyのVENUE_ROUGHNESS_MAPと同一）
VENUE_ROUGHNESS_MAP = {
    "桐生": 16.2, "戸田": 19.8, "江戸川": 18.5, "平和島": 19.2, "多摩川": 16.5,
    "浜名湖": 15.8, "蒲郡": 14.2, "常滑": 15.5, "津": 16.8, "三国": 16.3,
    "びわこ": 17.5, "住之江": 13.8, "尼崎": 14.5, "鳴門": 18.8, "丸亀": 15.2,
    "児島": 15.1, "宮島": 16.7, "徳山": 12.2, "下関": 13.5, "若松": 14.1,
    "芦屋": 13.2, "福岡": 17.8, "唐津": 14.5, "大村": 11.2,
}

# 開催場コードマッピング
VENUE_NAMES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川",
    "06": "浜名湖", "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国",
    "11": "びわこ", "12": "住之江", "13": "尼崎", "14": "鳴門", "15": "丸亀",
    "16": "児島", "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}
REVERSE_VENUE_NAMES = {v: k for k, v in VENUE_NAMES.items()}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


async def fetch_html(session, url, semaphore, retries=2):
    async with semaphore:
        for i in range(retries + 1):
            try:
                async with session.get(url, headers=HEADERS, timeout=30) as response:
                    if response.status == 200:
                        return await response.text()
            except Exception:
                pass
            if i < retries:
                await asyncio.sleep(1)
        return None


def parse_exhibition_data(html):
    """
    「直前情報」ページの出走表テーブルから、各艇の展示タイムを取り出す。

    実際のページのテーブル構造（2026年7月時点でboatrace.jpから直接確認済み）:
    1艇あたり4つの<tr>で構成される（本体行 + 進入行 + ST行 + 着順行）。
    枠番(1〜6)・体重・展示タイム・チルト・プロペラ・部品交換は「本体行」のみに
    実データが乗り、以降の3行は前走成績（進入/ST/着順）だけを持つ。
    「一周タイム」に相当する項目はこのページには存在しない。

    そのため、各艇の本体行を「先頭セルが1〜6の数字」で特定し、
    その行の中から展示タイムらしき小数（6.0〜9.0秒程度）を1つだけ拾う。
    体重（例: 52.4kg）は小数点以下1桁なので6.0〜9.0秒の抽出パターンとは衝突しない。
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    boats_by_num = {}
    for table in soup.select("table"):
        rows = table.select("tbody tr")
        for row in rows:
            cells = row.select("td")
            if not cells:
                continue
            first_text = cells[0].get_text(strip=True)
            if first_text not in ("1", "2", "3", "4", "5", "6"):
                continue

            boat_num = int(first_text)
            row_text = row.get_text(" ", strip=True)
            vals = re.findall(r"(\d{1,2}\.\d{2})", row_text)
            ex_time = None
            for v_str in vals:
                v = float(v_str)
                if 6.0 <= v <= 9.0:
                    ex_time = v
                    break

            # 同じ枠番が複数テーブルにまたがって出現した場合は、値が取れた方を優先する
            if boat_num not in boats_by_num or ex_time is not None:
                boats_by_num[boat_num] = {"ex_time": ex_time} if ex_time is not None else boats_by_num.get(boat_num, {})

    if not boats_by_num:
        return None

    boats = [boats_by_num.get(i, {}) for i in range(1, 7)]
    return boats


def _merge_boats(boats_official, boats_orig):
    """公式サイトの展示タイム(boats_official)とオリジナル展示(boats_orig)をマージする。
    一周/まわり足/直線タイムはオリジナル展示にしかないため、あれば必ず採用。
    展示タイムはオリジナル展示側の値を優先し、無ければ公式サイト側で補う。
    """
    merged = []
    for i in range(6):
        m = {}
        off = (boats_official or [{}] * 6)[i] if boats_official else {}
        orig = (boats_orig or [{}] * 6)[i] if boats_orig else {}
        m["ex_time"] = orig.get("ex_time") if orig.get("ex_time") is not None else off.get("ex_time")
        m["lap_time"] = orig.get("lap_time")
        m["turn_time"] = orig.get("turn_time")
        m["straight_time"] = orig.get("straight_time")
        merged.append(m)
    return merged


def _rank_best_boat(boats, field):
    """指定フィールドで最速(最小値)の艇番号と値を返す。タイムは小さいほど良い前提。"""
    vals = [(i + 1, b.get(field)) for i, b in enumerate(boats) if b.get(field) is not None]
    if not vals:
        return None, None
    return min(vals, key=lambda x: x[1])


def _rank_of_boat1(boats, field):
    """全艇中での1号艇の順位（1=最速）を返す。値が無ければNone。"""
    vals = [(i + 1, b.get(field)) for i, b in enumerate(boats) if b.get(field) is not None]
    if not vals or boats[0].get(field) is None:
        return None
    vals.sort(key=lambda x: x[1])
    for rank, (boat_num, _) in enumerate(vals, start=1):
        if boat_num == 1:
            return rank
    return None


def calculate_full_roughness_score(boats_official, boats_orig, boats_rl, env, venue_name, rno, deadline):
    """
    公式サイトの展示タイム、一周・まわり足・直線タイム（オリジナル展示）、
    風速・風向・波高・安定板、出走表の選手戦績（級別・全国勝率・モーター2連率・
    フライング歴）を総合して荒れ度スコアを算出する。

    元の予想アプリ（app.py）の calculate_dynamic_roughness() が採用している
    「会場別の荒れやすさベース値 + 各種シグナルの加減算」という設計を踏襲。
    オッズとの乖離判定（AI予想 vs 市場人気）はオッズスクレイピング等が必要な
    別系統の処理のため対象外。
    """
    boats = _merge_boats(boats_official, boats_orig)
    has_any_time = any(b.get("ex_time") is not None for b in boats)
    has_rl = bool(boats_rl) and boats_rl[0] is not None

    if not has_any_time and not has_rl:
        return {
            "venue": venue_name, "race_no": rno, "deadline": deadline,
            "score": 0, "status": "データ収集中", "reasons": "展示タイム未公表",
            "b1_ex": "-", "best_ex": "-", "b1_lap": "-", "best_lap": "-",
        }

    reasons = []
    score = VENUE_ROUGHNESS_MAP.get(venue_name, 16.0)

    b1 = boats[0]
    b1_ex, b1_lap = b1.get("ex_time"), b1.get("lap_time")
    best_ex_boat, best_ex_val = _rank_best_boat(boats, "ex_time")
    best_lap_boat, best_lap_val = _rank_best_boat(boats, "lap_time")

    # 展示タイム: 1号艇が最速でなければ、差分に応じて加点
    if b1_ex is not None and best_ex_val is not None and best_ex_boat != 1:
        diff_ex = round(b1_ex - best_ex_val, 2)
        if diff_ex > 0:
            score += diff_ex * 20
            reasons.append(f"展示最速:{best_ex_boat}号艇（1号艇比+{diff_ex}秒）")

    # 一周タイム: 展示タイムより重み付けを大きくする（元アプリのrough_race_finder.pyと同じ考え方）
    if b1_lap is not None and best_lap_val is not None and best_lap_boat != 1:
        diff_lap = round(b1_lap - best_lap_val, 2)
        if diff_lap > 0:
            score += diff_lap * 30
            reasons.append(f"一周最速:{best_lap_boat}号艇（1号艇比+{diff_lap}秒）")

    # 1号艇の展示/一周ランクが4位以下
    rank_ex = _rank_of_boat1(boats, "ex_time")
    rank_lap = _rank_of_boat1(boats, "lap_time")
    if (rank_ex and rank_ex >= 4) or (rank_lap and rank_lap >= 4):
        score += 12
        worst_rank = max(r for r in (rank_ex, rank_lap) if r)
        reasons.append(f"1号艇の展示/一周ランクが{worst_rank}位")

    # 外枠(3-6号艇)がいずれかの指標で一番時計
    outside_best = False
    for field in ("ex_time", "lap_time", "turn_time", "straight_time"):
        boat_num, _ = _rank_best_boat(boats, field)
        if boat_num and boat_num >= 3:
            outside_best = True
            break
    if outside_best:
        score += 15
        reasons.append("外枠(3-6号艇)がタイム系で一番時計")

    # 選手戦績（出走表: 級別・全国勝率・モーター2連率・フライング歴）
    if has_rl:
        b1_rl = boats_rl[0] or {}
        b1_class = b1_rl.get("class")
        if b1_class in ("B1", "B2"):
            score += 12
            reasons.append(f"1号艇級別:{b1_class}")

        # 全国勝率は0.00〜8.00程度の評価点スケール（％ではない。例: A1上位は6〜7台、
        # B2は3台前後が目安）。boatrace.jpの出走表「全国」列の1つ目の数値がこれに当たる。
        b1_win = b1_rl.get("national_win")
        if b1_win is not None and b1_win < 5.0:
            score += 10
            reasons.append(f"1号艇全国勝率:{b1_win}（平均以下）")

        win_rates = [(i + 1, b.get("national_win")) for i, b in enumerate(boats_rl) if b and b.get("national_win") is not None]
        if win_rates and b1_win is not None:
            outer_best_boat, outer_best_win = max(
                ((n, w) for n, w in win_rates if n != 1), key=lambda x: x[1], default=(None, None)
            )
            if outer_best_boat and outer_best_win > b1_win + 1.0:
                score += 12
                reasons.append(f"{outer_best_boat}号艇の全国勝率が1号艇より高い（{outer_best_win} vs {b1_win}）")

        if b1_rl.get("f_count", 0) > 0:
            score += 5
            reasons.append(f"1号艇F{b1_rl['f_count']}前歴あり")

        motor_rates = [(i + 1, b.get("motor_2rate")) for i, b in enumerate(boats_rl) if b and b.get("motor_2rate") is not None]
        b1_motor = b1_rl.get("motor_2rate")
        if b1_motor is not None and b1_motor < 30.0 and motor_rates:
            outer_motor_hot = [n for n, m in motor_rates if n != 1 and m >= 40.0]
            if outer_motor_hot:
                score += 10
                reasons.append(f"モーター好調な外枠あり: {'/'.join(str(n)+'号艇' for n in outer_motor_hot)}")

    # 風・波・安定板
    if env:
        wind_spd = env.get("wind_spd") or 0.0
        wave = env.get("wave")
        if wind_spd >= 5.0:
            score += 10
            reasons.append(f"強風 {wind_spd}m")
        if wave is not None and wave >= 5.0:
            score += 10
            reasons.append(f"波高 {wave}cm")
        if env.get("anteiban"):
            score -= 15
            reasons.append("安定板使用")

    score = round(max(5.0, min(score, 98.5)))
    status_label = "イン堅調" if score < 20 else "波乱含み" if score < 50 else "大波乱気配🔥"

    return {
        "venue": venue_name, "race_no": rno, "deadline": deadline,
        "score": score, "status": status_label,
        "reasons": " / ".join(reasons) if reasons else "イン優勢",
        "b1_ex": b1_ex if b1_ex is not None else "-",
        "best_ex": f"{best_ex_boat}号({best_ex_val})" if best_ex_val is not None else "-",
        "b1_lap": b1_lap if b1_lap is not None else "-",
        "best_lap": f"{best_lap_boat}号({best_lap_val})" if best_lap_val is not None else "-",
    }


async def find_rough_races_today(target_date=None, window_before_min=15, window_after_min=3):
    """
    全会場を巡回し、締切が window_after_min 分前 〜 window_before_min 分後
    の範囲にあるレースの直前情報を取得してスコアリングする。

    target_date: "YYYYMMDD" 形式（JST）。省略時は現在のJST日付。
    戻り値: (results, date_hd, status)
      status: "ok" | "no_timing"（対象時間帯のレースなし） | "no_timing"（開催情報取得失敗）
    """
    now = datetime.now(JST)
    date_hd = target_date or now.strftime("%Y%m%d")

    url_index = "https://www.boatrace.jp/owpc/pc/race/index"
    if target_date:
        url_index += f"?hd={target_date}"

    semaphore = asyncio.Semaphore(15)
    async with aiohttp.ClientSession() as session:
        html_index = await fetch_html(session, url_index, semaphore)
        if not html_index:
            return [], date_hd, "no_timing"

        active_venues = []
        for name, jcd in REVERSE_VENUE_NAMES.items():
            if name in html_index:
                active_venues.append({"jcd": jcd, "hd": date_hd, "name": name})

        if not active_venues:
            return [], date_hd, "no_timing"

        index_urls = [
            f"https://www.boatrace.jp/owpc/pc/race/raceindex?jcd={v['jcd']}&hd={v['hd']}"
            for v in active_venues
        ]
        index_htmls = await asyncio.gather(*[fetch_html(session, u, semaphore) for u in index_urls])

        target_urls = []
        for v, html in zip(active_venues, index_htmls):
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for tr in soup.select("tr"):
                txt = tr.get_text()
                m_time = re.search(r"(\d{1,2}:\d{2})", txt)
                if not m_time:
                    continue
                try:
                    deadline_str = m_time.group(1)
                    h, m = map(int, deadline_str.split(":"))
                    dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                    if h < 4 and now.hour > 20:
                        dt += timedelta(days=1)
                    diff_min = (dt - now).total_seconds() / 60
                    if -window_after_min <= diff_min <= window_before_min:
                        r_match = re.search(r"(\d+)R", txt)
                        rno = int(r_match.group(1)) if r_match else 1
                        url_before = (
                            f"https://www.boatrace.jp/owpc/pc/race/beforeinfo"
                            f"?rno={rno}&jcd={v['jcd']}&hd={v['hd']}"
                        )
                        url_racelist = (
                            f"https://www.boatrace.jp/owpc/pc/race/racelist"
                            f"?rno={rno}&jcd={v['jcd']}&hd={v['hd']}"
                        )
                        target_urls.append((url_before, url_racelist, v["name"], rno, deadline_str))
                except Exception:
                    continue

        if not target_urls:
            return [], date_hd, "no_timing"

        # 遅延importで racelist_scanner <-> rough_race_scanner の循環importを回避
        from racelist_scanner import parse_racelist

        before_htmls = await asyncio.gather(
            *[fetch_html(session, t[0], semaphore) for t in target_urls]
        )
        racelist_htmls = await asyncio.gather(
            *[fetch_html(session, t[1], semaphore) for t in target_urls]
        )

        # オリジナル展示（一周/まわり足/直線タイム・風・波・安定板）はPlaywright必須。
        # 対象レースが取れなかった場合はスキップし、公式サイトの情報のみで判定する。
        orig_results = [(None, None)] * len(target_urls)
        try:
            async with async_playwright() as pw:
                browser = await launch_browser(pw)
                try:
                    pw_semaphore = asyncio.Semaphore(3)
                    orig_results = await asyncio.gather(*[
                        fetch_original_exhibition(browser, t[2], date_hd, t[3], pw_semaphore)
                        for t in target_urls
                    ])
                finally:
                    await browser.close()
        except Exception:
            pass

        results = []
        for (url_before, url_rl, v_name, rno, dl), before_html, rl_html, (boats_orig, env) in zip(
            target_urls, before_htmls, racelist_htmls, orig_results
        ):
            boats_official = parse_exhibition_data(before_html)
            boats_rl = parse_racelist(rl_html)
            info = calculate_full_roughness_score(boats_official, boats_orig, boats_rl, env, v_name, rno, dl)
            if info:
                results.append(info)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results, date_hd, "ok"
