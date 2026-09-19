// 站点配置（唯一源文件，构建时会复制到 site/dist/）
// PDF_BASE：PDF 文件的存放位置
//   - 留空        → 使用仓库内相对路径，本地预览用（根目录访问时直接读仓库里的 PDF）
//   - R2 域名     → 部署到 Cloudflare 后必填，如 "https://pub-xxxxxxxx.r2.dev"
window.ARTICLES_CONFIG = {
  PDF_BASE: ""
};
