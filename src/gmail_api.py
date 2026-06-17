import base64
import json
import os
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS_FILE = Path("credentials.json")
TOKEN_FILE = Path("token.json")


def has_runtime_token():
    return bool(os.environ.get("GMAIL_TOKEN_JSON")) or TOKEN_FILE.exists()


def load_json_from_env_or_file(env_name, path):
    raw_value = os.environ.get(env_name)

    if raw_value:
        return json.loads(raw_value)

    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def get_credentials(scopes=None):
    scopes = scopes or SCOPES
    token_info = load_json_from_env_or_file("GMAIL_TOKEN_JSON", TOKEN_FILE)

    if not token_info:
        raise RuntimeError("Gmail token がありません。先に token.json を作成してください。")

    creds = Credentials.from_authorized_user_info(token_info, scopes)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    if not creds.valid:
        raise RuntimeError("Gmail token が無効です。再認証してください。")

    return creds


def get_gmail_service():
    return build("gmail", "v1", credentials=get_credentials())


def encode_message(to, subject, body):
    message = MIMEText(body, "plain", "utf-8")
    message["To"] = to
    message["Subject"] = subject
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    return encoded


def find_label_id(service, label_name):
    response = service.users().labels().list(userId="me").execute()

    for label in response.get("labels", []):
        if label.get("name") == label_name:
            return label.get("id")

    return None


def ensure_label(service, label_name):
    label_id = find_label_id(service, label_name)

    if label_id:
        return label_id

    response = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return response["id"]


def apply_label_to_message(service, message_id, label_id):
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"addLabelIds": [label_id]},
    ).execute()


def create_draft(to, subject, body, label_name=None):
    service = get_gmail_service()
    raw_message = encode_message(to, subject, body)
    draft = service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw_message}},
    ).execute()

    message_id = draft.get("message", {}).get("id")

    if label_name and message_id:
        label_id = ensure_label(service, label_name)
        apply_label_to_message(service, message_id, label_id)

    return draft
