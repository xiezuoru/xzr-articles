#!/bin/bash
# xzr-articles 部署脚本：构建索引 → 同步 PDF 到 R2 → 部署 Pages
# 首次使用前请先完成 README.md 中的「一次性初始化」
set -e
cd "$(dirname "$0")"

BUCKET="xzr-articles-pdf"
PROJECT="xzr-articles"
RCLONE_REMOTE="r2"          # rclone 配置中的 remote 名称
PYTHON="$HOME/.workbuddy/binaries/python/envs/default/bin/python"

echo "==> 1/3 构建索引和缩略图"
"$PYTHON" build.py

echo "==> 2/3 同步 PDF 到 R2（增量）"
rclone sync .. "r2:$BUCKET" \
  --include "*.pdf" \
  --exclude "site/**" \
  --s3-no-check-bucket \
  --transfers 8 --progress

echo "==> 3/3 部署 Pages"
wrangler pages deploy dist --project-name="$PROJECT"

echo "完成！访问 https://$PROJECT.pages.dev"
