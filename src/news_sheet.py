from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build

try:
    from email_drafts import extract_facility_name, extract_operator_company
    from gmail_api import SCOPES, SHEETS_SCOPES, get_credentials, has_runtime_token
    from main import article_dedupe_keys, clean_display_text, load_yaml
except ModuleNotFoundError:
    from src.email_drafts import extract_facility_name, extract_operator_company
    from src.gmail_api import SCOPES, SHEETS_SCOPES, get_credentials, has_runtime_token
    from src.main import article_dedupe_keys, clean_display_text, load_yaml


CONFIG_FILE = Path("config/news_sheet.yaml")
DEFAULT_COLUMNS = [
    "取得日",
    "分類",
    "ニュースタイトル",
    "URL",
    "施設名",
    "県名",
    "運営会社",
    "媒体",
    "重複キー",
]
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県",
    "茨城県", "栃木県", "群馬県", "埼玉県", "千葉県", "東京都", "神奈川県",
    "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県",
    "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県",
    "福岡県", "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県",
]


def load_news_sheet_config():
    if not CONFIG_FILE.exists():
        return {"enabled": False}

    config = load_yaml(CONFIG_FILE) or {}
    return config.get("news_sheet", {"enabled": False})


def get_sheets_service():
    return build("sheets", "v4", credentials=get_credentials(SCOPES + SHEETS_SCOPES))


def quote_sheet_name(name):
    return "'" + name.replace("'", "''") + "'"


def ensure_worksheet(service, spreadsheet_id, worksheet_name):
    spreadsheet = service.spreadsheets().get(
        spreadsheetId=spreadsheet_id,
        fields="sheets.properties.title",
    ).execute()
    sheet_names = {
        sheet.get("properties", {}).get("title", "")
        for sheet in spreadsheet.get("sheets", [])
    }

    if worksheet_name in sheet_names:
        return

    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "addSheet": {
                        "properties": {
                            "title": worksheet_name,
                        }
                    }
                }
            ]
        },
    ).execute()


def extract_prefecture(article):
    text = clean_display_text(
        " ".join([
            article.get("title", ""),
            article.get("summary", ""),
            article.get("source", ""),
        ])
    )

    for prefecture in PREFECTURES:
        if prefecture in text:
            return prefecture

    # Common news shorthand: city names without prefecture suffix.
    shorthand = {
        "大分": "大分県",
        "大阪": "大阪府",
        "京都": "京都府",
        "東京": "東京都",
        "北海道": "北海道",
    }

    for word, prefecture in shorthand.items():
        if word in text:
            return prefecture

    return ""


def build_row(article, judgement, columns):
    dedupe_keys = sorted(article_dedupe_keys(article))
    values = {
        "取得日": datetime.now().strftime("%Y-%m-%d"),
        "分類": judgement.get("category", ""),
        "ニュースタイトル": clean_display_text(article.get("title", "")),
        "URL": article.get("link", ""),
        "施設名": extract_facility_name(article),
        "県名": extract_prefecture(article),
        "運営会社": extract_operator_company(article),
        "媒体": article.get("source", ""),
        "重複キー": " / ".join(dedupe_keys),
    }
    return [values.get(column, "") for column in columns]


def get_existing_keys(service, spreadsheet_id, worksheet_name, columns):
    response = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{quote_sheet_name(worksheet_name)}!A:Z",
    ).execute()
    values = response.get("values", [])

    if not values:
        return set(), set(), False

    header = values[0]
    url_index = header.index("URL") if "URL" in header else None
    key_index = header.index("重複キー") if "重複キー" in header else None
    existing_urls = set()
    existing_keys = set()

    for row in values[1:]:
        if url_index is not None and url_index < len(row) and row[url_index]:
            existing_urls.add(row[url_index])
        if key_index is not None and key_index < len(row) and row[key_index]:
            existing_keys.update(key.strip() for key in row[key_index].split("/") if key.strip())

    return existing_urls, existing_keys, header[:len(columns)] == columns


def ensure_header(service, spreadsheet_id, worksheet_name, columns):
    existing_urls, existing_keys, header_ok = get_existing_keys(
        service,
        spreadsheet_id,
        worksheet_name,
        columns,
    )

    if not header_ok:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(worksheet_name)}!A1",
            valueInputOption="RAW",
            body={"values": [columns]},
        ).execute()

    return existing_urls, existing_keys


def append_news_rows(items):
    config = load_news_sheet_config()

    if not config.get("enabled"):
        return 0, 0

    if not has_runtime_token():
        print("Google token 未設定のため、スプレッドシート追記はスキップします。")
        return 0, 0

    spreadsheet_id = config.get("spreadsheet_id", "")
    worksheet_name = config.get("worksheet_name", "ニュース一覧")

    if not spreadsheet_id:
        print("spreadsheet_id 未設定のため、スプレッドシート追記はスキップします。")
        return 0, 0

    columns = config.get("columns") or DEFAULT_COLUMNS
    max_rows = int(config.get("max_rows_per_run", 30) or 0)
    service = get_sheets_service()
    ensure_worksheet(service, spreadsheet_id, worksheet_name)
    existing_urls, existing_keys = ensure_header(
        service,
        spreadsheet_id,
        worksheet_name,
        columns,
    )
    rows = []
    skipped_count = 0

    for item in items:
        if max_rows > 0 and len(rows) >= max_rows:
            break

        article = item["article"]
        dedupe_keys = article_dedupe_keys(article)

        if article.get("link", "") in existing_urls or dedupe_keys & existing_keys:
            skipped_count += 1
            continue

        rows.append(build_row(article, item["judgement"], columns))
        existing_urls.add(article.get("link", ""))
        existing_keys.update(dedupe_keys)

    if rows:
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=f"{quote_sheet_name(worksheet_name)}!A1",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows},
        ).execute()

    return len(rows), skipped_count
