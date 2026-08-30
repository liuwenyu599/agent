#!/bin/bash

# ============================================================
# judicial_app GitHub 一键推送脚本
#
# 项目：
#   /home/lwy/judicial_app
#
# GitHub：
#   git@github.com:liuwenyu599/agent.git
#
# 当前分支：
#   app
#
# 注意：
#   GitHub SSH 使用 ssh.github.com:443
#   专用密钥：
#   ~/.ssh/github_ed25519
#
# 第一次使用前：
#   1. 确保 ~/.ssh/github_lab2_ed25519 已存在
#   2. 将 ~/.ssh/github_lab2_ed25519.pub 添加到 GitHub
#      Settings → SSH and GPG keys → New SSH key
# ============================================================

set -e

PROJECT_DIR="/home/lwy/judicial_app"
BRANCH="app"
REMOTE="origin"
SSH_KEY="$HOME/.ssh/github_lab2_ed25519"

echo
echo "============================================================"
echo "        Judicial AI App → GitHub 推送工具"
echo "============================================================"
echo

# ------------------------------------------------------------
# 1. 检查项目目录
# ------------------------------------------------------------

if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ 项目目录不存在：$PROJECT_DIR"
    exit 1
fi

cd "$PROJECT_DIR"

echo "📁 项目目录：$PROJECT_DIR"
echo "🌿 当前目标分支：$BRANCH"
echo

# ------------------------------------------------------------
# 2. 检查 SSH 密钥
# ------------------------------------------------------------

echo "🔑 检查 GitHub SSH 密钥..."

if [ ! -f "$SSH_KEY" ]; then
    echo
    echo "❌ 没有找到 GitHub 专用 SSH 密钥："
    echo "   $SSH_KEY"
    echo
    echo "如果这是第一次连接 GitHub，请先建立密钥："
    echo
    echo "   ssh-keygen -t ed25519 -f ~/.ssh/github_lab2_ed25519 -C \"finestation-github\""
    echo
    echo "然后查看公钥："
    echo
    echo "   cat ~/.ssh/github_lab2_ed25519.pub"
    echo
    echo "把公钥添加到 GitHub："
    echo "   GitHub → Settings → SSH and GPG keys → New SSH key"
    echo
    echo "添加完成后，再运行："
    echo
    echo "   ./push.sh"
    echo
    exit 1
fi

echo "✅ 找到 GitHub SSH 密钥：$SSH_KEY"
echo

# ------------------------------------------------------------
# 3. 检查 SSH 配置
# ------------------------------------------------------------

echo "🔧 检查 SSH 配置..."

if ! grep -q "Host github.com" "$HOME/.ssh/config" 2>/dev/null; then
    echo
    echo "⚠️ ~/.ssh/config 中没有找到 GitHub 配置。"
    echo
    echo "建议配置为："
    echo
    echo "Host github.com"
    echo "    HostName ssh.github.com"
    echo "    User git"
    echo "    Port 443"
    echo "    IdentityFile ~/.ssh/github_lab2_ed25519"
    echo "    IdentitiesOnly yes"
    echo
    exit 1
fi

echo "✅ SSH 配置存在"
echo

# ------------------------------------------------------------
# 4. 测试 GitHub SSH
# ------------------------------------------------------------

echo "🌐 测试 GitHub SSH 连接..."
echo

if ! ssh -T -o ConnectTimeout=10 git@github.com 2>&1 | grep -q "successfully authenticated"; then
    echo
    echo "❌ GitHub SSH 认证失败。"
    echo
    echo "请检查："
    echo "1. ~/.ssh/github_lab2_ed25519 是否存在"
    echo "2. github_lab2_ed25519.pub 是否已经添加到 GitHub"
    echo "3. ~/.ssh/config 是否正确"
    echo
    exit 1
fi

echo "✅ GitHub SSH 认证成功"
echo

# ------------------------------------------------------------
# 5. 检查 Git 仓库
# ------------------------------------------------------------

if [ ! -d ".git" ]; then
    echo "❌ 当前目录不是 Git 仓库：$PROJECT_DIR"
    exit 1
fi

echo "✅ Git 仓库正常"
echo

# ------------------------------------------------------------
# 6. 检查远程仓库
# ------------------------------------------------------------

CURRENT_REMOTE=$(git remote get-url "$REMOTE" 2>/dev/null || true)

if [ "$CURRENT_REMOTE" != "git@github.com:liuwenyu599/agent.git" ]; then
    echo
    echo "⚠️ GitHub 远程仓库地址不正确："
    echo "   当前：$CURRENT_REMOTE"
    echo "   应为：git@github.com:liuwenyu599/agent.git"
    echo
    exit 1
fi

echo "✅ GitHub 仓库：$CURRENT_REMOTE"
echo

# ------------------------------------------------------------
# 7. 检查当前分支
# ------------------------------------------------------------

CURRENT_BRANCH=$(git branch --show-current)

if [ "$CURRENT_BRANCH" != "$BRANCH" ]; then
    echo
    echo "⚠️ 当前分支不是 $BRANCH"
    echo "   当前分支：$CURRENT_BRANCH"
    echo
    read -p "是否切换到 $BRANCH？[y/N] " ANSWER

    if [[ "$ANSWER" =~ ^[Yy]$ ]]; then
        git switch "$BRANCH"
    else
        echo "❌ 已取消。"
        exit 1
    fi
fi

echo "🌿 当前分支：$BRANCH"
echo

# ------------------------------------------------------------
# 8. 检查敏感文件
# ------------------------------------------------------------

echo "🔍 检查可能的敏感文件..."

SENSITIVE_FILES=$(find . \
    -type f \
    \( \
        -name ".env" \
        -o -name ".env.*" \
        -o -name "*.key" \
        -o -name "*.pem" \
        -o -name "*.p12" \
        -o -name "*.pfx" \
    \) \
    -not -path "./.git/*" 2>/dev/null || true)

if [ -n "$SENSITIVE_FILES" ]; then
    echo
    echo "⚠️ 发现可能的敏感文件："
    echo "$SENSITIVE_FILES"
    echo
    echo "请检查这些文件是否应该上传 GitHub。"
    echo
    read -p "仍然继续？[y/N] " ANSWER

    if [[ ! "$ANSWER" =~ ^[Yy]$ ]]; then
        echo "❌ 已取消。"
        exit 1
    fi
else
    echo "✅ 没发现明显的密钥文件"
fi

echo

# ------------------------------------------------------------
# 9. 显示代码变化
# ------------------------------------------------------------

echo "📋 检查代码变化..."

git status --short

echo

# ------------------------------------------------------------
# 10. 没有变化就退出
# ------------------------------------------------------------

if [ -z "$(git status --porcelain)" ]; then
    echo "✅ 工作区没有新的修改。"
    echo "   GitHub 已经是最新状态。"
    echo
    exit 0
fi

# ------------------------------------------------------------
# 11. 添加文件
# ------------------------------------------------------------

echo "📦 添加修改..."

git add .

echo
echo "即将提交以下文件："
echo

git status --short

echo

# ------------------------------------------------------------
# 12. 输入提交说明
# ------------------------------------------------------------

read -p "请输入本次提交说明（直接回车使用默认）： " COMMIT_MSG

if [ -z "$COMMIT_MSG" ]; then
    COMMIT_MSG="Update judicial assistant app"
fi

echo
echo "📝 提交：$COMMIT_MSG"

git commit -m "$COMMIT_MSG"

echo

# ------------------------------------------------------------
# 13. 推送
# ------------------------------------------------------------

echo "🚀 推送到 GitHub..."
echo
echo "   仓库：$CURRENT_REMOTE"
echo "   分支：$BRANCH"
echo

git push

echo
echo "============================================================"
echo "                    ✅ 推送成功"
echo "============================================================"
echo
echo "GitHub："
echo "https://github.com/liuwenyu599/agent"
echo
echo "分支：$BRANCH"
echo
