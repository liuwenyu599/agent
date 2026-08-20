#!/bin/bash
set -e

REPO="https://github.com/liuwenyu599/agent.git"
BRANCH="main"

echo "===== judicial-ai → GitHub ====="

# 确认当前目录确实是 Git 仓库
if [ ! -d ".git" ]; then
    echo "错误：当前目录不是 Git 仓库"
    echo "请先进入 judicial-ai："
    echo "cd ~/judicial-ai"
    exit 1
fi

echo "[1/5] 当前仓库："
git remote -v
echo

# 设置 GitHub 远程仓库
echo "[2/5] 设置 GitHub remote..."
if git remote get-url origin >/dev/null 2>&1; then
    git remote set-url origin "$REPO"
else
    git remote add origin "$REPO"
fi

# 使用 main
echo "[3/5] 设置分支 main..."
git branch -M "$BRANCH"

# 提交当前服务器上的全部修改
echo "[4/5] 提交当前 judicial-ai..."
git add .

if git diff --cached --quiet; then
    echo "没有新的修改需要提交"
else
    git commit -m "Update judicial-ai"
fi

# 强制以服务器当前版本覆盖 GitHub
echo "[5/5] 强制推送到 GitHub..."
git push -u origin "$BRANCH" --force

echo
echo "================================"
echo "推送完成"
echo "GitHub: $REPO"
echo "================================"