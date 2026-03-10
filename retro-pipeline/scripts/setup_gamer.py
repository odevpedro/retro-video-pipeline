#!/usr/bin/env python3
"""
setup_game.py
Cria automaticamente games/<slug>/source.json a partir do nome do jogo e plataforma.

Uso:
    python scripts/setup_game.py "Crash Bandicoot" "PlayStation 1"
    python scripts/setup_game.py "Super Mario World" "Super Nintendo" --force
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

# =========================
# Config
# =========================
ROOT      = Path(__file__).resolve().parents[1]
GAMES_DIR = ROOT / "games"

load_dotenv(ROOT / ".env")
RAWG_KEY = os.getenv("RAWG_KEY", "").strip()

# Canais especializados em longplay/gameplay retro
# Formato: (channel_handle, descrição)
LONGPLAY_CHANNELS = [
    "@WorldofLongplays",
    "@NintendoComplete",
    "@Longplays",
    "@GamingHistorySource",
    "@iplaySNES",
    "@psxlongplays",
    "@SegaLongplays",
    "@SNESdrunk",
]

# Quantos clips, duração de cada um
CLIPS_COUNT   = 6
CLIP_SECONDS  = 11

# Pontos do vídeo a usar (% da duração total)
CLIP_POSITIONS = [0.12, 0.25, 0.40, 0.55, 0.68, 0.82]

# Mapeia platform_label → platform_key (pasta em platforms/)
PLATFORM_KEY_MAP = {
    "playstation 1":          "playstation_1",
    "playstation 2":          "playstation_2",
    "playstation 3":          "playstation_3",
    "ps1":                    "playstation_1",
    "ps2":                    "playstation_2",
    "ps3":                    "playstation_3",
    "psx":                    "playstation_1",
    "nintendo entertainment system": "nes",
    "nes":                    "nes",
    "super nintendo":         "super_nintendo",
    "snes":                   "super_nintendo",
    "nintendo 64":            "nintendo_64",
    "n64":                    "nintendo_64",
    "gamecube":               "gamecube",
    "game cube":              "gamecube",
    "sega mega drive":        "mega_drive",
    "mega drive":             "mega_drive",
    "genesis":                "mega_drive",
    "sega genesis":           "mega_drive",
    "sega saturn":            "sega_saturn",
    "saturn":                 "sega_saturn",
    "sega dreamcast":         "sega_dreamcast",
    "dreamcast":              "sega_dreamcast",
    "game boy":               "game_boy",
    "gameboy":                "game_boy",
    "game boy color":         "game_boy_color",
    "gbc":                    "game_boy_color",
    "game boy advance":       "game_boy_advance",
    "gba":                    "game_boy_advance",
    "nintendo ds":            "nintendo_ds",
    "nds":                    "nintendo_ds",
    "atari 2600":             "atari_2600",
    "psp":                    "psp",
    "playstation portable":   "psp",
}


# =========================
# Helpers
# =========================
def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text.strip("_")


def seconds_to_ts(s: int) -> str:
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


def resolve_platform_key(platform_label: str) -> str:
    key = PLATFORM_KEY_MAP.get(platform_label.lower().strip())
    if not key:
        # Fallback: slugify direto
        key = slugify(platform_label)
        print(f"[warn] platform_key não mapeado para '{platform_label}' — usando '{key}'")
        print(f"       Certifique-se de ter platforms/{key}.png")
    return key


# =========================
# RAWG
# =========================
def rawg_get_json(url, params, retries=3, backoff=1.2):
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(backoff * (i + 1))
    raise last_err


def rawg_search(query: str) -> dict | None:
    if not RAWG_KEY:
        return None
    try:
        data = rawg_get_json("https://api.rawg.io/api/games",
                             {"key": RAWG_KEY, "search": query, "page_size": 3})
        results = data.get("results") or []
        if results:
            print(f"[rawg] encontrado: {results[0]['name']}")
            return results[0]
    except Exception as e:
        print(f"[rawg] falhou: {e}")
    return None


# =========================
# YouTube search via yt-dlp
# =========================
def yt_search_longplay(game_name: str, platform: str) -> dict | None:
    """
    Busca um vídeo de longplay no YouTube, priorizando canais especializados.
    Retorna dict com url, title, duration (segundos).
    """
    # Tenta múltiplas variações de query para aumentar chances
    queries = [
        f"{game_name} {platform} longplay",
        f"{game_name} longplay full game",
        f"{game_name} full game walkthrough",
        f"{game_name} {platform} full playthrough",
    ]

    # Tenta cada canal especializado primeiro
    for channel in LONGPLAY_CHANNELS:
        for query in queries[:2]:  # só as 2 primeiras queries por canal
            result = _yt_search(query, channel=channel)
            if result:
                print(f"[yt] encontrado em {channel}: {result['title'][:60]}")
                return result

    # Fallback: busca geral com todas as variações
    print("[yt] nenhum canal especializado encontrou — buscando no YouTube geral...")
    for query in queries:
        result = _yt_search(query, channel=None)
        if result:
            print(f"[yt] encontrado: {result['title'][:60]}")
            return result

    return None


def _yt_search(query: str, channel: str | None) -> dict | None:
    """Executa yt-dlp --dump-json para buscar um vídeo."""
    if channel:
        search_query = f"ytsearch5:{query}"
        extra = ["--match-filter", f"channel LIKE '%{channel.lstrip('@')}%'"]
    else:
        search_query = f"ytsearch3:{query}"
        extra = []

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-playlist",
        "--no-warnings",
        "--quiet",
        *extra,
        search_query,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, cwd=str(ROOT)
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        # yt-dlp pode retornar múltiplas linhas JSON (um por resultado)
        for line in result.stdout.strip().splitlines():
            try:
                info = json.loads(line)
                duration = info.get("duration") or 0
                title = info.get("title", "")
                # Filtra vídeos muito curtos (<3min) ou muito longos (>12h)
                if duration < 180 or duration > 43200:
                    print(f"       [skip] duração fora do range ({duration//60}min): {title[:50]}")
                    continue
                return {
                    "url":      info.get("webpage_url") or info.get("url"),
                    "title":    title,
                    "duration": duration,
                    "channel":  info.get("channel", ""),
                }
            except json.JSONDecodeError:
                continue

    except subprocess.TimeoutExpired:
        print(f"[yt] timeout ao buscar '{query}'")
    except Exception as e:
        print(f"[yt] erro: {e}")

    return None


# =========================
# Calcula clip_starts
# =========================
def compute_clip_starts(duration_seconds: int) -> list[str]:
    """
    Distribui os clips em posições fixas da duração do vídeo.
    Evita os primeiros e últimos 5% (intro/credits).
    """
    usable_start = int(duration_seconds * 0.05)
    usable_end   = int(duration_seconds * 0.92)
    usable_range = usable_end - usable_start

    starts = []
    for pos in CLIP_POSITIONS:
        t = usable_start + int(usable_range * pos)
        starts.append(seconds_to_ts(t))

    return starts


# =========================
# Cria source.json
# =========================
def create_source_json(
    game_name: str,
    platform_label: str,
    yt_info: dict,
    rawg_result: dict | None,
    force: bool = False,
) -> Path:
    slug         = slugify(game_name)
    platform_key = resolve_platform_key(platform_label)
    clip_starts  = compute_clip_starts(yt_info["duration"])

    rawg_query = game_name
    if rawg_result:
        rawg_query = rawg_result.get("name") or game_name

    game_folder = GAMES_DIR / slug
    game_folder.mkdir(parents=True, exist_ok=True)

    src_json = game_folder / "source.json"

    if src_json.exists() and not force:
        print(f"[skip] source.json já existe: {src_json}")
        print("       Use --force para sobrescrever.")
        return src_json

    data = {
        "slug":                slug,
        "youtube_longplay_url": yt_info["url"],
        "platform_label":      platform_label,
        "platform_key":        platform_key,
        "rawg_query":          rawg_query,
        "clip_starts":         clip_starts,
        "_yt_title":           yt_info["title"],
        "_yt_channel":         yt_info["channel"],
        "_yt_duration_s":      yt_info["duration"],
    }

    src_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n✅ source.json criado em: {src_json}")
    return src_json


# =========================
# Main
# =========================
def main():
    parser = argparse.ArgumentParser(
        description="Gera source.json automaticamente para um jogo."
    )
    parser.add_argument("game",     help='Nome do jogo. Ex: "Crash Bandicoot"')
    parser.add_argument("platform", help='Plataforma. Ex: "PlayStation 1"')
    parser.add_argument("--force",  action="store_true", help="Sobrescreve source.json existente")
    args = parser.parse_args()

    game_name      = args.game.strip()
    platform_label = args.platform.strip()

    print(f"\n🎮 Configurando: {game_name} ({platform_label})")
    print("=" * 50)

    # 1) Busca RAWG
    print("\n[1/3] Buscando metadados no RAWG...")
    rawg_result = rawg_search(game_name)
    if not rawg_result:
        print("[rawg] sem resultado — seguindo sem metadados")

    # 2) Busca YouTube
    print("\n[2/3] Buscando longplay no YouTube...")
    yt_info = yt_search_longplay(game_name, platform_label)
    if not yt_info:
        print("\n❌ Nenhum vídeo encontrado no YouTube.")
        print("   Dica: verifique o nome do jogo/plataforma ou adicione a URL manualmente.")
        sys.exit(1)

    duration_min = yt_info["duration"] // 60
    print(f"     Canal:    {yt_info['channel']}")
    print(f"     Duração:  {duration_min} min")
    print(f"     URL:      {yt_info['url']}")

    # 3) Gera source.json
    print("\n[3/3] Gerando source.json...")
    clip_starts = compute_clip_starts(yt_info["duration"])
    print(f"     clip_starts: {clip_starts}")

    src_json = create_source_json(
        game_name=game_name,
        platform_label=platform_label,
        yt_info=yt_info,
        rawg_result=rawg_result,
        force=args.force,
    )

    slug = slugify(game_name)
    print("\n" + "=" * 50)
    print("✅ source.json criado! Iniciando render...")
    print("=" * 50 + "\n")

    render_script = Path(__file__).parent / "render.py"
    subprocess.run(
        [sys.executable, str(render_script), slug],
        check=True
    )


if __name__ == "__main__":
    main()