import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone

import boto3
import numpy as np
import onnxruntime as ort
from botocore.exceptions import ClientError

TICKER = "n225"
MODEL_VERSION = "2026-04-01"
JST = timezone(timedelta(hours=9))


def get_target_date() -> date:
    """環境変数 TARGET_DATE (YYYY-MM-DD) を読む。未設定なら今日（JST）を返す。"""
    raw = os.getenv("TARGET_DATE", "").strip()
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now(JST).date()


def build_features(d: date) -> np.ndarray:
    """日付から5次元特徴量ベクトルを生成する。"""
    day_of_year = d.timetuple().tm_yday / 365.0
    day_of_week = d.weekday() / 6.0
    month = d.month / 12.0
    week_of_year = int(d.strftime("%W")) / 52.0
    is_month_start = float(d.day <= 5)
    return np.array(
        [[day_of_year, day_of_week, month, week_of_year, is_month_start]],
        dtype=np.float32,
    )


def download_model(s3: boto3.client, bucket: str) -> str:
    """S3からONNXモデルを /tmp に落として、そのパスを返す。"""
    key = f"models/{TICKER}.{MODEL_VERSION}.onnx"
    tmp = tempfile.NamedTemporaryFile(suffix=".onnx", delete=False)
    print(f"モデルをS3から取得: s3://{bucket}/{key}")
    s3.download_fileobj(bucket, key, tmp)
    tmp.close()
    return tmp.name


def run_inference(model_path: str, features: np.ndarray) -> float:
    sess = ort.InferenceSession(model_path)
    result = sess.run(None, {"features": features})
    return float(result[0][0][0])


def append_to_s3(s3: boto3.client, bucket: str, record: dict) -> None:
    """S3のJSONLファイルに1行追記する（既存行は保持する）。"""
    key = f"predictions/{TICKER}.jsonl"

    try:
        resp = s3.get_object(Bucket=bucket, Key=key)
        existing = resp["Body"].read().decode("utf-8").rstrip("\n")
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            existing = ""
        else:
            raise

    new_line = json.dumps(record, ensure_ascii=False)
    content = (existing + "\n" + new_line).lstrip("\n") + "\n"

    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=content.encode("utf-8"),
        ContentType="application/jsonlines",
    )


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

    model_path = download_model(s3, bucket)
    features = build_features(target_date)
    prob_up = run_inference(model_path, features)
    prediction_sign = 1 if prob_up >= 0.5 else -1

    record = {
        "target_date": target_date.isoformat(),
        "predicted_at": datetime.now(JST).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "model_version": MODEL_VERSION,
        "ticker": TICKER,
        "prediction_sign": prediction_sign,
        "probability_up": round(prob_up, 4),
    }

    print(f"推論結果: {record}")
    append_to_s3(s3, bucket, record)
    print(f"S3への書き込み完了: predictions/{TICKER}.jsonl")


if __name__ == "__main__":
    main()
