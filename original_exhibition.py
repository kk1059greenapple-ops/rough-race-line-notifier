"""
original_exhibition.py

「オリジナル展示」（一周タイム・まわり足タイム・直線タイム）と、風速・風向・
波高・安定板使用の有無を取得するモジュール。

boatrace.jp公式サイトの直前情報ページには「展示タイム」しか掲載されておらず、
一周・まわり足・直線タイム（オリジナル展示）は各競艇場が独自に計測し、
boaters-boatrace.com のような集約サイトでのみ確認できる
（公式発表: https://www.boatrace.jp/owpc/pc/site/news/2025/07/44414/ 参照）。

このモジュールは、元の予想アプリ（boat_race_analysis/app.py）の
_headless_boaters_text_extraction() / scrape_full_boaters_workflow() の
「2-B. オリジナル展示」抽出ロジックを、直前情報ページのみに絞って移植したもの。
このデータ源だけがPlaywright（ヘッドレスブラウザ）を必要とする
（boatrace.jp公式のスキャンはaiohttpのみで完結する）。

江戸川・多摩川・津の3場はオリジナル展示非公表のため、展示タイムのみ取得する。
"""

import re

from playwright.async_api import async_playwright

# 日本語会場名 → boaters-boatrace.com のローマ字会場コード
VENUE_ROMAJI = {
    "桐生": "kiryu", "戸田": "toda", "江戸川": "edogawa", "平和島": "heiwajima", "多摩川": "tamagawa",
    "浜名湖": "hamanako", "蒲郡": "gamagori", "常滑": "tokoname", "津": "tsu", "三国": "mikuni",
    "びわこ": "biwako", "住之江": "suminoe", "尼崎": "amagasaki", "鳴門": "naruto", "丸亀": "marugame",
    "児島": "kojima", "宮島": "miyajima", "徳山": "tokuyama", "下関": "shimonoseki", "若松": "wakamatsu",
    "芦屋": "ashiya", "福岡": "fukuoka", "唐津": "karatsu", "大村": "omura",
}

# 長い名称から先に判定しないと「北」が「北北東」等に誤マッチするため順序に注意
WIND_DIR_CANDIDATES = [
    "北北東", "東北東", "東南東", "南南東", "南南西", "西南西", "西北西", "北北西",
    "北東", "南東", "南西", "北西", "追い風", "向かい風", "左横風", "右横風",
    "北", "東", "南", "西",
]


async def _fetch_texts(browser, base_url, semaphore):
    async with semaphore:
        context = await browser.new_context()
        page = await context.new_page()
        texts = {}
        try:
            url = f"{base_url}/last-minute"
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1800)
            texts["直前情報"] = await page.evaluate("() => document.body.innerText")
            try:
                await page.get_by_text("オリジナル展示", exact=True).click(timeout=3000)
                await page.wait_for_timeout(1200)
                texts["オリジナル展示"] = await page.evaluate("() => document.body.innerText")
            except Exception:
                pass
        except Exception:
            pass
        finally:
            await context.close()
        return texts


def _parse_env(text):
    env = {"wind_spd": 0.0, "wind_dir": None, "wave": None, "anteiban": False}
    ws = re.search(r"風速\s*([\d.]+)[\s\n]*m", text)
    if ws:
        env["wind_spd"] = float(ws.group(1))
    wv = re.search(r"波高\s*([\d.]+)[\s\n]*cm", text)
    if wv:
        env["wave"] = float(wv.group(1))
    if "安定板" in text:
        env["anteiban"] = True
    for d in WIND_DIR_CANDIDATES:
        if d in text[:1500]:
            env["wind_dir"] = d
            break
    return env


def _parse_original_exhibition_boats(text):
    """『オリジナル展示』タブのテキストから一周/まわり足/直線/展示タイムを抽出する。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    boats = [{} for _ in range(6)]
    for idx in range(6):
        b_idx = str(idx + 1)
        for i, line in enumerate(lines):
            if line == b_idx and i + 6 < len(lines) and lines[i + 2] in ("A1", "A2", "B1", "B2"):
                for j in range(i + 1, min(i + 15, len(lines))):
                    val = lines[j]
                    if re.match(r"^\d{1,2}[.·]\d{2}$", val) or val == "-":
                        def f_val(v):
                            return None if v == "-" else float(v)

                        boats[idx]["lap_time"] = f_val(val)
                        if j + 3 < len(lines):
                            boats[idx]["turn_time"] = f_val(lines[j + 1])
                            boats[idx]["straight_time"] = f_val(lines[j + 2])
                            boats[idx]["ex_time"] = f_val(lines[j + 3])
                        break
                break
    return boats


def _parse_ex_time_only(text):
    """オリジナル展示非公表会場（江戸川・多摩川・津）用: 展示タイムのみ拾う。"""
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    boats = [{} for _ in range(6)]
    for idx in range(6):
        b_idx = str(idx + 1)
        for i, line in enumerate(lines):
            if line == b_idx and i + 15 < len(lines):
                for j in range(i + 1, i + 15):
                    if re.match(r"^\d\.\d{2}$", lines[j]):
                        boats[idx]["ex_time"] = float(lines[j])
                        break
                break
    return boats


async def fetch_original_exhibition(browser, venue_name, date_hd, rno, semaphore):
    """
    venue_name: 日本語会場名（例: "三国"）
    date_hd: "YYYYMMDD"
    rno: レース番号(int)
    戻り値: (boats[6]またはNone, env dictまたはNone)
    """
    venue_cd = VENUE_ROMAJI.get(venue_name)
    if not venue_cd or len(date_hd) != 8:
        return None, None

    date_str = f"{date_hd[0:4]}-{date_hd[4:6]}-{date_hd[6:8]}"
    base_url = f"https://boaters-boatrace.com/race/{venue_cd}/{date_str}/{rno}R"

    texts = await _fetch_texts(browser, base_url, semaphore)
    if not texts:
        return None, None

    env = {"wind_spd": 0.0, "wind_dir": "無風", "wave": None, "anteiban": False}
    for key in ("直前情報", "オリジナル展示"):
        if key in texts:
            e = _parse_env(texts[key])
            if e["wind_spd"]:
                env["wind_spd"] = e["wind_spd"]
            if e["wave"] is not None:
                env["wave"] = e["wave"]
            if e["anteiban"]:
                env["anteiban"] = True
            if e["wind_dir"]:
                env["wind_dir"] = e["wind_dir"]

    boats = None
    if "オリジナル展示" in texts:
        boats = _parse_original_exhibition_boats(texts["オリジナル展示"])
    elif "直前情報" in texts:
        boats = _parse_ex_time_only(texts["直前情報"])

    return boats, env


async def launch_browser(playwright):
    return await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
    )
