import os, subprocess, sys
from post_to_slack import post

out = subprocess.check_output([sys.executable, "src/fetch_and_print.py"], text=True)
lines = [x for x in out.splitlines() if x.strip()]

if "SLACK_WEBHOOK_URL" in os.environ and lines:
    post(lines)
else:
    print("\n".join(lines))
