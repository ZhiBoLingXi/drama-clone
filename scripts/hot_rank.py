#!/usr/bin/env python3
"""抓红果短剧热播榜，给出外壳（选题）时当灵感用。只用标准库。

  hot_rank.py --out <项目目录>/market            抓 https://hongguoduanju.com/rank/hot-drama
  hot_rank.py --html 页面.html --out market/      宿主不让脚本联网时：用自己的网页工具把页面存下来再解析

写出 market/hot-YYYYMMDD.json（每部剧一条）和 market/hot-YYYYMMDD.md（给模型读的一页摘要）。
页面的 robots.txt 允许 /rank/；一次只抓一页，不翻详情页。
退出码：0 成功；1 抓取或解析失败（照提示处理，不要编榜单）。
"""
import argparse
import datetime
import html as H
import json
import os
import re
import sys
import urllib.request
from collections import Counter

URL = "https://hongguoduanju.com/rank/hot-drama"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
SEASON = re.compile(r"(第[一二三四五六七八九十0-9]+季|[0-9]+$|一季$|完结篇|第[一二三四五六七八九十0-9]+部)")


def fetch():
    req = urllib.request.Request(URL, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="ignore")


def num(s):
    """「8209万」→ 82090000；「9.6」→ 9.6。"""
    if not s:
        return None
    m = re.match(r"([\d.]+)\s*(万|亿)?", s)
    if not m:
        return None
    v = float(m.group(1)) * {"万": 1e4, "亿": 1e8}.get(m.group(2), 1)
    return int(v) if m.group(2) else v


def text(s):
    return H.unescape(re.sub(r"<[^>]+>", "", s)).strip()


def parse(page):
    """每部剧以 <h2 id="rank-title-<series_id>"> 开头切块。类名带哈希后缀（pc-title-LHxn_J），只认前缀，改版换哈希也能读。"""
    rank_of = {}
    for m in re.finditer(r'"position":(\d+),"name":"[^"]*","url":"[^"]*series_id=(\d+)', page):
        rank_of[m.group(2)] = int(m.group(1))
    heads = list(re.finditer(r'<h2 id="rank-title-(\d+)"[^>]*>(.*?)</h2>', page, re.S))
    out = []
    for k, h in enumerate(heads):
        block = page[h.end(): heads[k + 1].start() if k + 1 < len(heads) else h.end() + 6000]
        g = lambda rx: (lambda m: m.group(1) if m else None)(re.search(rx, block, re.S))
        cats = [c.strip() for c in text(g(r'class="pc-categories-[^"]*">(.*?)</p>') or "").split("·") if c.strip()]
        title = text(h.group(2))
        sid = h.group(1)
        out.append({
            "rank": rank_of.get(sid, k + 1), "title": title, "series": SEASON.sub("", title).strip("，, "),
            "seriesId": sid, "url": f"https://hongguoduanju.com/detail?series_id={sid}",
            "heat": num(g(r">([\d.]+万?亿?)热度")), "score": num(g(r">([\d.]+)分</li>")),
            "favorites": num(g(r"<li>([\d.]+万?)收藏")), "likes": num(g(r"<li>([\d.]+万?)点赞")),
            "form": cats[0] if cats else None, "genre": cats[1] if len(cats) > 1 else None, "leads": cats[2:],
            "synopsis": text(g(r'class="pc-description-[^"]*">(.*?)</p>') or ""),
        })
    return sorted(out, key=lambda x: x["rank"])


def summary(items, day):
    """给模型读的一页：赛道冷热、形式、多季 IP、每部剧一行。灵感只取赛道、设定元素、标题句式，不取人名和具体桥段。"""
    genre = Counter(x["genre"] for x in items if x["genre"])
    form = Counter(x["form"] for x in items if x["form"])
    multi = Counter(x["series"] for x in items)
    sequel = [x["title"] for x in items if SEASON.search(x["title"])]
    w = lambda x: f"{x / 1e4:.0f}万" if x and x >= 1e4 else (str(x) if x else "?")
    lines = [f"# 红果热播榜 {day}", "",
             f"来源：{URL}，共 {len(items)} 部。热度、评分、收藏、点赞照页面原样抄。", "",
             "## 一眼看懂", "",
             f"- **题材**：{'、'.join(f'{k} {v}' for k, v in genre.most_common())}",
             f"- **形式**：{'、'.join(f'{k} {v}' for k, v in form.most_common())}",
             f"- **上榜的续季**（观众追着看的设定，已被验证）：{'、'.join(sequel) or '无'}",
             f"- **同一部剧多季同时上榜**：{'、'.join(k for k, v in multi.items() if v > 1) or '无'}", "",
             "## 榜单", "", "| # | 剧名 | 形式 | 题材 | 热度 | 评分 | 收藏 | 一句话 |", "|---|---|---|---|---|---|---|---|"]
    for x in items:
        syn = x["synopsis"].replace("|", "/")
        lines.append(f"| {x['rank']} | {x['title']} | {x['form'] or ''} | {x['genre'] or ''} | {w(x['heat'])} | {x['score'] or ''} | "
                     f"{w(x['favorites'])} | {syn[:60]}{'…' if len(syn) > 60 else ''} |")
    lines += ["", "## 怎么用", "",
              "- 看赛道冷热和形式分布，判断原剧的赛道现在热不热、新外壳往哪个题材靠更有量。",
              "- 取**设定元素**（重生年代、修仙、末日求生、考试副本、和离带娃……）和**标题句式**（身份反差、数字、「谁还……」），不取人名、剧名和具体桥段：这些是别人的作品。",
              "- 每个外壳候选写一行「榜单依据」：参考了第几名的哪一点，或者为什么故意避开榜上已经扎堆的题材。"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="抓红果热播榜，给外壳选题当灵感")
    ap.add_argument("--out", required=True, help="输出目录，一般是 <项目目录>/market")
    ap.add_argument("--html", help="已经存下来的页面 HTML；不给就联网抓")
    args = ap.parse_args()
    try:
        page = open(args.html, encoding="utf-8", errors="ignore").read() if args.html else fetch()
    except Exception as e:  # 网络被宿主拦了、超时、被反爬，都走这里
        print(json.dumps({"error": f"抓不到榜单：{e}",
                          "next": f"用你自己的网页工具打开 {URL}，把页面 HTML 存成文件，再跑 --html <文件>；"
                                  "网页工具也用不了，就在 market/unavailable.txt 写一句原因，告诉用户这次没有榜单参考，继续出外壳"},
                         ensure_ascii=False))
        return 1
    items = parse(page)
    if len(items) < 5:
        print(json.dumps({"error": f"只解析出 {len(items)} 部剧，页面可能改版了或者是验证页",
                          "next": "不要凭记忆编榜单。在 market/unavailable.txt 写明原因，告诉用户，继续出外壳"}, ensure_ascii=False))
        return 1
    day = datetime.date.today().strftime("%Y%m%d")
    os.makedirs(args.out, exist_ok=True)
    jp, mp = os.path.join(args.out, f"hot-{day}.json"), os.path.join(args.out, f"hot-{day}.md")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump({"source": URL, "fetchedAt": datetime.datetime.now().isoformat(timespec="seconds"), "items": items},
                  f, ensure_ascii=False, indent=1)
    with open(mp, "w", encoding="utf-8") as f:
        f.write(summary(items, day))
    print(json.dumps({"count": len(items), "json": jp, "summary": mp, "read": f"读 {mp}，再出外壳候选"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
