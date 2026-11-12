# Florida Bids Reels (Remotion)

Turns Diana's silent iPhone screen recording + DJI voiceover into a 1080×1920 Reel:
full-screen recording cut to the voice, a bold kicker per line, word-by-word captions, Iggy outro.

```
npm ci
./prep.sh ScreenRecording.MP4 voice.m4a          # -> public/screen.mp4, public/voice.m4a
cp props.sample.json props.json                    # then set lines[].from/to (voice) and screen.start/end
REMOTION_BROWSER=/path/to/chrome-headless-shell npm run render   # -> out/reel.mp4
```

Each line in `props.json`: `text` (captions), `kicker` (top text), `from`/`to` (seconds in the voice file),
`screen.start`/`screen.end` (which part of the screen recording plays during that line; it is sped up
or slowed to fit). Facebook Reels must be 3–90 s.
