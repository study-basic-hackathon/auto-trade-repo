from fastapi import FastAPI, HTTPException, Query
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import time
from typing import Any
import boto3
from botocore.exceptions import ClientError
import requests
import uvicorn
import yfinance as yf

JST = timezone(timedelta(hours=9))

# Yahoo!ファイナンスのページ内に埋め込まれている JSON データの開始位置です。
PRELOADED_STATE_MARKER = "window.__PRELOADED_STATE__ = "

# 売買代金上位ランキングの取得先 URL です。
TRADING_VALUE_URL = (
    "https://finance.yahoo.co.jp/stocks/ranking/tradingValueHigh"
    "?market=all&term=daily&page={page}"
)

# 出来高増加率ランキングの取得先 URL です。
VOLUME_INCREASE_URL = (
    "https://finance.yahoo.co.jp/stocks/ranking/volumeIncrease"
    "?market=all&term=previous&page={page}"
)

# ブラウザからのアクセスに近づけるためのヘッダーです。
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

app = FastAPI(title="backend-api")


def parse_number(value: str | int | float | None) -> float:
    # 文字列や数値を float にそろえて、計算しやすくします。
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        return float(value)

    normalized = value.replace(",", "").replace("+", "").strip()
    if normalized in {"", "---"}:
        return 0.0

    return float(normalized)


def extract_preloaded_state(html: str) -> dict[str, Any]:
    # HTML の中から window.__PRELOADED_STATE__ の JSON 部分だけを抜き出します。
    start_index = html.find(PRELOADED_STATE_MARKER)
    if start_index == -1:
        raise ValueError("Yahoo Finance preloaded state was not found in the page")

    json_start = start_index + len(PRELOADED_STATE_MARKER)
    json_end = html.find("</script>", json_start)
    if json_end == -1:
        raise ValueError("Yahoo Finance preloaded state script end was not found")

    return json.loads(html[json_start:json_end].strip())


def fetch_ranking_results(
    session: requests.Session,
    url_template: str,
    pages: int,
) -> list[dict[str, Any]]:
    # 複数ページを順番に取りに行き、ランキング結果を 1 つの配列にまとめます。
    results: list[dict[str, Any]] = []

    for page in range(1, pages + 1):
        response = session.get(url_template.format(page=page), timeout=15)
        response.raise_for_status()
        state = extract_preloaded_state(response.text)
        page_results = state.get("mainRankingList", {}).get("results")
        if not isinstance(page_results, list):
            raise ValueError("Yahoo Finance ranking results were not found")
        results.extend(page_results)

    return results


def build_trading_value_map(
    ranking_results: list[dict[str, Any]],
    min_trading_value: int,
) -> list[dict[str, Any]]:
    # 売買代金ランキングから、API で返したい形のデータに整形します。
    filtered_results: list[dict[str, Any]] = []

    for row in ranking_results:
        ranking_result = row.get("rankingResult", {})
        trading_value = ranking_result.get("tradingValue") or {}
        current_price = parse_number(row.get("savePrice"))
        previous_diff = parse_number(trading_value.get("changePrice"))
        trading_value_amount = parse_number(trading_value.get("tradingValue"))

        if trading_value_amount < min_trading_value:
            continue

        # 前日終値 = 現在値 - 前日比 として、値上率を計算します。
        previous_close = current_price - previous_diff
        increase_rate = 0.0
        if previous_close != 0:
            increase_rate = round(previous_diff / previous_close * 100, 3)

        filtered_results.append(
            {
                "コード": str(row.get("stockCode", "")).strip(),
                "名称": str(row.get("stockName", "")).strip(),
                "市場": str(row.get("marketName", "")).strip(),
                "取引値": current_price,
                "前日比": previous_diff,
                "値上率(%)": increase_rate,
                "売買代金": int(trading_value_amount),
            }
        )

    return filtered_results


def build_volume_increase_map(
    ranking_results: list[dict[str, Any]],
    min_volume_ratio: float,
) -> dict[str, dict[str, float | int]]:
    # 出来高増加率ランキングを、銘柄コードで引ける辞書に変換します。
    filtered_results: dict[str, dict[str, float | int]] = {}

    for row in ranking_results:
        ranking_result = row.get("rankingResult", {})
        previous_volume_rate = ranking_result.get("previousVolumeRate") or {}
        volume_ratio = parse_number(previous_volume_rate.get("previousVolumeRate"))
        if volume_ratio < min_volume_ratio:
            continue

        code = str(row.get("stockCode", "")).strip()
        filtered_results[code] = {
            "出来高": int(parse_number(previous_volume_rate.get("volume"))),
            "出来高増加率": round(volume_ratio, 3),
        }

    return filtered_results


def collect_day_trade_list(
    pages: int,
    min_trading_value: int,
    min_volume_ratio: float,
) -> list[dict[str, Any]]:
    # 1. ランキングを取得
    # 2. それぞれ整形
    # 3. 共通する銘柄コードだけを結合
    with requests.Session() as session:
        session.headers.update(DEFAULT_HEADERS)

        trading_results = fetch_ranking_results(session, TRADING_VALUE_URL, pages)
        volume_results = fetch_ranking_results(session, VOLUME_INCREASE_URL, pages)

    trading_rows = build_trading_value_map(trading_results, min_trading_value)
    volume_rows = build_volume_increase_map(volume_results, min_volume_ratio)

    merged_rows: list[dict[str, Any]] = []
    for trading_row in trading_rows:
        code = trading_row["コード"]
        volume_row = volume_rows.get(code)
        if volume_row is None:
            continue

        # 売買代金側と出来高増加率側の情報を 1 行にまとめます。
        merged_rows.append(
            {
                "コード": code,
                "名称": trading_row["名称"],
                "市場": trading_row["市場"],
                "取引値": trading_row["取引値"],
                "前日比": trading_row["前日比"],
                "値上率(%)": trading_row["値上率(%)"],
                "売買代金": trading_row["売買代金"],
                "出来高": volume_row["出来高"],
                "出来高増加率": volume_row["出来高増加率"],
            }
        )

    return merged_rows



def _recent_year_months(today: date, n: int = 12) -> list[str]:
    """today を含めて直近 n ヶ月分の YYYY-MM 文字列を新しい順で返す。"""
    out: list[str] = []
    cur = today.replace(day=1)
    for _ in range(n):
        out.append(cur.strftime("%Y-%m"))
        cur = (cur - timedelta(days=1)).replace(day=1)
    return out


def _read_jsonl_from_s3(
    s3, bucket: str, prefix: str, ticker: str, months: list[str]
) -> list[dict[str, Any]]:
    """{prefix}/{ticker}.YYYY-MM.jsonl 形式のファイル群を全て読み込んで結合する。"""
    records: list[dict[str, Any]] = []
    for ym in months:
        key = f"{prefix}/{ticker}.{ym}.jsonl"
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
                continue
            raise
        for line in obj["Body"].read().decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _span_months(cutoff: date, today: date) -> list[str]:
    """[cutoff, today] 期間に該当する YYYY-MM のリストを古い順で返す。"""
    months: set[str] = set()
    cur = cutoff.replace(day=1)
    last = today.replace(day=1)
    while cur <= last:
        months.add(cur.strftime("%Y-%m"))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return sorted(months)


def _aggregate_accuracy(records: list[dict[str, Any]]) -> dict[str, Any]:
    """精度指標 (direction_accuracy, MAE, MAPE, RMSE, returns_R²) を集計する。"""
    n = len(records)
    if n == 0:
        return {
            "samples": 0,
            "direction_accuracy": None,
            "mae": None,
            "mape": None,
            "rmse": None,
            "returns_r2": None,
        }

    hits = sum(1 for r in records if r.get("hit"))
    abs_errors = [float(r["abs_error"]) for r in records]
    abs_pct_errors = [float(r["abs_pct_error"]) for r in records]
    mae = sum(abs_errors) / n
    mape = sum(abs_pct_errors) / n
    rmse = math.sqrt(sum(e * e for e in abs_errors) / n)

    # 対数リターンベースの R² (両フィールドが揃っている件のみ)
    pairs = [
        (float(r["actual_log_return"]), float(r["predicted_log_return"]))
        for r in records
        if r.get("actual_log_return") is not None
        and r.get("predicted_log_return") is not None
    ]
    if len(pairs) >= 2:
        actual = [a for a, _ in pairs]
        mean_a = sum(actual) / len(actual)
        ss_tot = sum((a - mean_a) ** 2 for a in actual)
        ss_res = sum((a - p) ** 2 for a, p in pairs)
        returns_r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    else:
        returns_r2 = None

    return {
        "samples": n,
        "direction_accuracy": round(hits / n, 4),
        "mae": round(mae, 2),
        "mape": round(mape, 6),
        "rmse": round(rmse, 2),
        "returns_r2": round(returns_r2, 4) if returns_r2 is not None else None,
    }


@app.get("/api/metrics/accuracy")
def metrics_accuracy(
    days: int = Query(default=30, ge=1, le=730),
    ticker: str = Query(default="n225"),
) -> dict[str, Any]:
    """過去 days 日間の予測精度を集計して返す。

    metrics/{ticker}.YYYY-MM.jsonl を読み、actual_target_date が
    [today - days, today] の範囲内のレコードを集計対象とする。
    """
    today = datetime.now(JST).date()
    cutoff = today - timedelta(days=days)

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("SECRET_KEY"),
    )
    bucket = os.environ["S3_BUCKET_NAME"]

    all_records = _read_jsonl_from_s3(s3, bucket, "metrics", ticker, _span_months(cutoff, today))

    # 期間でフィルタ
    in_window: list[dict[str, Any]] = []
    for r in all_records:
        target_str = r.get("actual_target_date")
        if not target_str:
            continue
        try:
            target = datetime.strptime(target_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if cutoff <= target <= today:
            in_window.append(r)

    in_window.sort(key=lambda r: r["actual_target_date"])

    summary = _aggregate_accuracy(in_window)

    return {
        "ticker": ticker,
        "window_days": days,
        "from": cutoff.isoformat(),
        "to": today.isoformat(),
        **summary,
        "by_date": [
            {
                "actual_target_date": r["actual_target_date"],
                "as_of_date": r.get("as_of_date"),
                "predicted_close": r.get("predicted_close"),
                "actual_close": r.get("actual_close"),
                "prediction_sign": r.get("prediction_sign"),
                "actual_sign": r.get("actual_sign"),
                "hit": r.get("hit"),
                "abs_error": r.get("abs_error"),
                "abs_pct_error": r.get("abs_pct_error"),
            }
            for r in in_window
        ],
    }


@app.get("/api/predictions/latest")
def predictions_latest(
    ticker: str = Query(default="n225"),
) -> dict[str, Any]:
    """最新の予測レコードを 1 件返す。

    現在月から前月までを走査し、predicted_at が最も新しいレコードを返す。
    レコードが 1 件もなければ 404。
    """
    today = datetime.now(JST).date()
    # 現在月 + 前月をカバー (月初に当月ファイルが空のケースに備える)
    months = [
        (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
        today.strftime("%Y-%m"),
    ]

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("SECRET_KEY"),
    )
    bucket = os.environ["S3_BUCKET_NAME"]

    records = _read_jsonl_from_s3(s3, bucket, "predictions", ticker, months)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No predictions found for ticker={ticker}",
        )

    # predicted_at で降順ソートし、最新を選択
    records.sort(key=lambda r: r.get("predicted_at", ""), reverse=True)
    return {
        "ticker": ticker,
        "prediction": records[0],
    }


@app.get("/api/predictions/explanation/latest")
def predictions_explanation_latest(
    ticker: str = Query(default="n225"),
) -> dict[str, Any]:
    """最新の特徴量寄与 (相関係数による予想根拠) を 1 件返す。

    現在月から前月までを走査し、computed_at が最も新しいレコードを返す。
    レコードが 1 件もなければ 404。
    """
    today = datetime.now(JST).date()
    months = [
        (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
        today.strftime("%Y-%m"),
    ]

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("SECRET_KEY"),
    )
    bucket = os.environ["S3_BUCKET_NAME"]

    records = _read_jsonl_from_s3(s3, bucket, "explanations", ticker, months)
    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"No explanations found for ticker={ticker}",
        )

    records.sort(key=lambda r: r.get("computed_at", ""), reverse=True)
    return {
        "ticker": ticker,
        "explanation": records[0],
    }


@app.get("/api/predictions")
def predictions_list(
    days: int = Query(default=30, ge=1, le=730),
    ticker: str = Query(default="n225"),
) -> dict[str, Any]:
    """直近 days 日間の予測レコードを古い順で返す。

    target_date が [today - days, today] の範囲のレコードを対象。
    """
    today = datetime.now(JST).date()
    cutoff = today - timedelta(days=days)

    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("SECRET_KEY"),
    )
    bucket = os.environ["S3_BUCKET_NAME"]

    all_records = _read_jsonl_from_s3(s3, bucket, "predictions", ticker, _span_months(cutoff, today))

    # target_date でフィルタ
    in_window: list[dict[str, Any]] = []
    for r in all_records:
        target_str = r.get("target_date")
        if not target_str:
            continue
        try:
            target = datetime.strptime(target_str, "%Y-%m-%d").date()
        except ValueError:
            continue
        if cutoff <= target <= today:
            in_window.append(r)

    in_window.sort(key=lambda r: (r.get("target_date", ""), r.get("predicted_at", "")))

    return {
        "ticker": ticker,
        "window_days": days,
        "from": cutoff.isoformat(),
        "to": today.isoformat(),
        "count": len(in_window),
        "items": in_window,
    }


# ============================================================
# PTS (Japannext / Kabutan 集計) — 翌朝寄付き予想・GAP 候補・出来高サージ
# ------------------------------------------------------------
# Kabutan の PTS ランキングページ (デイ/ナイト/出来高) をスクレイプし、
# yfinance の TSE データと組み合わせてデイトレ向け情報を提供する。
# ============================================================

import re as _re

KABUTAN_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
PTS_NIGHT_VALUE_URL = "https://kabutan.jp/warning/pts_night_trading_value_ranking"
PTS_DAY_VALUE_URL = "https://kabutan.jp/warning/pts_day_trading_value_ranking"
PTS_NIGHT_VOLUME_URL = "https://kabutan.jp/warning/pts_night_volume_ranking"

_PTS_CACHE_TTL_SECONDS = 300  # 5 分
_pts_overnight_cache: tuple[float, dict[str, Any]] | None = None
_pts_premarket_cache: tuple[float, dict[str, Any]] | None = None
_pts_volume_surge_cache: tuple[float, dict[str, Any]] | None = None


def _strip_html(s: str) -> str:
    """HTML タグを除去して空白圧縮した平文を返す。"""
    t = _re.sub(r"<[^>]+>", " ", s).strip()
    return _re.sub(r"\s+", " ", t)


def _to_num(s: str) -> float | None:
    """カンマ・パーセント・空欄等を float | None に正規化する。"""
    if not s or s in ("－", "-", "", "&nbsp;"):
        return None
    cleaned = s.replace(",", "").replace("+", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except (TypeError, ValueError):
        return None


def _fetch_kabutan_pts_ranking(url: str) -> list[dict[str, Any]]:
    """Kabutan の PTS ランキングページから各銘柄の情報を取得する。

    返却フィールド (利用可能なもの):
      - code: 銘柄コード (例 "9984", "285A")
      - name: 銘柄名 (例 "ソフトバンクＧ")
      - market: 市場区分 (例 "東Ｐ" = 東証プライム)
      - tse_close: TSE 直近通常取引終値 (円)
      - pts_price: PTS 直近約定値 (円)
      - change_yen: PTS - TSE 差額
      - change_pct: PTS - TSE 変化率 (%)
      - metric: ランキングの指標値 (売買代金は 百万円、出来高は株数)
    """
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": KABUTAN_USER_AGENT,
                "Accept-Language": "ja,en-US;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[警告] Kabutan {url} 取得失敗: {e}")
        return []

    html = resp.text
    items: list[dict[str, Any]] = []
    # ランキングテーブルの行: 各 <tr> 内に 13 個前後の <th>/<td> があり、
    # そのうちセル [0]=コード, [1]=銘柄名, [2]=市場, [5]=TSE終値, [6]=PTS価格,
    # [7]=差額, [8]=変化率, [9]=指標値 (売買代金 or 出来高)
    rows = _re.findall(r"<tr(?:\s[^>]*)?>(.*?)</tr>", html, _re.DOTALL)
    for tr in rows:
        if "/stock/?code=" not in tr:
            continue
        cells = _re.findall(r"<(?:th|td)[^>]*>(.*?)</(?:th|td)>", tr, _re.DOTALL)
        if len(cells) < 10:
            continue  # ヘッダ系・指数表示行など
        code = _strip_html(cells[0])
        if not _re.match(r"^[A-Z0-9]{4,5}$", code):
            continue  # 4〜5 桁の銘柄コードでない行はスキップ

        items.append(
            {
                "code": code,
                "name": _strip_html(cells[1]),
                "market": _strip_html(cells[2]),
                "tse_close": _to_num(_strip_html(cells[5])) if len(cells) > 5 else None,
                "pts_price": _to_num(_strip_html(cells[6])) if len(cells) > 6 else None,
                "change_yen": _to_num(_strip_html(cells[7])) if len(cells) > 7 else None,
                "change_pct": _to_num(_strip_html(cells[8])) if len(cells) > 8 else None,
                "metric": _to_num(_strip_html(cells[9])) if len(cells) > 9 else None,
            }
        )
    return items


def _polymarket_url_for_code(code: str) -> str:
    """銘柄コードから Kabutan の銘柄詳細ページ URL を返す。"""
    return f"https://kabutan.jp/stock/?code={code}"


def _build_pts_ranking_response(
    url: str, session: str, metric_name: str, top_n: int = 20
) -> dict[str, Any]:
    """PTS ランキング (売買代金) を整形して返す共通ビルダー。"""
    raw = _fetch_kabutan_pts_ranking(url)
    items: list[dict[str, Any]] = []
    for rank, r in enumerate(raw[:top_n], start=1):
        items.append(
            {
                "rank": rank,
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "tse_close": r["tse_close"],
                "pts_price": r["pts_price"],
                "change_yen": r["change_yen"],
                "change_pct": r["change_pct"],
                metric_name: r["metric"],
                "kabutan_url": _polymarket_url_for_code(r["code"]),
            }
        )
    return {
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "session": session,
        "source": "kabutan",
        "count": len(items),
        "items": items,
    }


# ----------------------------------------------------------------
# 案 A: PTS ナイト + TSE 終値 統合配信 (翌朝寄付き要注目銘柄)
# ----------------------------------------------------------------

@app.get("/api/markets/pts/overnight")
def pts_overnight(no_cache: bool = Query(default=False)) -> dict[str, Any]:
    """PTS ナイトタイム売買代金 TOP20 + TSE 終値乖離率を返す。

    引け後 16:30〜翌 6:00 の値動きを集計したもの。
    翌営業日の寄付きで動きそうな銘柄をデイトレーダーに提示する用途。
    """
    global _pts_overnight_cache
    now = time.time()
    if not no_cache and _pts_overnight_cache is not None:
        cached_at, cached_value = _pts_overnight_cache
        if now - cached_at < _PTS_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }
    result = _build_pts_ranking_response(
        PTS_NIGHT_VALUE_URL, "night", "trading_value_million_jpy", top_n=15
    )
    _pts_overnight_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


# ----------------------------------------------------------------
# 案 B: PTS デイ + GAP 候補 (寄付前 8:20〜9:00)
# ----------------------------------------------------------------

@app.get("/api/markets/pts/premarket")
def pts_premarket(no_cache: bool = Query(default=False)) -> dict[str, Any]:
    """PTS デイタイム売買代金 TOP20 を返す (寄付前 GAP 候補)。

    PTS デイは 8:20-16:00。TSE 寄付 (9:00) 前の 8:20-8:59 の値動きが
    GAP 寄付き予想の最良の先行指標。change_pct がそのまま GAP 推定値。
    """
    global _pts_premarket_cache
    now = time.time()
    if not no_cache and _pts_premarket_cache is not None:
        cached_at, cached_value = _pts_premarket_cache
        if now - cached_at < _PTS_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }
    result = _build_pts_ranking_response(
        PTS_DAY_VALUE_URL, "day", "trading_value_million_jpy", top_n=15
    )
    _pts_premarket_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


# ----------------------------------------------------------------
# 案 C: PTS 出来高サージ検知 (突発ニュース反応の早期発見)
# ----------------------------------------------------------------

def _fetch_tse_avg_volume(ticker_code: str, days: int = 30) -> float | None:
    """yfinance で {ticker}.T の過去 days 営業日の平均出来高 (株数) を返す。"""
    try:
        ticker = yf.Ticker(f"{ticker_code}.T")
        hist = ticker.history(period=f"{days+10}d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or "Volume" not in hist.columns:
            return None
        vols = hist["Volume"].dropna()
        if vols.empty:
            return None
        return float(vols.tail(days).mean())
    except Exception:
        return None


@app.get("/api/markets/pts/volume_surge")
def pts_volume_surge(
    no_cache: bool = Query(default=False),
    min_surge_ratio: float = Query(default=0.5, ge=0.0, le=10.0),
) -> dict[str, Any]:
    """PTS ナイト出来高 TOP15 と TSE 30 日平均出来高の比 (surge ratio) を返す。

    PTS 出来高 / TSE 30日平均 が高いほど「異常な流動性」= 突発材料あり。
    `min_surge_ratio` 以下のものは items から除外。
    """
    global _pts_volume_surge_cache
    now = time.time()
    if not no_cache and _pts_volume_surge_cache is not None:
        cached_at, cached_value = _pts_volume_surge_cache
        if now - cached_at < _PTS_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }

    raw = _fetch_kabutan_pts_ranking(PTS_NIGHT_VOLUME_URL)[:15]
    items: list[dict[str, Any]] = []
    for r in raw:
        pts_volume = r["metric"]  # 出来高ページでは [9] が出来高 (株数)
        avg_volume = _fetch_tse_avg_volume(r["code"], days=30)
        surge_ratio = None
        if pts_volume and avg_volume and avg_volume > 0:
            # PTS 出来高は通常 TSE 出来高の数 % 程度なので、
            # surge_ratio が 0.5 を超えれば「異常」と判定できる経験則
            surge_ratio = pts_volume / avg_volume
        if surge_ratio is None or surge_ratio < min_surge_ratio:
            continue
        items.append(
            {
                "code": r["code"],
                "name": r["name"],
                "market": r["market"],
                "tse_close": r["tse_close"],
                "pts_price": r["pts_price"],
                "change_pct": r["change_pct"],
                "pts_volume": pts_volume,
                "tse_avg_volume_30d": round(avg_volume, 0) if avg_volume else None,
                "surge_ratio": round(surge_ratio, 3) if surge_ratio else None,
                "kabutan_url": _polymarket_url_for_code(r["code"]),
            }
        )
    items.sort(key=lambda x: x.get("surge_ratio") or 0, reverse=True)

    result = {
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "session": "night",
        "source": "kabutan + yfinance",
        "min_surge_ratio": min_surge_ratio,
        "count": len(items),
        "items": items,
    }
    _pts_volume_surge_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


# ============================================================
# Polymarket: 予想市場の確率データ (デイトレ補助のセンチメント指標)
# ------------------------------------------------------------
# Polymarket Gamma API (認証不要) から指定キーワードで該当する
# event を見つけ、確率と出来高を返す。30 分 TTL キャッシュ。
# ============================================================

POLYMARKET_MASTER_PATH = Path(__file__).parent / "data" / "polymarket_master.json"
POLYMARKET_GAMMA_URL = "https://gamma-api.polymarket.com/events"
POLYMARKET_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
)
_POLYMARKET_CACHE_TTL_SECONDS = 1800  # 30 分
_polymarket_cache: tuple[float, dict[str, Any]] | None = None


def _load_polymarket_master() -> list[dict[str, Any]]:
    """Polymarket マスタ JSON を読み込む。"""
    with open(POLYMARKET_MASTER_PATH, encoding="utf-8") as f:
        return json.load(f)


def _fetch_polymarket_events(
    pages: int = 3, page_size: int = 500
) -> list[dict[str, Any]]:
    """Polymarket Gamma API からアクティブな event 一覧を取得する。

    出来高降順で複数ページ取得 (デフォルト 3 ページ × 500 = 1500 events)。
    主要マーケット + やや出来高の小さい (BOJ・USD/JPY 等) もカバー。
    """
    all_events: list[dict[str, Any]] = []
    for page in range(pages):
        try:
            resp = requests.get(
                POLYMARKET_GAMMA_URL,
                params={
                    "limit": page_size,
                    "offset": page * page_size,
                    "active": "true",
                    "closed": "false",
                    "order": "volume",
                    "ascending": "false",
                },
                headers={"User-Agent": POLYMARKET_USER_AGENT},
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[警告] Polymarket events API 呼び出し失敗 (page {page}): {e}")
            break
        data = resp.json()
        if not isinstance(data, list) or not data:
            break
        all_events.extend(data)
        if len(data) < page_size:
            break  # ページ末端
    return all_events


def _find_event_by_keywords(
    keywords: list[str],
    events: list[dict[str, Any]],
    exclude_keywords: list[str] | None = None,
    prefer_earliest_resolution: bool = False,
) -> dict[str, Any] | None:
    """slug/title に keywords を全て含む event を探す。

    Args:
        keywords: 全部含まれている必要がある語 (AND)
        exclude_keywords: 1 つでも含まれていたら除外する語 (OR)
        prefer_earliest_resolution:
            True → endDate 昇順 (= 最も早く決着するもの) で先頭を返す。
                   月次/週次の決定系を「次回開催」で自動ロールしたい場合に使う。
            False → volume 降順 (= 最も出来高の大きいもの) で先頭を返す (既定挙動)。
    """
    needles = [kw.lower() for kw in keywords]
    excludes = [kw.lower() for kw in (exclude_keywords or [])]
    matches: list[dict[str, Any]] = []
    for ev in events:
        haystack = (
            (ev.get("slug") or "").lower()
            + " "
            + (ev.get("title") or "").lower()
        )
        if not all(n in haystack for n in needles):
            continue
        if excludes and any(e in haystack for e in excludes):
            continue
        matches.append(ev)
    if not matches:
        return None

    if prefer_earliest_resolution:
        matches.sort(key=lambda e: e.get("endDate") or "9999-12-31T00:00:00Z")
    else:
        def _vol(ev: dict[str, Any]) -> float:
            try:
                return float(ev.get("volume") or 0)
            except (TypeError, ValueError):
                return 0.0
        matches.sort(key=_vol, reverse=True)
    return matches[0]


def _parse_event_outcomes(event: dict[str, Any]) -> list[dict[str, Any]]:
    """event の sub-market 群を [{name, probability}] に整形する。

    - sub-market が 1 つだけ: その outcomes (Yes/No 等) を直接返す
    - 複数 sub-market: 各 sub-market の名前 + Yes 確率を outcome として返す
    """
    markets = event.get("markets") or []
    if not markets:
        return []

    if len(markets) == 1:
        m = markets[0]
        outs = m.get("outcomes")
        prices = m.get("outcomePrices")
        if isinstance(outs, str):
            try:
                outs = json.loads(outs)
            except json.JSONDecodeError:
                outs = []
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                prices = []
        outcomes: list[dict[str, Any]] = []
        for i, name in enumerate(outs or []):
            try:
                p = float(prices[i]) if i < len(prices or []) else None
            except (TypeError, ValueError):
                p = None
            outcomes.append({"name": str(name), "probability": p})
        return outcomes

    # 複数 sub-market: 各 sub-market の "Yes" 確率を outcome として扱う
    outcomes = []
    for m in markets:
        outcome_name = (
            m.get("groupItemTitle")
            or m.get("question")
            or m.get("slug")
            or ""
        )
        outs = m.get("outcomes")
        prices = m.get("outcomePrices")
        if isinstance(outs, str):
            try:
                outs = json.loads(outs)
            except json.JSONDecodeError:
                outs = []
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except json.JSONDecodeError:
                prices = []
        yes_price = None
        for i, name in enumerate(outs or []):
            if str(name).strip().lower() == "yes" and i < len(prices or []):
                try:
                    yes_price = float(prices[i])
                except (TypeError, ValueError):
                    yes_price = None
                break
        outcomes.append({"name": str(outcome_name), "probability": yes_price})
    return outcomes


def _select_main_outcome(
    outcomes: list[dict[str, Any]], match: str
) -> dict[str, Any]:
    """master の main_outcome_match に基づいて代表確率を選ぶ。

    match の特殊値:
      "_residual_": 1.0 - 全 outcome 確率の合計 (明示されない選択肢の確率を計算)
    通常: outcomes の name に部分一致するものを返す (大小無視)
    マッチしない場合は probability=None を返す (ラベルと値の乖離防止)。
    """
    if match == "_residual_":
        total = 0.0
        any_known = False
        for o in outcomes:
            if o.get("probability") is not None:
                total += float(o["probability"])
                any_known = True
        if not any_known:
            return {"name": "(residual)", "probability": None}
        residual = max(0.0, 1.0 - total)
        return {"name": "(residual)", "probability": residual}

    needle = match.lower()
    for o in outcomes:
        if needle in (o.get("name") or "").lower():
            return o
    # 該当なしの場合: 先頭 outcome を返すと「ラベル(例: ↑165) と実値が無関係」
    # の事故になるため、probability=None で返して呼び出し側で
    # available=false 扱いできるようにする
    return {"name": match, "probability": None, "_unmatched": True}


def _build_polymarket_item(
    master_entry: dict[str, Any], events: list[dict[str, Any]]
) -> dict[str, Any]:
    """マスタ 1 件分について Polymarket データを引いて API レスポンス用 dict を組み立てる。"""
    base = {
        "rank": master_entry.get("rank"),
        "label": master_entry.get("label"),
        "category": master_entry.get("category"),
        "category_key": master_entry.get("category_key"),
        "description_jp": master_entry.get("description_jp", ""),
        "impact_on_n225": master_entry.get("impact_on_n225", ""),
    }

    event = _find_event_by_keywords(
        master_entry.get("search_keywords", []),
        events,
        exclude_keywords=master_entry.get("exclude_keywords"),
        prefer_earliest_resolution=bool(
            master_entry.get("prefer_earliest_resolution", False)
        ),
    )
    if event is None:
        return {
            **base,
            "slug": None,
            "main_outcome": None,
            "all_outcomes": [],
            "volume_usd": None,
            "liquidity_usd": None,
            "resolution_date": None,
            "polymarket_url": None,
            "available": False,
        }

    outcomes = _parse_event_outcomes(event)
    main = _select_main_outcome(
        outcomes, master_entry.get("main_outcome_match", "yes")
    )

    # endDate は ISO 文字列。日付部分だけを取り出す
    end_date_raw = event.get("endDate") or ""
    resolution_date = end_date_raw.split("T")[0] if end_date_raw else None

    try:
        volume_usd = float(event.get("volume") or 0)
    except (TypeError, ValueError):
        volume_usd = None
    try:
        liquidity_usd = float(event.get("liquidity") or 0)
    except (TypeError, ValueError):
        liquidity_usd = None

    slug = event.get("slug")
    polymarket_url = f"https://polymarket.com/event/{slug}" if slug else None

    return {
        **base,
        "slug": slug,
        "main_outcome": {
            "name": main.get("name"),
            "name_jp": master_entry.get("main_outcome_name_jp"),
            "probability": (
                round(main["probability"], 4)
                if main.get("probability") is not None
                else None
            ),
        },
        "all_outcomes": [
            {
                "name": o.get("name"),
                "probability": (
                    round(o["probability"], 4)
                    if o.get("probability") is not None
                    else None
                ),
            }
            for o in outcomes
        ],
        "volume_usd": round(volume_usd, 2) if volume_usd is not None else None,
        "liquidity_usd": (
            round(liquidity_usd, 2) if liquidity_usd is not None else None
        ),
        "resolution_date": resolution_date,
        "polymarket_url": polymarket_url,
        # main_outcome_match に該当 outcome が見つからなかった場合は
        # ラベルと実値の乖離事故を避けるため available=False とする
        "available": not main.get("_unmatched", False),
    }


def _compute_polymarket_response() -> dict[str, Any]:
    """マスタ全件分の Polymarket データを取得して返す。"""
    master = _load_polymarket_master()
    # pages=8 で約 4000 events をカバー (BOJ・USD/JPY・各種 recession など低出来高マーケットを含むため)
    events = _fetch_polymarket_events(pages=8, page_size=500)

    items = [_build_polymarket_item(m, events) for m in master]
    items.sort(key=lambda x: x.get("rank") or 99)

    return {
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "source": "polymarket-gamma-api",
        "count": len(items),
        "items": items,
    }


@app.get("/api/markets/polymarket")
def markets_polymarket(
    no_cache: bool = Query(default=False),
) -> dict[str, Any]:
    """Polymarket 予想市場の確率データを 11 マーケット分まとめて返す。

    - 30 分 TTL キャッシュ
    - `?no_cache=true` で強制再取得
    - データソース失敗 / 該当 event 無しの個別マーケットは `available: false`
    """
    global _polymarket_cache

    now = time.time()
    if not no_cache and _polymarket_cache is not None:
        cached_at, cached_value = _polymarket_cache
        if now - cached_at < _POLYMARKET_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }

    result = _compute_polymarket_response()
    _polymarket_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


# ============================================================
# 米国マーケット (前日終値)
# ------------------------------------------------------------
# NYダウ / NASDAQ / S&P500 / USD/JPY の直近終値と前日比を返す。
# yfinance を 4 回叩くため 10 分間 TTL キャッシュ。
# ============================================================

_US_MARKETS_CACHE_TTL_SECONDS = 600  # 10 分
_us_markets_cache: tuple[float, dict[str, Any]] | None = None

# 表示順を保つため tuple のリストで定義 (キー, 表示名, yfinance シンボル)
US_MARKET_TICKERS: list[tuple[str, str, str]] = [
    ("dow",     "NYダウ",  "^DJI"),
    ("nasdaq",  "NASDAQ",  "^IXIC"),
    ("sp500",   "S&P 500", "^GSPC"),
    ("usd_jpy", "USD/JPY", "JPY=X"),
]


def _yf_latest_close_with_change(
    symbol: str, period: str = "10d"
) -> dict[str, float] | None:
    """yfinance で直近 2 営業日の終値を取得し close / change / change_pct を返す。

    取得失敗・データ不足時は None。
    """
    try:
        hist = yf.Ticker(symbol).history(
            period=period, interval="1d", auto_adjust=False
        )
    except Exception:
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return None
    latest = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    change = latest - prev
    change_pct = change / prev if prev != 0 else 0.0
    return {"close": latest, "change": change, "change_pct": change_pct}


def _compute_us_markets() -> dict[str, Any]:
    """米国主要指数 + USD/JPY の直近終値と前日比を取得する。"""
    items: dict[str, Any] = {}
    for key, display_name, symbol in US_MARKET_TICKERS:
        # yfinance のレート制限回避用に少し sleep
        time.sleep(0.2)
        data = _yf_latest_close_with_change(symbol)
        if data is None:
            items[key] = {
                "name": display_name,
                "symbol": symbol,
                "close": None,
                "change": None,
                "change_pct": None,
            }
        else:
            items[key] = {
                "name": display_name,
                "symbol": symbol,
                "close": round(data["close"], 2),
                "change": round(data["change"], 2),
                "change_pct": round(data["change_pct"], 4),
            }

    return {
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "items": items,
    }


@app.get("/api/markets/us")
def markets_us(
    no_cache: bool = Query(default=False),
) -> dict[str, Any]:
    """米国主要指数 (NYダウ / NASDAQ / S&P500) と USD/JPY の直近終値を返す。

    - データソース: yfinance
    - キャッシュ: 10 分間メモリ保持。`?no_cache=true` で強制再取得
    - 取得失敗した銘柄は close/change/change_pct が null になる
    """
    global _us_markets_cache

    now = time.time()
    if not no_cache and _us_markets_cache is not None:
        cached_at, cached_value = _us_markets_cache
        if now - cached_at < _US_MARKETS_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }

    result = _compute_us_markets()
    _us_markets_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


# ============================================================
# ADR (米国預託証券) 乖離率
# ------------------------------------------------------------
# 日本企業の東証株価とADR(米国上場)の終値を比較し、円換算後の
# 乖離率を返す。yfinance を呼ぶため重いので TTL キャッシュ。
# ============================================================

ADR_MASTER_PATH = Path(__file__).parent / "data" / "adr_master.json"
_ADR_CACHE_TTL_SECONDS = 600  # 10 分
_adr_cache: tuple[float, dict[str, Any]] | None = None


def _load_adr_master() -> list[dict[str, Any]]:
    """ADR マスタ JSON を読み込む。is_active=True のレコードのみ返す。"""
    with open(ADR_MASTER_PATH, encoding="utf-8") as f:
        records = json.load(f)
    return [r for r in records if r.get("is_active") is True]


def _yf_latest_close(ticker: str, period: str = "10d") -> float | None:
    """yfinance で指定銘柄の直近終値 1 件を取得 (失敗時 None)。"""
    try:
        hist = yf.Ticker(ticker).history(
            period=period, interval="1d", auto_adjust=False
        )
    except Exception:
        return None
    if hist is None or hist.empty or "Close" not in hist.columns:
        return None
    close_series = hist["Close"].dropna()
    if close_series.empty:
        return None
    return float(close_series.iloc[-1])


def _compute_adr_deviation() -> dict[str, Any]:
    """全 ADR 銘柄について TSE 終値 / ADR 終値 / 乖離率を計算する。"""
    master = _load_adr_master()

    usd_jpy = _yf_latest_close("JPY=X")
    if usd_jpy is None:
        raise HTTPException(
            status_code=502, detail="USD/JPY rate could not be fetched from yfinance"
        )

    items: list[dict[str, Any]] = []
    for row in master:
        # yfinance のレート制限回避用に少し sleep (notebook と同じ作法)
        time.sleep(0.2)
        tse_close = _yf_latest_close(row["tse_ticker"])
        time.sleep(0.2)
        adr_close_usd = _yf_latest_close(row["adr"])

        adr_close_jpy: float | None = None
        deviation_pct: float | None = None
        ratio = row.get("adr_shares_per_adr")
        if (
            tse_close is not None
            and adr_close_usd is not None
            and ratio is not None
            and float(ratio) > 0
        ):
            adr_close_jpy = adr_close_usd * usd_jpy / float(ratio)
            deviation_pct = (adr_close_jpy / tse_close - 1) * 100

        items.append(
            {
                "name": row.get("name"),
                "tse_code": str(row.get("tse_code", "")).zfill(4),
                "adr": row.get("adr"),
                "us_exchange": row.get("us_exchange"),
                "industry": row.get("industry"),
                "adr_shares_per_adr": ratio,
                "tse_close": round(tse_close, 2) if tse_close is not None else None,
                "adr_close_usd": round(adr_close_usd, 4) if adr_close_usd is not None else None,
                "adr_close_jpy": round(adr_close_jpy, 2) if adr_close_jpy is not None else None,
                "deviation_pct": round(deviation_pct, 2) if deviation_pct is not None else None,
            }
        )

    return {
        "fetched_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "usd_jpy": round(usd_jpy, 4),
        "count": len(items),
        "items": items,
    }


@app.get("/api/adr/deviation")
def adr_deviation(
    no_cache: bool = Query(default=False),
) -> dict[str, Any]:
    """東証銘柄と対応する ADR (米国預託証券) の乖離率を返す。

    - データソース: 銘柄マスタは `api/data/adr_master.json`、価格は yfinance
    - 計算式: ADR終値(USD) × USD/JPY ÷ adr_shares_per_adr → 円換算
              乖離(%) = (円換算ADR終値 / 東証終値 - 1) × 100
    - キャッシュ: 10 分間メモリ保持。`?no_cache=true` で強制再取得可能
    """
    global _adr_cache

    now = time.time()
    if not no_cache and _adr_cache is not None:
        cached_at, cached_value = _adr_cache
        if now - cached_at < _ADR_CACHE_TTL_SECONDS:
            return {
                **cached_value,
                "cached": True,
                "cache_age_seconds": int(now - cached_at),
            }

    result = _compute_adr_deviation()
    _adr_cache = (time.time(), result)
    return {**result, "cached": False, "cache_age_seconds": 0}


@app.get("/api/sample/predictions")
def sample_predictions() -> list[dict[str, Any]]:
    s3 = boto3.client(
        "s3",
        endpoint_url=os.environ.get("ENDPOINT_URL"),
        aws_access_key_id=os.environ.get("ACCESS_KEY"),
        aws_secret_access_key=os.environ.get("SECRET_KEY"),
    )
    obj = s3.get_object(
        Bucket=os.environ["S3_BUCKET_NAME"],
        Key="predictions/n225.jsonl",
    )
    lines = obj["Body"].read().decode("utf-8").strip().splitlines()
    return [json.loads(line) for line in lines]


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


# Nginxから /api/hello に転送されてきた場合の処理
@app.get("/api/hello")
def read_root():
    return {"message": "Hello from Python!"}


@app.get("/api/getdaytradelist")
def get_day_trade_list(
    pages: int = Query(default=10, ge=1, le=20),
    min_trading_value: int = Query(default=1_000_000_000, ge=0),
    min_volume_ratio: float = Query(default=2.0, ge=0),
) -> dict[str, Any]:
    # クエリパラメータを受け取り、条件に合う銘柄一覧を JSON で返します。
    try:
        items = collect_day_trade_list(
            pages=pages,
            min_trading_value=min_trading_value,
            min_volume_ratio=min_volume_ratio,
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance ranking data could not be fetched",
        ) from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502,
            detail="Yahoo Finance ranking data could not be parsed",
        ) from exc

    return {
        "count": len(items),
        "pages": pages,
        "min_trading_value": min_trading_value,
        "min_volume_ratio": min_volume_ratio,
        "items": items,
    }

