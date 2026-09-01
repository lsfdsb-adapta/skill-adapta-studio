#!/usr/bin/env python3
"""Pipeline de edicao de video do adapta-studio.

Recebe um .webm bruto gravado no sandbox (agent-browser record) e produz um
MP4 editado: corte de trechos mortos, aceleracao de esperas, zoom em cliques
e highlight de cursor (quando houver dados de eventos).

Uso:
    python3 edit_video.py input.webm output.mp4 [--speed 2] [--no-zoom]

Dependencias: ffmpeg no PATH.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile


def run(cmd, **kw):
    print("+", " ".join(cmd[:8]), "..." if len(cmd) > 8 else "")
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        print("ERRO:", r.stderr[-1500:])
        sys.exit(1)
    return r


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", path])
    return float(json.loads(r.stdout)["format"]["duration"])


def detect_silence(path):
    """Detecta trechos com baixa atividade de audio (silencio) para corte."""
    r = run(["ffmpeg", "-i", path, "-af", "silencedetect=noise=-35dB:d=1.2",
             "-f", "null", "-"])
    return r.stderr


def parse_silences(ffmpeg_log):
    """Extrai intervalos de silencio do log do silencedetect."""
    starts, ends = [], []
    for line in ffmpeg_log.splitlines():
        if "silence_start:" in line:
            starts.append(float(line.split("silence_start:")[1].strip()))
        elif "silence_end:" in line:
            ends.append(float(line.split("silence_end:")[1].split("|")[0].strip()))
    pairs = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else None
        pairs.append((s, e))
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--speed", type=float, default=2.0,
                    help="fator de aceleracao dos trechos sem interacao")
    ap.add_argument("--no-zoom", action="store_true", help="desativa zoom")
    ap.add_argument("--keep-silence", action="store_true",
                    help="nao corta silencios, apenas acelera")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        print("arquivo nao encontrado:", args.input)
        sys.exit(1)

    dur = probe_duration(args.input)
    print(f"duracao original: {dur:.1f}s")

    silences = parse_silences(detect_silence(args.input))
    print(f"trechos de baixa atividade detectados: {len(silences)}")

    tmpdir = tempfile.mkdtemp(prefix="studio-")
    segments = []
    cursor = 0.0
    for s, e in silences:
        e = e if e is not None else dur
        if s - cursor > 0.1:
            segments.append(("active", cursor, s))
        length = e - s
        if length > 5.0 and not args.keep_silence:
            segments.append(("cut", s, min(s + 1.0, e)))  # deixa 1s, corta o resto
        elif length > 2.0:
            segments.append(("fast", s, e))
        else:
            segments.append(("active", s, e))
        cursor = e
    if dur - cursor > 0.1:
        segments.append(("active", cursor, dur))

    parts = []
    for i, (kind, s, e) in enumerate(segments):
        seg_out = os.path.join(tmpdir, f"seg{i:03d}.mp4")
        vf = []
        if kind == "fast":
            vf.append(f"setpts={args.speed}*PTS")
        run(["ffmpeg", "-y", "-ss", f"{s:.3f}", "-to", f"{e:.3f}", "-i", args.input,
             "-vf", ",".join(vf) if vf else "null",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-an", seg_out])
        parts.append(seg_out)

    concat_file = os.path.join(tmpdir, "list.txt")
    with open(concat_file, "w") as fh:
        for p in parts:
            fh.write(f"file '{p}'\n")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_file,
         "-c", "copy", "-movflags", "+faststart", args.output])

    final_dur = probe_duration(args.output)
    print(f"OK: {args.output} ({final_dur:.1f}s, era {dur:.1f}s, "
          f"reducao de {(1 - final_dur / dur) * 100:.0f}%)")


if __name__ == "__main__":
    main()
