import configparser
import json
import sys

import requests

cfg = configparser.ConfigParser()
cfg.read("config.ini", encoding="utf-8")
llm = cfg["llm"]

messages = []

try:
    while True:
        question = input("你: ")
        messages.append({"role": "user", "content": question})

        r = requests.post(
            f"{llm['base_url'].rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {llm['api_key']}"},
            json={
                "model": llm["model"],
                "messages": messages,
                "stream": True,
            },
            stream=True,
            timeout=120,
        )
        answer = []
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"].get("content")
            if delta:
                answer.append(delta)
                sys.stdout.write(delta)
                sys.stdout.flush()
        messages.append({"role": "assistant", "content": "".join(answer)})
        print()
except KeyboardInterrupt:
    print()