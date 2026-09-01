#!/usr/bin/env python3
"""Camera Screen Studio em pos-processamento sobre gravacao REAL.

Recebe: video real (mp4/webm) + log do mouse (xdotool amostrado).
Produz: GIF com camera que comeca em zoom out, segue o mouse real e
da zoom in nos momentos de acao (cliques/digitacao).

Filtro de camera (suavizado com media movel ponderada exponencial):
- posicao da camera = media do mouse (janela ~0.4s) com atraso
- zoom = 1.0 quando o mouse se move rapido; 1.4 quando parado/digitando
- easing exponencial em todos os parametros (sem keyframes manuais)

Uso: python3 studio_camera.py <input.mp4> <mouse.log> <output.gif> [largura]
"""
import sys
import math
import subprocess
import os
import tempfile

from PIL import Image, ImageDraw

import numpy as np

FPS_IN = 24
OUT_W = int(sys.argv[4]) if len(sys.argv) > 4 else 760
ZOOM_MAX = 1.45
ZOOM_MIN = 1.0    # tela cheia: o GIF SEMPRE comeca mostrando a tela completa
CAM_LAG = 0.35      # segundos de atraso da camera (segue com inercia)
ZOOM_TAU = 0.5      # constante de tempo do zoom (s): transicao suave ~0.5s
CAM_TAU = 0.25       # constante de tempo da camera (s)
WATERMARK_LOGO = None   # caminho do logo (marca d'agua), 7o arg opcional
MAX_FRAMES = 400     # limite por tamanho; corta o FINAL apenas se estourar
OPENING_HOLD = 1.2   # segundos iniciais SEMPRE em tela cheia (padrao Screen Studio)
DWELL_IN = 0.6       # mouse parado por este tempo (com acao) para zoom in
DWELL_OUT = 0.3      # mouse rapido por este tempo para voltar a tela cheia


def load_mouse_log(path):
    """parse do log: 'timestamp X= x Y= y ...' -> [(t, x, y)]"""
    pts = []
    for line in open(path):
        parts = line.split()
        try:
            t = float(parts[0])
            x = float(parts[1].split("=")[1])
            y = float(parts[2].split("=")[1])
            pts.append((t, x, y))
        except (IndexError, ValueError):
            continue
    return pts


def mouse_at(pts, t):
    """posicao do mouse interpolada no tempo t."""
    if not pts:
        return None
    if t <= pts[0][0]:
        return pts[0][1], pts[0][2]
    if t >= pts[-1][0]:
        return pts[-1][1], pts[-1][2]
    for i in range(len(pts) - 1):
        if pts[i][0] <= t <= pts[i + 1][0]:
            (t0, x0, y0), (t1, x1, y1) = pts[i], pts[i + 1]
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f
    return pts[-1][1], pts[-1][2]


def mouse_speed(pts, t, window=0.15):
    """velocidade do mouse (px/s) ao redor de t."""
    xs = [p for p in pts if abs(p[0] - t) < window]
    if len(xs) < 2:
        return 0.0
    dt = xs[-1][0] - xs[0][0]
    if dt <= 0:
        return 0.0
    dist = math.hypot(xs[-1][1] - xs[0][1], xs[-1][2] - xs[0][2])
    return dist / dt


def render(img_arr, cx, cy, zoom, out_w, out_h):
    """crop subpixel de um frame numpy (H,W,3) com camera (cx,cy,zoom)."""
    h, w = img_arr.shape[:2]
    cw = w / zoom
    ch = h / zoom
    x0 = cx - cw / 2
    y0 = cy - ch / 2
    im = Image.fromarray(img_arr)
    sx = out_w / cw
    sy = out_h / ch
    return im.transform((out_w, out_h), Image.AFFINE,
                        (1 / sx, 0, x0, 0, 1 / sy, y0),
                        resample=Image.BICUBIC)


def draw_click_ripple(img, cx, cy, age, max_age=0.45):
    """ripple de clique: anel expandindo e desvanecendo (Screen Studio)."""
    if age < 0 or age > max_age:
        return img
    f = age / max_age            # 0..1
    r = 8 + 26 * f               # raio expandindo
    alpha = int(200 * (1 - f) ** 1.5)
    if alpha <= 0:
        return img
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(255, 255, 255, alpha), width=3)
    r2 = r * 0.55
    a2 = int(alpha * 0.7)
    if a2 > 0:
        d.ellipse([cx-r2, cy-r2, cx+r2, cy+r2], outline=(255, 255, 255, a2), width=2)
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def draw_cursor_trail(img, hist, out_w, out_h):
    """rastro do cursor estilo COMETA (espaco da fonte): fita continua
    interpolada entre os pontos recentes, espessura e alpha decrescentes
    da cabeca (cursor) para a cauda. Janela ~0.4s (10 frames a 24fps)."""
    pts = [p for p in hist if p is not None]
    if len(pts) < 3:
        return img
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    janela = 10
    tail = pts[-janela:]
    densos = []
    for k in range(len(tail) - 1):
        x0, y0 = tail[k]
        x1, y1 = tail[k + 1]
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        nsub = max(1, int(dist / 3))   # ponto a cada ~3px
        for s in range(nsub):
            f = s / nsub
            densos.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    densos.append(tail[-1])
    m = len(densos)
    for k in range(m - 1):
        age = 1.0 - k / max(1, m - 1)        # 1 = cauda, 0 = cabeca
        r = max(2, int(7 * (1 - age) ** 0.8 + 1.5))
        alpha = int(110 * (1 - age) ** 1.3)
        if alpha < 12:
            continue
        x, y = densos[k]
        nx, ny = densos[k + 1]
        d.line([(x, y), (nx, ny)], fill=(96, 165, 250, alpha), width=r * 2)
        d.ellipse([nx - r, ny - r, nx + r, ny + r], fill=(96, 165, 250, alpha))
    return Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")


def draw_watermark(img, logo_path, opacity=60, margin=10, max_h=26):
    """marca d'agua com o logo da Adapta no canto inferior direito."""
    if not logo_path or not os.path.exists(logo_path):
        return img
    logo = Image.open(logo_path).convert("RGBA")
    ratio = logo.width / logo.height
    h = max_h
    w = int(h * ratio)
    if w > 200:
        w = 200; h = int(w / ratio)
    logo = logo.resize((w, h), Image.LANCZOS)
    a = logo.getchannel("A").point(lambda v: int(v * opacity / 255))
    logo.putalpha(a)
    base = img.convert("RGBA")
    base.alpha_composite(logo, (base.width - w - margin, base.height - h - margin))
    return base.convert("RGB")


def motion_blur(img, cam_vx, cam_vy, zoom_v, fps):
    """blur temporal direcional: intensidade proporcional a velocidade da
    camera (px/frame na SAIDA). Media ponderada de deslocamentos."""
    v = (cam_vx ** 2 + cam_vy ** 2) ** 0.5 + abs(zoom_v) * 200
    px_per_frame = v / fps
    if px_per_frame < 1.5:
        return img          # parado: sem blur (nitido)
    strength = min(px_per_frame / 14.0, 1.0)
    if strength < 0.08:
        return img
    ang = math.atan2(cam_vy, cam_vx) if (cam_vx or cam_vy) else 0.0
    dx, dy = math.cos(ang), math.sin(ang)
    acc = np.asarray(img, dtype=np.float64)
    steps = [-strength, 0.0, strength]
    for s in steps:
        if s == 0.0:
            continue
        sh = img.transform(img.size, Image.AFFINE,
                           (1, 0, s * dx * 2, 0, 1, s * dy * 2),
                           resample=Image.BILINEAR)
        acc += np.asarray(sh, dtype=np.float64)
    acc /= (1 + 2)
    return Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8))


def load_clicks(path):
    """parse do log de cliques: 'timestamp CLICK' -> [t]"""
    if not path or not os.path.exists(path):
        return []
    ts = []
    for line in open(path):
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "CLICK":
            try:
                ts.append(float(parts[0]))
            except ValueError:
                continue
    return ts


def main():
    src, mlog, out = sys.argv[1], sys.argv[2], sys.argv[3]
    clicks_log = sys.argv[5] if len(sys.argv) > 5 else None
    global WATERMARK_LOGO
    WATERMARK_LOGO = sys.argv[6] if len(sys.argv) > 6 else None
    pts = load_mouse_log(mlog)
    print(f"log do mouse: {len(pts)} amostras")

    tmp = tempfile.mkdtemp(prefix="cam-")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                    "-vf", f"fps={FPS_IN}", os.path.join(tmp, "f%04d.png")], check=True)
    frames_files = sorted(os.listdir(tmp))
    n = len(frames_files)
    dur = n / FPS_IN
    print(f"frames: {n} ({dur:.1f}s)")

    t0 = pts[0][0] if pts else 0
    W_IN, H_IN = 1280, 720
    out_h = int(OUT_W * H_IN / W_IN)

    CROP_TOP = 56
    H_IN = H_IN - CROP_TOP
    pts = [(t, x, y - CROP_TOP) for (t, x, y) in pts]

    cam_x, cam_y = W_IN / 2, H_IN / 2
    zoom = ZOOM_MIN
    zoom_target = ZOOM_MIN
    clicks = load_clicks(clicks_log)
    click_times = sorted(ct - t0 for ct in clicks)
    moving_timer = 0.0
    frames = []
    trail_hist = []
    prev_cx, prev_cy, prev_zoom = W_IN / 2, H_IN / 2, ZOOM_MIN
    cam_vx, cam_vy, zoom_v = 0.0, 0.0, 0.0
    for i in range(n):
        t = i / FPS_IN
        m = mouse_at(pts, t0 + t - CAM_LAG)
        if m is None:
            m = (W_IN / 2, H_IN / 2)
        speed = mouse_speed(pts, t0 + t, window=0.2)

        if t < OPENING_HOLD:
            zoom_target, moving_timer = ZOOM_MIN, 0.0
        else:
            clicked = any(0 <= (t - ct) < 1.0 / FPS_IN for ct in click_times)
            if clicked:
                zoom_target = ZOOM_MAX
                moving_timer = 0.0
            elif speed > 150:
                moving_timer += 1 / FPS_IN
                if moving_timer >= DWELL_OUT:
                    zoom_target = ZOOM_MIN
            else:
                moving_timer = 0.0

        alpha = 1 - math.exp(-1.0 / (FPS_IN * ZOOM_TAU))
        zoom += (zoom_target - zoom) * alpha
        cam_alpha = 1 - math.exp(-1.0 / (FPS_IN * CAM_TAU))
        tx, ty = m
        cam_x += (tx - cam_x) * cam_alpha
        cam_y += (ty - cam_y) * cam_alpha
        half_w = W_IN / (2 * zoom)
        half_h = H_IN / (2 * zoom)
        cam_x = max(half_w, min(W_IN - half_w, cam_x))
        cam_y = max(half_h, min(H_IN - half_h, cam_y))

        arr = np.asarray(Image.open(os.path.join(tmp, frames_files[i])).convert("RGB"))
        arr = arr[CROP_TOP:, :, :]

        im_src = Image.fromarray(arr)

        for ct in click_times:
            age = t - ct
            if 0 <= age <= 0.45:
                cm = mouse_at(pts, t0 + ct)
                if cm is None:
                    continue
                im_src = draw_click_ripple(im_src, cm[0], cm[1], age)

        cm_now = mouse_at(pts, t0 + t)
        if cm_now is not None:
            trail_hist.append((cm_now[0], cm_now[1]))
            if len(trail_hist) > 12:
                trail_hist.pop(0)
            if speed > 80:
                im_src = draw_cursor_trail(im_src, trail_hist, None, None)
        else:
            trail_hist.append(None)
            if len(trail_hist) > 12:
                trail_hist.pop(0)

        fr = render(np.asarray(im_src), cam_x, cam_y, zoom, OUT_W, out_h)

        fr = motion_blur(fr, cam_vx, cam_vy, zoom_v, FPS_IN)
        fr = draw_watermark(fr, WATERMARK_LOGO)
        frames.append(fr)
        cam_vx = (cam_x - prev_cx) * FPS_IN
        cam_vy = (cam_y - prev_cy) * FPS_IN
        zoom_v = zoom - prev_zoom
        prev_cx, prev_cy, prev_zoom = cam_x, cam_y, zoom

    if len(frames) > MAX_FRAMES:
        frames = frames[:MAX_FRAMES]

    print(f"gif: {len(frames)} frames")
    for k, fr in enumerate(frames):
        arr = np.array(fr)
        arr[0, k % arr.shape[1], 0] = arr[0, k % arr.shape[1], 0] ^ 1
        frames[k] = Image.fromarray(arr)
    durs = [int(1000 / FPS_IN)] * len(frames)
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=durs, loop=0, optimize=False)
    print("size:", os.path.getsize(out))


if __name__ == "__main__":
    main()
