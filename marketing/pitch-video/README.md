# Lighty · 40-second pitch video

`lighty-pitch-40s.mp4` is a 1920×1080 (16:9), 30 fps clip that runs exactly 40.000 s, with music and sound effects.
It opens with MAINGAU's biggest retention problem, then clicks through the real Lighty dashboard: the regions map,
churn risk, Lighty's next step and Ask Lighty. It ends on one sentence that sums up the product. `storyboard.png`
shows one frame per beat. `timing-report.md` is measured from the rendered frames: how long each line can be read,
and how many words are on screen.

## Scene sheet

| Time | On screen | Caption / text |
|---|---|---|
| 0:00–0:04.5 | Ten people icons. The share counts up to 55–60 % while six of them drop out | **55–60%** of customers cancel after just one year. |
| 0:04.5–0:08 | The bulb switches on (glow and rays), and the name comes in with a horizontal wipe | Lighty |
| 0:08–0:15 | The dashboard window tilts into place. **Regions**: the map of Germany (pillars on night blue), hover and click on Hessen to zoom in, hover and click on Hanau. Hanau's row lights up, then the sidebar opens Churn risk | Spot churn hot spots across Germany. |
| 0:15–0:23.3 | **Churn risk**: "204 customers are likely to cancel." The table scrolls, a click selects MG-100448 and the churn card shows 39 % and why. "Price guarantee ends within 90 days" is highlighted, with a **Year-one cliff** callout | See who might cancel, and why. |
| 0:23.3–0:27.5 | "Open MG-100448", the page scrolls to Lighty's recommendation (highlighted): "Resolve the open service issue first. No offer." | Get the next best step to keep them. |
| 0:27.5–0:35 | **Ask Lighty**: "How can I retain this customer?" is typed and sent, and the answer arrives. The churn and price-guarantee lines are highlighted | Ask Lighty how to keep each customer. |
| 0:35–0:40 | The bulb switches on again, the line comes in word by word, and a light passes over it | Spot churn early. Keep customers past year one. |

Every line is readable for at least 3 s; the dashboard captions stay for 3–8 s. No more than eight words of added
text are on screen at once. The recorded app screens are not counted.

**Motion:**
- Drifting light spots and a moving dot grid behind every scene.
- The counter and the people icons in the opening.
- The bulb lighting up, and the one horizontal wipe on the name.
- The window tilting in.
- Camera zooms that follow the clicks.
- Yellow highlight rings that dim the rest of the screen.
- A pointer with click rings and spark bursts.
- A pop-up callout.
- Captions that spring up and come in word by word, with a yellow underline.

Nothing shakes, flashes or spins.

## Sound

`music.py` makes the music and the sound effects with numpy. There are no recordings and no vocals, so there is no
licence to clear, and every run produces the same file.

- **Effects** sit exactly where the video says they happen. `lighty-pitch.html` lists the moments (`soundCues()`),
  and `render.cjs` hands that list to `music.py`:
  - a mouse click on each of the 6 clicks
  - a key tap for each of the 31 typed characters (deeper for the spaces), and Enter when the question is sent
  - whooshes on the logo, the window and the close
  - soft swishes on the highlights
  - a pop for the callout
  - a chime when Lighty's answer arrives
  - light ticks for the people icons appearing and leaving in the opening

  The music dips by about 2 dB while typing. The taps and clicks sit 22–38 dB above the music between 2 and 7 kHz,
  so they are clearly heard.
- **Music** plays at 120 bpm:
  - Bm7 under the problem.
  - At 0:04.5, a lift into D for the logo (about 2.5 dB louder).
  - G, Em, Bm, G, D, G and Em under the demo, then Asus4 → A while the answer is on screen.
  - At 0:35, it resolves to D on the closing line.

  The track is normalised to −16 LUFS.

## What is real and what is added

The dashboard frames are the real web app (`frontend/`) on the real backend with the demo data. Everything is
real: the pages, the clicks (Hessen, Hanau, the sidebar, the table row, "Open MG-100448", the chat box), the
Plotly hover tooltips, the scrolling, the typing and Lighty's answer. The regions map is the redesign from
`claude/kind-goodall-8xfovz` (merged into `main`, not deployed yet).

`capture.cjs` drives the app with Playwright and saves each step at 2× resolution, so close-ups stay sharp. The
video adds:
- the window frame
- the camera
- the highlights and the callout
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
node render.cjs         # → lighty-pitch-40s.mp4, storyboard.png, timing-report.md, takes about 6 minutes
```

- `render.cjs --bg "#FFFFFF" --accent "#0069F1"` changes the two brand colours.
- `--stills ./frames` writes only the storyboard frames, as a quick check.
- All timings are at the top of the script in `lighty-pitch.html`:
  - `CAPTIONS` for the captions
  - `PLAY` for the recorded clips
  - `CAM` for the zooms
  - `SPOTS` and `CALLOUT` for the highlights
  - `POINTER` and `CLICKS` for the mouse

  The sound effects follow automatically.
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
| `music.py` | Music bed and sound effects → `music.wav` (not committed; `render.cjs` rebuilds it) |
| `fonts/` | Plus Jakarta Sans, latin subset, with its OFL licence |
