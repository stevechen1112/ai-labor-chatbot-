from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request


def http_post_json(url: str, data: dict, timeout=60):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read().decode("utf-8", "ignore"))


def run_basic(base: str, w_vec=0.6, w_lex=0.4):
    samples = [
        "加班費 計算",
        "特休 工資",
        "工時 調整",
        "勞資爭議 調解",
        "育嬰 留職停薪",
    ]
    ok = 0
    total = 0
    failures = []
    for q in samples:
        total += 1
        payload = {"query": q, "top_k": 5, "use_llm": False, "use_rerank": False, "w_vec": w_vec, "w_lex": w_lex}
        try:
            s, data = http_post_json(base + "/query", payload)
            cites = data.get("citations", [])
            passed = s == 200 and isinstance(cites, list) and len(cites) > 0
            ok += 1 if passed else 0
            first = cites[0].get("citation") if cites else ""
            if not passed:
                failures.append({"query": q, "status": s, "cites": len(cites)})
            print(f"[BASIC] {q} -> status={s} cites={len(cites)} first={first}")
        except Exception as e:
            failures.append({"query": q, "error": str(e)})
            print(f"[BASIC] {q} -> ERROR {e}")
    return {"passed": ok, "total": total, "failures": failures}


def run_file(base: str, path: Path, w_vec=0.6, w_lex=0.4):
    data = json.loads(path.read_text(encoding="utf-8"))
    suites = data.get("suites", [])
    total = 0
    ok = 0
    # confusion matrix: expected keyword -> actual top1 title count
    from collections import defaultdict
    conf = defaultdict(lambda: defaultdict(int))
    suite_reports = []
    for suite in suites:
        name = suite.get("name", "")
        queries = suite.get("queries", [])
        expect_any = suite.get("expect_any", [])
        s_ok = 0
        s_total = 0
        s_fail = []
        for q in queries:
            s_total += 1
            total += 1
            payload = {"query": q, "top_k": 5, "use_llm": False, "use_rerank": False, "w_vec": w_vec, "w_lex": w_lex}
            try:
                status, resp = http_post_json(base + "/query", payload)
                cites = resp.get("citations", [])
                titles = [c.get("title", "") for c in cites]
                cond_cites = status == 200 and len(cites) > 0
                cond_expect = True
                if expect_any:
                    cond_expect = any(any(exp in t for t in titles) for exp in expect_any)
                passed = cond_cites and cond_expect
                s_ok += 1 if passed else 0
                ok += 1 if passed else 0
                first = cites[0].get("citation") if cites else ""
                top_title = cites[0].get("title") if cites else ""
                # accumulate confusion using first expected keyword
                expected_key = expect_any[0] if expect_any else "(any)"
                conf[expected_key][top_title] += 1
                if not passed:
                    s_fail.append({
                        "query": q,
                        "status": status,
                        "cites": len(cites),
                        "titles": titles[:5],
                        "first": first,
                        "expect_any": expect_any,
                        "cond_cites": cond_cites,
                        "cond_expect": cond_expect,
                    })
                print(f"[{name}] {q} -> status={status} cites={len(cites)} match={cond_expect} first={first}")
            except Exception as e:
                s_fail.append({"query": q, "error": str(e)})
                print(f"[{name}] {q} -> ERROR {e}")
        suite_reports.append({"name": name, "passed": s_ok, "total": s_total, "failures": s_fail})
        print(f"SUITE '{name}' PASSED {s_ok}/{s_total}")
    # serialize conf
    conf_out = {ek: dict(v) for ek, v in conf.items()}
    return {"passed": ok, "total": total, "suites": suite_reports, "confusion": conf_out}


def main():
    ap = argparse.ArgumentParser(description="Regression suite for /query with fixed variants")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--cases", default=str(Path("data/tests/queries.json")))
    ap.add_argument("--out", default=str(Path("data/index/regression_report.json")))
    ap.add_argument("--fail-out", dest="fail_out", default=str(Path("data/index/regression_failures.json")))
    ap.add_argument("--w-vec", dest="w_vec", type=float, default=0.6)
    ap.add_argument("--w-lex", dest="w_lex", type=float, default=0.4)
    args = ap.parse_args()

    basic = run_basic(args.base, args.w_vec, args.w_lex)
    p = Path(args.cases)
    suites = {}
    failures = []
    if p.exists():
        suites = run_file(args.base, p, args.w_vec, args.w_lex)
        # collect flat failures list
        for s in suites.get("suites", []):
            for f in s.get("failures", []):
                failures.append({"suite": s.get("name"), **f})
    else:
        print(f"No cases file: {p}")

    report = {"basic": basic, "suites": suites, "weights": {"w_vec": args.w_vec, "w_lex": args.w_lex}}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote report -> {out}")
    # write failures
    failp = Path(args.fail_out)
    failp.parent.mkdir(parents=True, exist_ok=True)
    failp.write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote failures -> {failp}")


if __name__ == "__main__":
    main()
