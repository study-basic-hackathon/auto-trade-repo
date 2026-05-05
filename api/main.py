from fastapi import FastAPI, HTTPException, Query
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from typing import Any
import boto3
from botocore.exceptions import ClientError
import requests
import uvicorn

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

