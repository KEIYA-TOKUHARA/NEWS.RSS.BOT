from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

try:
    from gmail_api import CREDENTIALS_FILE, SCOPES, TOKEN_FILE
except ModuleNotFoundError:
    from src.gmail_api import CREDENTIALS_FILE, SCOPES, TOKEN_FILE


def main():
    if not CREDENTIALS_FILE.exists():
        raise RuntimeError(f"{CREDENTIALS_FILE} がありません。")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
    creds = flow.run_local_server(port=0)

    Path(TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
    print(f"{TOKEN_FILE} を作成しました。")


if __name__ == "__main__":
    main()
