import requests
import os
from dotenv import load_dotenv
load_dotenv()

refresh_token = os.getenv("SLACK_REFRESH_TOKEN")

resp = requests.post(
    "https://slack.com/api/tooling.tokens.rotate",
    headers={"Authorization": f"Bearer {refresh_token}"},
    data={"refresh_token": refresh_token},
)

data = resp.json()
print(data)
