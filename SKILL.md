---
name: adapta-studio
description: Pipeline de gravação e edição de vídeos de documentação das plataformas Adapta. Use quando o usuário pedir para gravar, documentar passo a passo, editar vídeo de uso de plataforma, ou produzir material de documentação com vídeo. Controla o browser no sandbox Vercel adapta-browser via API, grava a navegação, baixa o webm via /api/artifact e edita com ffmpeg/Python (corte de trechos mortos, aceleração, zoom em cliques), entregando MP4 final em artifacts/.
allowed-tools: Bash(python3:*), Bash(curl:*), Bash(ffmpeg:*)
hidden: true
---

# adapta-studio

Studio de screen recording para documentação das plataformas Adapta.

## Componentes

- **Browser remoto**: sandbox Vercel `adapta-browser-live`, controlado via API.
- **API base**: `https://adapta-browser.vercel.app`
- **Auth**: header `Authorization: Bearer $SESSION_API_SECRET` (segredo no env do projeto Vercel; se não estiver no ambiente local, pedir ao usuário).
- **Dashboard ao vivo**: retornado por `POST /api/session` (campo `dashboardUrl`), para o time assistir em tempo real.
- **Snapshot**: `AGENT_BROWSER_SNAPSHOT_ID` já configurado; sandboxes novos sobem em segundos.

## Fluxo de gravação

1. `POST /api/session` → garante sandbox no ar, retorna `dashboardUrl`.
2. `POST /api/cmd` com `{"args": ["open", "<url>"]}` → navegar.
3. `POST /api/cmd` com `{"args": ["record", "start", "/tmp/<nome>.webm"]}` → iniciar gravação.
   IMPORTANTE: a gravação só captura frames com o streaming ativo. Se `record stop` retornar "No frames captured", executar `{"args": ["stream", "enable"]}` e reiniciar a gravação.
4. Navegar o passo a passo via /api/cmd (click, fill, press, scroll, mouse move).
5. `POST /api/cmd` com `{"args": ["record", "stop"]}` → finalizar.
6. `POST /api/artifact` com `{"path": "/tmp/<nome>.webm"}` → retorna base64; decodificar e salvar localmente.
7. Editar com `scripts/edit_video.py` (ver abaixo).
8. Entregar MP4 em artifacts/ + documento passo a passo com timestamps.

## Endpoints da API

| Endpoint | Função |
|---|---|
| `POST /api/session` | Sobe/retoma sandbox, retorna dashboardUrl |
| `POST /api/cmd` | Executa comando agent-browser (args array) |
| `POST /api/shell` | Executa shell no sandbox (manutenção, instalar deps) |
| `POST /api/snapshot` | Snapshot do sandbox live |
| `POST /api/artifact` | Baixa arquivo do sandbox (base64) |

## Edição (scripts/edit_video.py)

Pipeline Python com ffmpeg:

- **Corte de trechos mortos**: detecta silêncio/estaticidade e remove (filtro `select` + `silencedetect`).
- **Aceleração de esperas**: trechos sem interação acelerados 2-4x (setpts).
- **Zoom em cliques**: nos momentos de clique, crop+scale suave no ponto do clique.
- **Highlight de cursor**: overlay de círculo seguindo a posição do mouse.
- **Saída**: MP4 H.264 yuv420p +faststart em artifacts/.

Uso:

```bash
python3 scripts/edit_video.py <input.webm> <output.mp4> [--speed 2] [--no-zoom]
```

## Camera Screen Studio (scripts/studio_camera.py)

Camera com zoom/pan estilo Screen Studio sobre gravacao real:

- Zoom acionado SOMENTE em cliques (log de cliques com timestamps).
- Easing exponencial: `alpha = 1 - exp(-dt/tau)`; abertura SEMPRE em tela cheia (OPENING_HOLD 1,2s).
- Zoom out em movimento rapido sustentado 0,3s; camera segue mouse com atraso 0,35s so em zoom in.
- Motion blur temporal (3 sub-exposicoes por frame via numpy); breathing para evitar frames identicos.
- Saida MP4 24fps exato (48fps decimado /2); GIF com delay uniforme 40ms (GIF so aceita multiplos de 10ms).
- PIL save_all funde frames identicos: perturbacao de 1px + delays como lista; NUNCA optimize=True.

Uso:

```bash
python3 scripts/studio_camera.py <input.mp4> <mouse.log> <output.gif> [largura] [clicks.log] [logo.png]
```

## GIFs (scripts/make_zoom_gif.py, make_smooth_gif.py)

- make_zoom_gif.py: GIF com zoom/pan por keyframes e easing smoothstep; fonte 1050px nativa, downscale so no final; paleta 128 cores.
- make_smooth_gif.py: renderizacao frame a frame com PIL, crop subpixel affine BICUBIC, cursor com sombra + ripple de clique; coordenadas medidas da tela real (nunca chutar).
- Limites do GIF: < 200 frames, < ~1MB quando possivel; delays multiplos de 10ms.

## Documento passo a passo (template)

Para cada gravação, produzir MD com: objetivo, pré-requisitos, passos numerados com timestamp do vídeo, erros comuns, screenshots anotados (`screenshot --annotate`).

## Limitações conhecidas

- Gravação requer `stream enable` ativo (senão "No frames captured").
- Sandbox expira em 24h; state de login não persiste entre sandboxes sem `state save/restore`.
- Login em plataformas com SSO/2FA pode exigir intervenção manual na primeira sessão.
- Coordenadas CDP sao do viewport; X inclui 56px de barra do Chrome em gravacoes headful (CROP_TOP=56 no studio_camera.py, nunca crop previo no video de entrada).
- NUNCA subamostrar video uniformemente para caber em N frames (stutter visivel); cortar o final estatico.
