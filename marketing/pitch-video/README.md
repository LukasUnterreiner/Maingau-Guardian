# Lighty · 30-second pitch video

`lighty-pitch-30s.mp4` is a 1920×1080 (16:9), 30 fps clip that runs exactly 30.000 s, with an AAC music bed.
It opens with MAINGAU's biggest retention problem, shows the real Lighty dashboard being clicked through (churn
risk, then Ask Lighty), and ends on one sentence that sums up the product. `storyboard.png` shows one frame per
beat. `timing-report.md` is measured from the rendered frames: how long each caption can be read, and how many
words are on screen.

## Scene sheet

| Time | On screen | Caption / text |
|---|---|---|
| 0:00–0:04 | The problem | **55–60%** of customers cancel after just one year. |
| 0:04–0:07.5 | Horizontal wipe reveals the Lighty bulb and name | Lighty |
| 0:07.5–0:15 | Churn risk page, zoom on "204 customers are likely to cancel." The table scrolls, a click selects MG-100448, the churn card shows 39 % and why (price guarantee ends within 90 days, open complaint) | See who is likely to cancel, and why. |
| 0:15–0:19.5 | Click "Open MG-100448", the page scrolls to Lighty's recommendation: "Resolve the open service issue first. No offer." | Get the next best step to keep them. |
| 0:19.5–0:26.5 | Ask Lighty: "How can I retain this customer?" is typed and sent; the answer appears, then a close-up of the churn and price-guarantee lines | Ask Lighty how to keep each customer. |
| 0:26.5–0:30 | Bulb logo and closing line | Spot churn early. Keep customers past year one. |

Every caption is readable for at least 3 s; the three dashboard captions stay for 4–7 s. No caption or title is
longer than eight words. Transitions: one horizontal wipe at 0:04, and 0.5 s cross-dissolves at 0:07.5 and 0:26.5.
Inside the dashboard, the moves are slow camera zooms, a mouse pointer and soft click rings. Nothing shakes,
flashes or spins.

## What is real and what is added

The dashboard frames are the real web app (`frontend/`) running on the real backend with the demo data: real
pages, real clicks (row selection, "Open MG-100448"), real scrolling, real typing in the chat box, and Lighty's
real answer. `capture.cjs` drives the app with Playwright and saves each step at 2× resolution, so close-ups
stay sharp.

The video adds the window frame, the camera zooms, the captions and the mouse pointer. Headless Chromium does not
draw a pointer, so it is placed on the exact spots that were clicked. A "Demo data" tag in the window bar says
that the customers are from the mock dataset. MG-100448 was picked because they joined in October 2025, their
price guarantee ends within 90 days and they have an open complaint, so they sit right at the year-one cliff.

## Recording the demo and rendering

```bash
# 1. backend with one employee token (no AI key needed: Lighty then answers with its rules, same every time)
EMPLOYEE_TOKENS="demo-token-service-0001:agent-7:service_agent" uvicorn app.main:app --port 8000
# 2. web app, signed in automatically
cd frontend && LIGHTY_API_URL=http://127.0.0.1:8000 LIGHTY_TOKEN=demo-token-service-0001 \
  streamlit run app.py --server.port 8501 --server.headless true
# 3. record, then render (from marketing/pitch-video/)
node capture.cjs        # → demo-frames/ (about 70 MB, not committed), takes about a minute
node render.cjs         # → lighty-pitch-30s.mp4, storyboard.png, timing-report.md, takes about 3 minutes
```

`render.cjs --bg "#FFFFFF" --accent "#0069F1"` changes the two brand colours. `--stills ./frames` writes only the
storyboard frames, as a quick check. All timings are at the top of the script in `lighty-pitch.html`: `BUILD` for
the captions, `PLAY` for the recorded clips, `CAM` for the zooms, `POINTER` and `CLICKS` for the mouse. Re-run
`capture.cjs` after the app changes, so the video shows the current app.

## Content notes

* **55–60 %** is the figure from the MAINGAU team. There is no source for it in this repo, so check the wording
  before external use.
* The name on screen is **Lighty**, as in the app, the logo files and the chat ("Ask Lighty").
* The logo is the bulb from `frontend/static/lighty-bulb.svg`. The end card shows the bulb and the closing line.
  Adding the wordmark there would put nine words on screen.
* Brand settings: background `#F1F6FF` (MAINGAU blue-grey-light) and accent `#004BAD` (MAINGAU brand blue). The
  typeface is Plus Jakarta Sans, the app's own (OFL, in `fonts/`).

## Music

`music.py` synthesises the track with numpy: felt piano, pad, sub bass and room reverb. There are no vocals and
no samples, so there is no licence to clear, and every run produces the same file. It plays at 120 bpm, so every
boundary lands on a beat:

* Bm7 under the problem.
* At 0:04, a lift into D for the Lighty reveal (about 5 dB louder, with the arpeggio and bass coming in).
* G, Bm, Em and G under the demo, then Asus4 → A while the answer is on screen.
* At 0:26.5, it resolves to D on the closing line and rings out by 0:30.

The track is normalised to −16 LUFS.

## Files

| File | What it is |
|---|---|
| `lighty-pitch.html` | The video: `renderAt(t)` draws second `t`. Served over HTTP (`python3 -m http.server`, then `/lighty-pitch.html`), it is a preview player. That server cannot seek audio, so sound only plays when you start from 0:00 |
| `capture.cjs` | Clicks through the running app and saves the frames plus `manifest.json` (clips and the boxes the camera and pointer use) |
| `render.cjs` | Steps through the 900 frames, encodes H.264 + AAC, writes `storyboard.png` and `timing-report.md` |
| `music.py` | Music bed → `music.wav` (not committed; `render.cjs` rebuilds it) |
| `fonts/` | Plus Jakarta Sans, latin subset, with its OFL licence |
