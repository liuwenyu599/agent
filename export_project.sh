#!/bin/bash

cd /home/lwy/judicial-ai || exit 1

OUT=ai_code.txt

{
echo "============================================================"
echo "司法智能写作助手 - 项目代码上下文"
echo "============================================================"
echo
echo "生成时间:"
date
echo

echo "============================================================"
echo "SYSTEM"
echo "============================================================"
uname -a
echo

echo "============================================================"
echo "PYTHON"
echo "============================================================"
python --version 2>/dev/null || true
echo

echo "============================================================"
echo "NODE"
echo "============================================================"
node -v 2>/dev/null || true
npm -v 2>/dev/null || true
echo

echo "============================================================"
echo "GPU"
echo "============================================================"
nvidia-smi 2>/dev/null || true
echo

echo "============================================================"
echo "PROJECT TREE"
echo "============================================================"

find . \
  -not -path "./.git/*" \
  -not -path "./*/node_modules/*" \
  -not -path "./*/__pycache__/*" \
  -not -path "./*/dist/*" \
  -not -path "./*/build/*" \
  -not -path "./logs/*" \
  -not -path "./run/*" \
  -not -path "./backups/*" \
  -not -path "./vector_index/*" \
  -not -path "./tasks/*" \
  -not -name "*.db" \
  -not -name "*.bak*" \
  | sort

echo

echo "============================================================"
echo "CORE BACKEND FILES"
echo "============================================================"

BACKEND_FILES=(
  "backend/main.py"
  "backend/config/settings.py"
  "backend/database/models.py"

  "backend/api/chat.py"
  "backend/api/templates.py"
  "backend/api/knowledge.py"
  "backend/api/document.py"
  "backend/api/auth.py"
  "backend/api/user.py"

  "backend/llm/vllm.py"

  "backend/services/llm_service.py"
  "backend/services/document_service.py"
  "backend/services/docx_export.py"
  "backend/services/rag_service.py"
  "backend/services/memory_service.py"

  "backend/rag/parser/base.py"
  "backend/rag/parser/docx_parser.py"

  "backend/knowledge/manager.py"

  "backend/auth/jwt.py"
  "backend/auth/permission.py"
)

for f in "${BACKEND_FILES[@]}"
do
    if [ -f "$f" ]; then
        echo
        echo "============================================================"
        echo "FILE: $f"
        echo "============================================================"
        cat "$f"
    fi
done

echo

echo "============================================================"
echo "CORE FRONTEND FILES"
echo "============================================================"

FRONTEND_FILES=(
  "frontend/user/src/App.vue"

  "frontend/user/src/views/ChatView.vue"
  "frontend/user/src/views/TemplateView.vue"
  "frontend/user/src/views/TemplatesView.vue"
  "frontend/user/src/views/KnowledgeView.vue"
  "frontend/user/src/views/KnowledgeDetailView.vue"
  "frontend/user/src/views/AdminView.vue"
  "frontend/user/src/views/DashboardView.vue"
  "frontend/user/src/views/LoginView.vue"

  "frontend/user/src/api/config.js"
  "frontend/user/src/api/auth.js"
  "frontend/user/src/api/knowledge.js"

  "frontend/user/src/router/index.js"

  "frontend/user/src/stores/auth.js"
  "frontend/user/src/stores/server.js"

  "frontend/user/src/utils/file.js"
  "frontend/user/src/utils/storage.js"
)

for f in "${FRONTEND_FILES[@]}"
do
    if [ -f "$f" ]; then
        echo
        echo "============================================================"
        echo "FILE: $f"
        echo "============================================================"
        cat "$f"
    fi
done

echo

echo "============================================================"
echo "PROJECT CONFIGURATION"
echo "============================================================"

for f in \
  "start.sh" \
  "frontend/user/package.json" \
  "frontend/user/vite.config.js"
do
    if [ -f "$f" ]; then
        echo
        echo "============================================================"
        echo "FILE: $f"
        echo "============================================================"
        cat "$f"
    fi
done

} > "$OUT"

echo
echo "Done."
echo "Output: $OUT"
ls -lh "$OUT"