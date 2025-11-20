from __future__ import annotations

import re


RULES = [
    # OT/加班相關（優先匹配具體場景）
    (re.compile(r"OT\s*計算", re.IGNORECASE), "加班費 延長工時 計算"),
    (re.compile(r"OT\s*工資", re.IGNORECASE), "加班費 工資"),
    (re.compile(r"OT\s*報酬", re.IGNORECASE), "加班費 報酬"),
    (re.compile(r"OT\s*薪資", re.IGNORECASE), "加班費 工資"),
    (re.compile(r"\bOT\b", re.IGNORECASE), "加班 延長工時"),  # 最後才做泛化
    (re.compile(r"加班報酬"), "加班費 報酬"),
    (re.compile(r"延時報酬"), "加班費 延長工時 報酬"),
    (re.compile(r"工時報酬"), "加班費 工時 報酬"),
    (re.compile(r"時薪\s*加成"), "加班費 工資"),
    (re.compile(r"加班\s*給付"), "加班費 報酬"),
    # 工資扣除
    (re.compile(r"薪資\s*扣款"), "工資 扣除"),
    # 工時上限
    (re.compile(r"每月\s*工時\s*上限"), "延長工時 上限"),
    # 特休
    (re.compile(r"特休\s*計算"), "特別休假 計算"),
]


def rewrite(q: str) -> str:
    s = q.strip()
    for pat, rep in RULES:
        s = pat.sub(rep, s)
    return s
