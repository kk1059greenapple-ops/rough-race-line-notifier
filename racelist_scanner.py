"""
racelist_scanner.py

「事前予想モード」: 各レースの締切15分前を待たず、出走表（racelist）ページの
選手データ（全国勝率・モーター成績・級別・フライング歴・今節成績）から、
その日の全レースを「荒れそうな順」にランキングする。

boatrace.jpの出走表ページの実HTML構造を直接確認して実装（2026年7月時点）:
- 枠番セルは全角数字（１２３...）で入っているため、NFKC正規化して半角化してから判定する
- 1艇のデータブロックは4つの<tr>で構成される
  （本体行 + 進入コース行 + STタイミング行 + 今節成績＝着順行）。
  本体行だけが選手プロフィールへのリンク(racersearch/profile)を持つので、
  それを目印にブロックの開始行を判定する（セル数では判定しない。
  今節成績の行も日数分の列を持つため本体行と同程度にセル数が多く、
  セル数だけでは見分けられないことが判明したため）
- 本体行の列順序: 枠番, 写真, 選手情報(登録番号/級別/氏名/支部/年齢体重),
  F数L数平均ST, 全国(勝率/2連率/3連率), 当地(勝率/2連率/3連率),
  モーター(No/2連率/3連率), ボート(No/2連率/3連率), ...(今節成績グリッド)
- 今節成績＝着順の行は、各日の着順がraceresultページへのリンクとして
  埋め込まれているため、href に "raceresult" を含む<a>タグを目印に抽出する

直前情報(rough_race_scanner.py)とは別の情報源・別のスコア基準なので、
「事前予想スコア」は直前情報の「荒れ度スコア」と単純比較はできない点に注意。
"""

import asyncio
import re
import unicodedata

from bs4 import BeautifulSoup

from rough_race_scanner import REVERSE_VENUE_NAMES, HEADERS, JST, fetch_html

CLASS_BONUS = {"A1": 0, "A2": 8, "B1": 15, "B2": 22}


def _half(text):
    return unicodedata.normalize("NFKC", text)


def _parse_boat_block(main_row, sub_rows):
    """1艇分のブロック(本体行+進入/ST/着順のサブ行)から必要な情報を抽出する。"""
    cells = main_row.select("td")
    if len(cells) < 8:
        return None

    info_text = cells[2].get_text(" ", strip=True)
    class_m = re.search(r"\b([AB][12])\b", info_text)
    racer_class = class_m.group(1) if class_m else None

    fl_text = cells[3].get_text(" ", strip=True)
    f_m = re.search(r"F(\d+)", fl_text)
    f_count = int(f_m.group(1)) if f_m else 0

    national_vals = re.findall(r"(\d{1,2}\.\d{2})", cells[4].get_text(" ", strip=True))
    national_win = float(national_vals[0]) if national_vals else None

    motor_vals = re.findall(r"(\d{1,2}\.\d{2})", cells[6].get_text(" ", strip=True))
    motor_2rate = float(motor_vals[0]) if motor_vals else None

    # 今節成績（着順）行を、raceresultへのリンクを持つ行として特定する
    recent_ranks = []
    for row in sub_rows:
        links = row.select("a[href*='raceresult']")
        if not links:
            continue
        for a in links:
            t = _half(a.get_text(strip=True))
            if t in ("1", "2", "3", "4", "5", "6"):
                recent_ranks.append(int(t))
        break  # 着順行は1ブロックにつき1行のはず

    return {
        "class": racer_class,
        "f_count": f_count,
        "national_win": national_win,
        "motor_2rate": motor_2rate,
        "recent_ranks": recent_ranks,
    }


def parse_racelist(html):
    """出走表ページから各艇の事前データを抽出する。戻り値は6要素のlist(dict)。"""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    boats_by_num = {}
    for table in soup.select("table"):
        rows = table.select("tbody tr")
        current_boat = None
        current_main_row = None
        current_sub_rows = []

        def flush():
            if current_boat is not None and current_main_row is not None:
                parsed = _parse_boat_block(current_main_row, current_sub_rows)
                if parsed is not None:
                    boats_by_num[current_boat] = parsed

        for row in rows:
            cells = row.select("td")
            if not cells:
                continue
            is_main_row = row.select_one("a[href*='racersearch/profile']") is not None
            first_text = _half(cells[0].get_text(strip=True))

            if is_main_row and first_text in ("1", "2", "3", "4", "5", "6"):
                flush()
                current_boat = int(first_text)
                current_main_row = row
                current_sub_rows = []
            elif current_boat is not None:
                current_sub_rows.append(row)
        flush()

    if not boats_by_num:
        return None
    return [boats_by_num.get(i) for i in range(1, 7)]


def calculate_pre_race_score(boats, venue_name, rno, deadline):
    """
    全国勝率・モーター2連率で1号艇が頭一つ抜けているかどうか、
    1号艇の級別・フライング歴、そして今節（当該開催）でのここ数走の着順（過去の戦績）
    から「事前の荒れそうな度合い」をスコア化する。
    展示タイムのような直前の実測値ではなく、あくまで公表済みの成績データに基づく目安。
    """
    if not boats or boats[0] is None:
        return None

    b1 = boats[0]
    score = 0.0
    reasons = []

    win_rates = [(i + 1, b.get("national_win")) for i, b in enumerate(boats) if b and b.get("national_win") is not None]
    if win_rates:
        best_boat, best_win = max(win_rates, key=lambda x: x[1])
        b1_win = b1.get("national_win")
        if b1_win is not None and best_boat != 1 and best_win > b1_win:
            score += (best_win - b1_win) * 8
            reasons.append(f"全国勝率トップ:{best_boat}号艇({best_win})")

    motor_rates = [(i + 1, b.get("motor_2rate")) for i, b in enumerate(boats) if b and b.get("motor_2rate") is not None]
    if motor_rates:
        best_m_boat, best_m = max(motor_rates, key=lambda x: x[1])
        b1_m = b1.get("motor_2rate")
        if b1_m is not None and best_m_boat != 1 and best_m > b1_m:
            score += (best_m - b1_m) * 0.6
            reasons.append(f"モーター2連率トップ:{best_m_boat}号艇({best_m}%)")

    b1_class = b1.get("class")
    if b1_class and b1_class != "A1":
        score += CLASS_BONUS.get(b1_class, 10)
        reasons.append(f"1号艇級別:{b1_class}")

    if b1.get("f_count", 0) > 0:
        score += 5
        reasons.append(f"1号艇F{b1['f_count']}前歴あり")

    # 今節（当該開催）ここ数走の着順（過去の戦績）: 1号艇の平均着順が悪いほど加点
    b1_recent = b1.get("recent_ranks") or []
    b1_avg_rank = None
    if b1_recent:
        b1_avg_rank = round(sum(b1_recent) / len(b1_recent), 1)
        if b1_avg_rank > 3.0:
            score += (b1_avg_rank - 3.0) * 10
            reasons.append(f"1号艇今節平均着順:{b1_avg_rank}位（{len(b1_recent)}走）")

    # 他艇に今節絶好調（平均着順が良い）の艇がいれば、その艇の台頭で加点
    other_avgs = []
    for i, b in enumerate(boats):
        if i == 0 or not b:
            continue
        ranks = b.get("recent_ranks") or []
        if ranks:
            other_avgs.append((i + 1, round(sum(ranks) / len(ranks), 1)))
    if other_avgs:
        hot_boat, hot_avg = min(other_avgs, key=lambda x: x[1])
        if hot_avg <= 2.0:
            score += (2.5 - hot_avg) * 8
            reasons.append(f"今節絶好調:{hot_boat}号艇（平均{hot_avg}位）")

    score = round(score)
    status = "堅そう" if score < 20 else "荒れ気味注意" if score < 45 else "波乱注意🔥"

    return {
        "venue": venue_name, "race_no": rno, "deadline": deadline,
        "score": score, "status": status,
        "reasons": " / ".join(reasons) if reasons else "1号艇が優位",
        "b1_class": b1_class or "-",
        "b1_win": b1.get("national_win", "-"),
        "b1_avg_rank": b1_avg_rank if b1_avg_rank is not None else "-",
    }


async def _get_active_venues(session, semaphore, date_hd):
    url_index = f"https://www.boatrace.jp/owpc/pc/race/index?hd={date_hd}"
    html_index = await fetch_html(session, url_index, semaphore)
    if not html_index:
        return []
    active_venues = []
    for name, jcd in REVERSE_VENUE_NAMES.items():
        if name in html_index:
            active_venues.append({"jcd": jcd, "hd": date_hd, "name": name})
    return active_venues


async def _get_race_numbers(session, semaphore, venue):
    """指定会場の本日開催レース番号一覧(締切時刻付き)を取得する。"""
    url = f"https://www.boatrace.jp/owpc/pc/race/raceindex?jcd={venue['jcd']}&hd={venue['hd']}"
    html = await fetch_html(session, url, semaphore)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    races = []
    seen = set()
    for a in soup.select("a[href*='rno=']"):
        m = re.search(r"rno=(\d+)", a.get("href", ""))
        if not m:
            continue
        rno = int(m.group(1))
        if rno in seen or not (1 <= rno <= 12):
            continue
        seen.add(rno)
        races.append(rno)
    return sorted(races)


async def scan_all_races_today(target_date=None):
    """
    本日（またはtarget_date）開催の全会場・全レースの出走表を巡回し、
    事前予想スコアでランキングした結果を返す。

    戻り値: (results, date_hd, status)
      status: "ok" | "no_race"（開催情報が取れない）
    """
    import aiohttp
    from datetime import datetime

    now = datetime.now(JST)
    date_hd = target_date or now.strftime("%Y%m%d")

    semaphore = asyncio.Semaphore(15)
    async with aiohttp.ClientSession() as session:
        venues = await _get_active_venues(session, semaphore, date_hd)
        if not venues:
            return [], date_hd, "no_race"

        race_number_lists = await asyncio.gather(
            *[_get_race_numbers(session, semaphore, v) for v in venues]
        )

        targets = []
        for venue, rnos in zip(venues, race_number_lists):
            for rno in rnos:
                url = (
                    f"https://www.boatrace.jp/owpc/pc/race/racelist"
                    f"?rno={rno}&jcd={venue['jcd']}&hd={venue['hd']}"
                )
                targets.append((url, venue["name"], rno))

        if not targets:
            return [], date_hd, "no_race"

        htmls = await asyncio.gather(*[fetch_html(session, u[0], semaphore) for u in targets])

        results = []
        for (url, v_name, rno), html in zip(targets, htmls):
            boats = parse_racelist(html)
            info = calculate_pre_race_score(boats, v_name, rno, deadline="-")
            if info:
                results.append(info)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results, date_hd, "ok"
