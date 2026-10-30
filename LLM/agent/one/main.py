import configparser
import json
import sys

import requests

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
llm = cfg["llm"]
question = input("你: ")

r = requests.post(
    f"{llm['base_url'].rstrip('/')}/chat/completions",
    headers={"Authorization": f"Bearer {llm['api_key']}"},
    json={
        "model": llm["model"],
        "messages": [{"role": "user", "content": question}],
        "stream": True,
    },
    stream=True,
    timeout=120,
)
for line in r.iter_lines(decode_unicode=True):
    if not line or not line.startswith("data: "):
        continue
    data = line[6:]
    if data == "[DONE]":
        break
    delta = json.loads(data)["choices"][0]["delta"].get("content")
    if delta:
        sys.stdout.write(delta)
        sys.stdout.flush()
print()