import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# =========================
# Config
# =========================
VIDEO_SECONDS = 15
W, H = 1080, 1920

TOP_PAD = 120                 # área do título
BOTTOM_PANEL_H = 520          # área inferior com imagens/texto
GAMEPLAY_H = H - TOP_PAD - BOTTOM_PANEL_H

SAFE_START_PADDING = 5
SAFE_END_PADDING = 5

ROOT = Path(__file__).resolve().parents[1]
GAMES_DIR = ROOT / "games"
TMP_DIR = ROOT / "tmp"
OUT_DIR = ROOT / "output"

# ===== Download strategy (avoid huge files) =====
DOWNLOAD_SECTION_START = "00:08:00"   # de onde começa a janela que você quer baixar
DOWNLOAD_SECTION_END   = "00:25:00"   # até onde vai (janela de 17 min)
MAX_HEIGHT = 720                      # 720 (bom) ou 480 (mais leve)

load_dotenv(ROOT / ".env")
RAWG_KEY = os.getenv("RAWG_KEY", "").strip()
FONT_FILE = os.getenv("FONT_FILE", "").strip()  # opcional

if not RAWG_KEY:
    print("ERRO: RAWG_KEY não encontrado. Crie um .env com RAWG_KEY=....")
    sys.exit(1)


def run(cmd: list[str]) -> None:
    """Executa comando e falha se der erro."""
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True)


def sh(cmd: list[str]) -> str:
    """Executa comando e retorna stdout."""
    res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.stdout.strip()


def ensure_dirs():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def ffprobe_duration_seconds(video_path: Path) -> float:
    out = sh([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ])
    return float(out)


def yt_download(url: str, out_file: Path, force: bool = False) -> None:
    """
    Baixa apenas uma seção do vídeo e limita resolução para evitar downloads gigantes.
    """
    if force and out_file.exists():
        out_file.unlink(missing_ok=True)

    if out_file.exists() and out_file.stat().st_size > 0:
        print(f"[skip] já existe: {out_file.name}")
        return

    section = f"*{DOWNLOAD_SECTION_START}-{DOWNLOAD_SECTION_END}"
    fmt = f"bv*[ext=mp4][height<={MAX_HEIGHT}]+ba[ext=m4a]/b[ext=mp4][height<={MAX_HEIGHT}]"

    run([
        sys.executable, "-m", "yt_dlp",
        "--download-sections", section,
        "-f", fmt,
        "--remux-video", "mp4",
        "--retries", "10",
        "--fragment-retries", "10",
        "--concurrent-fragments", "4",
        "-o", str(out_file),
        url
    ])


def ff_cut_random_clip(src: Path, dst: Path, seconds: int, force: bool = False) -> None:
    """
    Corta um trecho aleatório do longplay.
    """
    if force and dst.exists():
        dst.unlink(missing_ok=True)

    if dst.exists() and dst.stat().st_size > 0:
        print(f"[skip] já existe: {dst.name}")
        return

    dur = ffprobe_duration_seconds(src)
    min_start = SAFE_START_PADDING
    max_start = max(min_start + 1, int(dur - SAFE_END_PADDING - seconds))

    if max_start <= min_start:
        start = max(0, int((dur - seconds) / 2))
    else:
        start = random.randint(min_start, max_start)

    start_ts = f"{start//3600:02d}:{(start%3600)//60:02d}:{start%60:02d}"
    print(f"[cut] start={start_ts} dur={seconds}s")

    run([
        "ffmpeg",
        "-y",
        "-ss", start_ts,
        "-t", str(seconds),
        "-i", str(src),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        str(dst)
    ])


def rawg_search_game(query: str) -> dict:
    url = "https://api.rawg.io/api/games"
    params = {"key": RAWG_KEY, "search": query, "page_size": 1}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"RAWG: nenhum resultado para '{query}'")
    return results[0]


def rawg_game_details(game_id: int) -> dict:
    url = f"https://api.rawg.io/api/games/{game_id}"
    params = {"key": RAWG_KEY}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def shorten(text: str, max_len: int = 170) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def build_overlay_text(details: dict, platform_label: str) -> tuple[str, str]:
    name = details.get("name") or "Unknown"
    released = details.get("released") or ""
    year = released[:4] if released else ""
    devs = details.get("developers") or []
    pubs = details.get("publishers") or []

    dev = devs[0]["name"] if devs else "—"
    pub = pubs[0]["name"] if pubs else "—"

    desc_raw = details.get("description_raw") or ""
    desc = shorten(desc_raw, 170) if desc_raw else "—"

    # Evita caractere problemático no Windows/FFmpeg (•)
    title_top = f"{name} | {platform_label}{(' - ' + year) if year else ''}"

    body = (
        f"Lançamento: {released if released else '—'}\n"
        f"Plataforma: {platform_label}\n"
        f"Desenvolvedor: {dev}\n"
        f"Publicadora: {pub}\n"
        f"Descrição: {desc}"
    )
    return title_top, body


def write_text_file(path: Path, content: str) -> None:
    """
    Grava texto em UTF-8 sem BOM (melhor compatibilidade).
    Remove CR para evitar problemas no drawtext.
    """
    content = content.replace("\r", "")
    path.write_text(content, encoding="utf-8")


def render_vertical(
    clip_path: Path,
    cover_path: Path,
    console_path: Path,
    out_path: Path,
    title_top: str,
    body_bottom: str,
    slug: str,
) -> None:
    """
    Render final 1080x1920 com gameplay + painel inferior + textos.
    Usa drawtext com textfile= (robusto no Windows).
    """
    # arquivos de texto para o ffmpeg ler
    title_file = TMP_DIR / f"{slug}_title.txt"
    body_file = TMP_DIR / f"{slug}_body.txt"
    write_text_file(title_file, title_top)
    write_text_file(body_file, body_bottom)

    # Font config (se não tiver, drawtext usa default)
    # Em drawtext, o parâmetro é fontfile=...
    font_opt = f":fontfile={FONT_FILE}" if FONT_FILE else ""

    cover_w, cover_h = 260, 260
    console_w, console_h = 320, 220

    panel_y = TOP_PAD + GAMEPLAY_H
    text_x = 40
    text_y = panel_y + 40

    cover_x = 40
    cover_y = panel_y + BOTTOM_PANEL_H - cover_h - 40

    console_x = W - console_w - 40
    console_y = panel_y + BOTTOM_PANEL_H - console_h - 60

    gameplay_y = TOP_PAD

    # Importante: em textfile, use caminho com barras normais para evitar escape no Windows
    title_file_ff = str(title_file).replace("\\", "/")
    body_file_ff = str(body_file).replace("\\", "/")

    filter_complex = f"""
    [0:v]scale={W}:{GAMEPLAY_H}:force_original_aspect_ratio=increase,crop={W}:{GAMEPLAY_H}[game];
    color=c=black:s={W}x{H}[bg];
    [bg][game]overlay=0:{gameplay_y}[base];

    [1:v]scale={cover_w}:{cover_h}:force_original_aspect_ratio=decrease,pad={cover_w}:{cover_h}:(ow-iw)/2:(oh-ih)/2:color=black[cover];
    [2:v]scale={console_w}:{console_h}:force_original_aspect_ratio=decrease,pad={console_w}:{console_h}:(ow-iw)/2:(oh-ih)/2:color=black[console];

    [base][cover]overlay={cover_x}:{cover_y}[base2];
    [base2][console]overlay={console_x}:{console_y}[base3];

    [base3]drawtext{font_opt}:textfile='{title_file_ff}':reload=1:x=40:y=35:fontsize=44:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2[base4];
    [base4]drawtext{font_opt}:textfile='{body_file_ff}':reload=1:x={text_x}:y={text_y}:fontsize=30:fontcolor=white:line_spacing=10:shadowcolor=black:shadowx=2:shadowy=2
    """.strip()

    filter_complex = "\n".join(line.strip() for line in filter_complex.splitlines() if line.strip())

    run([
        "ffmpeg",
        "-y",
        "-i", str(clip_path),
        "-i", str(cover_path),
        "-i", str(console_path),
        "-filter_complex", filter_complex,
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        str(out_path)
    ])


def load_game_folder(game_folder: Path) -> dict:
    src_json = game_folder / "source.json"
    cover = game_folder / "cover.png"
    console = game_folder / "console.png"

    if not src_json.exists():
        raise FileNotFoundError(f"Faltou source.json em {game_folder}")
    if not cover.exists():
        raise FileNotFoundError(f"Faltou cover.png em {game_folder}")
    if not console.exists():
        raise FileNotFoundError(f"Faltou console.png em {game_folder}")

    cfg = json.loads(src_json.read_text(encoding="utf-8"))
    cfg["_folder"] = game_folder
    cfg["_cover"] = cover
    cfg["_console"] = console
    return cfg


def main():
    ensure_dirs()

    if len(sys.argv) < 2:
        print("Uso: python scripts/render.py <slug_da_pasta_em_games> [--force]")
        print("Ex:  python scripts/render.py crash_bandicoot --force")
        sys.exit(1)

    slug = sys.argv[1]
    force = "--force" in sys.argv

    game_folder = GAMES_DIR / slug
    cfg = load_game_folder(game_folder)

    yt_url = cfg["youtube_longplay_url"]
    platform_label = cfg.get("platform_label", "—")
    rawg_query = cfg.get("rawg_query") or cfg.get("slug") or slug

    print("[rawg] buscando:", rawg_query)
    first = rawg_search_game(rawg_query)
    details = rawg_game_details(first["id"])
    title_top, body_bottom = build_overlay_text(details, platform_label)

    longplay_path = TMP_DIR / f"{slug}_longplay.mp4"
    yt_download(yt_url, longplay_path, force=force)

    clip_path = TMP_DIR / f"{slug}_clip.mp4"
    ff_cut_random_clip(longplay_path, clip_path, VIDEO_SECONDS, force=force)

    out_path = OUT_DIR / f"{slug}.mp4"
    render_vertical(
        clip_path=clip_path,
        cover_path=cfg["_cover"],
        console_path=cfg["_console"],
        out_path=out_path,
        title_top=title_top,
        body_bottom=body_bottom,
        slug=slug
    )

    print("\n✅ Gerado:", out_path)


if __name__ == "__main__":
    main()