#!/usr/bin/env bash
set -e

PROJECT_NAME="retro-pipeline"
GAME_SLUG="crash_bandicoot"

echo "Creating project structure: ${PROJECT_NAME}"

# Root
mkdir -p "${PROJECT_NAME}"
cd "${PROJECT_NAME}"

# Folders
mkdir -p "games/${GAME_SLUG}"
mkdir -p "scripts"
mkdir -p "tmp"
mkdir -p "output"

# Placeholder files for assets
touch "games/${GAME_SLUG}/cover.png"
touch "games/${GAME_SLUG}/console.png"
touch "games/${GAME_SLUG}/case.mp4"

# source.json template
cat > "games/${GAME_SLUG}/source.json" <<'JSON'
{
  "slug": "crash_bandicoot",
  "youtube_longplay_url": "https://www.youtube.com/watch?v=XXXXXXXXXXX",
  "platform_label": "PlayStation 1",
  "rawg_query": "Crash Bandicoot"
}
JSON

# .env template
cat > ".env" <<'ENV'
RAWG_KEY=COLOQUE_SUA_CHAVE_AQUI

# Opcional: defina uma fonte para o drawtext do ffmpeg se necessário
# Linux (exemplo):
# FONT_FILE=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf
#
# Windows via WSL (exemplo):
# FONT_FILE=/mnt/c/Windows/Fonts/arial.ttf
ENV

# requirements.txt
cat > "requirements.txt" <<'REQ'
requests==2.32.3
python-dotenv==1.0.1
REQ

# .gitignore
cat > ".gitignore" <<'GIT'
# outputs and temps
tmp/
output/
*.mp4

# secrets
.env

# python
venv/
__pycache__/
*.pyc
GIT

echo ""
echo "✅ Done!"
echo "Next steps:"
echo "1) Put your RAWG_KEY in .env"
echo "2) Replace the youtube_longplay_url in games/${GAME_SLUG}/source.json"
echo "3) Add cover.png and console.png into games/${GAME_SLUG}/"
echo "4) Copy your render.py into scripts/"
