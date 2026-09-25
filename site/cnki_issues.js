#!/usr/bin/env node
'use strict';
/*
 * 知网期号补全工具 —— 给 xzr-articles 里缺 issue 的文章补上「第 N 期」
 *
 * 为什么需要它：site/dist/articles.json 里有 160+ 篇只有年 + 刊、没有期号。
 * 期号只能从知网拿，而知网的检索域对脚本/云 IP 一律下发滑块验证，会话内抓不了。
 * 所以这个脚本必须在你自己的终端里跑（非沙箱 → 用你的 IP + 你的浏览器）。
 *
 * ── 两种用法 ───────────────────────────────────────────────
 *
 * 【推荐】parse 模式：你手工导出题录，脚本负责解析 + 匹配 + 生成 overrides
 *     1) 打开 https://kns.cnki.net/ ，检索式用：AU=谢作如
 *     2) 结果页全选 → 「导出与分析」→「导出文献」→ 选「参考文献」格式 → 复制
 *     3) 把复制到的内容存成文本文件，比如 ~/Desktop/cnki.txt
 *     4) node site/cnki_issues.js parse ~/Desktop/cnki.txt
 *   这个模式不碰知网 DOM，只解析标准化的参考文献文本，稳。
 *
 * 【实验性】auto 模式：脚本用 CDP 驱动你的 Chrome 逐条检索
 *     1) 完全退出 Chrome（⌘Q），然后另开一个专用实例：
 *        open -na "Google Chrome" --args --remote-debugging-port=9222 \
 *             --user-data-dir="$HOME/.cnki-profile"
 *     2) node site/cnki_issues.js auto --limit 5
 *     3) 首次若出现滑块，在浏览器里拖一下，按回车继续
 *   注意：auto 模式的页面选择器是按常见结构写的，本机无法实测（会话内连不上知网）。
 *   第一次请务必带 --limit 3 试水，把输出贴出来以便修正。
 *
 * ── 其它命令 ───────────────────────────────────────────────
 *   node site/cnki_issues.js todo              列出还缺期号的条目（按刊+年分组）
 *   node site/cnki_issues.js merge             把 cnki_issues.json 合并进 overrides.json（自动备份）
 */

const fs = require('fs');
const path = require('path');
const os = require('os');
const readline = require('readline');

const SITE = __dirname;
const ARTICLES = path.join(SITE, 'dist', 'articles.json');
const OVERRIDES = path.join(SITE, 'overrides.json');
const OUT = path.join(SITE, 'cnki_issues.json');
const PROGRESS = path.join(os.tmpdir(), 'cnki_progress.json');

// ── 命令行解析 ────────────────────────────────────────────────
const argv = process.argv.slice(2);
const cmd = argv[0] || 'help';
const opt = { _: [] };
for (let i = 1; i < argv.length; i++) {
  const a = argv[i];
  if (a.startsWith('--')) {
    const k = a.slice(2);
    const next = argv[i + 1];
    if (next && !next.startsWith('--')) { opt[k] = next; i++; } else { opt[k] = true; }
  } else {
    opt._.push(a);
  }
}

function die(msg) { console.error('\n✗ ' + msg + '\n'); process.exit(1); }
function say(msg) { console.log(msg); }
function rule(t) { console.log('\n' + (t ? '── ' + t + ' ' : '') + '─'.repeat(Math.max(4, 60 - (t ? t.length : 0) * 2))); }

// ── 标题归一化（匹配靠它，务必稳） ────────────────────────────
// 文集里的 title 由文件名派生，标点常被换成下划线；知网标题是原样的中文标点。
// 两边都去掉一切非「中文/字母/数字」的字符后再比。
function normTitle(s) {
  return String(s == null ? '' : s)
    .replace(/[\uFE30-\uFE4F\u3000-\u303F]/g, '')   // 中文标点区
    .replace(/[\uFF01-\uFF5E]/g, '')                 // 全角 ASCII
    .replace(/[^\u4e00-\u9fa5a-zA-Z0-9]/g, '')      // 其余非字母数字（含 _ “ ” 等）
    .toLowerCase();
}

// ── 读文章索引 ────────────────────────────────────────────────
function loadArticles() {
  if (!fs.existsSync(ARTICLES)) die('找不到 ' + ARTICLES + '\n  请先在仓库根目录跑一次：python site/build.py');
  return JSON.parse(fs.readFileSync(ARTICLES, 'utf8'));
}
function pending(list) { return list.filter(a => !a.issue); }

// ── 期号规整：06 → 第6期，10 月 → 10月，2025(6) → 第6期 ──────
function normIssue(raw) {
  if (raw == null) return null;
  let s = String(raw).trim();
  if (!s) return null;
  s = s.replace(/^[（(]?\s*0*(\d{1,2})\s*[)）]?$/, '$1');   // 纯数字（去前导零）
  let m = s.match(/(\d{1,2})\s*期/);
  if (m) return '第' + String(Number(m[1])) + '期';
  m = s.match(/^\s*(\d{1,2})\s*月/);
  if (m) return String(Number(m[1])) + '月';
  m = s.match(/^\s*(\d{1,2})\s*$/);
  if (m) return '第' + String(Number(m[1])) + '期';
  return s;   // 兜底原样返回（如「第7-8期」「增刊」）
}

// ══════════════════════════════════════════════════════════════
// part 1 · 解析知网导出的题录文本
// ══════════════════════════════════════════════════════════════

// 格式 A：GB/T 7714 参考文献（知网「参考文献」导出，一行一条）
//   [1] 谢作如. 创客教育为什么要强调"造"[J]. 中小学信息技术教育, 2015, (06): 70-70.
//   [2] 谢作如, 张敬云. 利用Arduino探究单摆周期[J]. 中小学信息技术教育, 2016, (03): 64-66.
function parseGBT7714(text) {
  const out = [];
  const lines = text.split(/\r?\n/);
  for (const raw of lines) {
    const line = raw.replace(/\s+/g, ' ').trim();
    if (!line || !line.includes('[J]')) continue;
    // [J]. 之后：刊名, 年, (期): 页码
    const tail = line.match(/\[J\]\.?\s*(.*)$/);
    if (!tail) continue;
    const rest = tail[1];
    const mm = rest.match(/^([^,，]+?)\s*[,，]\s*(\d{4})\s*[,，]?\s*(?:[（(]\s*(\d{1,3}(?:\s*[-–—]\s*\d{1,3})?)\s*[)）])?/);
    if (!mm) continue;
    const magazine = mm[1].trim();
    const year = Number(mm[2]);
    const issue = normIssue(mm[3]);
    // [J] 之前：作者列表. 标题
    const head = line.slice(0, line.indexOf('[J]')).replace(/^\[?\s*\d+\s*\]?\s*/, '').trim();
    const dot = head.search(/[.．]\s/);
    const title = (dot >= 0 ? head.slice(dot + 1) : head).trim().replace(/^[.．]\s*/, '');
    if (!title || !year) continue;
    out.push({ title, magazine, year, issue, page: (rest.match(/[:：]\s*([\d\-–—,，\s]+)\.?$/) || [])[1] || null, raw: line });
  }
  return out;
}

// 格式 B：标签式（NoteExpress / EndNote / RefWorks / 知网「自定义」等），多行一条
//   题名: 创客教育为什么要强调"造"
//   作者: 谢作如
//   来源: 中小学信息技术教育
//   年: 2015
//   期: 06
const FIELD_MAP = [
  ['title', /^(题名|标题|篇名|文献题名|Title|TI|标题-题名)$/i],
  ['author', /^(作者|责任者|Author|AU)$/i],
  ['magazine', /^(来源|刊名|期刊|文献来源|Source|JO|出处)$/i],
  ['year', /^(年|年份|发表年|Year|PY)$/i],
  ['issue', /^(期|期号|卷期|Issue|期-期号)$/i],
];
function parseLabeled(text) {
  const out = [];
  let cur = {};
  const flush = () => {
    if (cur.title && (cur.year || cur.magazine)) {
      out.push({
        title: cur.title, magazine: cur.magazine || null,
        year: cur.year ? Number((String(cur.year).match(/(\d{4})/) || [])[1]) : null,
        issue: normIssue(cur.issue), page: cur.page || null, raw: null,
      });
    }
    cur = {};
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const m = line.match(/^([^:：\-]{1,12})\s*[:：\-]\s*(.+)$/);
    if (!m) continue;
    const key = m[1].trim();
    const hit = FIELD_MAP.find(([, re]) => re.test(key));
    if (hit) {
      if (hit[0] === 'title' && cur.title) flush();   // 新一条开始
      cur[hit[0]] = m[2].trim();
    }
  }
  flush();
  return out;
}

// 格式 C：制表符 / 多空格分隔的一行一条（知网「自定义」导出常见）
//   创客教育为什么要强调"造"\t谢作如\t中小学信息技术教育\t2015-06-15
function parseTabbed(text) {
  const out = [];
  const lines = text.split(/\r?\n/);
  const seen = new Set();
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, '');
    if (!line.trim()) continue;
    const cells = line.split(/\t|(?:\s{2,})/).map(s => s.trim()).filter(Boolean);
    if (cells.length < 3) continue;
    // 找日期格：2015-06-15 / 2015/6 / 2015年6月
    let dateIdx = -1, year = null, month = null;
    for (let i = 0; i < cells.length; i++) {
      const m = cells[i].match(/^(20\d{2})\s*[-/年]\s*0?(\d{1,2})/);
      if (m) { dateIdx = i; year = Number(m[1]); month = Number(m[2]); break; }
    }
    if (dateIdx < 0) continue;
    // 刊名：日期格左边紧邻的非人名格（含「教育/技术/学报/杂志/研究」等关键词，或最长的中文格）
    let magazine = null;
    for (let i = dateIdx - 1; i >= 0; i--) {
      const c = cells[i];
      if (/[\u4e00-\u9fa5]/.test(c) && c.length >= 3 && !/^[\u4e00-\u9fa5]{2,3}$/.test(c)) { magazine = c; break; }
    }
    const title = cells[0];
    if (!title || !year) continue;
    const key = normTitle(title) + '|' + year;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ title, magazine, year, issue: month ? '第' + month + '期' : null, page: null, raw: line });
  }
  return out;
}

function parseExport(text) {
  const a = parseLabeled(text);
  const b = parseGBT7714(text);
  const c = parseTabbed(text);
  // 标签式最准，其次 GB/T 7714，最后制表符
  const merged = [];
  const seen = new Set();
  for (const arr of [a, b, c]) {
    for (const it of arr) {
      const key = normTitle(it.title) + '|' + (it.year || '');
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(it);
    }
  }
  return merged;
}

// ── 与文章索引匹配 ────────────────────────────────────────────
function matchToArticles(recs, articles) {
  const idx = new Map();
  for (const a of articles) {
    const k = normTitle(a.title);
    if (!idx.has(k)) idx.set(k, []);
    idx.get(k).push(a);
  }
  const hits = [], misses = [];
  for (const r of recs) {
    const k = normTitle(r.title);
    let cands = idx.get(k) || [];
    if (!cands.length) {
      // 前缀兜底：文集标题可能被文件名截断或带后缀
      for (const [ak, arr] of idx) {
        if (ak.length >= 6 && k.length >= 6 && (ak.startsWith(k) || k.startsWith(ak))) { cands = arr; break; }
      }
    }
    if (!cands.length) { misses.push(r); continue; }
    let pick = cands[0];
    if (cands.length > 1) {
      // 用年 / 刊名消歧
      pick = cands.find(c => r.year && c.year === r.year) ||
             cands.find(c => r.magazine && c.magazine === r.magazine) || cands[0];
    }
    const patch = {};
    if (r.issue && !pick.issue) patch.issue = r.issue;
    if (r.year && !pick.year) patch.year = r.year;
    if (r.magazine && !pick.magazine) patch.magazine = r.magazine;
    hits.push({ article: pick, rec: r, patch });
  }
  return { hits, misses };
}

// ══════════════════════════════════════════════════════════════
// part 2 · 输出
// ══════════════════════════════════════════════════════════════
function resultToOverrides(hits) {
  const out = {};
  const base = a => a.path.split('/').pop();
  for (const h of hits) {
    if (!Object.keys(h.patch).length) continue;
    const k = base(h.article);
    out[k] = Object.assign({}, out[k], h.patch);
  }
  return out;
}

function writeResult(hits, misses, extra) {
  const ov = resultToOverrides(hits);
  const payload = Object.assign({ generatedAt: new Date().toISOString(), overrides: ov, hits: hits.length, misses: misses.length }, extra || {});
  fs.writeFileSync(OUT, JSON.stringify(payload, null, 2) + '\n', 'utf8');
  return ov;
}

function reportMisses(misses, limit) {
  if (!misses.length) return;
  rule('未匹配上的题录（' + misses.length + ' 条）');
  misses.slice(0, limit || 30).forEach(m => {
    say('  · ' + (m.year || '?') + ' ' + (m.magazine || '?') + ' | ' + m.title);
  });
  if (misses.length > (limit || 30)) say('  …… 其余 ' + (misses.length - (limit || 30)) + ' 条见 ' + OUT);
}

// ══════════════════════════════════════════════════════════════
// part 3 · CDP（auto 模式，实验性）
// ══════════════════════════════════════════════════════════════
async function httpJSON(url) {
  const r = await fetch(url, { signal: AbortSignal.timeout(5000) });
  return r.json();
}

async function cdpConnect(port) {
  let list;
  try { list = await httpJSON('http://127.0.0.1:' + port + '/json'); }
  catch (e) {
    die('连不上 Chrome 调试端口 ' + port + '\n' +
        '  请先完全退出 Chrome（⌘Q），再另开一个专用实例：\n' +
        '  open -na "Google Chrome" --args --remote-debugging-port=' + port + ' --user-data-dir="$HOME/.cnki-profile"\n');
  }
  const page = list.find(t => t.type === 'page' && !/^devtools:/.test(t.url || ''));
  if (!page) die('调试端口上没有可用的标签页');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = () => rej(new Error('WebSocket 连接失败'));
  });
  const cdp = { ws, seq: 0, pending: new Map(), waiters: new Map() };
  ws.onmessage = ev => {
    let m; try { m = JSON.parse(ev.data); } catch (e) { return; }
    if (m.id != null && cdp.pending.has(m.id)) {
      const { res, rej } = cdp.pending.get(m.id); cdp.pending.delete(m.id);
      m.error ? rej(new Error(m.error.message)) : res(m.result);
    } else if (m.method && cdp.waiters.has(m.method)) {
      cdp.waiters.get(m.method).forEach(f => f(m.params));
      cdp.waiters.delete(m.method);
    }
  };
  cdp.send = (method, params) => new Promise((res, rej) => {
    const id = ++cdp.seq;
    cdp.pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params: params || {} }));
  });
  cdp.once = (event, ms) => new Promise(res => {
    const arr = cdp.waiters.get(event) || [];
    arr.push(res); cdp.waiters.set(event, arr);
    setTimeout(() => res(null), ms || 20000);
  });
  await cdp.send('Page.enable');
  await cdp.send('Runtime.enable');
  return cdp;
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function evalJS(cdp, expr) {
  const r = await cdp.send('Runtime.evaluate', {
    expression: expr, returnByValue: true, awaitPromise: true,
  });
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.text + ' ' + (r.exceptionDetails.exception && r.exceptionDetails.exception.description || ''));
  return r.result.value;
}

async function navigate(cdp, url, settleMs) {
  const loaded = cdp.once('Page.loadEventFired', 25000);
  await cdp.send('Page.navigate', { url });
  await loaded;
  await sleep(settleMs == null ? 2000 : settleMs);
}

function ask(q) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise(res => rl.question(q, ans => { rl.close(); res(ans); }));
}

// 知网篇名检索：清掉标点，只留词
function cleanQuery(title) {
  return String(title)
    .replace(/[_]+/g, ' ')
    .replace(/[“”"‘’《》【】（）()\[\]{}<>—－、，。！？：；·|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

// 从详情页整页文本里抠「刊名 + 年 + 期」（宽松正则，不依赖具体 DOM）
// 知网详情页常见形态：`中小学信息技术教育,2015,(06):70-70` 或 `2015年06期`
function extractFromDetailText(text) {
  const t = text.replace(/\u00a0/g, ' ');
  let magazine = null, year = null, issue = null;
  let m = t.match(/([\u4e00-\u9fa5][\u4e00-\u9fa5A-Za-z·]{2,22})\s*[,，]\s*(20\d{2})\s*[,，]\s*[（(]?\s*(\d{1,3})\s*[)）]?/);
  if (m) { magazine = m[1]; year = Number(m[2]); issue = normIssue(m[3]); }
  if (!issue) {
    const m2 = t.match(/(20\d{2})\s*年\s*(?:第\s*)?0?(\d{1,3})\s*期/);
    if (m2) { year = year || Number(m2[1]); issue = normIssue(m2[2]); }
  }
  return { magazine, year, issue };
}

async function autoMode(port, limit, fromFile) {
  const articles = loadArticles();
  let todo;
  if (fromFile) {
    const wanted = new Set(JSON.parse(fs.readFileSync(fromFile, 'utf8')));
    todo = pending(articles).filter(a => wanted.has(a.path.split('/').pop()));
  } else {
    todo = pending(articles);
  }
  if (limit) todo = todo.slice(0, Number(limit));

  say('待抓取 ' + todo.length + ' 条。');
  const cdp = await cdpConnect(port);
  say('已连上 Chrome。正在打开知网首页……');
  await navigate(cdp, 'https://www.cnki.net/', 3000);

  const title = await evalJS(cdp, 'document.title');
  say('当前页面：' + title);
  say('\n如果浏览器里出现了滑块验证，请手动拖一下完成验证。');
  await ask('完成后按回车继续…');

  const results = [];
  const errors = [];
  let i = 0;
  for (const a of todo) {
    i++;
    const q = cleanQuery(a.title);
    const url = 'https://kns.cnki.net/kns8s/defaultresult/index?korder=TI&kw=' + encodeURIComponent(q);
    process.stdout.write('  [' + i + '/' + todo.length + '] ' + a.title.slice(0, 28) + ' … ');
    try {
      await navigate(cdp, url, 3500);
      const info = await evalJS(cdp, `(() => {
        const hrefs = [...document.querySelectorAll('a')]
          .map(x => x.href).filter(h => /\\/kcms2?\\/.*?(abstract|detail)/i.test(h));
        const body = (document.body ? document.body.innerText : '').slice(0, 400);
        return JSON.stringify({ href: hrefs[0] || null, bodyLen: body.length, head: body.slice(0, 120) });
      })()`);
      const j = JSON.parse(info);
      if (!j.href) {
        // 可能是验证页或空结果
        say('未拿到结果链接（页面 ' + j.bodyLen + ' 字符：' + j.head.replace(/\s+/g, ' ').slice(0, 60) + '）');
        errors.push({ file: a.path.split('/').pop(), title: a.title, reason: 'no-result-link', head: j.head });
        continue;
      }
      await navigate(cdp, j.href, 3000);
      const txt = await evalJS(cdp, 'document.body ? document.body.innerText : ""');
      const got = extractFromDetailText(txt);
      if (!got.issue) {
        say('详情页没读到期号');
        errors.push({ file: a.path.split('/').pop(), title: a.title, reason: 'no-issue', detailUrl: j.href });
        continue;
      }
      say('→ ' + [got.year, got.issue, got.magazine].filter(Boolean).join(' · '));
      results.push({ file: a.path.split('/').pop(), title: a.title, year: got.year, issue: got.issue, magazine: got.magazine, detailUrl: j.href });
      fs.writeFileSync(PROGRESS, JSON.stringify(results, null, 2), 'utf8');
    } catch (e) {
      say('ERR ' + e.message);
      errors.push({ file: a.path.split('/').pop(), title: a.title, reason: e.message });
    }
  }

  const ov = {};
  for (const r of results) {
    ov[r.file] = {};
    if (r.issue) ov[r.file].issue = r.issue;
    if (r.year) ov[r.file].year = r.year;
    if (r.magazine) ov[r.file].magazine = r.magazine;
  }
  fs.writeFileSync(OUT, JSON.stringify({ generatedAt: new Date().toISOString(), mode: 'auto', overrides: ov, results, errors }, null, 2) + '\n', 'utf8');
  rule('结果');
  say('成功 ' + results.length + ' 条，失败 ' + errors.length + ' 条');
  say('已写入 ' + OUT + '（含 errors，便于反馈修正）');
  say('合并进 overrides：node site/cnki_issues.js merge');
  try { cdp.ws.close(); } catch (e) {}
}

// ══════════════════════════════════════════════════════════════
// 命令
// ══════════════════════════════════════════════════════════════
function cmdTodo() {
  const list = loadArticles();
  const miss = pending(list);
  rule('待补期号 ' + miss.length + ' 篇 / 共 ' + list.length + ' 篇');
  const groups = new Map();
  for (const a of miss) {
    const k = (a.year || '?') + ' · ' + (a.magazine || '?');
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(a);
  }
  const sorted = [...groups.entries()].sort((a, b) => b[1].length - a[1].length);
  for (const [k, arr] of sorted) say('  ' + String(arr.length).padStart(3) + ' 篇   ' + k);
  say('\n共 ' + sorted.length + ' 个「年 · 刊」组。');
}

function cmdParse(files) {
  if (!files.length) die('用法：node site/cnki_issues.js parse <题录文本文件> [更多文件…]');
  const articles = loadArticles();
  let all = [];
  for (const f of files) {
    const p = path.resolve(f.replace(/^~(?=\/)/, os.homedir()));
    if (!fs.existsSync(p)) die('找不到文件：' + p);
    const txt = fs.readFileSync(p, 'utf8');
    const recs = parseExport(txt);
    say('  ' + path.basename(p) + '：解析出 ' + recs.length + ' 条题录');
    all = all.concat(recs);
  }
  if (!all.length) {
    die('一条都没解析出来。请确认导出格式是知网的「参考文献」或「自定义」，并检查文件是否为空。');
  }
  const { hits, misses } = matchToArticles(all, articles);
  const ov = writeResult(hits, misses, { mode: 'parse' });

  rule('匹配结果');
  const withIssue = hits.filter(h => h.patch.issue);
  say('  解析题录      ' + all.length + ' 条');
  say('  匹配到文章    ' + hits.length + ' 条');
  say('  其中新增期号  ' + withIssue.length + ' 条');
  say('  未匹配        ' + misses.length + ' 条');
  reportMisses(misses);

  rule('可直接合并进 site/overrides.json 的片段');
  say(JSON.stringify(ov, null, 2));
  say('\n完整结果已写入 ' + OUT);
  say('合并进 overrides：node site/cnki_issues.js merge');
}

function cmdMerge() {
  if (!fs.existsSync(OUT)) die('还没有 ' + OUT + '，先跑 parse 或 auto。');
  const res = JSON.parse(fs.readFileSync(OUT, 'utf8'));
  const ov = res.overrides || {};
  const keys = Object.keys(ov);
  if (!keys.length) die('结果里没有可合并的条目。');
  const cur = JSON.parse(fs.readFileSync(OVERRIDES, 'utf8'));
  const bak = OVERRIDES + '.bak-' + new Date().toISOString().replace(/[:.]/g, '').slice(0, 15);
  fs.copyFileSync(OVERRIDES, bak);
  let changed = 0;
  for (const k of keys) {
    if (!cur[k]) cur[k] = {};
    for (const [f, v] of Object.entries(ov[k])) {
      if (v != null && cur[k][f] !== v) { cur[k][f] = v; changed++; }
    }
  }
  fs.writeFileSync(OVERRIDES, JSON.stringify(cur, null, 2) + '\n', 'utf8');
  rule('合并完成');
  say('  ' + keys.length + ' 条记录、' + changed + ' 个字段写入 overrides.json');
  say('  备份：' + bak);
  say('\n接着跑一次构建让结果生效：');
  say('  python site/build.py');
}

function cmdHelp() {
  say(`
知网期号补全工具

  node site/cnki_issues.js todo                       列出还缺期号的条目
  node site/cnki_issues.js parse <文件…>              解析知网导出的题录文本（推荐）
  node site/cnki_issues.js auto [--port 9222] [--limit N] [--from <文件>]
                                                      CDP 驱动你的 Chrome 逐条抓（实验性）
  node site/cnki_issues.js merge                      合并结果进 overrides.json（自动备份）

parse 怎么用：
  1) 打开 https://kns.cnki.net/ ，检索式：AU=谢作如
  2) 结果页全选 →「导出与分析」→「导出文献」→ 选「参考文献」格式 → 复制
  3) 存成文本文件，例如 ~/Desktop/cnki.txt
  4) node site/cnki_issues.js parse ~/Desktop/cnki.txt
  支持格式：GB/T 7714 参考文献、标签式（题名/来源/年/期）、制表符导出。

auto 怎么用：
  1) ⌘Q 完全退出 Chrome，再开专用实例：
     open -na "Google Chrome" --args --remote-debugging-port=9222 --user-data-dir="$HOME/.cnki-profile"
  2) node site/cnki_issues.js auto --limit 3
  3) 首次出现滑块请手动拖过，按回车继续
`);
}

(async () => {
  switch (cmd) {
    case 'todo': cmdTodo(); break;
    case 'parse': cmdParse(opt._); break;
    case 'merge': cmdMerge(); break;
    case 'auto':
      if (Number(process.version.slice(1).split('.')[0]) < 21) die('auto 模式需要 Node ≥ 21（内置 WebSocket），当前 ' + process.version);
      await autoMode(opt.port || 9222, opt.limit, opt.from);
      break;
    case 'help': default: cmdHelp(); break;
  }
})().catch(e => { console.error('\n✗ ' + (e && e.stack || e)); process.exit(1); });
