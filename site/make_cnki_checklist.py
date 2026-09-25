#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成「知网期号核对清单」—— site/dist/articles.json 里所有缺期号的文章，
汇成一页可点、可填、可导出的本地 HTML（仓库根目录 cnki_check.html）。

为什么是"人工 + 清单"而不是爬虫：
  知网的检索域 kns.cnki.net 对自动化/云 IP 一律下发滑块验证（captchaType=blockPuzzle），
  自己拿账号去跑脚本既不稳也不合规。所以这里只做"省事"的部分——
  把 163 条待查项整理好、每条给一个直达的知网检索链接、填完自动生成 overrides 片段。

用法：
    python site/make_cnki_checklist.py
然后双击仓库根目录的 cnki_check.html。
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "site" / "dist" / "articles.json"
OUT = ROOT / "cnki_check.html"

# 知网检索结果页需要的参数。crossids 是"主题检索"默认勾选的资源类型，
# 直接从知网首页真实检索一次抓下来的，别手改。
CROSSIDS = ("YSTT4HG0,LSTPFY1C,EMRPGLPA,JUP3MUPD,MPMFIG1A,"
            "WQ0UVIAA,BLZOG7CK,PWFIRAGL,NLBO1Z6R,NN3FJMUV")

# 检索式里带标点容易被知网拆词，清一遍更容易命中
_PUNCT = re.compile(r'[“”"\'‘’、，。；：！？《》〈〉（）()\[\]【】\-—…·\s]+')


def query_of(title: str) -> str:
    """把标题清成适合丢进知网检索框的形式。"""
    q = _PUNCT.sub(" ", title)
    q = re.sub(r"\s+", " ", q).strip()
    return q


def main() -> int:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    todo = [a for a in data if not a.get("issue")]

    groups = defaultdict(list)
    for a in todo:
        groups[(a.get("magazine") or "（刊物待定）", a.get("year") or 0)].append(a)

    items = []
    for (mag, year), arr in sorted(groups.items(), key=lambda kv: (-kv[0][1], kv[0][0])):
        for a in sorted(arr, key=lambda x: x["title"]):
            items.append({
                "file": a["path"].rsplit("/", 1)[-1],
                "title": a["title"],
                "year": a.get("year"),
                "magazine": mag,
                "q": query_of(a["title"]),
            })

    payload = json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    html = TEMPLATE.replace("__DATA__", payload).replace("__CROSSIDS__", CROSSIDS)
    OUT.write_text(html, encoding="utf-8")

    print(f"待核对 {len(items)} 篇，分属 {len(groups)} 个「刊物 + 年份」组")
    for (mag, year), arr in sorted(groups.items(), key=lambda kv: (-kv[0][1], kv[0][0])):
        print(f"  {year}  {mag:<22} {len(arr):>3} 篇")
    print(f"已生成 {OUT}")
    return 0


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>知网期号核对清单 · 谢作如文集</title>
<style>
  :root{
    --bg:#f6f6f4; --card:#fff; --ink:#23262a; --dim:#6b7075; --line:#e2e2df;
    --accent:#185fa5; --accent-soft:#e6f1fb; --ok:#0f6e56; --ok-soft:#e1f5ee;
    --warn:#854f0b; --warn-soft:#faeeda;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
    font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:10;background:rgba(246,246,244,.94);
    backdrop-filter:saturate(1.6) blur(8px);border-bottom:1px solid var(--line);padding:14px 20px 10px}
  h1{margin:0 0 4px;font-size:16px;font-weight:600}
  .sub{color:var(--dim);font-size:12.5px;margin-bottom:10px}
  .bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
  input[type=search],select{padding:6px 10px;border:1px solid var(--line);border-radius:7px;
    background:#fff;color:var(--ink);font-size:13px;font-family:inherit}
  input[type=search]{flex:1 1 220px;min-width:150px}
  button{padding:6px 12px;border:1px solid var(--line);border-radius:7px;background:#fff;
    color:var(--ink);font-size:13px;font-family:inherit;cursor:pointer}
  button:hover{border-color:#b9bdc0}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
  button.primary:hover{background:#0c447c;border-color:#0c447c}
  .prog{display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--dim)}
  .track{width:170px;height:6px;border-radius:3px;background:#e6e6e3;overflow:hidden}
  .fill{height:100%;width:0;background:var(--ok);transition:width .18s}
  main{padding:16px 20px 90px;max-width:1180px;margin:0 auto}
  .grp{margin:0 0 18px;border:1px solid var(--line);border-radius:12px;background:var(--card);overflow:hidden}
  .gh{display:flex;align-items:center;gap:10px;padding:10px 14px;background:#fbfbfa;
    border-bottom:1px solid var(--line);cursor:pointer;user-select:none}
  .gh .nm{font-weight:500}
  .gh .yr{color:var(--dim);font-size:12.5px}
  .gh .n{margin-left:auto;color:var(--dim);font-size:12.5px}
  .gh .cnt{color:var(--ok);font-size:12.5px}
  .grp.collapsed .items{display:none}
  .row{display:grid;grid-template-columns:minmax(0,1fr) 104px auto auto;gap:10px;
    align-items:center;padding:9px 14px;border-top:1px solid var(--line)}
  .row:first-child{border-top:0}
  .row.done{background:var(--ok-soft)}
  .ti{min-width:0}
  .ti .t{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .ti .f{color:#9a9ea2;font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .issue{width:100%;padding:5px 8px;border:1px solid var(--line);border-radius:6px;
    font:inherit;font-size:13px;text-align:center}
  .issue:focus{outline:2px solid var(--accent-soft);border-color:var(--accent)}
  a.sr{display:inline-block;padding:5px 10px;border:1px solid var(--line);border-radius:7px;
    color:var(--accent);text-decoration:none;font-size:12.5px;white-space:nowrap;background:#fff}
  a.sr:hover{background:var(--accent-soft);border-color:var(--accent)}
  .tip{margin:0 0 14px;padding:11px 14px;border-radius:10px;background:var(--warn-soft);
    color:var(--warn);font-size:12.5px;border:1px solid #f0dcb4}
  .tip b{font-weight:600}
  footer{position:fixed;left:0;right:0;bottom:0;background:rgba(246,246,244,.96);
    border-top:1px solid var(--line);padding:10px 20px;display:flex;gap:10px;
    align-items:center;flex-wrap:wrap;backdrop-filter:saturate(1.6) blur(8px)}
  footer .grow{flex:1}
  @media (max-width:620px){
    .row{grid-template-columns:minmax(0,1fr) 84px;row-gap:6px}
    .row .act{grid-column:2}
    header{padding:12px 14px 8px}
    main{padding:14px}
  }
</style>
</head>
<body>
<header>
  <h1>知网期号核对清单</h1>
  <div class="sub">逐条点「查知网」→ 在弹出的结果页看一眼刊名与期号 → 填进右边的框。填完点底部「导出」。<b>数据只存在你本机浏览器里。</b></div>
  <div class="bar">
    <input type="search" id="q" placeholder="过滤标题 / 文件名…">
    <label class="prog"><input type="checkbox" id="onlyUndone"> 只看未填</label>
    <span class="prog"><span class="track"><span class="fill" id="fill"></span></span><span id="cnt"></span></span>
  </div>
</header>

<main>
  <div class="tip">
    <b>为什么是手工点、不是自动抓？</b>知网的检索域 <code>kns.cnki.net</code> 对脚本和云 IP 一律下发滑块验证，
    用自动化去绕既不稳定也违反知网的服务协议。所以这一页只做省事的整理工作：<b>直达链接 + 填写框 + 自动导出成 overrides 片段</b>。
    你本机浏览器（温州电信 IP）访问知网是正常的，拖一次滑块能管一个会话。
  </div>
  <div id="list"></div>
</main>

<footer>
  <button class="primary" id="exp">导出 overrides 片段</button>
  <button id="copy">复制到剪贴板</button>
  <button id="imp">导入进度</button>
  <input type="file" id="impf" accept=".json" hidden>
  <button id="clr">清空</button>
  <span class="grow"></span>
  <span class="sub" id="msg" style="margin:0"></span>
</footer>

<pre id="out" hidden style="position:fixed;inset:8% 8%;overflow:auto;background:#fff;border:1px solid #ccc;border-radius:12px;padding:16px;z-index:99;font-size:12.5px"></pre>

<script>
const DATA = __DATA__;
const CROSSIDS = "__CROSSIDS__";
const KEY = "xzr-cnki-checklist-v1";
let STORE = {};

try { STORE = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { STORE = {}; }

function save(){
  try { localStorage.setItem(KEY, JSON.stringify(STORE)); } catch (e) {}
}

function groupKey(it){ return (it.year || "?") + "|" + it.magazine; }

function searchUrl(it){
  return "https://kns.cnki.net/kns8s/defaultresult/index"
    + "?crossids=" + encodeURIComponent(CROSSIDS)
    + "&korder=TI&kw=" + encodeURIComponent(it.q);
}

const list = document.getElementById("list");

function render(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const onlyUndone = document.getElementById("onlyUndone").checked;

  const groups = new Map();
  for (const it of DATA){
    const k = groupKey(it);
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(it);
  }

  let shown = 0, done = 0;
  const html = [];

  for (const [k, arr] of groups){
    const hit = arr.filter(it => {
      const v = (STORE[it.file] || {}).issue || "";
      if (onlyUndone && v) return false;
      if (!q) return true;
      return (it.title + " " + it.file + " " + it.magazine).toLowerCase().includes(q);
    });
    done += arr.filter(it => (STORE[it.file] || {}).issue).length;
    if (!hit.length) continue;
    shown += hit.length;

    const [year, mag] = k.split("|");
    const gDone = arr.filter(it => (STORE[it.file] || {}).issue).length;
    const shownTxt = (q || onlyUndone)
      ? hit.length + " / " + arr.length + " 条"
      : arr.length + " 条";
    html.push('<section class="grp" data-g="' + esc(k) + '">'
      + '<div class="gh"><span class="yr">' + esc(year) + '</span>'
      + '<span class="nm">' + esc(mag) + '</span>'
      + '<span class="n"><span class="nshow">' + shownTxt + '</span>'
      + '<span class="ndone">' + (gDone ? ' · 已填 ' + gDone : '') + '</span></span></div>'
      + '<div class="items">');

    for (const it of hit){
      const v = esc((STORE[it.file] || {}).issue || "");
      html.push('<div class="row' + (v ? ' done' : '') + '" data-f="' + esc(it.file)
        + '" data-g="' + esc(k) + '">'
        + '<div class="ti"><div class="t" title="' + esc(it.title) + '">' + esc(it.title) + '</div>'
        + '<div class="f">' + esc(it.file) + '</div></div>'
        + '<input class="issue" placeholder="第 N 期" value="' + v + '">'
        + '<span class="act"><a class="sr" target="_blank" rel="noopener" href="' + searchUrl(it) + '">查知网</a></span>'
        + '<span class="act"><button class="cp" title="复制题名">复制</button></span>'
        + '</div>');
    }
    html.push('</div></section>');
  }

  list.innerHTML = html.join("");
  document.getElementById("cnt").textContent = "已填 " + done + " / " + DATA.length;
  document.getElementById("fill").style.width = (DATA.length ? done / DATA.length * 100 : 0) + "%";

  list.querySelectorAll(".gh").forEach(el =>
    el.addEventListener("click", () => el.parentElement.classList.toggle("collapsed")));

  list.querySelectorAll(".issue").forEach(el => {
    el.addEventListener("input", () => {
      const row = el.closest(".row");
      const f = row.dataset.f;
      const val = el.value.trim();
      STORE[f] = STORE[f] || {};
      STORE[f].issue = val;
      if (!val) delete STORE[f].issue;
      row.classList.toggle("done", !!val);
      save();
      const d = DATA.filter(it => (STORE[it.file] || {}).issue).length;
      document.getElementById("cnt").textContent = "已填 " + d + " / " + DATA.length;
      document.getElementById("fill").style.width = (d / DATA.length * 100) + "%";
      updateGroupCount(row.dataset.g);
    });
  });

  list.querySelectorAll(".cp").forEach(btn => {
    btn.addEventListener("click", async () => {
      const f = btn.closest(".row").dataset.f;
      const it = DATA.find(x => x.file === f);
      try { await navigator.clipboard.writeText(it.title); toast("已复制题名"); }
      catch (e) { toast("复制失败，请手动选中"); }
    });
  });
}

// 某个分组已填的条数 —— 输入时就地刷新组头，避免整页重绘丢焦点
function updateGroupCount(key){
  let done = 0, total = 0;
  for (const it of DATA){
    if (groupKey(it) !== key) continue;
    total++;
    if ((STORE[it.file] || {}).issue) done++;
  }
  const sel = window.CSS && CSS.escape ? CSS.escape(key) : key;
  const el = list.querySelector('.grp[data-g="' + sel + '"] .ndone');
  if (el) el.textContent = done ? " · 已填 " + done + (done === total ? "（本组完成）" : "") : "";
}

function esc(s){
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

let toastT;
function toast(m){
  const el = document.getElementById("msg");
  el.textContent = m;
  clearTimeout(toastT);
  toastT = setTimeout(() => el.textContent = "", 2200);
}

function buildOut(){
  const o = {};
  for (const it of DATA){
    const v = (STORE[it.file] || {}).issue;
    if (v) o[it.file] = { issue: v };
  }
  return o;
}

function download(name, text){
  const blob = new Blob([text], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 3000);
}

document.getElementById("exp").addEventListener("click", () => {
  const o = buildOut();
  const n = Object.keys(o).length;
  if (!n) return toast("还没有填任何期号");
  download("overrides-补期号.json", JSON.stringify(o, null, 2) + "\n");
  toast("已导出 " + n + " 条");
});

document.getElementById("copy").addEventListener("click", async () => {
  const o = buildOut();
  const n = Object.keys(o).length;
  if (!n) return toast("还没有填任何期号");
  const text = JSON.stringify(o, null, 2);
  const pre = document.getElementById("out");
  pre.textContent = text;
  pre.hidden = false;
  pre.onclick = () => pre.hidden = true;
  try { await navigator.clipboard.writeText(text); toast("已复制 " + n + " 条 JSON"); }
  catch (e) { toast("请从弹出的框里手动复制"); }
});

document.getElementById("clr").addEventListener("click", () => {
  if (!confirm("清空所有已填的期号？此操作不可撤销。")) return;
  STORE = {}; save(); render(); toast("已清空");
});

document.getElementById("imp").addEventListener("click", () => document.getElementById("impf").click());
document.getElementById("impf").addEventListener("change", async ev => {
  const f = ev.target.files[0];
  if (!f) return;
  try {
    const o = JSON.parse(await f.text());
    let n = 0;
    for (const k in o){ STORE[k] = Object.assign({}, STORE[k], o[k]); n++; }
    save(); render(); toast("导入 " + n + " 条");
  } catch (e) { toast("文件读不动：" + e.message); }
  ev.target.value = "";
});

document.getElementById("q").addEventListener("input", render);
document.getElementById("onlyUndone").addEventListener("change", render);

render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    sys.exit(main())
