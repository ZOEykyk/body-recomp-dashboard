import datetime as dt
import base64
import json
import os
import re
from io import StringIO
from pathlib import Path
from typing import Any
from urllib import error, request

import pandas as pd
import streamlit as st

DATA_FILE = "records.csv"
TARGET_WEIGHT = 82.0
DEFAULT_GITHUB_REPOSITORY = "ZOEykyk/body-recomp-dashboard"
DEFAULT_RECORDS_BRANCH = "main"
STEP_RANK_ORDER = ["S", "A", "B", "C", "D"]

REQUIRED_COLUMNS = [
    "日付",
    "体重",
    "歩数",
    "歩数ランク",
    "睡眠時間",
    "朝",
    "昼",
    "夜",
    "間食",
    "仕事中のドリンク",
    "推定摂取カロリー",
    "筋トレ有無",
    "筋トレ内容",
    "体調",
    "飲酒",
    "今日の採点",
    "コメント",
]

OPTIONAL_COLUMNS = [
    "朝カロリー(kcal)",
    "昼カロリー(kcal)",
    "夜カロリー(kcal)",
    "間食カロリー(kcal)",
    "ドリンクカロリー(kcal)",
    "ベンチプレス(kg)",
]

COLUMNS = REQUIRED_COLUMNS + OPTIONAL_COLUMNS

COLUMN_ALIASES = {
    "体重(kg)": "体重",
    "推定摂取カロリー(kcal)": "推定摂取カロリー",
    "摂取カロリー": "推定摂取カロリー",
    "筋トレ": "筋トレ有無",
    "トレーニング": "筋トレ有無",
    "ドリンク": "仕事中のドリンク",
    "仕事中ドリンク": "仕事中のドリンク",
}

TEXT_COLUMNS = [
    "歩数ランク",
    "朝",
    "昼",
    "夜",
    "間食",
    "仕事中のドリンク",
    "筋トレ有無",
    "筋トレ内容",
    "体調",
    "飲酒",
    "コメント",
]

NUMERIC_COLUMNS = [
    "体重",
    "歩数",
    "睡眠時間",
    "推定摂取カロリー",
    "今日の採点",
    "朝カロリー(kcal)",
    "昼カロリー(kcal)",
    "夜カロリー(kcal)",
    "間食カロリー(kcal)",
    "ドリンクカロリー(kcal)",
    "ベンチプレス(kg)",
]

CALORIE_KEYWORDS = {
    "赤飯おにぎり": 230,
    "おにぎり": 190,
    "鮭おにぎり": 190,
    "ツナマヨ": 230,
    "ご飯特盛": 500,
    "ご飯大盛": 380,
    "ご飯": 260,
    "白米": 260,
    "牛丼": 750,
    "牛丼大盛": 950,
    "定食": 900,
    "ハンバーグ定食": 1100,
    "ウマトマ": 900,
    "ハンバーグ": 520,
    "味噌汁": 180,
    "きつねうどん大": 700,
    "きつねうどん": 560,
    "肉ぶっかけうどん": 650,
    "ぶっかけうどん": 500,
    "うどん大": 650,
    "うどん": 450,
    "とり天": 180,
    "天ぷら盛り合わせ": 600,
    "天ぷら": 250,
    "そば": 420,
    "とろろそば": 480,
    "パスタ": 750,
    "ラーメン": 850,
    "カレー": 850,
    "唐揚げ": 350,
    "チキン": 200,
    "グリルチキン": 180,
    "サラダチキン": 120,
    "ゆでたまご": 80,
    "卵": 80,
    "プロテイン": 130,
    "オイコス": 100,
    "ヨーグルト": 100,
    "サラダ": 100,
    "菓子": 220,
    "チョコ": 250,
    "アイス": 260,
    "ジュース": 130,
    "トマトジュース": 70,
    "コーヒー": 20,
    "カフェラテ": 150,
    "ビール": 200,
}

MEAL_FALLBACK = {
    "朝": 300,
    "昼": 750,
    "夜": 850,
    "間食": 200,
    "仕事中のドリンク": 100,
}

JSON_KEY_ALIASES = {
    "日付": ["日付", "date", "record_date", "記録日"],
    "体重": ["体重", "体重(kg)", "weight", "weight_kg"],
    "歩数": ["歩数", "steps"],
    "歩数ランク": ["歩数ランク", "step_rank", "steps_rank"],
    "睡眠時間": ["睡眠時間", "睡眠", "sleep", "sleep_hours"],
    "朝": ["朝", "朝食", "breakfast"],
    "昼": ["昼", "昼食", "lunch"],
    "夜": ["夜", "夕食", "晩ごはん", "dinner"],
    "間食": ["間食", "snack", "snacks"],
    "仕事中のドリンク": ["仕事中のドリンク", "ドリンク", "work_drinks", "drinks"],
    "推定摂取カロリー": [
        "推定摂取カロリー",
        "推定摂取カロリー(kcal)",
        "摂取カロリー",
        "total_kcal",
        "calories",
        "kcal",
    ],
    "筋トレ有無": ["筋トレ有無", "筋トレ", "trained", "workout"],
    "筋トレ内容": ["筋トレ内容", "training_detail", "workout_detail"],
    "体調": ["体調", "condition", "health"],
    "飲酒": ["飲酒", "alcohol", "drinking"],
    "今日の採点": ["今日の採点", "採点", "score"],
    "コメント": ["コメント", "comment", "memo", "メモ"],
}

CONDITION_SCORES = {
    "最高": 5,
    "とても良い": 5,
    "良い": 4,
    "普通": 3,
    "やや悪い": 2,
    "悪い": 1,
    "不調": 1,
}


st.set_page_config(page_title="ボディリコンプ管理システム", page_icon="🏋️", layout="wide")
st.title("🏋️ ボディリコンプ管理システム")
st.caption("食事・体重・歩数・筋トレをCSVに保存し、減量ペースを分析します。")


class RecordValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


def get_config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, "")
    except Exception:
        value = ""
    return str(value or os.environ.get(name, default) or "").strip()


def github_storage_config() -> dict[str, str]:
    return {
        "token": get_config_value("GITHUB_TOKEN"),
        "repository": get_config_value("GITHUB_REPOSITORY", DEFAULT_GITHUB_REPOSITORY),
        "branch": get_config_value("RECORDS_CSV_BRANCH", DEFAULT_RECORDS_BRANCH),
        "path": get_config_value("RECORDS_CSV_PATH", DATA_FILE),
    }


def github_storage_enabled() -> bool:
    config = github_storage_config()
    return bool(config["token"] and config["repository"])


def github_request(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = github_storage_config()
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "body-recomp-dashboard",
        },
    )

    try:
        with request.urlopen(req, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 404:
            raise FileNotFoundError(detail) from exc
        raise RuntimeError(f"GitHub API error {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"GitHub APIに接続できませんでした: {exc.reason}") from exc


def github_file_url() -> str:
    config = github_storage_config()
    path = config["path"].replace("\\", "/")
    return f"https://api.github.com/repos/{config['repository']}/contents/{path}"


def read_github_records() -> tuple[str | None, str | None]:
    config = github_storage_config()
    url = f"{github_file_url()}?ref={config['branch']}"
    try:
        response = github_request("GET", url)
    except FileNotFoundError:
        return None, None

    content = base64.b64decode(response["content"]).decode("utf-8-sig")
    return content, response["sha"]


def write_github_records(csv_text: str) -> None:
    config = github_storage_config()
    _, sha = read_github_records()
    payload: dict[str, Any] = {
        "message": "Update records.csv from Streamlit app",
        "content": base64.b64encode(csv_text.encode("utf-8-sig")).decode("ascii"),
        "branch": config["branch"],
    }
    if sha:
        payload["sha"] = sha
    github_request("PUT", github_file_url(), payload)


def estimate_calories(text: str, meal_type: str = "") -> int:
    """Text-based rough calorie estimate. Explicit kcal values win."""
    if not text or not str(text).strip():
        return 0

    text = str(text)
    lowered = text.lower()
    total = 0

    explicit_numbers = re.findall(r"(\d+)\s*kcal", lowered)
    total += sum(int(number) for number in explicit_numbers)

    for keyword, kcal in CALORIE_KEYWORDS.items():
        count = text.count(keyword)
        if count > 0:
            total += count * kcal

    if total == 0 and meal_type in MEAL_FALLBACK:
        total = MEAL_FALLBACK[meal_type]

    return total


def final_kcal(auto_kcal: int, manual_kcal: int) -> int:
    return manual_kcal if manual_kcal > 0 else auto_kcal


def rank_steps(steps: Any) -> str:
    value = parse_number(steps, default=0)
    if value >= 12000:
        return "S"
    if value >= 10000:
        return "A"
    if value >= 8000:
        return "B"
    if value >= 6000:
        return "C"
    return "D"


def parse_number(value: Any, default: float = 0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)

    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return default
    return float(match.group(0))


def parse_number_for_record(field: str, value: Any, errors: list[str], default: float = 0) -> float:
    if value is None or value == "":
        return default
    parsed = parse_number(value, default=None)
    if parsed is None:
        errors.append(f"{field}: 数値として読み取れませんでした（入力値: {value}）")
        return default
    return parsed


def normalize_yes_no(value: Any) -> str:
    if isinstance(value, bool):
        return "あり" if value else "なし"
    text = str(value).strip()
    if not text:
        return "なし"
    lowered = text.lower()
    if lowered in {"true", "yes", "y", "1", "done"}:
        return "あり"
    if lowered in {"false", "no", "n", "0", "none"}:
        return "なし"
    if any(word in text for word in ["あり", "有", "実施", "した"]):
        return "あり"
    if any(word in text for word in ["なし", "無", "休み", "してない"]):
        return "なし"
    return text


def normalize_date(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        raise ValueError("日付がありません")
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"日付を読み取れませんでした: {value}")
    return parsed.normalize()


def get_nested_value(data: dict[str, Any], keys: list[str]) -> Any:
    for key in keys:
        if key in data:
            return data[key]

    meals = data.get("食事") or data.get("meals")
    if isinstance(meals, dict):
        for key in keys:
            if key in meals:
                return meals[key]

    training = data.get("筋トレ") or data.get("training") or data.get("workout")
    if isinstance(training, dict):
        for key in keys:
            if key in training:
                return training[key]

    return None


def normalize_record(raw: dict[str, Any], record_number: int = 1) -> dict[str, Any]:
    row = {column: "" for column in COLUMNS}
    errors: list[str] = []

    for column, aliases in JSON_KEY_ALIASES.items():
        value = get_nested_value(raw, aliases)
        if value is not None:
            row[column] = value

    try:
        row["日付"] = normalize_date(row["日付"])
    except ValueError as exc:
        errors.append(f"日付: {exc}")

    row["体重"] = parse_number_for_record("体重", row["体重"], errors)
    row["歩数"] = int(parse_number_for_record("歩数", row["歩数"], errors))
    row["歩数ランク"] = rank_steps(row["歩数"])
    row["睡眠時間"] = parse_number_for_record("睡眠時間", row["睡眠時間"], errors)
    row["筋トレ有無"] = normalize_yes_no(row["筋トレ有無"])
    row["今日の採点"] = int(parse_number_for_record("今日の採点", row["今日の採点"], errors))

    for column in ["朝", "昼", "夜", "間食", "仕事中のドリンク", "筋トレ内容", "体調", "飲酒", "コメント"]:
        row[column] = "" if row[column] is None else str(row[column])

    row["朝カロリー(kcal)"] = int(estimate_calories(row["朝"], "朝"))
    row["昼カロリー(kcal)"] = int(estimate_calories(row["昼"], "昼"))
    row["夜カロリー(kcal)"] = int(estimate_calories(row["夜"], "夜"))
    row["間食カロリー(kcal)"] = int(estimate_calories(row["間食"], "間食"))
    row["ドリンクカロリー(kcal)"] = int(estimate_calories(row["仕事中のドリンク"], "仕事中のドリンク"))

    estimated = parse_number_for_record("推定摂取カロリー", row["推定摂取カロリー"], errors)
    if estimated <= 0:
        estimated = sum(
            int(row[column])
            for column in [
                "朝カロリー(kcal)",
                "昼カロリー(kcal)",
                "夜カロリー(kcal)",
                "間食カロリー(kcal)",
                "ドリンクカロリー(kcal)",
            ]
        )
    row["推定摂取カロリー"] = int(estimated)

    if errors:
        raise RecordValidationError([f"{record_number}件目の{message}" for message in errors])

    return row


def normalize_columns(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    for old_column, new_column in COLUMN_ALIASES.items():
        if old_column in data.columns and new_column not in data.columns:
            data[new_column] = data[old_column]

    for column in COLUMNS:
        if column not in data.columns:
            data[column] = "" if column in TEXT_COLUMNS else 0

    return data[COLUMNS]


def load_data() -> pd.DataFrame:
    if github_storage_enabled():
        try:
            csv_text, _ = read_github_records()
            loaded = pd.read_csv(StringIO(csv_text)) if csv_text else pd.DataFrame(columns=COLUMNS)
        except Exception as exc:
            st.error(f"GitHub上のrecords.csvを読み込めませんでした: {exc}")
            loaded = pd.DataFrame(columns=COLUMNS)
    elif Path(DATA_FILE).exists():
        loaded = pd.read_csv(DATA_FILE)
    else:
        loaded = pd.DataFrame(columns=COLUMNS)

    loaded = normalize_columns(loaded)

    if not loaded.empty:
        loaded["日付"] = pd.to_datetime(loaded["日付"], errors="coerce")
        loaded = loaded.dropna(subset=["日付"])
        for column in NUMERIC_COLUMNS:
            loaded[column] = pd.to_numeric(loaded[column], errors="coerce").fillna(0)
        loaded["歩数"] = loaded["歩数"].astype(int)
        loaded["推定摂取カロリー"] = loaded["推定摂取カロリー"].astype(int)
        loaded["今日の採点"] = loaded["今日の採点"].astype(int)
        loaded["歩数ランク"] = loaded["歩数"].apply(rank_steps)
        loaded = loaded.sort_values("日付")

    return loaded


def csv_text_from_data(data: pd.DataFrame) -> str:
    data = normalize_columns(data)
    return data.to_csv(index=False)


def save_data(data: pd.DataFrame) -> None:
    data = normalize_columns(data)
    csv_text = csv_text_from_data(data)
    if github_storage_enabled():
        write_github_records(csv_text)

    data.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")


def upsert_records(data: pd.DataFrame, rows: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    data = normalize_columns(data)
    rows = normalize_columns(rows)

    data["_date_key"] = pd.to_datetime(data["日付"], errors="coerce").dt.strftime("%Y-%m-%d")
    rows["_date_key"] = pd.to_datetime(rows["日付"], errors="coerce").dt.strftime("%Y-%m-%d")
    existing_keys = set(data["_date_key"].dropna())
    updated = int(rows["_date_key"].isin(existing_keys).sum())
    added = int((~rows["_date_key"].isin(existing_keys)).sum())

    data = data[~data["_date_key"].isin(rows["_date_key"])]
    combined = pd.concat([data.drop(columns=["_date_key"]), rows.drop(columns=["_date_key"])], ignore_index=True)
    combined["歩数ランク"] = combined["歩数"].apply(rank_steps)
    combined = combined.sort_values("日付")
    return normalize_columns(combined), added, updated


def predict_target_date(data: pd.DataFrame, target_weight: float) -> str:
    if len(data) < 2:
        return "予測には2件以上の記録が必要です。"

    recent = data.tail(min(len(data), 14)).copy()
    first_weight = float(recent["体重"].iloc[0])
    latest_weight = float(recent["体重"].iloc[-1])
    days_elapsed = max((recent["日付"].iloc[-1] - recent["日付"].iloc[0]).days, 1)
    daily_pace = (first_weight - latest_weight) / days_elapsed

    if latest_weight <= target_weight:
        return f"すでに目標の{target_weight:.1f}kgを達成しています。"
    if daily_pace <= 0:
        return "直近データでは体重が減っていないため、到達日はまだ予測できません。"

    days_needed = int((latest_weight - target_weight) / daily_pace)
    target_date = dt.date.today() + dt.timedelta(days=days_needed)
    return f"現在ペースなら、約{days_needed}日後（{target_date.strftime('%Y/%m/%d')}）に{target_weight:.1f}kg到達見込みです。"


def alcohol_present(value: Any) -> bool:
    text = str(value).strip().lower()
    if not text:
        return False
    return text not in {"なし", "無", "no", "n", "false", "0"}


def condition_score(value: Any) -> float | None:
    text = str(value).strip()
    if not text:
        return None

    numeric = parse_number(text, default=None)
    if numeric is not None and 0 <= numeric <= 100:
        return numeric / 20 if numeric > 5 else numeric

    for keyword, score in CONDITION_SCORES.items():
        if keyword in text:
            return float(score)
    return None


def count_bench_90kg_sets(training_detail: Any) -> int:
    text = str(training_detail or "")
    if not text:
        return 0

    total = 0
    for match in re.finditer(r"90\s*kg\s*([0-9,\s]+)", text, flags=re.IGNORECASE):
        reps_text = match.group(1).strip(" ,")
        reps = [rep for rep in re.split(r"[,\s]+", reps_text) if rep.isdigit()]
        total += len(reps)

    if total > 0:
        return total
    return len(re.findall(r"90\s*kg", text, flags=re.IGNORECASE))


def weekly_label(series: pd.Series) -> pd.Series:
    return series.dt.to_period("W-SUN").apply(lambda period: f"{period.start_time:%Y/%m/%d}週")


df = load_data()
storage_config = github_storage_config()
if github_storage_enabled():
    st.caption(f"保存先: GitHub `{storage_config['repository']}/{storage_config['path']}` ({storage_config['branch']})")
else:
    st.caption("保存先: ローカル records.csv（Streamlit Cloudで永続化するにはGitHub保存用のsecretsを設定してください）")

st.header("今日の記録")
with st.form("daily_record_form"):
    basic_col1, basic_col2 = st.columns(2)
    with basic_col1:
        record_date = st.date_input("日付", value=dt.date.today())
        weight = st.number_input("朝の体重(kg)", min_value=40.0, max_value=150.0, value=85.0, step=0.1)
        sleep_hours = st.number_input("睡眠時間", min_value=0.0, max_value=24.0, value=7.0, step=0.5)
    with basic_col2:
        steps = st.number_input("歩数", min_value=0, max_value=50000, value=7000, step=500)
        condition = st.text_input("体調", placeholder="例：良い / やや疲れ / 眠い")
        alcohol = st.selectbox("飲酒", ["なし", "あり"])

    st.subheader("食べたもの")
    st.caption("自動推定がずれる場合は、右側のカロリー欄へ手入力してください。手入力がある場合はそちらを優先します。")

    meal_col1, meal_col2 = st.columns(2)
    with meal_col1:
        breakfast = st.text_area("朝", placeholder="例：トマトジュース、ゆでたまご", height=80)
        breakfast_kcal_manual = st.number_input("朝カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

        lunch = st.text_area("昼", placeholder="例：ぶっかけうどん、とり天1個", height=80)
        lunch_kcal_manual = st.number_input("昼カロリー 手入力（任意）", min_value=0, max_value=4000, value=0, step=50)

        snacks = st.text_area("間食", placeholder="例：菓子123kcal、オイコス", height=80)
        snacks_kcal_manual = st.number_input("間食カロリー 手入力（任意）", min_value=0, max_value=3000, value=0, step=50)

    with meal_col2:
        dinner = st.text_area("夜", placeholder="例：赤飯おにぎり、グリルチキン、オイコス", height=80)
        dinner_kcal_manual = st.number_input("夜カロリー 手入力（任意）", min_value=0, max_value=5000, value=0, step=50)

        work_drinks = st.text_area("仕事中のドリンク", placeholder="例：コーヒー、カフェラテ、プロテイン", height=80)
        drinks_kcal_manual = st.number_input("ドリンクカロリー 手入力（任意）", min_value=0, max_value=2000, value=0, step=50)

    st.subheader("筋トレ")
    trained = st.checkbox("筋トレした")
    training_detail = st.text_area(
        "筋トレ内容",
        placeholder="例：ベンチプレス 90kg 5,6,6,4 / 腹筋 10,10,5 / サイドレイズ 12kg 15回",
        height=120,
    )
    bench = st.number_input("ベンチプレス最高重量(kg)", min_value=0.0, max_value=250.0, value=90.0, step=2.5)

    score = st.slider("今日の採点", min_value=0, max_value=100, value=70, step=5)
    comment = st.text_area("コメント", placeholder="例：空腹感は少なめ。明日は歩数を増やす。", height=80)

    submitted = st.form_submit_button("CSVに保存する")

if submitted:
    breakfast_kcal = final_kcal(estimate_calories(breakfast, "朝"), breakfast_kcal_manual)
    lunch_kcal = final_kcal(estimate_calories(lunch, "昼"), lunch_kcal_manual)
    dinner_kcal = final_kcal(estimate_calories(dinner, "夜"), dinner_kcal_manual)
    snacks_kcal = final_kcal(estimate_calories(snacks, "間食"), snacks_kcal_manual)
    drinks_kcal = final_kcal(estimate_calories(work_drinks, "仕事中のドリンク"), drinks_kcal_manual)
    estimated_calories = breakfast_kcal + lunch_kcal + dinner_kcal + snacks_kcal + drinks_kcal

    new_row = pd.DataFrame(
        [
            {
                "日付": pd.to_datetime(record_date),
                "体重": weight,
                "歩数": steps,
                "歩数ランク": rank_steps(steps),
                "睡眠時間": sleep_hours,
                "朝": breakfast,
                "昼": lunch,
                "夜": dinner,
                "間食": snacks,
                "仕事中のドリンク": work_drinks,
                "推定摂取カロリー": estimated_calories,
                "筋トレ有無": "あり" if trained else "なし",
                "筋トレ内容": training_detail,
                "体調": condition,
                "飲酒": alcohol,
                "今日の採点": score,
                "コメント": comment,
                "朝カロリー(kcal)": breakfast_kcal,
                "昼カロリー(kcal)": lunch_kcal,
                "夜カロリー(kcal)": dinner_kcal,
                "間食カロリー(kcal)": snacks_kcal,
                "ドリンクカロリー(kcal)": drinks_kcal,
                "ベンチプレス(kg)": bench if trained else 0,
            }
        ]
    )
    df = pd.concat([df, new_row], ignore_index=True)
    df = df.sort_values("日付")
    try:
        save_data(df)
        st.success(f"CSVへ保存しました。合計カロリーは約{estimated_calories:,}kcalです。")
        st.write(
            f"朝 {breakfast_kcal:,}kcal / 昼 {lunch_kcal:,}kcal / 夜 {dinner_kcal:,}kcal / "
            f"間食 {snacks_kcal:,}kcal / ドリンク {drinks_kcal:,}kcal"
        )
    except Exception as exc:
        st.error(f"保存に失敗しました: {exc}")

st.header("ChatGPTログ貼り付け")
st.caption("1日分のJSONを貼り付けると、records.csvへ保存します。同じ日付があれば上書きし、なければ追加します。JSON配列なら複数日分も保存できます。")
chatgpt_log = st.text_area(
    "JSON形式のログ",
    placeholder='{"日付":"2026-06-28","体重":85.2,"歩数":8200,"歩数ランク":"B","睡眠時間":7.5,"朝":"プロテイン","昼":"うどん","夜":"鶏むね肉","間食":"オイコス","仕事中のドリンク":"コーヒー","推定摂取カロリー":1850,"筋トレ有無":true,"筋トレ内容":"ベンチプレス","体調":"良い","飲酒":"なし","今日の採点":85,"コメント":"よくできた"}',
    height=220,
)

if st.button("ChatGPTログをCSVに追加"):
    try:
        parsed = json.loads(chatgpt_log)
        records = parsed if isinstance(parsed, list) else [parsed]
        if not records:
            raise ValueError("JSON配列が空です。1件以上のログを入れてください。")
        if not all(isinstance(record, dict) for record in records):
            raise ValueError("JSONはオブジェクト、またはオブジェクトの配列にしてください。")

        normalized_records = []
        validation_errors = []
        for index, record in enumerate(records, start=1):
            try:
                normalized_records.append(normalize_record(record, record_number=index))
            except RecordValidationError as exc:
                validation_errors.extend(exc.errors)
        if validation_errors:
            raise RecordValidationError(validation_errors)

        imported_rows = pd.DataFrame(normalized_records)
        df, added_count, updated_count = upsert_records(df, imported_rows)
        save_data(df)
        st.success(
            f"{len(imported_rows)}件のChatGPTログをrecords.csvへ保存しました。"
            f"追加: {added_count}件 / 上書き: {updated_count}件"
        )
    except json.JSONDecodeError as exc:
        st.error(f"JSONの形式を確認してください: {exc}")
    except RecordValidationError as exc:
        st.error("読み取れなかった項目があります。")
        for message in exc.errors:
            st.write(f"- {message}")
    except Exception as exc:
        st.error(f"取り込みに失敗しました: {exc}")

if df.empty:
    st.info("まだ記録がありません。まずは今日の記録を保存してみましょう。")
else:
    df = df.sort_values("日付")
    latest = df.iloc[-1]
    df_for_chart = df.set_index("日付").copy()
    df_for_chart["7日平均体重"] = df_for_chart["体重"].rolling(window=7, min_periods=1).mean()
    df_for_chart["ベンチプレス90kgセット数"] = df_for_chart["筋トレ内容"].apply(count_bench_90kg_sets)
    df_for_chart["飲酒あり"] = df_for_chart["飲酒"].apply(alcohol_present)
    df_for_chart["体調スコア"] = df_for_chart["体調"].apply(condition_score)
    df_for_chart["週"] = weekly_label(df_for_chart.index.to_series())

    today = pd.Timestamp(dt.date.today())
    week_start = today - pd.Timedelta(days=today.weekday())
    this_week = df_for_chart[df_for_chart.index >= week_start]
    condition_average = df_for_chart["体調スコア"].dropna().mean()

    st.header("ダッシュボード")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最新体重", f"{latest['体重']:.1f}kg")
    c2.metric("今週の平均体重", f"{this_week['体重'].mean():.1f}kg" if not this_week.empty else "-")
    c3.metric("7日平均体重", f"{df_for_chart['7日平均体重'].iloc[-1]:.1f}kg")
    c4.metric("平均歩数", f"{df['歩数'].mean():,.0f}歩")

    c5, c6, c7, c8 = st.columns(4)
    c5.metric("平均摂取カロリー", f"{df['推定摂取カロリー'].mean():,.0f}kcal")
    c6.metric("筋トレ回数", f"{int((df['筋トレ有無'] == 'あり').sum())}回")
    c7.metric("飲酒ありの日数", f"{int(df_for_chart['飲酒あり'].sum())}日")
    c8.metric("体調平均", f"{condition_average:.1f}/5" if pd.notna(condition_average) else "-")

    st.subheader("82kg到達予測")
    st.info(predict_target_date(df, TARGET_WEIGHT))

    st.subheader("体重推移")
    st.line_chart(df_for_chart[["体重", "7日平均体重"]])

    st.subheader("摂取カロリー推移")
    st.bar_chart(df_for_chart[["推定摂取カロリー"]])

    st.subheader("歩数推移")
    st.bar_chart(df_for_chart[["歩数"]])

    st.subheader("歩数ランク別の日数")
    step_rank_counts = df["歩数ランク"].value_counts().reindex(STEP_RANK_ORDER, fill_value=0)
    st.bar_chart(step_rank_counts)

    st.subheader("週ごとの筋トレ回数")
    weekly_training = (
        df_for_chart.assign(筋トレ回数=(df_for_chart["筋トレ有無"] == "あり").astype(int))
        .groupby("週")["筋トレ回数"]
        .sum()
    )
    st.bar_chart(weekly_training)

    st.subheader("ベンチプレス90kgセット数の推移")
    st.line_chart(df_for_chart[["ベンチプレス90kgセット数"]])

    st.subheader("直近の食事・筋トレ内容")
    st.write(f"朝: {latest.get('朝', '')} / {int(latest.get('朝カロリー(kcal)', 0)):,}kcal")
    st.write(f"昼: {latest.get('昼', '')} / {int(latest.get('昼カロリー(kcal)', 0)):,}kcal")
    st.write(f"夜: {latest.get('夜', '')} / {int(latest.get('夜カロリー(kcal)', 0)):,}kcal")
    st.write(f"間食: {latest.get('間食', '')} / {int(latest.get('間食カロリー(kcal)', 0)):,}kcal")
    st.write(
        f"仕事中のドリンク: {latest.get('仕事中のドリンク', '')} / "
        f"{int(latest.get('ドリンクカロリー(kcal)', 0)):,}kcal"
    )
    st.write(f"筋トレ: {latest.get('筋トレ有無', '')} / {latest.get('筋トレ内容', '')}")
    st.write(f"体調: {latest.get('体調', '')} / 飲酒: {latest.get('飲酒', '')} / 採点: {latest.get('今日の採点', 0)}")
    st.write(f"コメント: {latest.get('コメント', '')}")

    st.subheader("記録一覧")
    st.dataframe(df, use_container_width=True)

    csv = df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button("CSVダウンロード", csv, "body_recomp_records.csv", "text/csv")

st.caption("注意: カロリーは概算です。正確にしたい日は手入力欄を使ってください。")
