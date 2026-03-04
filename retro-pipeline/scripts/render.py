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
GAMEPLAY_H = H - TOP_PAD - BOTTOM_PANEL_H  # 1280

SAFE_START_PADDING = 5
SAFE_END_PADDING = 5

# Margem extra em segundos ao baixar cada trecho (garante que o corte não caia no limite)
DOWNLOAD_BUFFER = 10

ROOT = Path(__file__).resolve().parents[1]
GAMES_DIR = ROOT / "games"
TMP_DIR = ROOT / "tmp"
OUT_DIR = ROOT / "output"

# Fallback quando source.json não tem clip_starts
DOWNLOAD_SECTION_START = "00:08:00"
DOWNLOAD_SECTION_END = "00:25:00"
MAX_HEIGHT = 720

load_dotenv(ROOT / ".env")
RAWG_KEY = os.getenv("RAWG_KEY", "").strip()
FONT_FILE = os.getenv("FONT_FILE", "").strip()


# =========================
# Helpers
# =========================
def run(cmd):
    print(">", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=str(ROOT))


def sh(cmd):
    res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(ROOT))
    return res.stdout.strip()


def ensure_dirs():
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)


def human_size(num_bytes):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}"
        size /= 1024.0
    return f"{size:.2f} TB"


def print_size(path, label):
    if path.exists():
        print(f"[size] {label}: {path.name} = {human_size(path.stat().st_size)}")


def ffprobe_duration_seconds(video_path):
    out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)])
    return float(out)


def ts_to_seconds(ts: str) -> int:
    """Converte 'HH:MM:SS' ou 'MM:SS' em segundos."""
    parts = ts.strip().split(":")
    parts = [int(p) for p in parts]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return parts[0]


def seconds_to_ts(s: int) -> str:
    """Converte segundos em 'HH:MM:SS'."""
    return f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}"


# =========================
# Download — dois modos
# =========================
def yt_download_section(url: str, out_file: Path, start: str, end: str, force: bool = False) -> None:
    """Baixa UMA seção contínua do vídeo (modo fallback / legado)."""
    if out_file.exists() and out_file.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_file.name}")
        print_size(out_file, "download")
        return

    fmt = f"bv*[ext=mp4][height<={MAX_HEIGHT}]+ba[ext=m4a]/b[ext=mp4][height<={MAX_HEIGHT}]"
    run([
        sys.executable, "-m", "yt_dlp",
        "--download-sections", f"*{start}-{end}",
        "-f", fmt,
        "--remux-video", "mp4",
        "--retries", "10", "--fragment-retries", "10",
        "--concurrent-fragments", "4",
        "-o", str(out_file),
        url
    ])
    print_size(out_file, "download")


def yt_download_clips(url: str, slug: str, clip_starts_ts: list[str], force: bool = False) -> list[Path]:
    """
    Baixa apenas os N trechos curtos necessários, um arquivo por clipe.
    Cada trecho = clip_start .. clip_start + CLIP_SECONDS + DOWNLOAD_BUFFER
    Retorna lista de paths dos arquivos baixados.
    """
    fmt = f"bv*[ext=mp4][height<={MAX_HEIGHT}]+ba[ext=m4a]/b[ext=mp4][height<={MAX_HEIGHT}]"
    paths = []

    for idx, start_ts in enumerate(clip_starts_ts, start=1):
        out_file = TMP_DIR / f"{slug}_dl_{idx}.mp4"
        paths.append(out_file)

        if out_file.exists() and out_file.stat().st_size > 0 and not force:
            print(f"[skip] já existe: {out_file.name}")
            print_size(out_file, f"dl{idx}")
            continue

        start_s = ts_to_seconds(start_ts)
        end_s   = start_s + CLIP_SECONDS + DOWNLOAD_BUFFER
        end_ts  = seconds_to_ts(end_s)

        print(f"[download] trecho {idx}: {start_ts} → {end_ts} (~{CLIP_SECONDS + DOWNLOAD_BUFFER}s)")
        run([
            sys.executable, "-m", "yt_dlp",
            "--download-sections", f"*{start_ts}-{end_ts}",
            "-f", fmt,
            "--remux-video", "mp4",
            "--retries", "10", "--fragment-retries", "10",
            "--concurrent-fragments", "4",
            "-o", str(out_file),
            url
        ])
        print_size(out_file, f"dl{idx}")

    return paths


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


def rawg_search_game(query):
    data = rawg_get_json("https://api.rawg.io/api/games",
                         {"key": RAWG_KEY, "search": query, "page_size": 1})
    results = data.get("results") or []
    if not results:
        raise RuntimeError(f"RAWG: nenhum resultado para '{query}'")
    return results[0]


def rawg_game_details(game_id):
    return rawg_get_json(f"https://api.rawg.io/api/games/{game_id}", {"key": RAWG_KEY})


def shorten(text, max_len=120):
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 1].rstrip() + "…"


def wrap_text(text: str, max_chars: int = 44) -> str:
    """Quebra o texto em linhas de no máximo max_chars caracteres, respeitando palavras."""
    words = text.split()
    lines, current = [], ""
    for word in words:
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def build_overlay_text(details, platform_label):
    name     = details.get("name") or "Unknown"
    released = details.get("released") or ""
    year     = released[:4] if released else ""
    devs     = details.get("developers") or []
    pubs     = details.get("publishers") or []
    dev      = devs[0]["name"] if devs else "—"
    pub      = pubs[0]["name"] if pubs else "—"
    desc_raw = details.get("description_raw") or ""
    desc_short   = shorten(desc_raw, 120) if desc_raw else "—"
    desc_wrapped = wrap_text(f"Description: {desc_short}", max_chars=44)

    title_top = f"{name}  |  {platform_label}{(' • ' + year) if year else ''}"
    # Plataforma e ano já aparecem no título — não repetir no corpo
    body = (
        f"Developer: {dev}\n"
        f"Publisher: {pub}\n"
        f"{desc_wrapped}"
    )
    return title_top, body


# =========================
# Clips: corte + concat
# =========================
def ff_cut_clip(src: Path, dst: Path, start_seconds: int, seconds: int, force: bool = False) -> None:
    if dst.exists() and dst.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {dst.name}")
        print_size(dst, "clip")
        return

    start_ts = seconds_to_ts(start_seconds)
    run(["ffmpeg", "-y", "-ss", start_ts, "-t", str(seconds), "-i", str(src),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-c:a", "aac", "-b:a", "128k", str(dst)])
    print_size(dst, "clip")


def ff_cut_clip_from_start(src: Path, dst: Path, seconds: int, force: bool = False) -> None:
    """Corta 'seconds' segundos a partir do início do arquivo (usado no modo clip_starts)."""
    ff_cut_clip(src, dst, start_seconds=0, seconds=seconds, force=force)


def pick_3_distinct_starts(dur, seconds):
    min_start = SAFE_START_PADDING
    max_start = max(min_start + 1, int(dur - SAFE_END_PADDING - seconds))

    if max_start <= min_start:
        base = max(0, int((dur - seconds) / 2))
        return [base, base, base]

    span   = max_start - min_start
    thirds = [min_start + int(span * 0.05),
              min_start + int(span * 0.38),
              min_start + int(span * 0.71)]
    windows = [(thirds[0], min(thirds[0] + int(span * 0.18), max_start)),
               (thirds[1], min(thirds[1] + int(span * 0.18), max_start)),
               (thirds[2], min(thirds[2] + int(span * 0.18), max_start))]

    starts = []
    for a, b in windows:
        starts.append(a if b <= a else random.randint(a, b))
    return starts


def ff_concat_3(clips: list[Path], out_path: Path, force: bool = False) -> None:
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_path.name}")
        print_size(out_path, "concat")
        return

    filter_complex = "[0:v][0:a][1:v][1:a][2:v][2:a]" + f"concat=n={len(clips)}:v=1:a=1[v][a]"
    cmd = ["ffmpeg", "-y"]
    for c in clips:
        cmd += ["-i", str(c)]
    cmd += ["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", str(out_path)]
    run(cmd)
    print_size(out_path, "concat")


# =========================
# Render final
# =========================
def write_text_file(path, content):
    path.write_text(content, encoding="utf-8")


def render_vertical(slug, clip_path, cover_path, console_path, out_path,
                    title_top, body_bottom, force=False):
    if out_path.exists() and out_path.stat().st_size > 0 and not force:
        print(f"[skip] já existe: {out_path.name}")
        print_size(out_path, "output")
        return

    title_txt = TMP_DIR / f"{slug}_title.txt"
    body_txt  = TMP_DIR / f"{slug}_body.txt"
    write_text_file(title_txt, title_top)
    write_text_file(body_txt, body_bottom)

    title_rel = title_txt.relative_to(ROOT).as_posix()
    body_rel  = body_txt.relative_to(ROOT).as_posix()

    font_opt = f":fontfile={FONT_FILE}" if FONT_FILE else ""

    panel_y = TOP_PAD + GAMEPLAY_H   # 1400
    margin  = 30

    # =========================================================
    # Imagens GRANDES cruzando a fronteira gameplay/painel
    # (zona intermediária conforme template)
    #
    #  gameplay termina em y=1400
    #  imagens começam em y≈1200 (dentro do gameplay) e
    #  terminam em y≈1680 (dentro do painel)
    # =========================================================
    cover_w,   cover_h   = 340, 340
    console_w, console_h = 440, 300

    # Centraliza verticalmente em torno da linha divisória
    img_center_y = panel_y + 40          # levemente abaixo da linha
    cover_y   = img_center_y - cover_h // 2      # ≈ 1230
    console_y = img_center_y - console_h // 2    # ≈ 1250

    cover_x   = margin
    console_x = W - console_w - margin

    # Título centralizado na faixa superior
    title_x = margin
    title_y = (TOP_PAD - 44) // 2       # ≈ 38

    # Texto no fundo do painel, abaixo das imagens
    body_x = margin
    body_y = img_center_y + max(cover_h, console_h) // 2 + 30   # ≈ 1730

    title_box = "box=1:boxcolor=black@0.55:boxborderw=12"
    body_box  = "box=1:boxcolor=black@0.40:boxborderw=10"

    filter_complex = (
        f"[0:v]scale={W}:{GAMEPLAY_H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{GAMEPLAY_H}[game];"
        f"color=c=black:s={W}x{H}[bg];"
        f"[bg][game]overlay=0:{TOP_PAD}[base];"

        f"[1:v]scale={cover_w}:{cover_h}:force_original_aspect_ratio=decrease[cover];"

        f"[2:v]scale={console_w}:{console_h}:force_original_aspect_ratio=decrease[console];"

        f"[base][cover]overlay={cover_x}:{cover_y}[base2];"
        f"[base2][console]overlay={console_x}:{console_y}[base3];"

        f"[base3]drawtext=textfile='{title_rel}':reload=1:x={title_x}:y={title_y}:"
        f"fontsize=44:fontcolor=white:shadowcolor=black:shadowx=2:shadowy=2:{title_box}{font_opt}[base4];"

        f"[base4]drawtext=textfile='{body_rel}':reload=1:x={body_x}:y={body_y}:"
        f"fontsize=28:fontcolor=white:line_spacing=8:shadowcolor=black:shadowx=2:shadowy=2:{body_box}{font_opt}[v]"
    )

    run([
        "ffmpeg", "-y",
        "-i", str(clip_path),
        "-loop", "1", "-i", str(cover_path),
        "-loop", "1", "-i", str(console_path),
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "0:a?",
        "-t", str(TOTAL_SECONDS),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", "-shortest",
        str(out_path)
    ])

    print_size(out_path, "output")
    print("\n✅ Gerado:", out_path)


# =========================
# Game config
# =========================
def load_game_folder(game_folder: Path) -> dict:
    src_json = game_folder / "source.json"
    cover    = game_folder / "cover.png"
    console  = game_folder / "console.png"

    if not src_json.exists():
        raise FileNotFoundError(f"Faltou source.json em {game_folder}")
    if not cover.exists() or cover.stat().st_size == 0:
        raise FileNotFoundError(f"Faltou cover.png em {game_folder}")
    if not console.exists() or console.stat().st_size == 0:
        raise FileNotFoundError(f"Faltou console.png em {game_folder}")

    cfg = json.loads(src_json.read_text(encoding="utf-8"))
    cfg["_folder"]  = game_folder
    cfg["_cover"]   = cover
    cfg["_console"] = console
    return cfg


# =========================
# Main
# =========================
def main():
    ensure_dirs()

    parser = argparse.ArgumentParser()
    parser.add_argument("slug", help="nome da pasta dentro de /games, ex: crash_bandicoot")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    slug  = args.slug
    force = args.force

    game_folder = GAMES_DIR / slug
    cfg = load_game_folder(game_folder)

    yt_url         = cfg["youtube_longplay_url"]
    platform_label = cfg.get("platform_label", "—")
    rawg_query     = cfg.get("rawg_query") or cfg.get("slug") or slug
    clip_starts    = cfg.get("clip_starts")  # ex: ["00:05:00", "00:22:00", "00:45:00"]

    # 1) RAWG metadata
    title_top   = f"{slug.replace('_', ' ').title()}  |  {platform_label}"
    body_bottom = f"Plataforma: {platform_label}"

    if RAWG_KEY:
        try:
            print("[rawg] buscando:", rawg_query)
            first   = rawg_search_game(rawg_query)
            details = rawg_game_details(first["id"])
            title_top, body_bottom = build_overlay_text(details, platform_label)
        except Exception as e:
            print(f"[rawg] falhou ({type(e).__name__}): {e}")
            print("[rawg] seguindo com texto fallback…")
    else:
        print("[rawg] RAWG_KEY ausente — seguindo sem metadata.")

    # ============================================================
    # 2) Download + corte — dois modos:
    #
    #  MODO A — clip_starts definido no source.json (recomendado)
    #    → baixa apenas 3 trechos curtos (~15s cada), ~5MB total
    #
    #  MODO B — sem clip_starts (legado)
    #    → baixa uma seção grande (~17min) e escolhe pontos aleatórios
    # ============================================================
    clips = []

    if clip_starts:
        if len(clip_starts) != CLIPS_COUNT:
            raise ValueError(f"clip_starts deve ter exatamente {CLIPS_COUNT} timestamps, got {len(clip_starts)}")

        print(f"[modo] clip_starts detectado — baixando {CLIPS_COUNT} trechos curtos")
        dl_paths = yt_download_clips(yt_url, slug, clip_starts, force=force)

        for idx, (dl_path, _) in enumerate(zip(dl_paths, clip_starts), start=1):
            clip_i = TMP_DIR / f"{slug}_clip_{idx}.mp4"
            print(f"[cut] clip{idx} — primeiros {CLIP_SECONDS}s de {dl_path.name}")
            ff_cut_clip_from_start(dl_path, clip_i, CLIP_SECONDS, force=force)
            clips.append(clip_i)

    else:
        print("[modo] clip_starts ausente — usando download de seção longa (legado)")
        longplay_path = TMP_DIR / f"{slug}_longplay.mp4"
        yt_download_section(yt_url, longplay_path, DOWNLOAD_SECTION_START, DOWNLOAD_SECTION_END, force=force)

        dur    = ffprobe_duration_seconds(longplay_path)
        starts = pick_3_distinct_starts(dur, CLIP_SECONDS)

        for idx, start in enumerate(starts, start=1):
            clip_i = TMP_DIR / f"{slug}_clip_{idx}.mp4"
            print(f"[cut] clip{idx} start={seconds_to_ts(start)}")
            ff_cut_clip(longplay_path, clip_i, start, CLIP_SECONDS, force=force)
            clips.append(clip_i)

    # 3) Concat
    clip_path = TMP_DIR / f"{slug}_clip.mp4"
    ff_concat_3(clips, clip_path, force=force)

    # 4) Render final
    out_path = OUT_DIR / f"{slug}.mp4"
    render_vertical(
        slug=slug,
        clip_path=clip_path,
        cover_path=cfg["_cover"],
        console_path=cfg["_console"],
        out_path=out_path,
        title_top=title_top,
        body_bottom=body_bottom,
        force=force,
    )


if __name__ == "__main__":
    main()