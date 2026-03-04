#!/usr/bin/env bash
# setup_platforms.sh
# Executa a partir da raiz do projeto (retro-pipeline/)
# Uso: bash setup_platforms.sh

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
PLATFORMS="$ROOT/platforms"
GAMES="$ROOT/games"
TMP="$ROOT/tmp"
OUTPUT="$ROOT/output"

# =========================
# Cria estrutura de pastas
# =========================
for dir in "$PLATFORMS" "$GAMES" "$TMP" "$OUTPUT"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        echo "[ok] criado: $dir"
    else
        echo "[skip] já existe: $dir"
    fi
done

echo ""
echo "Baixando imagens dos consoles via Wikimedia API..."
echo ""

# Delega o download para Python — usa a API do Wikimedia para
# obter a URL real de cada imagem (evita problemas com hash do path)
python3 - "$PLATFORMS" << 'PYEOF'
import sys
import time
import requests
from pathlib import Path

PLATFORMS = Path(sys.argv[1])

UA = "retro-video-pipeline/1.0 (educational project)"

# key | nome do arquivo no Wikimedia Commons
consoles = [
    ("playstation_1",   "PSX-Console-wController.jpg"),
    ("playstation_2",   "PS2-Fat-Console-Set.jpg"),
    ("playstation_3",   "PS3-Slim-Console.jpg"),
    ("nes",             "NES-Console-Set.jpg"),
    ("super_nintendo",  "SNES-Mod1-Console-Set.jpg"),
    ("nintendo_64",     "Nintendo-64-wController-L.jpg"),
    ("gamecube",        "GameCube-Console-Set.jpg"),
    ("mega_drive",      "Sega-Mega-Drive-JP-Mk1-Console-Set.jpg"),
    ("sega_saturn",     "Sega-Saturn-Console-Set-Mk1.jpg"),
    ("sega_dreamcast",  "Dreamcast-Console-Set.jpg"),
    ("game_boy",        "Nintendo-Game-Boy-FL.jpg"),
    ("game_boy_color",  "Game-Boy-Color-FL.jpg"),
    ("game_boy_advance","Game-Boy-Advance-Purple-FL.jpg"),
    ("nintendo_ds",     "Nintendo-DS-Lite-Blue.jpg"),
    ("atari_2600",      "Atari-2600-Wood-4Sw-Set.jpg"),
]

def get_wikimedia_url(filename, width=600):
    """Usa a API do Wikimedia para obter a URL real do thumbnail."""
    api = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "titles": f"File:{filename}",
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": width,
        "format": "json",
    }
    r = requests.get(api, params=params, timeout=15,
                     headers={"User-Agent": UA})
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    for page in pages.values():
        info = page.get("imageinfo", [{}])[0]
        return info.get("thumburl") or info.get("url")
    return None

ok = fail = skip = 0

for key, filename in consoles:
    dest = PLATFORMS / f"{key}.png"

    if dest.exists() and dest.stat().st_size > 0:
        print(f"[skip] {key}.png já existe")
        skip += 1
        continue

    print(f"[api]  resolvendo {filename}...")
    try:
        url = get_wikimedia_url(filename)
        if not url:
            raise ValueError("URL não encontrada na API")

        print(f"[down] {key}.png ← {url}")
        r = requests.get(url, timeout=30,
                         headers={"User-Agent": UA,
                                  "Referer": "https://en.wikipedia.org/"})
        r.raise_for_status()
        dest.write_bytes(r.content)
        kb = dest.stat().st_size // 1024
        print(f"       ✓ {kb} KB")
        ok += 1
    except Exception as e:
        print(f"       ✗ falhou: {e}")
        dest.unlink(missing_ok=True)
        fail += 1

    time.sleep(1)  # respeita rate limit

print()
print(f"Resultado: {ok} baixados, {skip} já existiam, {fail} falharam")
if fail:
    print(f"⚠️  {fail} falharam — rode novamente ou adicione manualmente em platforms/<key>.png")
PYEOF

# =========================
# Resumo final
# =========================
echo ""
echo "=============================="
echo "Estrutura criada em: $ROOT"
echo ""
echo "platforms/"
for f in "$PLATFORMS"/*.png 2>/dev/null; do
    [ -f "$f" ] || continue
    kb=$(( $(wc -c < "$f") / 1024 ))
    echo "  $(basename "$f")  (${kb} KB)"
done
echo ""
echo "Para usar no source.json, defina platform_key com um dos valores acima"
echo "(sem a extensão .png). Exemplo:"
echo ""
echo '  "platform_key": "playstation_1"'
echo ""
echo "=============================="