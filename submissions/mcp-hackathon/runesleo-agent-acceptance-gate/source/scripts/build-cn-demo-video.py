#!/usr/bin/env python3
"""Build ≤60s Chinese tip-knife demo — visual cards, not PPT bullets."""

from __future__ import annotations

import math
import os
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "research" / "demo-video-cn"
SLIDES_DIR = OUT_DIR / "slides"
AUDIO_DIR = OUT_DIR / "audio"
FINAL = OUT_DIR / "leo-labs-okxai-demo-zh.mp4"

DEFAULT_VOICE = "zh-CN-YunyangNeural"
FALLBACK_VOICE = "zh-CN-XiaoxiaoNeural"
DEFAULT_RATE = "+10%"
VOICE = os.environ.get("VOICE", DEFAULT_VOICE)
RATE = os.environ.get("RATE", DEFAULT_RATE)
EDGE_RETRIES = 2

W, H = 1280, 720

# scene: min_secs, voiceover, kind, payload
SCENES = [
    (
        5,
        "别人晒一张收益截图，先别抄。Agent 调一次，先过闸。",
        "hook",
        {
            "kicker": "Leo Labs · OKX.AI #3977",
            "headline": "先别抄那张晒单",
            "sub": "按次付费数据闸 · 真用，不是交差",
        },
    ),
    (
        9,
        "第一刀，晒单验真。排行榜、持仓、现金回流对账。对不上就标不完整，别拿截图当真理。",
        "pnl",
        {},
    ),
    (
        8,
        "第二刀，同场矩阵。同一场比赛的盘口放一屏：价差、流动性、互相打架的价格，一眼看穿。",
        "matrix",
        {},
    ),
    (
        8,
        "第三刀，决策卡。下单前只给三个结果：跳过、观望、人工复核。过关不等于买点，也不代下单。",
        "decision",
        {},
    ),
    (
        7,
        "JSON 进，结构化结论出。边缘立刻履约，笔记本不必一直开着。给 Agent 用的真闸门。",
        "close",
        {
            "kicker": "api.leolabs.me",
            "headline": "三刀就够用",
            "lines": ["晒单验真", "同场矩阵", "决策卡"],
            "tag": "#OKXAI",
        },
    ),
]


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if not p.exists():
            continue
        for index in ((0, 1, 2) if bold else (0, 1)):
            try:
                return ImageFont.truetype(str(p), size=size, index=index)
            except Exception:
                continue
    return ImageFont.load_default()


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def gradient_bg(c1=(6, 8, 18), c2=(18, 12, 48), c3=(8, 40, 52)) -> Image.Image:
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):
        ty = y / (H - 1)
        for x in range(W):
            tx = x / (W - 1)
            r = int(lerp(lerp(c1[0], c2[0], tx), c3[0], ty))
            g = int(lerp(lerp(c1[1], c2[1], tx), c3[1], ty))
            b = int(lerp(lerp(c1[2], c2[2], tx), c3[2], ty))
            # soft vignette
            dx = (tx - 0.5) * 2
            dy = (ty - 0.45) * 2
            vig = max(0.55, 1 - 0.35 * (dx * dx + dy * dy))
            px[x, y] = (min(255, int(r * vig)), min(255, int(g * vig)), min(255, int(b * vig)))
    # glow orbs
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse([820, -80, 1280, 380], fill=(0, 200, 255, 38))
    od.ellipse([-120, 420, 420, 900], fill=(120, 60, 255, 40))
    od.ellipse([500, 500, 900, 820], fill=(0, 255, 160, 22))
    overlay = overlay.filter(ImageFilter.GaussianBlur(48))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius, fill, outline=None, width=2):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_badge(draw, xy, text, fill, font):
    x, y = xy
    pad_x, pad_y = 14, 8
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    rounded_rect(draw, [x, y, x + tw + pad_x * 2, y + th + pad_y * 2], 18, fill)
    draw.text((x + pad_x, y + pad_y - 1), text, font=font, fill=(8, 12, 20))


def draw_hook(payload: dict) -> Image.Image:
    img = gradient_bg()
    draw = ImageDraw.Draw(img)
    font_k = find_font(22)
    font_h = find_font(64, bold=True)
    font_s = find_font(28)
    font_card = find_font(26)
    font_small = find_font(20)

    draw.text((56, 40), payload["kicker"], font=font_k, fill=(140, 160, 190))
    draw.text((56, 90), payload["headline"], font=font_h, fill=(245, 248, 255))
    draw.text((56, 175), payload["sub"], font=font_s, fill=(120, 220, 255))

    # left fake screenshot card
    rounded_rect(draw, [56, 260, 600, 620], 24, (20, 24, 36), (80, 90, 120), 2)
    draw.text((88, 290), "晒单截图（假）", font=font_card, fill=(180, 190, 210))
    draw.text((88, 350), "+128.4%  7D", font=find_font(48, True), fill=(90, 255, 170))
    draw.text((88, 420), "看起来很猛", font=font_s, fill=(160, 170, 190))
    draw.text((88, 470), "抄之前先过闸 →", font=font_small, fill=(255, 180, 80))

    # right audit card
    rounded_rect(draw, [660, 260, 1224, 620], 24, (18, 28, 40), (0, 220, 180), 3)
    draw_badge(draw, (692, 290), "验真结果", (0, 230, 180), font_small)
    draw.text((692, 360), "LB vs 回流", font=font_card, fill=(220, 230, 245))
    draw.text((692, 420), "pagination_incomplete", font=find_font(32, True), fill=(255, 120, 120))
    draw.text((692, 480), "先别 trust_for_copy", font=font_s, fill=(255, 200, 120))
    draw.text((692, 540), "有用不靠喊单", font=font_small, fill=(140, 200, 255))
    return img


def draw_pnl(_: dict) -> Image.Image:
    img = gradient_bg((8, 10, 20), (10, 30, 40), (20, 10, 36))
    draw = ImageDraw.Draw(img)
    font_h = find_font(52, bold=True)
    font_b = find_font(26)
    font_n = find_font(36, True)
    font_s = find_font(20)

    draw_badge(draw, (56, 40), "01  晒单验真", (0, 230, 180), font_s)
    draw.text((56, 100), "别人晒成绩单，你先对账", font=font_h, fill=(245, 248, 255))

    cards = [
        ("Leaderboard", "+$12.0k", (90, 210, 255)),
        ("Positions cashPnL", "+$9.4k", (255, 200, 90)),
        ("Full cashflow", "incomplete", (255, 110, 120)),
    ]
    x0 = 56
    for title, value, color in cards:
        rounded_rect(draw, [x0, 230, x0 + 370, 520], 22, (16, 22, 34), color, 3)
        draw.text((x0 + 28, 270), title, font=font_b, fill=(170, 180, 200))
        draw.text((x0 + 28, 360), value, font=font_n, fill=color)
        draw.text((x0 + 28, 440), "公开 API · 只读", font=font_s, fill=(120, 130, 150))
        x0 += 400

    draw.text((56, 580), "Agent 调用 /pm-pnl-audit  →  结构化 divergence + action", font=font_b, fill=(160, 220, 255))
    return img


def draw_matrix(_: dict) -> Image.Image:
    img = gradient_bg((10, 8, 24), (30, 12, 50), (8, 28, 40))
    draw = ImageDraw.Draw(img)
    font_h = find_font(52, bold=True)
    font_b = find_font(24)
    font_s = find_font(20)
    font_cell = find_font(22)

    draw_badge(draw, (56, 40), "02  同场矩阵", (160, 120, 255), font_s)
    draw.text((56, 100), "同一场盘口，一屏拆穿", font=font_h, fill=(245, 248, 255))

    # matrix grid mock
    rounded_rect(draw, [56, 210, 1224, 560], 22, (14, 18, 30), (120, 100, 255), 2)
    headers = ["市场", "价", "价差", "流动性", "状态"]
    rows = [
        ("Moneyline Home", "0.48", "2.1%", "$82k", "OK"),
        ("Spread -0.5", "0.51", "6.8%", "$11k", "宽"),
        ("Totals 2.5", "0.44", "1.4%", "$60k", "OK"),
        ("BTTS Yes", "0.57", "9.2%", "$4k", "硬闸"),
    ]
    xs = [80, 420, 620, 820, 1040]
    for i, hname in enumerate(headers):
        draw.text((xs[i], 240), hname, font=font_s, fill=(140, 150, 180))
    for r, row in enumerate(rows):
        y = 300 + r * 55
        color = (255, 120, 120) if row[4] in ("宽", "硬闸") else (120, 230, 170)
        for i, cell in enumerate(row):
            draw.text((xs[i], y), cell, font=font_cell, fill=color if i == 4 else (230, 235, 245))

    draw.text((56, 600), "缺组 / 赛程未核 → hard_veto，不装懂", font=font_b, fill=(200, 180, 255))
    return img


def draw_decision(_: dict) -> Image.Image:
    img = gradient_bg((8, 14, 28), (12, 40, 36), (28, 12, 40))
    draw = ImageDraw.Draw(img)
    font_h = find_font(52, bold=True)
    font_b = find_font(26)
    font_s = find_font(20)
    font_big = find_font(40, True)

    draw_badge(draw, (56, 40), "03  决策卡", (255, 200, 80), font_s)
    draw.text((56, 100), "下单前只问三件事", font=font_h, fill=(245, 248, 255))

    opts = [
        ("SKIP", "直接跳过", (255, 100, 110), "价差太宽 / 硬闸"),
        ("WATCH", "先观望", (255, 200, 80), "可看不可冲"),
        ("REVIEW", "人工复核", (80, 220, 160), "eligible ≠ 买点"),
    ]
    x0 = 56
    for title, sub, color, note in opts:
        rounded_rect(draw, [x0, 230, x0 + 370, 520], 22, (16, 22, 34), color, 3)
        draw.text((x0 + 28, 280), title, font=font_big, fill=color)
        draw.text((x0 + 28, 360), sub, font=font_b, fill=(230, 235, 245))
        draw.text((x0 + 28, 430), note, font=font_s, fill=(150, 160, 180))
        x0 += 400

    draw.text((56, 580), "可带 size → 算 shares · 无私钥 · 不下单", font=font_b, fill=(255, 220, 140))
    return img


def draw_close(payload: dict) -> Image.Image:
    img = gradient_bg((6, 10, 22), (20, 16, 50), (6, 36, 40))
    draw = ImageDraw.Draw(img)
    font_k = find_font(22)
    font_h = find_font(58, bold=True)
    font_b = find_font(32, True)
    font_s = find_font(24)

    draw.text((56, 50), payload["kicker"], font=font_k, fill=(140, 160, 190))
    draw.text((56, 110), payload["headline"], font=font_h, fill=(245, 248, 255))

    y = 230
    for i, line in enumerate(payload["lines"], 1):
        rounded_rect(draw, [56, y, 700, y + 78], 18, (18, 24, 38), (0, 210, 180), 2)
        draw.text((84, y + 20), f"{i}.  {line}", font=font_b, fill=(230, 240, 255))
        y += 100

    rounded_rect(draw, [760, 230, 1224, 520], 24, (12, 28, 36), (0, 200, 255), 3)
    draw.text((800, 280), "Agent 真能用", font=font_b, fill=(120, 230, 255))
    draw.text((800, 350), "会过期的信息", font=font_s, fill=(200, 210, 220))
    draw.text((800, 400), "才值得按次付费", font=font_s, fill=(200, 210, 220))
    draw.text((800, 470), payload["tag"], font=find_font(36, True), fill=(255, 220, 100))

    draw.text((56, 620), "不是为了黑客松交差 · 是日常 Agent 工作流里的闸", font=font_s, fill=(160, 180, 200))
    return img


DRAWERS = {
    "hook": draw_hook,
    "pnl": draw_pnl,
    "matrix": draw_matrix,
    "decision": draw_decision,
    "close": draw_close,
}


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate())


def edge_tts_to_mp3(text: str, mp3_path: Path, voice: str) -> None:
    subprocess.run(
        [
            "edge-tts",
            "--voice", voice,
            "--rate", RATE,
            "--text", text,
            "--write-media", str(mp3_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def audio_to_wav(audio_path: Path, wav_path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(audio_path),
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1",
            str(wav_path),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def say_tingting_to_wav(text: str, wav_path: Path) -> str:
    aiff_path = wav_path.with_suffix(".aiff")
    subprocess.run(
        ["say", "-v", "Tingting", "-r", "185", "-o", str(aiff_path), text],
        check=True,
    )
    audio_to_wav(aiff_path, wav_path)
    return "Tingting"


def narration_to_wav(text: str, mp3_path: Path, wav_path: Path) -> str:
    voices = [VOICE]
    if VOICE != FALLBACK_VOICE:
        voices.append(FALLBACK_VOICE)
    last_error: Exception | None = None
    for voice in voices:
        for attempt in range(1, EDGE_RETRIES + 1):
            try:
                edge_tts_to_mp3(text, mp3_path, voice)
                audio_to_wav(mp3_path, wav_path)
                return voice
            except (OSError, subprocess.CalledProcessError) as exc:
                last_error = exc
                detail = getattr(exc, "stderr", "") or str(exc)
                detail = detail.strip().splitlines()[-1] if detail.strip() else str(exc)
                print(f"WARN: edge-tts failed with {voice} attempt {attempt}/{EDGE_RETRIES}: {detail}")
    print(f"WARN: falling back to Tingting: {last_error}")
    return say_tingting_to_wav(text, wav_path)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SLIDES_DIR.mkdir(parents=True, exist_ok=True)
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    concat_parts: list[Path] = []
    total = len(SCENES)
    voices_used: set[str] = set()
    print(f"TTS default: voice={VOICE} rate={RATE}")

    for i, (min_secs, line, kind, payload) in enumerate(SCENES, start=1):
        slide_path = SLIDES_DIR / f"slide-{i:02d}.png"
        DRAWERS[kind](payload).save(slide_path)

        mp3 = AUDIO_DIR / f"line-{i:02d}.mp3"
        wav = AUDIO_DIR / f"line-{i:02d}.wav"
        voice_used = narration_to_wav(line, mp3, wav)
        voices_used.add(voice_used)
        audio_secs = wav_duration(wav)
        duration = max(float(min_secs), audio_secs + 0.35)

        part = OUT_DIR / f"part-{i:02d}.mp4"
        # slight zoom ken-burns for less static feel
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-loop", "1", "-i", str(slide_path),
                "-i", str(wav),
                "-filter_complex",
                f"[0:v]scale=1350:760,zoompan=z='min(1.08,1+0.0008*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps=30,format=yuv420p[v]",
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-c:a", "aac", "-b:a", "160k",
                "-t", f"{duration:.2f}",
                "-shortest",
                str(part),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        concat_parts.append(part)
        print(f"scene {i}/{total}: {duration:.1f}s — {kind} — {voice_used}")

    list_file = OUT_DIR / "concat.txt"
    list_file.write_text("".join(f"file '{p.name}'\n" for p in concat_parts), encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(FINAL),
        ],
        check=True,
        cwd=str(OUT_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(FINAL),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    dur = float(probe.stdout.strip())
    print(f"\nDONE: {FINAL}")
    print(f"duration: {dur:.1f}s")
    print(f"voices: {', '.join(sorted(voices_used))}")
    if dur > 90:
        print("WARN: over 90s")


if __name__ == "__main__":
    main()
