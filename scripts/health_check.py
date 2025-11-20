from __future__ import annotations

import json
import urllib.request
import urllib.parse
import argparse


def http_get(url: str):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def http_post(url: str, data: dict):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def main(base: str = "http://127.0.0.1:8000"):
    try:
        s, b = http_get(base + "/warmup")
        print("WARMUP", s, b[:120])
    except Exception as e:
        print("WARMUP error", e)
    try:
        s, b = http_get(base + "/health")
        print("HEALTH", s, b[:120])
    except Exception as e:
        print("HEALTH error", e)
    try:
        # Build encoded URL for article lookup
        qs = urllib.parse.urlencode({"law": "勞動基準法", "no": "32"})
        s, b = http_get(base + "/article?" + qs)
        print("ARTICLE", s)
    except Exception as e:
        print("ARTICLE error", e)
    try:
        s, b = http_post(base + "/query", {"query": "加班費 計算", "top_k": 3, "use_llm": False, "use_rerank": False})
        print("QUERY", s, b[:160])
    except Exception as e:
        print("QUERY error", e)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    main(args.base)
