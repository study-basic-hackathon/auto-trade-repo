from fastapi import FastAPI, HTTPException, Query
import json
from typing import Any
import requests
import uvicorn

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

