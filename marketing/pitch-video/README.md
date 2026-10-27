# MAINGAU Guardian · 30-second pitch video

`guardian-pitch-30s.mp4` is a 1920×1080 (16:9), 30 fps clip that runs exactly 30.000 s, with an AAC music bed.
It is for CRM, marketing and customer-service leads at MAINGAU Energie and has one call to action: book a live demo.
`storyboard.png` shows one frame per beat. `timing-report.md` is measured from the rendered frames: how long each
line can be read and how many words are on screen.

## Before it goes out

The end card still shows the placeholder **`[URL]`**. Re-render with the booking link:

```bash
node render.cjs --url "your-booking-link"     # about 70 s; rewrites the mp4, storyboard and timing report
```

`--bg` and `--accent` change the two brief colours the same way. Needs Node with Playwright and Chromium, ffmpeg
with libx264, and python3 with numpy.

## Brief settings used

| Brief | Used | Source |
|---|---|---|
| Background | `#F1F6FF` | MAINGAU blue-grey-light, the canvas of the web app (`frontend/theme/lighty-theme.css`) |
| Accent | `#004BAD` | MAINGAU brand blue (same file) |
| Typeface | Plus Jakarta Sans | The web app's stand-in for MAINGAU's licensed RT Rondelle; OFL, in `fonts/` |
| Proof figure | ~7,959 EUR | Projected Protected Customer Value vs. the sales-first baseline (`README.md`, `API_CONTRACT.md`); a model-based estimate on mock data |

## Scene sheet

| Time | On screen | Words |
|---|---|---:|
| 0:00–0:04 | “Sales offers to upset customers can lose money.” fades in, holds, fades out | 8 |
| 0:04–0:06.6 | Horizontal wipe reveals the shield mark and “MAINGAU Guardian” | 2 |
| 0:06.75–0:09 | Name gives way to “The AI that knows when NOT to sell.” (mark stays) | 8 |
| 0:09–0:11.6 | “Recover upset customers before selling to them.” | 7 |
| 0:11.6–0:14 | Customer card: Sample customer · Open complaint · **Service first** tag · callback icon | 6 |
| 0:14–0:16.5 | “Every blocked offer comes with a clear reason.” | 8 |
| 0:16.5–0:19 | Checklist: ✓ Product eligible · ✓ No complaints · ⊘ **Consent withdrawn: offer blocked** | 8 |
| 0:19–0:21.5 | “Compare alternatives before anything reaches a customer.” | 7 |
| 0:21.5–0:24 | Two bars (Expected value): Sales offer vs. **Service first**, marked Recommended | 7 |
| 0:24–0:27 | **Model estimate** · ~7,959 EUR · protected vs. sales-first | 7 |
| 0:27–0:30 | Mark + “MAINGAU Guardian”; from 0:27.8 “Book a live demo” + URL | 2 → 7 |

Transitions: one 0.6 s horizontal wipe at 0:04, and 0.5 s cross-dissolves centred on 0:09, 0:14, 0:19, 0:24
and 0:27. Lines inside a scene fade, with an 18 px rise. Nothing shakes, flashes, spins or zooms.

## Where the brief contradicts itself

1. **CTA timing.** If the CTA starts at 0:28.5, it is readable for only 1.5 s, but the brief requires 2 s.
   The CTA fades in at 0:27.8 instead, so it is readable from 0:27.97 to the end (2.03 s). The logo line still
   comes first, on its own. To use the brief's timing, set `"s7-cta"` in `guardian-pitch.html` to `[28.5, 0.3]`.
2. **Eight words at once.** Each value line plus its visual is more than eight words. Example: “Every blocked
   offer comes with a clear reason.” (8) plus the checklist (8) makes 16. So each value scene shows its line
   first, then its visual. In the reveal, the name gives way to the eight-word tagline, and the shield mark stays.
   During a 0.5 s cross-dissolve, the outgoing and incoming text overlap at partial opacity. The limit is checked
   on settled frames.
3. **Checklist row.** It reads “Consent withdrawn: offer blocked”, without the full stop, to match the other
   rows. The other two rows use labels from the engine's eligibility rules (`app/services/rule_labels.py`).

## Content notes

* All on-screen data is illustrative. There are no customer IDs or names, and the card says “Sample customer”.
  The bars carry no numbers.
* The proof figure always carries the “Model estimate” label and the “~”. It is never shown as a measured result.
* The product is called Lighty in the rest of this repo. The video uses “MAINGAU Guardian” as briefed. The
  shield mark is a simple placeholder, because the repo has no Guardian logo. Swap the `#mark` symbol in
  `guardian-pitch.html` if there is an official one.

## Music

`music.py` synthesises the track with numpy: felt piano, a pad, a sub bass and room reverb. There are no vocals
and no samples, so there is no licence to clear, and every run produces the same file. It plays at 120 bpm, so
every scene boundary lands on a beat:

* Bm7 under the hook.
* At 0:04, a lift into D. The pad opens up, the arpeggio and bass come in, and the level rises about 4 dB.
* G, Bm, Em and Asus4 → A through the value scenes and the proof.
* At 0:27, it resolves to D on the end card and rings out by 0:30.

The track is normalised to −16 LUFS with peaks below −1.5 dBTP.

## Files

| File | What it is |
|---|---|
| `guardian-pitch.html` | All scenes. `renderAt(t)` draws second `t`. Served over HTTP, it is a preview player (`python3 -m http.server`, then open `/guardian-pitch.html`). That server cannot seek, so sound only plays when you start from 0:00 |
| `render.cjs` | Steps through the 900 frames, encodes H.264 + AAC, writes `storyboard.png` and `timing-report.md` |
| `music.py` | Music bed → `music.wav` (not committed; `render.cjs` rebuilds it) |
| `fonts/` | Plus Jakarta Sans, latin subset, with its OFL licence |
