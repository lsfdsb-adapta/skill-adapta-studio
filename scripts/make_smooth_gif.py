#!/usr/bin/env python3
"""GIF estilo Screen Studio v5: coordenadas medidas via DOM, movimento simples descendente.

Receita:
- alvos medidos com getBoundingClientRect no browser real (nunca chutar)
- cursor entra, clica no e-mail, desce para a senha, clica, desce para Entrar
- crop subpixel via affine (sem jitter), easing expo, trail, ripple de clique
Uso: python3 make_smooth_gif.py <saida.gif> <f_tela> <f_email> <f_senha> <f_final>
"""
import sys
import math
from PIL import Image, ImageDraw

FPS = 30
OUT_W = 720
MAX_FRAMES = 196

# ALVOS MEDIDOS E VALIDADOS POR VISAO no screenshot real 1050x637:
# cruz vermelha confirmada sobre cada elemento
EMAIL = (0.359, 0.542)
SENHA = (0.359, 0.658)
ENTRAR = (0.287, 0.752)


def ease_out_expo(p):
    if p >= 1.0:
        return 1.0
    return 1 - math.pow(2, -10 * p)


def ease_in_out_expo(p):
    if p <= 0:
        return 0
    if p >= 1:
        return 1
    if p < 0.5:
        return math.pow(2, 20 * p - 10) / 2
    return (2 - math.pow(2, -20 * p + 10)) / 2


def render(img, cx, cy, zoom, out_w, out_h):
    w, h = img.size
    cw = w / zoom
    ch = h / zoom
    sx = out_w / cw
    sy = out_h / ch
    x0 = cx - cw / 2
    y0 = cy - ch / 2
    # PIL AFFINE mapeia coordenada de SAIDA para FONTE:
    # src_x = out_x/sx + x0  =>  (1/sx, 0, x0, 0, 1/sy, y0)
    return img.transform(
        (out_w, out_h),
        Image.AFFINE,
        (1 / sx, 0, x0, 0, 1 / sy, y0),
        resample=Image.BICUBIC,
    )


class Cursor:
    def __init__(self):
        self.trail = []

    def draw(self, frame, fx, fy, click=0.0, pressed=False):
        W, H = frame.size
        x = fx * W
        y = fy * H
        d = ImageDraw.Draw(frame, "RGBA")
        for i, (tx, ty) in enumerate(self.trail[-8:]):
            age = (i + 1) / 9
            r = 3.5 * (1 - age)
            if r > 0.5:
                d.ellipse([tx - r, ty - r, tx + r, ty + r], fill=(120, 180, 255, int(70 * (1 - age))))
        self.trail.append((x, y))
        if len(self.trail) > 12:
            self.trail.pop(0)
        if click > 0:
            for speed in (1.0, 1.55):
                c = click * speed
                if 0 < c < 1:
                    r = 4 + c * 26
                    a = int(220 * (1 - c))
                    d.ellipse([x - r, y - r, x + r, y + r], outline=(90, 170, 255, a), width=max(1, 3 - int(c * 2)))
        s = 1.35 if pressed else 1.2
        off = 2 if pressed else 0
        pts = [(x + off, y + off), (x + off, y + off + 20 * s), (x + 5 * s + off, y + 16 * s + off),
               (x + 9 * s + off, y + 21 * s + off), (x + 12 * s + off, y + 17 * s + off),
               (x + 8 * s + off, y + 12 * s + off), (x + 13 * s + off, y + 8 * s + off)]
        d.polygon([(px + 1.5, py + 2.5) for px, py in pts], fill=(0, 0, 0, 140))
        d.polygon(pts, fill=(17, 17, 17, 255))
        inner = [(x + 1.5 + off, y + 2.5 + off), (x + 1.5 + off, y + 17 * s + off),
                 (x + 5 * s + off, y + 13.5 * s + off), (x + 8 * s + off, y + 17.5 * s + off),
                 (x + 9.5 * s + off, y + 15.5 * s + off), (x + 6 * s + off, y + 11 * s + off),
                 (x + 10.5 * s + off, y + 7.5 * s + off)]
        d.polygon(inner, fill=(255, 255, 255, 255))


def main():
    out_path, f_tela, f_email, f_senha, f_final = sys.argv[1:6]
    img_tela = Image.open(f_tela).convert("RGB")
    img_email = Image.open(f_email).convert("RGB")
    img_senha = Image.open(f_senha).convert("RGB")
    img_final = Image.open(f_final).convert("RGB")

    W, H = img_tela.size
    out_h = int(OUT_W * H / W)

    frames = []
    cur = Cursor()

    def add(img, zoom, cx, cy, cpos, click=0.0, pressed=False):
        fr = render(img, cx * W, cy * H, zoom, OUT_W, out_h)
        # cpos e fracao da FONTE; converter para fracao do FRAME de saida
        # (a camera transformou a imagem: o alvo nao esta na mesma fracao do frame)
        fx = (cpos[0] - cx) * zoom + 0.5
        fy = (cpos[1] - cy) * zoom + 0.5
        cur.draw(fr, fx, fy, click, pressed)
        frames.append(fr)

    # plano: so descendo, sem vai-e-vem, zoom fixo moderado no formulario
    # camera fixa centrada no formulario (ponto medio entre email e entrar)
    form_cy = (EMAIL[1] + ENTRAR[1]) / 2
    cam = (EMAIL[0] + 0.02, form_cy)
    zoom = 1.35

    plan = [
        # (dur, cur_ini, cur_fim, acao)
        (0.7, (0.45, 0.35), EMAIL, None),         # cursor entra e vai ao email
        (0.9, EMAIL, EMAIL, "click_email"),       # clique no email
        (0.7, EMAIL, SENHA, None),                 # desce a senha
        (0.9, SENHA, SENHA, "click_senha"),       # clique na senha
        (0.7, SENHA, ENTRAR, None),                # desce ao Entrar
        (0.8, ENTRAR, ENTRAR, "click_entrar"),    # clique no Entrar
    ]

    for (dur, u0, u1, acao) in plan:
        N = max(2, int(dur * FPS))
        for i in range(N):
            p = i / (N - 1)
            ce = ease_out_expo(p)
            ux = u0[0] + (u1[0] - u0[0]) * ce
            uy = u0[1] + (u1[1] - u0[1]) * ce
            click = 0.0
            pressed = False
            img = img_tela
            if acao == "click_email":
                if p > 0.6:
                    click = (p - 0.6) / 0.4
                    pressed = click < 0.5
                img = img_email if p > 0.6 else img_tela
            elif acao == "click_senha":
                if p > 0.6:
                    click = (p - 0.6) / 0.4
                    pressed = click < 0.5
                img = img_senha if p > 0.6 else img_email
            elif acao == "click_entrar":
                if p > 0.6:
                    click = (p - 0.6) / 0.4
                    pressed = click < 0.5
                img = img_final if p > 0.6 else img_senha
            add(img, zoom, cam[0], cam[1], (ux, uy), click, pressed)

    # hold final
    for i in range(int(0.6 * FPS)):
        add(img_final, zoom, cam[0], cam[1], ENTRAR)

    if len(frames) > MAX_FRAMES:
        step = len(frames) / MAX_FRAMES
        frames = [frames[int(i * step)] for i in range(MAX_FRAMES)]

    print(f"frames: {len(frames)}")
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=int(1000 / FPS), loop=0, optimize=True)


if __name__ == "__main__":
    main()
