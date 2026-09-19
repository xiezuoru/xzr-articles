# 谢作如文集网站

把本仓库的 PDF 文章变成一个可搜索、可筛选、可在线阅读的网站。
纯静态，无数据库：网页托管在 **Cloudflare Pages**，PDF 文件托管在 **Cloudflare R2**。

## 目录结构

```
xzr-articles/
├── 2003年度/ … 2026年度/      # 文章 PDF（按年份）
├── 中国信息技术教育-专栏文章-对话/ 等   # 文章 PDF（按专栏）
└── site/
    ├── build.py               # 索引构建脚本（扫描 PDF → articles.json + 缩略图）
    ├── overrides.json         # 手动修正个别文章的元数据
    ├── deploy.sh              # 一键部署（构建 → 同步 R2 → 部署 Pages）
    └── dist/                  # 网站本体（构建产物，勿手改）
        ├── index.html         # 首页（卡片 + 列表 + 搜索筛选）
        ├── reader.html        # PDF 在线阅读器（PDF.js）
        ├── config.js          # 配置：PDF_BASE 指向 R2 公开域名
        ├── articles.json      # 构建生成的文章索引
        └── thumbs/            # 构建生成的封面缩略图
```

## 一次性初始化（约 10 分钟）

1. **安装工具**
   ```bash
   npm install -g wrangler     # Cloudflare 官方 CLI
   brew install rclone         # 用于增量同步 PDF 到 R2
   wrangler login              # 浏览器登录 Cloudflare 账号
   ```

2. **创建 R2 桶并开公开访问**
   ```bash
   wrangler r2 bucket create xzr-articles-pdf
   wrangler r2 bucket dev-url enable xzr-articles-pdf   # 得到 https://pub-xxxx.r2.dev
   ```
   把得到的域名填进 `dist/config.js` 的 `PDF_BASE`（不要结尾斜杠）。

3. **配置 R2 的 CORS**（允许 Pages 域名跨域加载 PDF）
   把下面的 JSON 存为 `cors.json`（域名换成你的 Pages 域名）：
   ```json
   [{"AllowedOrigins": ["https://xzr-articles.pages.dev"],
     "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"], "MaxAgeSeconds": 3600}]
   ```
   ```bash
   wrangler r2 bucket cors put xzr-articles-pdf --file cors.json
   ```

4. **配置 rclone**（`rclone config` 新建名为 `r2` 的 remote）
   - type: `s3`，provider: `Cloudflare`
   - access_key_id / secret_access_key：Cloudflare 控制台 → R2 → Manage R2 API Tokens 创建
   - endpoint: `https://<账户ID>.r2.cloudflarestorage.com`

5. **创建 Pages 项目并首次部署**
   ```bash
   cd site
   ./deploy.sh
   ```

6. **开启访问统计**：Cloudflare 控制台 → Workers & Pages → xzr-articles →
   Web Analytics → 开启（免费，无需改代码）。

## 日常新增文章（三步）

1. 把新 PDF 放进对应目录（如 `2026年度/`）
2. 命名尽量保持惯例：`刊物-标题_作者.pdf` 或 `2026年3期-标题_作者.pdf`
3. 运行 `./deploy.sh`（或在终端执行 `cd site && ./deploy.sh`）

如果某篇文章标题/年份/刊物解析不对，在 `overrides.json` 里按文件名修正后重新部署。

## 本地预览

```bash
cd xzr-articles 仓库根目录
python3 -m http.server 8000
# 浏览器打开 http://localhost:8000/site/dist/
```

## 自定义域名（可选）

Pages 项目 → Custom domains → 绑定自己的域名（如 `articles.example.com`），
R2 桶也可绑 `pdf.example.com` 替代 r2.dev 域名（记得同步改 config.js 和 CORS）。
注意：绑自有域名且主要面向国内访问时，域名需完成 ICP 备案才能有较好的国内速度。
