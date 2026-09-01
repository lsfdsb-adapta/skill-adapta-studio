#!/usr/bin/env python3
"""Gera GIF com movimento de camera (zoom in/pan/zoom out) a partir de frames PNG.

Uso: python3 make_zoom_gif.py <frame_inicial> <frame_email> <frame_senha> <frame_final> <saida.gif>
"""
import subprocess
import sys
import tempfile
import os


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("ERRO:", " ".join(cmd))
        print(r.stderr[-800:])
        sys.exit(1)
    return r


def main():
    f_full, f_email, f_senha, f_out_frame, out_gif = sys.argv[1:6]
    tmp = tempfile.mkdtemp(prefix="zoomgif-")

    # Sequencia de cenas: (arquivo, duracao_s, tipo)
    # tipo: full (estatico), zin (zoom in), pan, zout (zoom out)
    scenes = [
        (f_full, 2.0, "full"),
        (f_email, 3.5, "zin"),
        (f_senha, 3.0, "pan"),
        (f_out_frame, 3.5, "zout"),
    ]

    parts = []
    idx = 0
    for src, dur, kind in scenes:
        n = int(dur * 10)  # 10 fps
        out_pattern = os.path.join(tmp, f"s{idx:02d}_%03d.png")
        if kind == "full":
            vf = f"fps=10,scale=900:-1"
        elif kind == "zin":
            vf = ("fps=10,scale=900:-1,zoompan="
                  f"z='min(zoom+0.0045,1.5)':x='iw*0.30-(iw/zoom/2)':y='ih*0.58-(ih/zoom/2)':d={n}:s=900x545")
        elif kind == "pan":
            vf = ("fps=10,scale=900:-1,zoompan="
                  f"z='1.5':x='iw*0.30-(iw/zoom/2)+on*2.5':y='ih*0.68-(ih/zoom/2)':d={n}:s=900x545")
        else:  # zout
            vf = ("fps=10,scale=900:-1,zoompan="
                  f"z='if(lte(zoom,1.0),1.5,max(1.001,zoom-0.0045))':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s=900x545")
        run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", src,
             "-frames:v", str(n), "-vf", vf.replace(f"d={n}", "d=1"), out_pattern])
        parts.append(out_pattern)
        idx += 1

    # Renumerar todos os frames em sequencia
    seq = os.path.join(tmp, "seq")
    os.makedirs(seq)
    counter = 0
    for pattern in parts:
        files = sorted([f for f in os.listdir(tmp) if f.startswith(os.path.basename(pattern).split("%")[0])])
        for f in files:
            counter += 1
            os.rename(os.path.join(tmp, f), os.path.join(seq, f"{counter:03d}.png"))

    run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "10",
         "-i", os.path.join(seq, "%03d.png"),
         "-vf", "split[a][b];[a]palettegen[p];[b][p]paletteuse",
         "-loop", "0", out_gif])

    r = subprocess.run(["ffprobe", "-v", "error", "-count_frames",
                        "-select_streams", "v:0", "-show_entries",
                        "stream=nb_read_frames", "-of", "csv=p=0", out_gif],
                       capture_output=True, text=True)
    print(f"OK: {out_gif} ({counter} frames, ffprobe: {r.stdout.strip()})")


if __name__ == "__main__":
    main()
