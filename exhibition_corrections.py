"""
exhibition_corrections.py

一周・まわり足・直線・展示タイムの会場×コース別補正値マスタ。

コース1は旋回半径が小さい分、他艇と単純な実力差が無くても構造的に速いタイムが
出やすく（逆にコース6は旋回半径が大きい分、構造的に遅いタイムが出やすい）、
生タイムのまま艇間比較すると「内側の艇が実際より優秀に見え、外側の艇が実際より
見劣りする」方向にバイアスがかかる。この補正値を加算することで、コース位置による
物理的な有利・不利を打ち消し、純粋な機力（選手・モーターの調子）を比較できるようにする。

元の予想アプリ（boat_race_analysis/exhibition_time_modifiers.py）のデータ・計算式を
そのまま移植したもの。補正計算式: 補正後タイム = 生タイム + 補正値
（コース1は正の補正値を加算して「速く見えすぎている」分を打ち消し、
  コース6は負の補正値を加算して「遅く見えすぎている」分を打ち消す）
"""

VENUE_EX_MODIFIERS = {
    "桐生": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.25, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.15, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.05, "ex": -0.01},
        4: {"turn": -0.01, "straight": -0.02, "lap": -0.08, "ex": -0.02},
        5: {"turn": -0.02, "straight": -0.03, "lap": -0.12, "ex": -0.03},
        6: {"turn": -0.03, "straight": -0.03, "lap": -0.15, "ex": -0.04},
    },
    "戸田": {
        1: {"turn": 0.05, "straight": 0.02, "lap": 0.28, "ex": 0.03},
        2: {"turn": 0.03, "straight": 0.01, "lap": 0.18, "ex": 0.01},
        3: {"turn": 0.00, "straight": 0.00, "lap": -0.02, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.03, "lap": -0.12, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.04, "lap": -0.16, "ex": -0.04},
        6: {"turn": -0.04, "straight": -0.04, "lap": -0.20, "ex": -0.05},
    },
    "江戸川": {
        1: {"turn": 0.03, "straight": 0.01, "lap": 0.20, "ex": 0.02},
        2: {"turn": 0.01, "straight": 0.00, "lap": 0.10, "ex": 0.01},
        3: {"turn": 0.00, "straight": -0.01, "lap": -0.05, "ex": 0.00},
        4: {"turn": -0.01, "straight": -0.01, "lap": -0.08, "ex": -0.01},
        5: {"turn": -0.02, "straight": -0.02, "lap": -0.12, "ex": -0.02},
        6: {"turn": -0.03, "straight": -0.02, "lap": -0.15, "ex": -0.03},
    },
    "平和島": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.26, "ex": 0.03},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.14, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.06, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.10, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.14, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.03, "lap": -0.18, "ex": -0.04},
    },
    "多摩川": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.24, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.12, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.04, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.08, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.12, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.03, "lap": -0.16, "ex": -0.04},
    },
    "浜名湖": {
        1: {"turn": 0.05, "straight": 0.01, "lap": 0.25, "ex": 0.03},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.15, "ex": 0.01},
        3: {"turn": 0.00, "straight": -0.01, "lap": -0.05, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.10, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.15, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.03, "lap": -0.18, "ex": -0.04},
    },
    "蒲郡": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.22, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.12, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.05, "ex": -0.01},
        4: {"turn": -0.01, "straight": -0.02, "lap": -0.08, "ex": -0.02},
        5: {"turn": -0.02, "straight": -0.03, "lap": -0.12, "ex": -0.03},
        6: {"turn": -0.03, "straight": -0.03, "lap": -0.15, "ex": -0.04},
    },
    "常滑": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.23, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.13, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.05, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.09, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.13, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.03, "lap": -0.16, "ex": -0.04},
    },
    "津": {
        1: {"turn": 0.05, "straight": 0.02, "lap": 0.26, "ex": 0.03},
        2: {"turn": 0.03, "straight": 0.01, "lap": 0.15, "ex": 0.01},
        3: {"turn": 0.00, "straight": 0.00, "lap": -0.04, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.10, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.15, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.04, "lap": -0.18, "ex": -0.04},
    },
    "三国": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.25, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.14, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.05, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.02, "lap": -0.09, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.03, "lap": -0.14, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.03, "lap": -0.17, "ex": -0.04},
    },
    "びわこ": {
        1: {"turn": 0.05, "straight": 0.02, "lap": 0.28, "ex": 0.03},
        2: {"turn": 0.03, "straight": 0.01, "lap": 0.16, "ex": 0.01},
        3: {"turn": 0.00, "straight": 0.00, "lap": -0.03, "ex": -0.01},
        4: {"turn": -0.02, "straight": -0.03, "lap": -0.12, "ex": -0.02},
        5: {"turn": -0.03, "straight": -0.04, "lap": -0.16, "ex": -0.03},
        6: {"turn": -0.04, "straight": -0.04, "lap": -0.20, "ex": -0.04},
    },
    "住之江": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.22, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.11, "ex": 0.01},
        3: {"turn": -0.01, "straight": -0.01, "lap": -0.04, "ex": -0.01},
        4: {"turn": -0.01, "straight": -0.02, "lap": -0.08, "ex": -0.02},
        5: {"turn": -0.02, "straight": -0.03, "lap": -0.12, "ex": -0.03},
        6: {"turn": -0.03, "straight": -0.03, "lap": -0.15, "ex": -0.04},
    },
    "尼崎": {
        1: {"turn": 0.04, "straight": 0.01, "lap": 0.24, "ex": 0.02},
        2: {"turn": 0.02, "straight": 0.00, "lap": 0.12, "ex": 0.01},
    },
}

# 上記に無い会場・コース用のフォールバック（13場の平均値ベース）
DEFAULT_EX_MODIFIERS = {
    1: {"turn": 0.04, "straight": 0.01, "lap": 0.24, "ex": 0.02},
    2: {"turn": 0.02, "straight": 0.00, "lap": 0.13, "ex": 0.01},
    3: {"turn": -0.01, "straight": -0.01, "lap": -0.04, "ex": -0.01},
    4: {"turn": -0.02, "straight": -0.02, "lap": -0.09, "ex": -0.02},
    5: {"turn": -0.03, "straight": -0.03, "lap": -0.14, "ex": -0.03},
    6: {"turn": -0.04, "straight": -0.03, "lap": -0.17, "ex": -0.04},
}

# rough_race_scanner.py側のフィールド名 -> このモジュールのmetric_typeキー対応
FIELD_TO_METRIC = {
    "ex_time": "ex",
    "lap_time": "lap",
    "turn_time": "turn",
    "straight_time": "straight",
}


def get_exhibition_correction(venue: str, course: int, metric_type: str) -> float:
    """指定された競艇場・コース・計測指標の補正値（秒）を取得する。
    metric_type: 'turn' | 'straight' | 'lap' | 'ex'
    """
    target_venue = None
    for k in VENUE_EX_MODIFIERS.keys():
        if k in venue:
            target_venue = k
            break

    if target_venue:
        course_data = VENUE_EX_MODIFIERS[target_venue].get(course)
        if course_data and metric_type in course_data:
            return course_data[metric_type]

    fallback_data = DEFAULT_EX_MODIFIERS.get(course, {metric_type: 0.0})
    return fallback_data.get(metric_type, 0.0)


def corrected_value(venue: str, course: int, field: str, raw_value):
    """rough_race_scanner.py側のフィールド名(ex_time等)とコースから、補正後の値を返す。
    raw_valueがNoneの場合はNoneを返す。
    """
    if raw_value is None:
        return None
    metric_type = FIELD_TO_METRIC.get(field)
    if metric_type is None:
        return raw_value
    corr = get_exhibition_correction(venue, course, metric_type)
    return round(raw_value + corr, 3)
