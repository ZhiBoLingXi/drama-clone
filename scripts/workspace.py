"""原剧工作区和裂变变体：一部原剧只拉一次，裂变出的每部新剧一个文件夹。只用标准库。

<根目录>/<原剧名>/                 原剧工作区（init 建）
  source/                          原剧，只拉一次，所有变体共用
    template.json                  模板 id、库、剧名、拉了哪些集
    extract/                       source 命令的产物（raw/ source/ beats/ dialogue/ manifest.json corpus.txt）
    beat-sheet.json beats-all.json fingerprints-all.json
  market/hot-YYYYMMDD.md           热播榜，一周内所有变体共用
  shells.md                        外壳候选，每轮一节，用户选定的写「选定：候选X」
  variants.json                    已立项的变体登记
  V01-<新剧名>/                     一个变体一个文件夹（variant 建）
    variant.json bible.md season-map.md cast.json approved-sample.txt
    out/                           任务包、正文骨架、实现表
    delivery/                      交付件（deliver 写），命名见 references/naming.md
"""
import datetime
import glob
import json
import os
import re

ILLEGAL = re.compile(r'[\\/:*?"<>|\s]+')
HAN = re.compile("[一-鿿]")


def _load(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _dump(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def safe(name):
    """文件夹名：去掉书名号和文件系统不认的字符。中文冒号、逗号保留。"""
    return ILLEGAL.sub("-", name.strip().strip("《》")).strip("-")


def layout(P):
    """三种目录都认：变体目录（有 variant.json）、原剧工作区（有 source/）、老的单项目目录（extract/ 直接在里面）。"""
    P = os.path.abspath(P)
    if os.path.exists(os.path.join(P, "variant.json")):
        mode, W = "variant", os.path.dirname(P)
    elif os.path.isdir(os.path.join(P, "source")):
        mode, W = "workspace", P
    else:
        mode, W = "legacy", P
    src = os.path.join(W, "source") if mode != "legacy" else P
    ex = os.path.join(src, "extract")
    return {"mode": mode, "P": P, "W": W, "src": src, "ex": ex,
            "base": os.path.join(src, "beat-sheet.json"), "ba": os.path.join(src, "beats-all.json"),
            "fp": os.path.join(src, "fingerprints-all.json"), "market": os.path.join(W, "market"),
            "cast": os.path.join(P, "cast.json") if mode == "variant" else os.path.join(ex, "cast.json"),
            "out": os.path.join(P, "out"), "delivery": os.path.join(P, "delivery"),
            "shells": os.path.join(W, "shells.md"), "variants": os.path.join(W, "variants.json")}


def variants(W):
    return _load(os.path.join(W, "variants.json"), {"variants": []})["variants"]


def find_workspace(root, title, template_id=None):
    """根目录下已经有这部原剧的工作区就复用：先按模板 id 找，再按原剧名找。"""
    for p in glob.glob(os.path.join(root, "*", "source", "template.json")):
        t = _load(p, {})
        if (template_id and t.get("templateId") == template_id) or safe(t.get("title", "")) == safe(title):
            return os.path.dirname(os.path.dirname(p))
    return None


def cmd_init(args):
    """建原剧工作区，或者找到已有的。已经拉过、提取过的，告诉调用方不用再拉。"""
    os.makedirs(args.root, exist_ok=True)
    W = find_workspace(args.root, args.source_title, args.template_id)
    created = W is None
    if created:
        W = os.path.join(os.path.abspath(args.root), safe(args.source_title))
        for d in ("source/extract/raw", "market"):
            os.makedirs(os.path.join(W, d), exist_ok=True)
    tp = os.path.join(W, "source", "template.json")
    t = _load(tp, {})
    t.update({k: v for k, v in (("title", args.source_title.strip("《》")), ("templateId", args.template_id),
                                ("library", args.library)) if v and not t.get(k)})
    t.setdefault("createdAt", datetime.date.today().isoformat())
    _dump(tp, t)
    L = layout(W)
    raw = sorted(os.path.basename(p) for p in glob.glob(os.path.join(L["ex"], "raw", "*.json")))
    extracted = os.path.exists(os.path.join(L["ex"], "manifest.json"))
    vs = variants(W)
    print(json.dumps({
        "workspace": W, "created": created, "template": t,
        "pulled": raw, "extracted": extracted,
        "variants": [f"{v['id']} 《{v['title']}》 {v.get('status', '')}" for v in vs],
        "todo": ("这部原剧已经拉过、提取过，不要再拉模板。" if extracted else
                 ("已经拉了一部分窗口（见 pulled），只补缺的窗口，拉过的不要重拉。" if raw else
                  "还没拉。照 SKILL.md「输入从哪来」按集窗口拉模板，存到 source/extract/raw/。")),
        "next": f"python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clone_check.py')} next --project {W}"},
        ensure_ascii=False, indent=1))
    return 0


def hot_titles(W):
    """最近一份热播榜里的剧名，新剧名不能和它们撞。"""
    ps = sorted(glob.glob(os.path.join(W, "market", "hot-*.json")))
    return [x["title"] for x in (_load(ps[-1], {}).get("items", []) if ps else [])]


def check_title(title, W, fp_terms=()):
    """剧名规范（references/naming.md）。返回问题列表，空就是过。"""
    t = title.strip().strip("《》")
    errs = []
    n = len(HAN.findall(t))
    if not 4 <= n <= 16:
        errs.append(f"汉字 {n} 个，剧名要 4-16 个汉字")
    if len(t) > 20:
        errs.append(f"连标点 {len(t)} 个字，太长，最多 20 个")
    if re.search(r'[《》\\/:*?"<>|]', t):
        errs.append("不要带书名号和 / \\ : * ? \" < > | 这些字符")
    tpl = _load(os.path.join(W, "source", "template.json"), {})
    src = (tpl.get("title") or "").strip("《》")
    if src and (src in t or t in src):
        errs.append(f"和原剧《{src}》重名或互相包含")
    for h in hot_titles(W):
        core = re.sub(r"(第[一二三四五六七八九十0-9]+季|[0-9]+$|完结篇)", "", h)
        if t == h or (len(core) >= 4 and (core in t or t in core)):
            errs.append(f"和热播榜上的《{h}》重名或太像")
    for v in variants(W):
        if v["title"] == t:
            errs.append(f"和本工作区已立项的 {v['id']}《{t}》重名")
    hits = sorted({w for w in fp_terms if len(w) >= 2 and w in t})
    if hits:
        errs.append(f"带了原剧指纹词：{'、'.join(hits)}")
    return errs


def fp_terms_of(L):
    out = set()
    fp = _load(L["fp"], {}) or {}
    for f in fp.get("fingerprints", []):
        out |= set(f.get("terms", []))
    m = _load(os.path.join(L["ex"], "manifest.json"), {}) or {}
    out |= set(m.get("names", []))
    return out


def cmd_title_check(args):
    L = layout(args.workspace)
    res = {t: check_title(t, L["W"], fp_terms_of(L)) for t in args.titles}
    print(json.dumps({"passed": all(not v for v in res.values()), "titles": res,
                      "note": "过了的剧名才拿给用户选；没过的换掉，不要硬给"}, ensure_ascii=False, indent=1))
    return 0 if all(not v for v in res.values()) else 2


def cmd_variant(args):
    """用户选定外壳和剧名以后立项：建 V<编号>-<剧名>/，登记进 variants.json。"""
    L = layout(args.workspace)
    if L["mode"] != "workspace":
        print(json.dumps({"error": f"{args.workspace} 不是原剧工作区（里面要有 source/）。先跑 init"}, ensure_ascii=False))
        return 1
    W = L["W"]
    t = args.title.strip().strip("《》")
    errs = check_title(t, W, fp_terms_of(L))
    if errs:
        print(json.dumps({"error": "剧名不合规范", "problems": errs}, ensure_ascii=False, indent=1))
        return 2
    reg = _load(L["variants"], {"variants": []})
    vid = f"V{len(reg['variants']) + 1:02d}"
    d = os.path.join(W, f"{vid}-{safe(t)}")
    os.makedirs(os.path.join(d, "out"), exist_ok=True)
    os.makedirs(os.path.join(d, "delivery"), exist_ok=True)
    meta = {"id": vid, "title": t, "shell": args.shell, "axes": args.axes or "", "dir": os.path.basename(d),
            "createdAt": datetime.date.today().isoformat(), "status": "写作中"}
    _dump(os.path.join(d, "variant.json"), meta)
    reg["variants"].append(meta)
    _dump(L["variants"], reg)
    print(json.dumps({"variant": d, "id": vid, "title": t,
                      "next": f"python3 {os.path.join(os.path.dirname(os.path.abspath(__file__)), 'clone_check.py')} next --project {d}",
                      "note": "以后这部新剧的所有命令都用 --project 指向这个变体目录；原剧提取和热播榜从工作区共用，不要再拉"},
                     ensure_ascii=False, indent=1))
    return 0


def set_status(P, status):
    """变体状态同时写进 variant.json 和工作区的 variants.json。"""
    vp = os.path.join(P, "variant.json")
    meta = _load(vp, {})
    meta["status"] = status
    _dump(vp, meta)
    W = os.path.dirname(P)
    reg = _load(os.path.join(W, "variants.json"), {"variants": []})
    for v in reg["variants"]:
        if v["id"] == meta.get("id"):
            v["status"] = status
    _dump(os.path.join(W, "variants.json"), reg)
