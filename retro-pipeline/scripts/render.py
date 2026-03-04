import argparse
import json
import os
import random
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
TOTAL_SECONDS = 15
CLIPS_COUNT = 3
CLIP_SECONDS = TOTAL_SECONDS // CLIPS_COUNT  # 5s cada

W, H = 1080, 1920
TOP_PAD = 120
BOTTOM_PANEL_H = 520
GAMEPLAY_H = H - TOP_PAD - BOTTOM_PANEL_H

SAFE_START_PADDING = 5
SAFE_END_PADDING = 5

ROOT = Path(__file__).resolve().parents[1]
GAMES_DIR = ROOT / "games"
TMP_DIR = ROOT / "tmp"
OUT_DIR = ROOT / "output"

# ===== Download strategy (avoid huge files) =====
DOWNLOAD_SECTION_START = "00:08:00"
DOWNLOAD_SECTION_END = "00:25:00"
MAX_HEIGHT = 720

load_dotenv(ROOT / ".env")
RAWG_KEY = os.getenv("RAWG_KEY", "").strip()
FONT_FILE = os.getenv("FONT_FILE", "").strip()  # opcional


# =========================
# Helpers
# =========================
def run(cmd: list[str]) -> None:
    """Executa comando e falha se der erro. Usa cwd=ROOT p/ caminhos relativos funcionarem."""
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def sh(cmd: list[str]) -> str:
    """Executa comando e retorna stdout."""
    res = subprocess.run(
        cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(ROOT)
    )
    return res.stdout.strip()


def ensure_dirs():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def human_size(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}"
        size /= 1024.0
    return f"{size:.2f} TB"


def print_size(path: Path, label: str):
    if path.exists():
        print(f"[size] {label}: {path.name} = {human_size(path.stat().st_size)}")


def ffprobe_duration_seconds(video_path: Path) -> float:
    out = sh([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ])
    return float(out)


def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return re.sub(r"_+", "_", s).strip("_")


# =========================
# Download
# =========================
def yt_download(url: str, out_file: Path, force: bool = False) -> None:
    """
    Baixa apenas uma seção do vídeo e limita resolução para evitar downloads gigantes.
    """
    if out_file.exists() and out_file.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_file.name}")
        print_size(out_file, "download")
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
    print_size(out_file, "download")


# =========================
# RAWG
# =========================
def rawg_get_json(url: str, params: dict, retries: int = 3, backoff: float = 1.2) -> dict:
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


def rawg_search_game(query: str) -> dict:
    url = "https://api.rawg.io/api/games"
    params = {"key": RAWG_KEY, "search": query, "page_size": 1}
    data = rawg_get_json(url, params=params, retries=3)
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"RAWG: nenhum resultado para '{query}'")
    return results[0]


def rawg_game_details(game_id: int) -> dict:
    url = f"https://api.rawg.io/api/games/{game_id}"
    params = {"key": RAWG_KEY}
    return rawg_get_json(url, params=params, retries=3)


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

    title_top = f"{name}  |  {platform_label}{(' • ' + year) if year else ''}"
    body = (
        f"Lançamento: {released if released else '—'}\n"
        f"Plataforma: {platform_label}\n"
        f"Desenvolvedor: {dev}\n"
        f"Publicadora: {pub}\n"
        f"Descrição: {desc}"
    )
    return title_top, body


# =========================
# Clips: 3 trechos + concat
# =========================
def ff_cut_clip(src: Path, dst: Path, start_seconds: int, seconds: int, force: bool = False) -> None:
    if dst.exists() and dst.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {dst.name}")
        print_size(dst, "clip")
        return

    start_ts = f"{start_seconds//3600:02d}:{(start_seconds%3600)//60:02d}:{start_seconds%60:02d}"
    run([
        "ffmpeg", "-y",
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
    print_size(dst, "clip")


def pick_3_distinct_starts(dur: float, seconds: int) -> list[int]:
    """
    Divide a duração em 3 "terços" e escolhe 1 ponto aleatório em cada.
    Garante cenários mais distintos.
    """
    min_start = SAFE_START_PADDING
    max_start = max(min_start + 1, int(dur - SAFE_END_PADDING - seconds))

    if max_start <= min_start:
        base = max(0, int((dur - seconds) / 2))
        return [base, base, base]

    span = max_start - min_start
    thirds = [min_start + int(span * 0.05), min_start + int(span * 0.38), min_start + int(span * 0.71)]
    windows = [
        (thirds[0], min(thirds[0] + int(span * 0.18), max_start)),
        (thirds[1], min(thirds[1] + int(span * 0.18), max_start)),
        (thirds[2], min(thirds[2] + int(span * 0.18), max_start)),
    ]

    starts = []
    for a, b in windows:
        if b <= a:
            starts.append(a)
        else:
            starts.append(random.randint(a, b))
    return starts


def ff_concat_3(clips: list[Path], out_path: Path, force: bool = False) -> None:
    """
    Concatena 3 clipes re-encodando (evita Non-monotonic DTS do -c copy).
    """
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_path.name}")
        print_size(out_path, "concat")
        return

    filter_complex = (
        "[0:v][0:a][1:v][1:a][2:v][2:a]"
        f"concat=n={len(clips)}:v=1:a=1[v][a]"
    )

    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        str(out_path),
    ]
    run(cmd)
    print_size(out_path, "concat")


# =========================
# Render final (vertical + textos)
# =========================
def write_text_file(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def render_vertical(
    slug: str,
    clip_path: Path,
    cover_path: Path,
    console_path: Path,
    out_path: Path,
    title_top: str,
    body_bottom: str,
    force: bool = False,
) -> None:
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_path.name}")
        print_size(out_path, "output")
        return

    title_txt = TMP_DIR / f"{slug}_title.txt"
    body_txt = TMP_DIR / f"{slug}_body.txt"
    write_text_file(title_txt, title_top)
    write_text_file(body_txt, body_bottom)

    # paths relativos ao ROOT (porque run() usa cwd=ROOT)
    title_rel = title_txt.relative_to(ROOT).as_posix()
    body_rel = body_txt.relative_to(ROOT).as_posix()

    # ---- Layout (ajuste aqui) ----
    cover_w, cover_h = 320, 320        # aumentado
    console_w, console_h = 360, 240    # aumentado

    panel_y = TOP_PAD + GAMEPLAY_H

    # imagens no rodapé
    cover_x = 40
    cover_y = panel_y + (BOTTOM_PANEL_H - cover_h) - 40

    console_x = W - console_w - 40
    console_y = panel_y + (BOTTOM_PANEL_H - console_h) - 40

    # texto na “faixa preta” superior (não sobrepõe as imagens)
    title_x, title_y = 40, 35
    body_x, body_y = 40, 95  # corpo um pouco mais pra baixo do título

    gameplay_y = TOP_PAD

    # Importante: drawtext com caminho relativo + aspas
    filter_complex = f"""
    [0:v]scale={W}:{GAMEPLAY_H}:force_original_aspect_ratio=increase,crop={W}:{GAMEPLAY_H}[game];
    color=c=black:s={W}x{H}[bg];
    [bg][game]overlay=0:{gameplay_y}[base];

    [1:v]scale={cover_w}:{cover_h}:force_original_aspect_ratio=decrease,
         pad={cover_w}:{cover_h}:(ow-iw)/2:(oh-ih)/2:color=black[cover];
    [2:v]scale={console_w}:{console_h}:force_original_aspect_ratio=decrease,
         pad={console_w}:{console_h}:(ow-iw)/2:(oh-ih)/2:color=black[console];

    [base][cover]overlay={cover_x}:{cover_y}:eof_action=repeat[base2];
    [base2][console]overlay={console_x}:{console_y}:eof_action=repeat[base3];

    [base3]drawtext=textfile='{title_rel}':reload=1:x={title_x}:y={title_y}:fontsize=44:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2[base4];
    [base4]drawtext=textfile='{body_rel}':reload=1:x={body_x}:y={body_y}:fontsize=30:fontcolor=white:line_spacing=10:shadowcolor=black:shadowx=2:shadowy=2[v]
    """.strip()

    filter_complex = "\n".join(line.strip() for line in filter_complex.splitlines() if line.strip())

    # ⚠️ CRÍTICO: PNGs precisam ser loopados pra durar o vídeo todo
    # E -t TOTAL_SECONDS trava pra nunca “render infinito”
    run([
        "ffmpeg",
        "-y",
        "-i", str(clip_path),
        "-loop", "1", "-i", str(cover_path),
        "-loop", "1", "-i", str(console_path),
        "-t", str(TOTAL_SECONDS),
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_path)
    ])
    print_size(out_path, "output")


# =========================
# Game config
# =========================
def load_game_folder(game_folder: Path) -> dict:
    src_json = game_folder / "source.json"
    cover = game_folder / "cover.png"
    console = game_folder / "console.png"

    if not src_json.exists():
        raise FileNotFoundError(f"Faltou source.json em {game_folder}")

    if not cover.exists() or cover.stat().st_size == 0:
        raise FileNotFoundError(f"Faltou cover.png (ou está vazio) em {game_folder}")

    if not console.exists() or console.stat().st_size == 0:
        raise FileNotFoundError(f"Faltou console.png (ou está vazio) em {game_folder}")

    cfg = json.loads(src_json.read_text(encoding="utf-8"))
    cfg["_folder"] = game_folder
    cfg["_cover"] = cover
    cfg["_console"] = console
    return cfg


# =========================
# Main
# =========================
def main():
    ensure_dirs()

    parser = argparse.ArgumentParser()
    parser.add_argument("slug", help="nome da pasta dentro de /games, ex: crash_bandicoot")
    parser.add_argument("--force", action="store_true", help="refaz download/cortes/render mesmo se já existir")
    args = parser.parse_args()

    slug = args.slug
    force = args.force

    game_folder = GAMES_DIR / slug
    cfg = load_game_folder(game_folder)

    yt_url = cfg["youtube_longplay_url"]
    platform_label = cfg.get("platform_label", "—")
    rawg_query = cfg.get("rawg_query") or cfg.get("slug") or slug

    # 1) RAWG metadata (se falhar, segue com fallback)
    title_top = f"{slug.replace('_', ' ').title()}  |  {platform_label}"
    body_bottom = f"Plataforma: {platform_label}"

    if RAWG_KEY:
        try:
            print("[rawg] buscando:", rawg_query)
            first = rawg_search_game(rawg_query)
            details = rawg_game_details(first["id"])
            title_top, body_bottom = build_overlay_text(details, platform_label)
        except Exception as e:
            print(f"[rawg] falhou ({type(e).__name__}): {e}")
            print("[rawg] seguindo com texto fallback…")
    else:
        print("[rawg] RAWG_KEY ausente — seguindo sem metadata.")

    # 2) Download
    longplay_path = TMP_DIR / f"{slug}_longplay.mp4"
    yt_download(yt_url, longplay_path, force=force)

    # 3) 3 clipes distintos + concat
    dur = ffprobe_duration_seconds(longplay_path)
    starts = pick_3_distinct_starts(dur, CLIP_SECONDS)

    clips = []
    for idx, start in enumerate(starts, start=1):
        clip_i = TMP_DIR / f"{slug}_clip_{idx}.mp4"
        print(f"[cut] clip{idx} start={start//3600:02d}:{(start%3600)//60:02d}:{start%60:02d}")
        ff_cut_clip(longplay_path, clip_i, start, CLIP_SECONDS, force=force)
        clips.append(clip_i)

    clip_path = TMP_DIR / f"{slug}_clip.mp4"
    ff_concat_3(clips, clip_path, force=force)

    # 4) Render final
    out_path = OUT_DIR / f"{slug}.mp4"
def render_vertical(
    slug: str,
    clip_path: Path,
    cover_path: Path,
    console_path: Path,
    out_path: Path,
    title_top: str,
    body_bottom: str,
    force: bool = False,
) -> None:
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_path.name}")
        print_size(out_path, "output")
        return

    title_txt = TMP_DIR / f"{slug}_title.txt"
    body_txt = TMP_DIR / f"{slug}_body.txt"
    write_text_file(title_txt, title_top)
    write_text_file(body_txt, body_bottom)

    title_rel = title_txt.relative_to(ROOT).as_posix()
    body_rel = body_txt.relative_to(ROOT).as_posix()

    font_opt = f":fontfile={FONT_FILE}" if FONT_FILE else ""

    # Um pouco maiores (você pediu)
    cover_w, cover_h = 320, 320
    console_w, console_h = 360, 240

    panel_y = TOP_PAD + GAMEPLAY_H  # início do painel preto
    gameplay_y = TOP_PAD

    # Layout no painel preto (texto acima, imagens abaixo)
    margin = 40
    cover_x = margin
    console_x = W - console_w - margin

    cover_y = panel_y + BOTTOM_PANEL_H - cover_h - margin
    console_y = panel_y + BOTTOM_PANEL_H - console_h - margin

    title_x = margin
    title_y = panel_y + 24

    body_x = margin
    body_y = panel_y + 90

    # (opcional) caixa atrás do texto pra melhorar leitura
    title_box = "box=1:boxcolor=black@0.45:boxborderw=10"
    body_box  = "box=1:boxcolor=black@0.35:boxborderw=10"

    filter_complex = f"""
    [0:v]scale={W}:{GAMEPLAY_H}:force_original_aspect_ratio=increase,crop={W}:{GAMEPLAY_H}[game];
    color=c=black:s={W}x{H}[bg];
    [bg][game]overlay=0:{gameplay_y}[base];

    [1:v]scale={cover_w}:{cover_h}:force_original_aspect_ratio=decrease,
         pad={cover_w}:{cover_h}:(ow-iw)/2:(oh-ih)/2:color=black[cover];

    [2:v]scale={console_w}:{console_h}:force_original_aspect_ratio=decrease,
         pad={console_w}:{console_h}:(ow-iw)/2:(oh-ih)/2:color=black[console];

    [base][cover]overlay={cover_x}:{cover_y}[base2];
    [base2][console]overlay={console_x}:{console_y}[base3];

    [base3]drawtext=textfile='{title_rel}':reload=1:x={title_x}:y={title_y}:
           fontsize=44:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2:{title_box}{font_opt}[base4];

    [base4]drawtext=textfile='{body_rel}':reload=1:x={body_x}:y={body_y}:
           fontsize=28:fontcolor=white:line_spacing=10:shadowcolor=black:shadowx=2:shadowy=2:{body_box}{font_opt}[v]
    """.strip()

    filter_complex = "\n".join(line.strip() for line in filter_complex.splitlines() if line.strip())

    run([
        "ffmpeg",
        "-y",
        "-i", str(clip_path),

        # IMPORTANTÍSSIMO: imagens em loop pro vídeo todo
        "-loop", "1", "-i", str(cover_path),
        "-loop", "1", "-i", str(console_path),

        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "0:a?",

        # teto de duração (evita “render infinito” se algo der ruim)
        "-t", str(TOTAL_SECONDS),

        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",

        "-c:a", "aac",
        "-b:a", "128k",

        "-movflags", "+faststart",
        "-shortest",
        str(out_path)
    ])

    print_size(out_path, "output")

    print("\n✅ Gerado:", out_path)


if __name__ == "__main__":
    main()