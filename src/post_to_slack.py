import os, requests

WEBHOOK = os.environ["SLACK_WEBHOOK_URL"]

def post(lines):
    if not lines:
        return
    blocks = []
    for t in lines[:20]:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": t}})
        blocks.append({"type": "divider"})
    payload = {"text": "宿泊業界ニュース（キーワード一致）", "blocks": blocks}
    r = requests.post(WEBHOOK, json=payload, timeout=15)
    r.raise_for_status()
