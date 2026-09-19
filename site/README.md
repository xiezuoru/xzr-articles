# 谢作如文集网站

把本仓库的 PDF 文章变成一个可搜索、可筛选、可在线阅读的网站。
纯静态，无数据库，线上地址：<https://xzr.quickform.cc/>

## 线上是怎么部署的

**Cloudflare Pages 直接连 GitHub 仓库构建**，部署目录 = **仓库根目录**：

- 页面（`index.html` / `reader.html` / `config.js`）在根目录，访问根路径即为首页
- PDF 也在仓库里，和网页同域，`config.js` 里的 `PDF_BASE` **保持为空**即可正常阅读
- 索引数据（`site/dist/articles.json`、`articles.js`、`thumbs/`）**必须提交进 git**——
  Cloudflare 从仓库拉代码构建，仓库里没有的文件线上就取不到

> 注意：Cloudflare 对不存在的路径会返回 **200 的兜底 HTML**，所以网页不能靠状态码
> 判断文件是否存在，代码里改为校验 `Content-Type` 与 JSON 结构。

## 目录结构

```
xzr-articles/
├── index.html                 # ★ 网站首页（卡片墙 + 列表 + 搜索筛选）
├── reader.html                # ★ PDF 在线阅读器（PDF.js）
├── config.js                  # ★ 配置：PDF_BASE（同域部署时留空）
├── vendor/                    # PDF.js 自带副本（阅读器用，不依赖 CDN）
├── 2003年度/ … 2026年度/      # 文章 PDF（按年份）
├── 中国信息技术教育-专栏文章-对话/ 等   # 文章 PDF（按专栏）
└── site/
    ├── build.py               # 索引构建：扫描 PDF → articles.json/articles.js + 缩略图
    ├── overrides.json         # 手动修正个别文章的元数据
    ├── deploy.sh              # 备用部署方式（wrangler + R2，一般用不到）
    └── dist/                  # 索引数据目录（数据进 git，网页副本不进）
        ├── articles.json      # 构建生成的文章索引（进 git）
        ├── articles.js        # 同上，JS 版，供 file:// 直接打开时使用（进 git）
        ├── thumbs/            # 构建生成的封面缩略图（进 git）
        └── index.html 等       # 由根目录复制而来，不进 git（含 vendor/）
```

> 两个容易踩的坑：
> 1. **索引数据必须进 git**。Cloudflare 从 GitHub 构建，`.gitignore` 掉的构建产物线上取不到，首页会提示"索引加载失败"。
> 2. **阅读器链接相对页面、而不是索引数据目录**。`index.html` 与 `reader.html` 始终同级（仓库根目录 / 构建后的 dist），若把数据目录 `site/dist/` 拼进链接，线上会指向仓库里并不存在的路径，点击文章会直接被打回首页。
> 3. PDF.js 用的是 `vendor/` 里的自带副本（国内网络、微信内置浏览器访问 cdnjs 常超时），缺失时才回退 CDN。

## 日常新增文章

1. 把新 PDF 放进对应目录（如 `2026年度/`），命名沿用惯例：`刊物-标题_作者.pdf`
2. 重新生成索引：
   ```bash
   cd ~/Documents/GitHub/xzr-articles/site && python3 build.py
   ```
   （首次使用先装依赖：`pip3 install PyMuPDF`）
3. 提交并推送，Cloudflare 会自动重新部署：
   ```bash
   cd ~/Documents/GitHub/xzr-articles
   git add -A && git commit -m "新增文章：xxx" && git push
   ```

标题/年份/刊物解析不对时，在 `site/overrides.json` 里按文件名写死字段，再跑一次 `build.py`。

## 本地预览

```bash
cd ~/Documents/GitHub/xzr-articles
python3 -m http.server 8000
# 浏览器打开 http://localhost:8000/
```

也可以**直接双击根目录的 `index.html`**：浏览、搜索、筛选、封面都能用
（页面会自动改用 `articles.js` 载入索引，绕开浏览器对 file:// 读取本地 JSON 的限制）。
只有「在线阅读器」在 file:// 下受浏览器安全策略限制，需用上面的本地服务器方式，
或点阅读器右上角「下载 PDF」用浏览器自带阅读器查看。

## 可选：把 PDF 搬到 R2

现在的做法是把 PDF 一起放进 Pages 部署，简单但有两点限制：

- 每次部署要把全部 PDF（约 1.4G）重新上传一遍，较慢
- Pages 单个文件上限 **25 MiB**，将来出现更大的 PDF 会导致部署失败

需要时再迁到 R2（10 GB 免费、流量免费）：

1. `wrangler r2 bucket create xzr-articles-pdf`，开启公开访问拿到 `https://pub-xxxx.r2.dev`
2. 把域名填进根目录 `config.js` 的 `PDF_BASE`（结尾不要斜杠）
3. 配 R2 的 CORS，允许站点域名跨域读取：
   ```bash
   wrangler r2 bucket cors put xzr-articles-pdf --file cors.json
   ```
   `cors.json` 内容：`[{"AllowedOrigins":["https://xzr.quickform.cc"],"AllowedMethods":["GET","HEAD"],"AllowedHeaders":["*"],"MaxAgeSeconds":3600}]`
4. 用 rclone 把 PDF 同步到桶里（`site/deploy.sh` 里有现成命令）

## 访问统计

Cloudflare 控制台 → Workers & Pages → 对应项目 → **Web Analytics** 开启即可（免费，无需改代码）。
