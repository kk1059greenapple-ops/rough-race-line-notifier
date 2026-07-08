"""
rough_race_scanner.py

全24会場を横断して「締切間際（-3分〜+15分）」のレースを検出し、
直前展示情報（展示タイム／周回タイム）から荒れ度スコアを算出するモジュール。

既存の app.py 内蔵の rough_race_finder.py（Streamlit UIから手動実行される版）の
検出ロジックを土台にしているが、本モジュールは以下の点を変更した独立版:

- Playwright/ブラウザ操作には依存しない（aiohttp + BeautifulSoup のみ）
- サーバー実行環境が UTC でも正しく動くよう、時刻計算をすべて JST 明示に修正
  （元のコードは datetime.now() のみでサーバーがUTCだと9時間ズレるバグがあった）
- Streamlit（st.*）依存を完全に排除し、GitHub Actions等の非対話環境で単独実行可能

このモジュールは app.py・rough_race_finder.py を一切変更せず、
新規フォルダ line_notifier/ 配下の独立システムとして動作する。
"""

import asyncio
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))

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


def calculate_roughness_score(boats, venue_name, rno, deadline):
    """
    1号艇の展示タイムが他艇（特に最速艇）と比べてどれだけ見劣りするかでスコア化する。
    展示タイムのみが実際に取得できる指標のため（一周タイム等はboatrace.jpの
    直前情報ページには存在しない）、判定はこの1指標に基づく単純なものにしている。
    """
    if not boats:
        return None

    b1 = boats[0]
    b1_ex = b1.get("ex_time")
    score = 0
    reasons = []

    valid_ex = [(i + 1, b.get("ex_time")) for i, b in enumerate(boats) if b.get("ex_time")]
    if not valid_ex:
        return {
            "venue": venue_name, "race_no": rno, "deadline": deadline,
            "score": 0, "status": "データ収集中", "reasons": "展示タイム未公表",
            "b1_ex": "-", "best_ex": "-", "b1_lap": "-", "best_lap": "-",
        }

    best_ex_boat, best_ex_val = min(valid_ex, key=lambda x: x[1])
    if b1_ex is not None:
        diff_ex = round(b1_ex - best_ex_val, 2)
        if best_ex_boat != 1 and diff_ex > 0:
            # 展示タイム差0.1秒あたり20点。0.35秒差で70点(大波乱気配)に到達する目安。
            score = int(diff_ex * 200)
            reasons.append(f"展示最速:{best_ex_boat}号艇（1号艇比 +{diff_ex}秒）")
    elif best_ex_boat != 1:
        reasons.append(f"1号艇の展示タイム未公表（展示最速は{best_ex_boat}号艇）")

    status_label = "イン堅調" if score < 20 else "波乱含み" if score < 50 else "大波乱気配🔥"

    return {
        "venue": venue_name, "race_no": rno, "deadline": deadline,
        "score": score, "status": status_label,
        "reasons": " / ".join(reasons) if reasons else "イン優勢",
        "b1_ex": b1_ex if b1_ex is not None else "-",
        "best_ex": f"{best_ex_boat}号({best_ex_val})" if best_ex_val is not None else "-",
        "b1_lap": "-", "best_lap": "-",
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
                        target_urls.append((url_before, v["name"], rno, deadline_str))
                except Exception:
                    continue

        if not target_urls:
            return [], date_hd, "no_timing"

        before_htmls = await asyncio.gather(*[fetch_html(session, u[0], semaphore) for u in target_urls])
        results = []
        for (url, v_name, rno, dl), html in zip(target_urls, before_htmls):
            boats_data = parse_exhibition_data(html)
            info = calculate_roughness_score(boats_data, v_name, rno, dl)
            if info:
                results.append(info)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results, date_hd, "ok"
