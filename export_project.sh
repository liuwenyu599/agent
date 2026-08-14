#!/bin/bash
cd /home/lwy/judicial-ai || exit 1

OUT=ai_code.txt

{
echo "========== SYSTEM INFO =========="
date
uname -a
echo

echo "========== GPU =========="
nvidia-smi || true
echo

echo "========== CONDA =========="
conda env list || true
echo

echo "========== PYTHON =========="
python --version || true
pip freeze || true
echo

echo "========== NODE =========="
node -v || true
npm -v || true
echo

echo "========== DIRECTORY TREE =========="
find . \
  -not -path "*/node_modules/*" \
  -not -path "*/.git/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  -not -path "*/output/*" \
  | sort

echo
echo "========== SOURCE FILES =========="

find . -type f \
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
-name "*.sh" -o \
-name "*.vue" -o \
-name "requirements.txt" -o \
-name "package.json" -o \
-name "package-lock.json" -o \
-name "vite.config.js" -o \
-name "vite.config.ts" \
\) \
-not -path "*/node_modules/*" \
-not -path "*/.git/*" \
-not -path "*/__pycache__/*" \
-not -path "*/dist/*" \
-not -path "*/build/*" \
-not -path "*/output/*" \
| sort | while read -r f
do
    echo
    echo "========== $f =========="
    cat "$f"
done

} > "$OUT"

echo
echo "Done."
ls -lh "$OUT"
