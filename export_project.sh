#!/bin/bash

cd /home/lwy/judicial-ai || exit 1

OUT=ai_code.txt

{
echo "============================================================"
echo "司法智能办公辅助平台 V1.0 - 项目代码上下文"
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
  -type f \
  -not -path "./.git/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "./logs/*" \
  -not -path "./run/*" \
  -not -path "./backups/*" \
  -not -path "./vector_index/*" \
  -not -path "./tasks/*" \
  -not -path "./frontend/user/src-tauri/target/*" \
  -not -name "*.db" \
  -not -name "*.sqlite" \
  -not -name "*.sqlite3" \
  -not -name "*.bak*" \
  -not -name "*.log" \
  | sort

echo

echo "============================================================"
echo "SOURCE FILES"
echo "============================================================"

find . \
  -type f \
  \( \
    -name "*.py" -o \
    -name "*.pyi" -o \
    -name "*.vue" -o \
    -name "*.js" -o \
    -name "*.jsx" -o \
    -name "*.ts" -o \
    -name "*.tsx" -o \
    -name "*.html" -o \
    -name "*.css" -o \
    -name "*.scss" -o \
    -name "*.less" -o \
    -name "*.json" -o \
    -name "*.yaml" -o \
    -name "*.yml" -o \
    -name "*.toml" -o \
    -name "*.sh" -o \
    -name "*.sql" \
  \) \
  -not -path "./.git/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "./logs/*" \
  -not -path "./run/*" \
  -not -path "./backups/*" \
  -not -path "./vector_index/*" \
  -not -path "./tasks/*" \
  -not -path "./frontend/user/src-tauri/target/*" \
  -not -name "*.db" \
  -not -name "*.sqlite" \
  -not -name "*.sqlite3" \
  -not -name "*.bak*" \
  -not -name "*.log" \
  | sort |
while IFS= read -r f
do
    echo
    echo "============================================================"
    echo "FILE: $f"
    echo "============================================================"
    cat "$f"
done

} > "$OUT"

echo
echo "Done."
echo "Output: $OUT"
echo

echo "统计:"
echo "文件数量:"
find . \
  -type f \
  \( \
    -name "*.py" -o \
    -name "*.vue" -o \
    -name "*.js" -o \
    -name "*.ts" -o \
    -name "*.json" -o \
    -name "*.html" -o \
    -name "*.css" -o \
    -name "*.yaml" -o \
    -name "*.yml" -o \
    -name "*.sh" \
  \) \
  -not -path "./.git/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/__pycache__/*" \
  -not -name "*.bak*" \
  | wc -l

echo
ls -lh "$OUT"