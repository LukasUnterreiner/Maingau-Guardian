# Lighty · 40-second pitch video

`lighty-pitch-40s.mp4` is a 1920×1080 (16:9), 30 fps clip that runs exactly 40.000 s, with music and sound effects.
It opens with MAINGAU's biggest retention problem, then clicks through the real Lighty dashboard: the regions map,
churn risk, Lighty's next step and Ask Lighty. It ends on one sentence that sums up the product. `storyboard.png`
shows one frame per beat. `timing-report.md` is measured from the rendered frames: how long each line can be read,
and how many words are on screen.

## Scene sheet

| Time | On screen | Caption / text |
|---|---|---|
| 0:00–0:04.5 | Ten people icons. The share counts up out of a blur to 55–60 % while six of them drop out of focus | **55–60%** of customers cancel after just one year. |
| 0:04.5–0:08 | Music drops in. The bulb turns in and switches on (glow and rays), and the name comes in with a horizontal wipe | Lighty |
| 0:08–0:14.5 | The dashboard window swings in, in 3D. **Regions**: the map of Germany (pillars on night blue), hover and click on Hessen to zoom in, hover and click on Hanau. Hanau's row pops out, then the sidebar opens Churn risk | Spot churn hot spots across Germany. |
| 0:14.5–0:22 | **Churn risk**: "204 customers are likely to cancel." The table scrolls, a click selects MG-100448 and the churn card shows 39 % and why. "Price guarantee ends within 90 days" pops out, with a **Year-one cliff** callout | See who might cancel, and why. |
| 0:22–0:25.8 | "Open MG-100448", the page scrolls to Lighty's recommendation, which pops out: "Resolve the open service issue first. No offer." | Get the next best step to keep them. |
| 0:25.8–0:32.5 | **Ask Lighty**: "How can I retain this customer?" is typed and sent, and the answer arrives. The churn and price-guarantee lines pop out | Ask Lighty how to keep each customer. |
| 0:32.5–0:36.5 | The dashboard rushes forward into a blur. On night blue, the slogan flips up out of depth, one part per hit, each part under its own icon (eye, speech bubble, tick) | **See it, Say it, Sort it** |
| 0:36.5–0:40 | The bulb switches on again, the line comes in word by word, and a light passes over it | Spot churn early. Keep customers past year one. |

Every caption and title is readable for at least 3 s; the dashboard captions stay for 3–6.5 s. The slogan's three
parts land on quick hits right after the drop, then the whole line holds for more than 3 s. No more than eight
words of added text are on screen at once. The recorded app screens are not counted.

**3D and blur, kept readable:**
- **Close-ups stay flat and sharp.** The dashboard window tilts in 3D only while the camera is wide. It turns flat
  for every close-up.
- **Motion blur only while the camera moves.** It appears briefly on camera moves and is gone as soon as the
  camera stops.
- **Pop-outs.** The highlighted detail lifts off the screen, sharp and slightly larger, with a yellow edge. The rest
  of the screen softens and dims behind it, like a shallow depth of field.
- **Scene changes.** These blur and scale through. The opening, the logo and the slogan come in out of a blur or
  out of depth.
- **Background depth.** Out-of-focus glass panes float at three depths behind every scene. The captions are
  frosted glass, so the screen behind them blurs.
- **Other motion:** the click rings and spark bursts, the "Year-one cliff" callout and the yellow caption underline.

Nothing shakes, flashes or spins, and no text moves while it is meant to be read.

## Sound

`music.py` makes the music and the sound effects with numpy. There are no recordings, no samples and no vocals, so
there is no licence to clear, and every run produces the same file.

- **Music:** an upbeat electronic product-demo track at 120 bpm (kick, clap, hats, bass, offbeat plucks, a
  side-chained pad, an arpeggio). Its bars line up with the video:
  - a quiet, filtered intro under the problem, with a riser into the logo
  - an impact and the beat at 0:04.5
  - the full groove under the dashboard
  - a breakdown without kick, clap or bass while the question is typed, so the key taps stay clear
  - a riser into the slogan
  - an impact at 0:32.5, then three quick chord hits on "See it", "Say it", "Sort it"
  - a final D chord on the closing line that rings out

  The track is normalised to −14 LUFS.
- **Effects** sit exactly where the video says they happen. `lighty-pitch.html` lists the moments (`soundCues()`),
  and `render.cjs` hands them to `music.py` together with the moments the music lines up with:
  - a mouse click on each of the 6 clicks
  - a key tap for each of the 31 typed characters (deeper for the spaces), and Enter when the question is sent
  - whooshes on the window and the scene changes
  - soft swishes on the pop-outs
  - a pop for the callout
  - a chime when Lighty's answer arrives
  - light ticks for the people icons in the opening

  The key taps stand out from the music by more than 20 dB between 2 and 7 kHz. The mouse clicks do too, except
  the first, which lands right after a clap and stands out by only about 3 dB.

## What is real and what is added

The dashboard frames are the real web app (`frontend/`) on the real backend with the demo data. Everything is
real: the pages, the clicks (Hessen, Hanau, the sidebar, the table row, "Open MG-100448", the chat box), the
Plotly hover tooltips, the scrolling, the typing and Lighty's answer. The regions map is the redesign from
`claude/kind-goodall-8xfovz` (merged into `main`, not deployed yet).

`capture.cjs` drives the app with Playwright and saves each step at 2× resolution, so close-ups stay sharp. The
video adds:
- the window frame
- the camera
- the 3D, the blur, the pop-outs and the callout
- the captions
- the pointer, placed on the exact spots that were clicked (headless Chromium draws none)

A "Demo data" tag in the window bar marks the mock customers. MG-100448 lives in Hanau, joined in October 2025,
their price guarantee ends within 90 days and they have an open complaint. That puts them at the year-one cliff.

## Recording the demo and rendering

```bash
# 1. backend with one employee token (no AI key needed: Lighty then answers with its rules, same every time)
EMPLOYEE_TOKENS="demo-token-service-0001:agent-7:service_agent" uvicorn app.main:app --port 8000
# 2. web app, signed in automatically
cd frontend && LIGHTY_API_URL=http://127.0.0.1:8000 LIGHTY_TOKEN=demo-token-service-0001 \
  streamlit run app.py --server.port 8501 --server.headless true
# 3. record, then render (from marketing/pitch-video/)
node capture.cjs        # → demo-frames/ (about 70 MB, not committed), takes about a minute
node render.cjs         # → lighty-pitch-40s.mp4, storyboard.png, timing-report.md, takes about 10 minutes
```

- `render.cjs --bg "#FFFFFF" --accent "#0069F1"` changes the two brand colours.
- `--stills ./frames` writes only the storyboard frames, as a quick check.
- All timings are at the top of the script in `lighty-pitch.html`:
  - `CAPTIONS` for the captions
  - `PLAY` for the recorded clips
  - `CAM` for the zooms
  - `POPS` and `CALLOUT` for the pop-outs
  - `HITS` for the slogan's three beats
  - `POINTER` and `CLICKS` for the mouse

  The sound effects follow automatically. The logo, slogan and close must stay on a bar of the music (bars start
  at 0:00.5, every 2 s). `music.py` stops with a message if they don't.
- Re-run `capture.cjs` after the app changes, so the video shows the current app.

## Content notes

* **55–60 %** is the figure from the MAINGAU team. There is no source for it in this repo, so check the wording
  before external use.
* The name on screen is **Lighty**, as in the app, the logo files and the chat ("Ask Lighty").
* The logo is the bulb from `frontend/static/lighty-bulb.svg`. The end card shows the bulb and the closing line.
  Adding the wordmark there would put nine words on screen.
* Brand settings:
  - background `#F1F6FF` (MAINGAU blue-grey-light)
  - accent `#004BAD` (MAINGAU brand blue)
  - spark yellow `#FFE500` from the bulb, used only for highlights
  - typeface: Plus Jakarta Sans, the app's own (OFL, in `fonts/`)

## Files

| File | What it is |
|---|---|
| `lighty-pitch.html` | The video: `renderAt(t)` draws second `t`, `soundCues()` lists the effects. Served over HTTP (`python3 -m http.server`, then `/lighty-pitch.html`), it is a preview player. That server cannot seek audio, so sound only plays when you start from 0:00 |
| `capture.cjs` | Clicks through the running app and saves the frames plus `manifest.json` (clips and the boxes the camera, highlights and pointer use) |
| `render.cjs` | Steps through the 1,200 frames, mixes the sound, encodes H.264 + AAC, writes `storyboard.png` and `timing-report.md` |
| `music.py` | Music and sound effects → `music.wav` (not committed; `render.cjs` rebuilds it) |
| `fonts/` | Plus Jakarta Sans, latin subset, with its OFL licence |
