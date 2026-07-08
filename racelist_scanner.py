"""
racelist_scanner.py

「事前予想モード」: 各レースの締切15分前を待たず、出走表（racelist）ページの
選手データ（全国勝率・モーター成績・級別・フライング歴）から、
その日の全レースを「荒れそうな順」にランキングする。

boatrace.jpの出走表ページの実HTML構造を直接確認して実装（2026年7月時点）:
- 枠番セルは全角数字（１２３...）で入っているため、NFKC正規化して半角化してから判定する
- 1艇のデータブロックは10個の<td>を持つ「本体行」1行 + 今節成績グリッド用の
  多数のサブ行（セル数が少ない）で構成される。本体行はセル数(>=8)で見分ける
- 本体行の列順序: 枠番, 写真, 選手情報(登録番号/級別/氏名/支部/年齢体重),
  F数L数平均ST, 全国(勝率/2連率/3連率), 当地(勝率/2連率/3連率),
  モーター(No/2連率/3連率), ボート(No/2連率/3連率), ...(今節成績)

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


def parse_racelist(html):
    """出走表ページから各艇の事前データを抽出する。戻り値は6要素のlist(dict)。"""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")

    boats_by_num = {}
    for table in soup.select("table"):
        for row in table.select("tbody tr"):
            cells = row.select("td")
            if len(cells) < 8:
                continue  # 今節成績などのサブ行はセル数が少ないので除外

            first_text = _half(cells[0].get_text(strip=True))
            if first_text not in ("1", "2", "3", "4", "5", "6"):
                continue
            boat_num = int(first_text)

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

            boats_by_num[boat_num] = {
                "class": racer_class,
                "f_count": f_count,
                "national_win": national_win,
                "motor_2rate": motor_2rate,
            }

    if not boats_by_num:
        return None
    return [boats_by_num.get(i) for i in range(1, 7)]


def calculate_pre_race_score(boats, venue_name, rno, deadline):
    """
    全国勝率・モーター2連率で1号艇が頭一つ抜けているかどうかと、
    1号艇の級別・フライング歴から「事前の荒れそうな度合い」をスコア化する。
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

    score = round(score)
    status = "堅そう" if score < 20 else "荒れ気味注意" if score < 45 else "波乱注意🔥"

    return {
        "venue": venue_name, "race_no": rno, "deadline": deadline,
        "score": score, "status": status,
        "reasons": " / ".join(reasons) if reasons else "1号艇が優位",
        "b1_class": b1_class or "-",
        "b1_win": b1.get("national_win", "-"),
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
