"""日経225 LSTM 推論バッチ。

参考: https://github.com/appdevelopmentworks/model-train-lab/blob/main/LSTM.ipynb

処理フロー:
1. yfinance から 5 銘柄 (N225, S&P500, NASDAQ, VIX, USD/JPY) の直近価格を取得
2. S3 から ONNX モデルとスケーラーパラメータ (JSON) を取得
3. ノートブック Cell 9 `predict_next_close` と同じ前処理 (log return + StandardScaler)
4. ONNXRuntime で翌営業日の対数リターンを推論し、終値に変換
5. 結果を月次 JSONL (predictions/n225.YYYY-MM.jsonl) に追記
6. 過去の予測のうち実績が出たものを評価し、月次 JSONL (metrics/n225.YYYY-MM.jsonl) に追記

実行スケジュール: 平日 08:00 JST (EventBridge Scheduler)
"""

import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import boto3
import numpy as np
import onnxruntime as ort
import pandas as pd
import yfinance as yf
from botocore.exceptions import ClientError

TICKER = "n225"
MODEL_VERSION = "2026-05-01"
JST = timezone(timedelta(hours=9))

# yfinance のシンボル → 学習時 CSV のカラム接頭辞
# (n225_lstm_dataset.csv の列順: n225_open/high/low/close/volume,
#  sp500_close, nasdaq_close, vix_close, usdjpy_close)
YF_TICKERS: dict[str, str] = {
    "^N225": "n225",   # OHLCV を使用
    "^GSPC": "sp500",  # close のみ
    "^IXIC": "nasdaq", # close のみ
    "^VIX":  "vix",    # close のみ
    "JPY=X": "usdjpy", # close のみ
}

# 取得する暦日数。SEQ_LEN=60 営業日 + 多銘柄アライメント余裕 + 連休バッファ
DOWNLOAD_DAYS = 180


def get_target_date() -> date:
    """環境変数 TARGET_DATE (YYYY-MM-DD) を読む。未設定なら今日 (JST) を返す。"""
    raw = os.getenv("TARGET_DATE", "").strip()
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now(JST).date()


def download_yfinance_dataset(target_date: date) -> pd.DataFrame:
    """yfinance から 5 銘柄を取得し、学習時 CSV と同じ列構成の DataFrame を返す。

    返却列の順序:
      n225_open, n225_high, n225_low, n225_close, n225_volume,
      sp500_close, nasdaq_close, vix_close, usdjpy_close

    日付インデックスは N225 の取引日のみを採用する (日本の祝日や週末で N225 が
    取引されない日は除外)。他銘柄 (米国指数・為替) は N225 取引日に合わせて
    forward-fill で揃える。
    """
    end = target_date + timedelta(days=1)  # yfinance の end は exclusive
    start = target_date - timedelta(days=DOWNLOAD_DAYS)

    n225_df: pd.DataFrame | None = None
    other_frames: list[pd.DataFrame] = []

    for symbol, prefix in YF_TICKERS.items():
        df = yf.download(
            symbol,
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1d",
            progress=False,
            auto_adjust=False,
        )
        if df is None or df.empty:
            raise RuntimeError(f"yfinance からデータを取得できませんでした: {symbol}")

        # yfinance v0.2 系は MultiIndex columns を返すことがある
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if prefix == "n225":
            sub = df[["Open", "High", "Low", "Close", "Volume"]].copy()
            sub.columns = [
                f"{prefix}_open",
                f"{prefix}_high",
                f"{prefix}_low",
                f"{prefix}_close",
                f"{prefix}_volume",
            ]
            # N225 が実際に取引された日 = Close が NaN でない行
            n225_df = sub.dropna(subset=[f"{prefix}_close"])
        else:
            sub = df[["Close"]].copy()
            sub.columns = [f"{prefix}_close"]
            other_frames.append(sub)

    if n225_df is None or n225_df.empty:
        raise RuntimeError("N225 のデータが取得できませんでした")

    # 他銘柄を N225 取引日に合わせて forward-fill (それ以前のデータも含めて ffill するため
    # 一度フル系列で ffill してから N225 の index に reindex する)
    aligned_others = [
        f.sort_index().ffill().reindex(n225_df.index, method="ffill")
        for f in other_frames
    ]

    merged = pd.concat([n225_df] + aligned_others, axis=1, sort=False).dropna()

    # target_date 以前 (= 推論時点で参照可能) のデータに限定
    merged = merged[merged.index.date <= target_date]

    if merged.empty:
        raise RuntimeError("結合後のデータが空です。yfinance の応答を確認してください")
    return merged


def download_model_artifacts(s3, bucket: str) -> tuple[str, dict]:
    """S3 から ONNX モデルとスケーラーパラメータ JSON をダウンロードする。

    期待する S3 オブジェクト:
      models/{TICKER}.{MODEL_VERSION}.onnx
      models/{TICKER}.{MODEL_VERSION}.params.json
        - feature_mean / feature_std (list[float])
        - target_mean  / target_std  (float)
        - feature_cols (list[str])  ← 学習時の列順
        - target_col   (str)
        - seq_len      (int)
    """
    onnx_key = f"models/{TICKER}.{MODEL_VERSION}.onnx"
    params_key = f"models/{TICKER}.{MODEL_VERSION}.params.json"

    print(f"モデルを S3 から取得: s3://{bucket}/{onnx_key}")
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    s3.download_fileobj(bucket, onnx_key, tmp)
    tmp.close()

    print(f"スケーラーパラメータを S3 から取得: s3://{bucket}/{params_key}")
    obj = s3.get_object(Bucket=bucket, Key=params_key)
    params = json.loads(obj["Body"].read().decode("utf-8"))

    return tmp.name, params


def build_features(df: pd.DataFrame, params: dict) -> tuple[np.ndarray, float]:
    """ノートブック Cell 2 / Cell 9 と同じ前処理を再現する。

    Returns:
        X: (1, seq_len, n_features) float32 — ONNX 入力
        current_close: 直近の N225 終値 (価格復元に使用)
    """
    feature_cols: list[str] = params["feature_cols"]
    seq_len: int = int(params["seq_len"])
    target_col: str = params["target_col"]

    # log-return 変換 (volume だけ log1p、それ以外は対数比)
    returns = pd.DataFrame(index=df.index)
    for col in df.columns:
        if "volume" in col:
            returns[col] = np.log1p(df[col]).diff()
        else:
            returns[col] = np.log(df[col] / df[col].shift(1))
    returns = returns.dropna()

    if len(returns) < seq_len:
        raise ValueError(
            f"必要なリターン日数: {seq_len}, 取得できたのは: {len(returns)}"
        )

    # 直近 seq_len 日の特徴量 (学習時と同じ列順)
    recent = returns[feature_cols].iloc[-seq_len:].values.astype(np.float32)

    # StandardScaler を学習時の mean/scale で再現
    feature_mean = np.asarray(params["feature_mean"], dtype=np.float32)
    feature_std = np.asarray(params["feature_std"], dtype=np.float32)
    scaled = (recent - feature_mean) / feature_std

    X = scaled[np.newaxis, :, :]  # (1, seq_len, n_features)
    current_close = float(df[target_col].iloc[-1])
    return X, current_close


def run_inference(model_path: str, X: np.ndarray, params: dict) -> float:
    """ONNX で推論し、target_scaler を逆変換した対数リターンを返す。"""
    sess = ort.InferenceSession(model_path)
    input_name = sess.get_inputs()[0].name  # 学習時の export では "input"
    pred_scaled = sess.run(None, {input_name: X})[0]  # shape: (1, 1)

    # target_scaler の逆変換: x * std + mean
    target_mean = float(params["target_mean"])
    target_std = float(params["target_std"])
    pred_log_return = float(pred_scaled[0][0]) * target_std + target_mean
    return pred_log_return


def append_monthly_jsonl(s3, bucket: str, target_date: date, record: dict) -> str:
    """月次 JSONL に 1 行追記する。月が変わると新しいファイルが作られる。

    キー命名規約: predictions/{TICKER}.YYYY-MM.jsonl
    """
    key = f"predictions/{TICKER}.{target_date.strftime('%Y-%m')}.jsonl"
    _append_jsonl_records(s3, bucket, key, [record])
    return key


# ============================================================
# 精度モニタリング (predictions/* と yfinance 実績を突合)
# ============================================================

def _read_jsonl_or_empty(s3, bucket: str, key: str) -> list[dict]:
    """S3 から JSONL を読んで dict のリストを返す。存在しなければ空リスト。"""
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return []
        raise
    body = resp["Body"].read().decode("utf-8")
    return [json.loads(line) for line in body.splitlines() if line.strip()]


def _append_jsonl_records(s3, bucket: str, key: str, records: list[dict]) -> None:
    """S3 の JSONL に複数行追記する (既存内容は保持)。"""
    if not records:
        return
    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        existing = resp["Body"].read().decode("utf-8").rstrip("\n")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            existing = ""
        else:
            raise
    new_lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in records)
    content = ((existing + "\n" + new_lines) if existing else new_lines) + "\n"
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/jsonlines",
    )


def _recent_year_months(today: date, n: int = 2) -> list[str]:
    """today を含めて直近 n ヶ月分の YYYY-MM 文字列を古い順で返す。"""
    out: list[str] = []
    cur = today.replace(day=1)
    for _ in range(n):
        out.append(cur.strftime("%Y-%m"))
        # 前月の 1 日へ
        cur = (cur - timedelta(days=1)).replace(day=1)
    return list(reversed(out))


def _evaluate_one(pred: dict, df: pd.DataFrame, target_col: str) -> dict | None:
    """1 つの予測レコードを評価する。実績未確定なら None を返す。"""
    # 旧スキーマ (run.sample.py 由来) など必須フィールド欠落のものは評価不可
    if not {"as_of_date", "current_close", "predicted_close", "prediction_sign"} <= pred.keys():
        return None

    as_of = datetime.strptime(pred["as_of_date"], "%Y-%m-%d").date()
    # df.index 内で as_of より大きい最初の日付 = 予測対象日
    future_mask = df.index.date > as_of
    if not future_mask.any():
        return None  # まだ実績データが届いていない
    actual_target = df.index[future_mask][0]
    actual_close = float(df.loc[actual_target, target_col])
    current_close = float(pred["current_close"])
    if current_close <= 0 or actual_close <= 0:
        return None
    actual_log_return = float(np.log(actual_close / current_close))
    actual_sign = 1 if actual_log_return > 0 else -1
    abs_error = abs(actual_close - float(pred["predicted_close"]))
    abs_pct_error = abs_error / actual_close

    return {
        "evaluated_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "as_of_date": pred["as_of_date"],
        "actual_target_date": actual_target.date().isoformat(),
        "model_version": pred.get("model_version", ""),
        "ticker": pred.get("ticker", TICKER),
        "current_close": round(current_close, 2),
        "predicted_close": round(float(pred["predicted_close"]), 2),
        "actual_close": round(actual_close, 2),
        "predicted_log_return": pred.get("predicted_log_return"),
        "actual_log_return": round(actual_log_return, 6),
        "prediction_sign": int(pred["prediction_sign"]),
        "actual_sign": actual_sign,
        "hit": actual_sign == int(pred["prediction_sign"]),
        "abs_error": round(abs_error, 2),
        "abs_pct_error": round(abs_pct_error, 6),
        "predicted_at": pred.get("predicted_at"),
    }


def evaluate_pending_predictions(
    s3, bucket: str, df: pd.DataFrame, today: date, target_col: str
) -> int:
    """過去の予測のうち実績が確定した未評価のものを評価し、metrics/ に追記する。

    Returns:
        新規に評価できた件数。
    """
    months = _recent_year_months(today, n=2)
    total_new = 0

    for ym in months:
        pred_key = f"predictions/{TICKER}.{ym}.jsonl"
        metric_key = f"metrics/{TICKER}.{ym}.jsonl"

        predictions = _read_jsonl_or_empty(s3, bucket, pred_key)
        if not predictions:
            continue

        existing_metrics = _read_jsonl_or_empty(s3, bucket, metric_key)
        # 評価済みキー (as_of_date + model_version) を集める
        evaluated_keys = {
            (m.get("as_of_date"), m.get("model_version"))
            for m in existing_metrics
        }

        new_records: list[dict] = []
        for pred in predictions:
            key = (pred.get("as_of_date"), pred.get("model_version"))
            if key in evaluated_keys:
                continue
            metric = _evaluate_one(pred, df, target_col)
            if metric is None:
                continue
            new_records.append(metric)

        if new_records:
            _append_jsonl_records(s3, bucket, metric_key, new_records)
            total_new += len(new_records)
            print(f"精度評価 {ym}: 新規 {len(new_records)} 件 → s3://{bucket}/{metric_key}")

    return total_new


def main() -> None:
    target_date = get_target_date()
    print(f"推論対象日付: {target_date}")

    s3 = boto3.client(
        "s3",
        endpoint_url=os.getenv("ENDPOINT_URL") or None,
        aws_access_key_id=os.getenv("ACCESS_KEY") or None,
        aws_secret_access_key=os.getenv("SECRET_KEY") or None,
    )
    bucket = os.getenv("S3_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("S3_BUCKET_NAME 環境変数が未設定です")

    # 1) yfinance から 5 銘柄を取得
    df = download_yfinance_dataset(target_date)
    print(
        f"yfinance データ取得完了: shape={df.shape}, "
        f"期間={df.index.min().date()} 〜 {df.index.max().date()}"
    )

    # 2) S3 からモデルとスケーラーパラメータを取得
    model_path, params = download_model_artifacts(s3, bucket)

    # 3) 特徴量作成
    X, current_close = build_features(df, params)

    # 4) ONNX 推論 (対数リターン)
    pred_log_return = run_inference(model_path, X, params)

    # 5) 結果整形
    predicted_close = current_close * float(np.exp(pred_log_return))
    predicted_return = float(np.exp(pred_log_return) - 1)
    prediction_sign = 1 if pred_log_return > 0 else -1
    # 対数リターンを sigmoid(k=100) で 0-1 に圧縮した擬似上昇確率
    # (日次対数リターンは概ね ±0.02 のオーダーなので、k=100 で 0.0〜1.0 に収まる)
    probability_up = float(1.0 / (1.0 + np.exp(-pred_log_return * 100.0)))

    record = {
        "target_date": target_date.isoformat(),
        "predicted_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "model_version": MODEL_VERSION,
        "ticker": TICKER,
        "prediction_sign": prediction_sign,
        "probability_up": round(probability_up, 4),
        "predicted_log_return": round(pred_log_return, 6),
        "predicted_return": round(predicted_return, 6),
        "predicted_close": round(predicted_close, 2),
        "current_close": round(current_close, 2),
        "as_of_date": df.index[-1].date().isoformat(),
    }

    print(f"推論結果: {record}")

    # 6) 月次 JSONL に追記
    key = append_monthly_jsonl(s3, bucket, target_date, record)
    print(f"S3 への書き込み完了: s3://{bucket}/{key}")

    # 7) 過去予測の精度評価 (実績が確定した未評価レコードを metrics/ に追記)
    target_col = params["target_col"]
    n_evaluated = evaluate_pending_predictions(s3, bucket, df, target_date, target_col)
    if n_evaluated == 0:
        print("精度評価: 新規評価対象なし")
    else:
        print(f"精度評価: 合計 {n_evaluated} 件を metrics/ に追記")


if __name__ == "__main__":
    main()
