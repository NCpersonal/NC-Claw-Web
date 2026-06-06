#!/bin/bash
set -e

G='\033[0;32m'
Y='\033[1;33m'
R='\033[0m'
D='\033[2m'
RD='\033[0;31m'

CURRENT=$(grep -oP 'version\s*=\s*"\K[0-9]+\.[0-9]+\.[0-9]+' pyproject.toml | head -1)
echo -e "\n${D}Current version:${R} ${G}${CURRENT}${R}"

if [ -n "$1" ]; then
    NEW="$1"
else
    read -p "New version: " NEW
fi

if [ -z "$NEW" ]; then
    echo -e "${RD}No version. Aborted.${R}"
    exit 1
fi

echo -e "\n${Y}Releasing ${CURRENT} -> ${NEW}${R}\n"

# 1. 更新版本号
echo -e "${D}[1/6]${R} Updating version..."
sed -i "s/${CURRENT}/${NEW}/g" pyproject.toml
sed -i "s/${CURRENT}/${NEW}/g" nc_claw/claw.py
sed -i "s/${CURRENT}/${NEW}/g" nc_claw/__init__.py
echo -e "  ${G}OK${R} pyproject.toml   ${CURRENT} -> ${NEW}"
echo -e "  ${G}OK${R} claw.py          ${CURRENT} -> ${NEW}"
echo -e "  ${G}OK${R} __init__.py      ${CURRENT} -> ${NEW}"

# 2. 清理
echo -e "\n${D}[2/6]${R} Cleaning..."
rm -rf dist/ build/ *.egg-info nc_claw.egg-info
echo -e "  ${G}OK${R} Cleaned"

# 3. 构建
echo -e "\n${D}[3/6]${R} Building..."
python3 -m build
if [ ! "$(ls -A dist/ 2>/dev/null)" ]; then
    echo -e "  ${RD}FAIL Build failed.${R}"
    exit 1
fi
echo -e "  ${G}OK${R} Built $(ls dist/ | wc -l) files"

# 4. 上传 PyPI
echo -e "\n${D}[4/6]${R} Uploading to PyPI..."
twine upload dist/*
echo -e "  ${G}OK${R} Published to PyPI"

# 5. Git 提交
echo -e "\n${D}[5/6]${R} Git commit..."
git add -A
git commit -m "release v${NEW}"
echo -e "  ${G}OK${R} Committed"

# 6. Git 推送
echo -e "\n${D}[6/6]${R} Git push..."
git tag -d "v${NEW}" 2>/dev/null || true
git tag "v${NEW}"
git push origin main
git push origin "v${NEW}" --force 2>/dev/null || true
echo -e "  ${G}OK${R} Pushed to GitHub"

echo -e "\n${G}------------------------------------${R}"
echo -e "${G} OK v${NEW} released${R}"
echo -e "${G}------------------------------------${R}"
echo -e "${D} PyPI:  pip install --upgrade nc-claw${R}"
echo -e "${D} GitHub: https://github.com/NCpersonal/NC-Claw-Web${R}"
echo ""
echo "update nc-claw..."
sudo pip install --upgrade nc-claw --break-system-packages
echo -e "\n${G}Done!${R}"