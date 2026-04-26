import os
from datetime import date, datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def get_target_date() -> date:
    """環境変数 TARGET_DATE (YYYY-MM-DD) を読む。未設定なら今日（JST）を返す。"""
    raw = os.getenv("TARGET_DATE", "").strip()
    if raw:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    return datetime.now(JST).date()


def main() -> None:
    target_date = get_target_date()
    print(f"推論対象日付: {target_date}")

    # TODO: モデルの取得・推論・S3への書き込みを実装する
    # 参考実装: run.sample.py


if __name__ == "__main__":
    main()
