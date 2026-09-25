#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
xzr-articles 站点索引构建脚本

扫描仓库中的 PDF，解析元数据（标题/年份/刊物/合集/作者），
同名文章去重合并，用 PyMuPDF 生成首页缩略图，输出 dist/articles.json。

用法：
    python build.py              # 全量构建
    python build.py --no-thumbs  # 只更新索引，不生成缩略图（已有封面不受影响）

手动修正：在 overrides.json 中按文件名指定字段，例如：
    {"中学生天地B-202606期-.pdf": {"title": "AI专题（下）", "magazine": "中学生天地"}}
"""
import json
import re
import sys
import shutil
import hashlib
from pathlib import Path

import fitz  # PyMuPDF

ROOT = Path(__file__).resolve().parent.parent   # 仓库根目录
SITE = Path(__file__).resolve().parent
DIST = SITE / "dist"
THUMBS = DIST / "thumbs"
OVERRIDES_FILE = SITE / "overrides.json"

# 已知刊物（用于从文件名中识别来源；按长名优先匹配）
MAGAZINES = [
    "中小学信息技术教育", "中国信息技术教育", "中国现代教育装备",
    "中小学数字化教学", "人民教育", "上海教育科研", "上海教育",
    "中国科技教育", "浙江教学研究", "现代教育科学", "信息教研周刊",
    "人大复印资料", "无线电", "学与玩", "中学生天地", "光明少年",
    "教育家", "基础教育课程", "创新人才教育", "教育视界",
    "实验教学与仪器", "教学月刊", "中国电化教育", "数字教育",
    # —— 以下为补全元数据时新增（说明见 overrides.json 顶部）——
    "中国教师报", "中国教育报", "远程教育杂志", "物理教师",
    "教育研究与评论", "教育与装备研究", "浙江教育技术",
    "新校长", "华附联盟", "爱上机器人",
    "信息技术教育", "教育信息化",   # “信息技术教育”须排在两个长名之后
]

# 某些专栏目录整体属于某年/某刊，文件名和子目录名里都看不出来
COLLECTION_META = {
    "学与玩-玩转AI": {"year": 2026},   # 该栏目 2026 年第 2~9 期连载
}

# 专栏/栏目词（出现时不当作标题）
COLUMN_WORDS = {"对话", "创客三级跳", "新技能", "生活技术探究", "环球教育时讯"}

# ==== 版面取证：从 PDF 页眉/页脚读取刊物名与年期编码 ====
# 很多 PDF（尤其知网导出的）正文里查不到出处，但页眉/页脚印着英文刊名、
# 官网域名或 "MAR. 2024 NO.05"、"2015/19"、"2019 年第 3 期" 这类年期编码，
# 比文件名可靠。只认页眉页脚区域，避免把正文参考文献里的线索当成本文出处。
LAYOUT_MAG = [
    # 注意：chinaitedu.cn 与教师邮箱 teacher@chinaitedu.cn 属《中国信息技术教育》；
    # 而 www.itedu.org.cn 是《中小学信息技术教育》官网（已由该刊 2015(7):8-10
    # 《从机器人、STEM到创客教育》的「本期策划」页眉互证），两者不可合并。
    (re.compile(r"chinaitedu\.cn|中国信息技术教育"), "中国信息技术教育"),
    (re.compile(r"itedu\.org\.cn|中小学信息技术教育"), "中小学信息技术教育"),
    (re.compile(r"China Science & Technology Education|中国科技教育"), "中国科技教育"),
    (re.compile(r"人民教育|PEOPLE'?S EDUCATION"), "人民教育"),
    (re.compile(r"光明少年|GUANGMING TEENS"), "光明少年"),
    (re.compile(r"教育家|\bEDUCATOR\b"), "教育家"),
    (re.compile(r"远程教育杂志|JOURNAL OF DISTANCE EDUCATION"), "远程教育杂志"),
    (re.compile(r"创新人才教育|Innovative Talents"), "创新人才教育"),
    (re.compile(r"中小学数字化教学"), "中小学数字化教学"),
    (re.compile(r"浙江教育技术"), "浙江教育技术"),
    (re.compile(r"教育与装备研究"), "教育与装备研究"),
    (re.compile(r"教育研究与评论"), "教育研究与评论"),
    (re.compile(r"物理教师|PHYSICS TEACHER"), "物理教师"),
    (re.compile(r"中国教师报"), "中国教师报"),
    (re.compile(r"中国教育报"), "中国教育报"),
    (re.compile(r"中国电化教育"), "中国电化教育"),
    (re.compile(r"信息技术教育"), "信息技术教育"),     # 兜底，须在上面两个长名之后
]

_MONTH_WORD = r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"
# 依次从强到弱：越靠后的写法越容易跟正文里的日期/页码混淆，
# 所以只有页码年份与文件已有的年份一致（或本来就没年份）时才采信。
RE_MONTH_CODE = re.compile(r"\b(" + _MONTH_WORD + r")\.?\s*(20\d{2})\s*NO\.?\s*(\d{1,2})", re.I)
RE_CN_YEAR_ISSUE = re.compile(r"(20\d{2})\s*年\s*第\s*(\d+)\s*期")
RE_CN_ISSUE = re.compile(r"第\s*(\d+)\s*期")
RE_CN_VOL_ISSUE = re.compile(r"第\s*\d+\s*卷\s*第\s*(\d+)\s*期")
RE_CN_YEAR = re.compile(r"(20\d{2})\s*年")
RE_DOT_CODE = re.compile(r"(?<![\d.])(20\d{2})\s*\.\s*(\d{1,2})\b")
RE_BULLET_CODE = re.compile(r"(?<![\d.])(20\d{2})\s*[●•·]\s*(\d{1,2})\b")
RE_SLASH_CODE = re.compile(r"(?<![\d/／])(20\d{2})\s*[/／]\s*(\d{1,2})(?!\d)")
# 扫描件里年份常被拆成 "2 0 0 6. 3" 这样
RE_SPACED_DOT = re.compile(r"(?<![\d.])(\d)\s+(\d)\s+(\d)\s+(\d)\s*\.\s*(\d{1,2})(?!\d)")
_FULL2HALF = str.maketrans("０１２３４５６７８９", "0123456789")


def _bands(doc):
    """取首页与末页的页眉页脚文本（含全角数字归一）。版面取证只看这两页。"""
    out = []
    for pi in ([0] if doc.page_count < 2 else [0, doc.page_count - 1]):
        page = doc[pi]
        H = page.rect.height
        try:
            blocks = page.get_text("blocks")
        except Exception:
            continue
        band = " ".join(b[4] for b in blocks
                        if b[1] < H * 0.17 or b[3] > H * 0.84)
        if band.strip():
            out.append(band.translate(_FULL2HALF))
    return out


def probe_layout(pdf_path, expect_year=None):
    """从 PDF 首页/末页的页眉页脚推断 (刊物, 年份, 期号)，读不到返回 (None, None, None)。

    模式按可靠性从强到弱逐个套用，且要求年份能与 expect_year 对上，
    以免把正文里的 "2016.10" 之类当成本刊的期号。"""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None, None, None
    try:
        bands = _bands(doc)
    except Exception:
        bands = []
    finally:
        doc.close()
    if not bands:
        return None, None, None

    def year_ok(y):
        return expect_year is None or y == int(expect_year)

    mag = None
    for band in bands:
        for rx, name in LAYOUT_MAG:
            if rx.search(band):
                mag = name
                break
        if mag:
            break

    # 1) 英文月份 + NO.N —— 最可靠
    for band in bands:
        m = RE_MONTH_CODE.search(band)
        if m and year_ok(m.group(2)):
            return mag, int(m.group(2)), f"第{int(m.group(3))}期"
    # 2) 中文「YYYY 年第 N 期」
    for band in bands:
        m = RE_CN_YEAR_ISSUE.search(band)
        if m and year_ok(m.group(1)):
            return mag, int(m.group(1)), f"第{m.group(2)}期"
    # 3) 「第 N 卷第 M 期」＋「YYYY 年」
    for band in bands:
        m = RE_CN_VOL_ISSUE.search(band)
        y = RE_CN_YEAR.search(band)
        if m and y and year_ok(y.group(1)):
            return mag, int(y.group(1)), f"第{m.group(1)}期"
    # 4) YYYY.M / YYYY●M / YYYY/M / 被拆开的 "2 0 0 6. 3"
    for band in bands:
        for rx, gi, gj in ((RE_DOT_CODE, 1, 2), (RE_BULLET_CODE, 1, 2),
                           (RE_SLASH_CODE, 1, 2)):
            for m in rx.finditer(band):
                if year_ok(m.group(gi)) and 1 <= int(m.group(gj)) <= 12:
                    return mag, int(m.group(gi)), f"第{int(m.group(gj))}期"
        m = RE_SPACED_DOT.search(band)
        if m:
            y = int("".join(m.group(k) for k in range(1, 5)))
            if year_ok(y) and 1 <= int(m.group(5)) <= 12:
                return mag, y, f"第{int(m.group(5))}期"
    # 5) 版面里已经认准刊物，再认一个裸的「第 N 期」（双月刊常用）
    if mag:
        for band in bands:
            m = RE_CN_ISSUE.search(band)
            if m:
                y = RE_CN_YEAR.search(band)
                return mag, (int(y.group(1)) if y else None), f"第{m.group(1)}期"
    # 6) 只拿到刊物和年份
    year = None
    for band in bands:
        m = RE_CN_YEAR.search(band)
        if m and year_ok(m.group(1)):
            year = int(m.group(1))
            break
    return mag, year, None


AUTHOR_RE = re.compile(r"_([一-龥]{2,4})$")
DATE_RES = [
    re.compile(r"^(?P<y>19|20)?(?P<yy>\d{2})年(?P<rest>.*)$"),           # 2024年11月下 / 24年3期
    re.compile(r"^(?P<y>20\d{2})[.\-](?P<m>\d{1,2})$"),                  # 2014.1 / 2018-9
    re.compile(r"^(?P<y>20\d{2})$"),                                     # 2014
    re.compile(r"^(?P<ym>20\d{4})期$"),                                  # 202603期
    re.compile(r"^(?P<y>20\d{2})第?(?P<n>\d+)期$"),                      # 2025年第7期
]


def norm_title(t: str) -> str:
    """归一化标题用于去重。"""
    return re.sub(r"[\s《》“”\"'‘’_—\-·…、，。：:；;！!？?（）()【】\[\]]", "", t).lower()


def clean_title(t: str) -> str:
    """修复知网导出造成的书名号/引号丢失（被替换为下划线）。"""
    t = t.replace("_省略_", "……").replace("_..._", "……")
    t = re.sub(r"_{2,}", "——", t)                       # 连续下划线 → 破折号
    prev = None
    while prev != t:                                     # 成对下划线 → 引号
        prev = t
        t = re.sub(r"_([^_]+)_", r"“\1”", t)
    t = t.strip("_").strip()
    t = re.sub(r"_", "", t)                              # 残余下划线直接去掉
    return t


def parse_date(seg: str):
    """识别日期段，返回 (year:int|None, issue:str|None)。非日期段返回 None。"""
    s = seg.strip()
    m = re.match(r"^(20\d{2})年(.*)$", s)
    if m:
        return int(m.group(1)), (m.group(2) or None)
    m = re.match(r"^(20\d{2})[.\-](\d{1,2})$", s)
    if m:
        return int(m.group(1)), f"{int(m.group(2))}月"
    m = re.match(r"^(20\d{2})(\d{2})期$", s)
    if m:
        return int(m.group(1)), f"{int(m.group(2))}月"
    m = re.match(r"^(20\d{2})年第?(\d+)期$", s)
    if m:
        return int(m.group(1)), f"第{m.group(2)}期"
    if re.match(r"^(19|20)\d{2}$", s):
        return int(s), None
    m = re.match(r"^第?(\d{1,3})期$", s)
    if m:
        return None, f"第{m.group(1)}期"
    return None


def match_magazine(seg: str):
    """段中包含已知刊物名则返回刊物名。"""
    for mag in MAGAZINES:
        if mag in seg:
            return mag
    return None


def guess_topic(title: str) -> str:
    """按关键词粗分主题（对应 README 的分类思路）。"""
    rules = [
        ("人工智能教育", ["人工智能", "AI", "大模型", "深度学习", "神经网络", "智能"]),
        ("创客与STEM教育", ["创客", "STEM", "STEAM", "开源硬件", "Arduino", "S4A", "虚谷", "掌控板", "行空板", "机器人"]),
        ("物联网与信息科技", ["物联网", "传感", "大数据", "信息系统", "信息技术", "网络", "计算思维", "算法", "程序"]),
        ("跨学科与综合实践", ["跨学科", "综合实践", "劳动教育", "项目"]),
    ]
    for topic, kws in rules:
        if any(k in title for k in kws):
            return topic
    return "其他"


def parse_pdf(rel: Path, top_dir: str, known_authors=frozenset()):
    """解析单个 PDF 的元数据。"""
    name = rel.stem
    author = None
    m = AUTHOR_RE.search(name)
    if m:
        author = m.group(1)
        name = name[: m.start()]

    year, issue, magazine = None, None, None
    title_parts = []
    for seg in name.split("-"):
        seg = seg.strip()
        if not seg:
            continue
        d = parse_date(seg)
        if d:
            year = year or d[0]
            issue = issue or d[1]
            continue
        mag = match_magazine(seg)
        if mag:
            magazine = magazine or mag
            rest = seg.replace(mag, "").strip()
            if rest and rest not in COLUMN_WORDS and len(rest) >= 4:
                title_parts.append(rest)
            continue
        if seg in COLUMN_WORDS:
            continue
        title_parts.append(seg)

    # 有的文件用 "-作者" 而非 "_作者" 结尾（如 学与玩 系列）
    if author is None and len(title_parts) >= 2 and title_parts[-1] in known_authors:
        author = title_parts.pop()

    title = clean_title("-".join(title_parts)) if title_parts else clean_title(name)

    # 年度信息兜底：顶层目录 > 二级目录
    if year is None:
        m = re.match(r"^(20\d{2})年度$", top_dir)
        if m:
            year = int(m.group(1))
    if year is None and len(rel.parts) >= 2:
        m = re.match(r"^(20\d{2})$", rel.parts[-2])
        if m:
            year = int(m.group(1))

    # 刊物兜底：专栏目录名中往往包含刊物名
    if magazine is None:
        magazine = match_magazine(top_dir)

    return {
        "title": title,
        "author": author,
        "year": year,
        "issue": issue,
        "magazine": magazine,
        "topic": guess_topic(title),
    }


def main():
    no_thumbs = "--no-thumbs" in sys.argv
    overrides = {}
    if OVERRIDES_FILE.exists():
        overrides = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))

    THUMBS.mkdir(parents=True, exist_ok=True)

    pdfs = sorted(p for p in ROOT.rglob("*.pdf") if ".git" not in p.parts and "site" not in p.parts)
    print(f"发现 {len(pdfs)} 个 PDF")

    # 第一遍：收集所有 "_作者" 名字，用于识别 "-作者" 结尾的文件名
    known_authors = set()
    for p in pdfs:
        m = AUTHOR_RE.search(p.stem)
        if m:
            known_authors.add(m.group(1))

    articles = {}  # norm_title+year -> article
    skipped = []
    for p in pdfs:
        rel = p.relative_to(ROOT)
        top_dir = rel.parts[0]
        meta = parse_pdf(rel, top_dir, known_authors)
        base = rel.name
        if base in overrides:
            meta.update(overrides[base])
        for f, v in COLLECTION_META.get(top_dir, {}).items():
            if not meta.get(f):
                meta[f] = v
        # 文件名里没有的刊物/年份/期号，最后从版面（页眉页脚）里找
        if not (meta["year"] and meta["magazine"] and meta["issue"]):
            lmag, lyear, lissue = probe_layout(str(p), meta["year"])
            if not meta["magazine"] and lmag:
                meta["magazine"] = lmag
            if not meta["year"] and lyear:
                meta["year"] = lyear
            if not meta["issue"] and lissue:
                meta["issue"] = lissue
        if not meta["title"]:
            skipped.append(str(rel))
            meta["title"] = rel.stem

        key = norm_title(meta["title"]) + "|" + str(meta["year"] or "")
        size_mb = round(p.stat().st_size / 1024 / 1024, 2)
        entry = {
            "path": str(rel).replace("\\", "/"),
            "size_mb": size_mb,
            "collection": top_dir,
        }
        if key in articles:
            a = articles[key]
            a["collections"].add(top_dir)
            if size_mb > a["_size"]:  # 保留扫描质量更好的（更大的）文件
                a["_size"] = size_mb
                a["path"] = entry["path"]
                a["size_mb"] = size_mb
            # 两个副本的元数据可能各有缺失（如年度目录里的文件没写刊物、
            # 各类杂志专题组稿里的写了），按"谁有就用谁的"补齐，避免信息丢失
            for f in ("author", "issue", "magazine", "year"):
                if not a.get(f) and meta.get(f):
                    a[f] = meta[f]
        else:
            aid = hashlib.md5(key.encode("utf-8")).hexdigest()[:10]
            articles[key] = {
                "id": aid,
                **meta,
                "path": entry["path"],
                "size_mb": size_mb,
                "collections": {top_dir},
                "_size": size_mb,
            }

    # 第二遍合并：同一篇文章，一个文件带年份、另一个不带（如专栏目录里的副本）
    by_norm = {}
    for key, a in articles.items():
        by_norm.setdefault(norm_title(a["title"]), []).append(key)
    for norm, keys in by_norm.items():
        if len(keys) < 2:
            continue
        with_year = [k for k in keys if articles[k]["year"]]
        without = [k for k in keys if not articles[k]["year"]]
        if with_year and without:
            target = articles[with_year[0]]
            for k in without:
                src = articles[k]
                target["collections"] |= src["collections"]
                for f in ("author", "issue", "magazine"):
                    if not target[f] and src[f]:
                        target[f] = src[f]
                del articles[k]

    out = []
    err_thumbs = []
    for a in articles.values():
        a["collections"] = sorted(a["collections"])
        pdf_path = ROOT / a["path"]
        thumb_name = f"{a['id']}.jpg"
        thumb_path = THUMBS / thumb_name
        try:
            doc = fitz.open(pdf_path)
            a["pages"] = doc.page_count
            if not no_thumbs and not thumb_path.exists():
                page = doc[0]
                zoom = 420 / page.rect.width
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                pix.save(thumb_path, jpg_quality=72)
            doc.close()
            a["thumb"] = f"thumbs/{thumb_name}" if thumb_path.exists() else None
        except Exception as e:  # 损坏的 PDF 不阻断构建
            err_thumbs.append(f"{a['path']}: {e}")
            a["pages"] = None
            a["thumb"] = None
        del a["_size"]
        out.append(a)

    out.sort(key=lambda x: (x["year"] or 0, x["title"]), reverse=True)
    payload = json.dumps(out, ensure_ascii=False)
    (DIST / "articles.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    # 同一份数据的 JS 版本：本地直接双击 index.html（file:// 协议）时浏览器
    # 不允许 fetch 本地 JSON，但允许 <script> 加载，页面会自动降级到这里
    (DIST / "articles.js").write_text(
        "window.ARTICLES_DATA = " + payload + ";\n", encoding="utf-8")

    # 清理孤儿缩略图：缩略图文件名 = 文章 id（"标题|年份"的哈希），
    # 所以用 overrides.json 修正过标题/年份、或调整过解析规则后，
    # 旧 id 的缩略图就成了没人引用的孤儿，只会白占体积
    if not no_thumbs:
        used = {f"{a['id']}.jpg" for a in out}
        orphans = sorted(f for f in THUMBS.glob("*.jpg") if f.name not in used)
        for f in orphans:
            f.unlink()
        if orphans:
            print(f"已清理 {len(orphans)} 张孤儿缩略图：",
                  *[f.name for f in orphans], sep="\n  ")

    # 网页源文件放在仓库根目录（访问根目录首页即可打开网站），
    # 构建时复制进 dist，供 Cloudflare Pages 部署
    for f in ("index.html", "reader.html", "config.js"):
        src = ROOT / f
        if src.exists():
            shutil.copy2(src, DIST / f)
        else:
            print(f"警告：根目录缺少 {f}")

    # PDF.js 自带副本：阅读器用它，避免依赖 CDN（国内/微信访问 cdnjs 不稳定）
    vend = ROOT / "vendor"
    if vend.is_dir():
        shutil.copytree(vend, DIST / "vendor", dirs_exist_ok=True)
    else:
        print("警告：根目录缺少 vendor/（PDF.js 自带副本），阅读器将回退 CDN")

    n_merged = len(pdfs) - len(out)
    print(f"文章数：{len(out)}（合并了 {n_merged} 个同年重复文件）")
    print(f"缺少年份：{sum(1 for a in out if not a['year'])}，缺少刊物：{sum(1 for a in out if not a['magazine'])}")
    if skipped:
        print("标题为空（已用文件名兜底）:", *skipped, sep="\n  ")
    if err_thumbs:
        print("以下 PDF 读取失败:", *err_thumbs, sep="\n  ")
    missing = [a for a in out if not a["thumb"]]
    if missing:
        print(f"\n警告：有 {len(missing)} 篇没有封面缩略图"
              f"（--no-thumbs 模式不会生成）")
        for a in missing:
            print("   ", a["path"])
        print("   修复：运行 python build.py（不带 --no-thumbs）")
    print(f"索引已写入 {DIST / 'articles.json'}，缩略图目录 {THUMBS}")


if __name__ == "__main__":
    main()
