// 站点配置：部署到 Cloudflare 时，把 PDF_BASE 改成 R2 桶的公开访问域名
// 本地预览时保持为空（页面通过相对路径 ../../ 访问仓库里的 PDF）
window.ARTICLES_CONFIG = {
  // 例: "https://pub-xxxxxxxxxxxxxxxx.r2.dev" 或 "https://pdf.你的域名.com"
  PDF_BASE: ""
};
