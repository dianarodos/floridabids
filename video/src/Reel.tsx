// Florida Bids Reel: Diana's silent screen recording, cut to her voiceover, with a bold kicker per
// line, word-by-word captions and the Iggy outro. Everything is driven by props.json (see README.md).
import React from "react";
import {
  AbsoluteFill, Audio, Img, OffthreadVideo, Sequence, interpolate, spring, staticFile,
  useCurrentFrame, useVideoConfig,
} from "remotion";

export type Line = {
  text: string;            // what she says (captions)
  kicker?: string;         // big text at the top while this line plays
  from: number;            // seconds in the voice file where the line starts
  to: number;              // ...and where the next line takes over
  screen: { start: number; end: number };  // the part of the screen recording to show (seconds)
};
export type ReelProps = {
  screen: string;          // file in public/
  voice: string;           // file in public/
  voiceStart?: number;     // seconds to skip at the start of the voice file
  lines: Line[];
  outro?: number;          // seconds of Iggy ending
  url?: string;
};

const C = { cream: "#fbf6ec", green: "#0d5c50", ink: "#14211e", amber: "#f2b33d" };
const OUTRO = 3;

export const reelDuration = (p: ReelProps) => {
  const last = p.lines[p.lines.length - 1];
  return last.to - p.lines[0].from + (p.outro ?? OUTRO);
};

const Fonts = () => (
  <style>{`
@font-face{font-family:Serif;font-weight:700;src:url(${staticFile("source-serif-4-latin-700-normal.woff2")}) format('woff2')}
@font-face{font-family:Plex;font-weight:600;src:url(${staticFile("ibm-plex-sans-latin-600-normal.woff2")}) format('woff2')}
@font-face{font-family:Plex;font-weight:500;src:url(${staticFile("ibm-plex-sans-latin-500-normal.woff2")}) format('woff2')}`}</style>
);

// --- screen recording: full-bleed, scaled to the width, centered so the status bar and Safari bar fall off
const Screen: React.FC<{ src: string; seg: Line["screen"]; dur: number }> = ({ src, seg, dur }) => {
  // speed so the chosen part of the recording exactly fills the line (never runs past seg.end)
  const rate = Math.min(4, Math.max(0.2, (seg.end - seg.start - 0.05) / Math.max(0.3, dur)));
  return (
    <AbsoluteFill style={{ background: C.ink }}>
      <OffthreadVideo src={staticFile(src)} muted startFrom={Math.round(seg.start * 30)} playbackRate={rate}
        style={{ width: "100%", height: "100%", objectFit: "cover" }} />
    </AbsoluteFill>
  );
};

// --- big kicker at the top (inside Instagram's safe area)
const Kicker: React.FC<{ text: string }> = ({ text }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const s = spring({ frame: f, fps, config: { damping: 14, stiffness: 170 } });
  return (
    <div style={{ position: "absolute", top: 230, left: 60, right: 60, display: "flex", justifyContent: "center" }}>
      <div style={{ background: C.green, color: "#fff", fontFamily: "Serif", fontWeight: 700, fontSize: 82, lineHeight: 1.05,
        padding: "26px 38px", borderRadius: 30, textAlign: "center", boxShadow: "0 18px 50px rgba(0,0,0,.35)",
        transform: `scale(${0.7 + 0.3 * s}) rotate(${(1 - s) * -4}deg)`, opacity: s }}>{text}</div>
    </div>
  );
};

// --- word-by-word captions in the lower middle (above Instagram's caption/UI area)
const Captions: React.FC<{ text: string; dur: number }> = ({ text, dur }) => {
  const f = useCurrentFrame(); const t = f / 30;
  const words = text.split(/\s+/).filter(Boolean);
  const total = words.reduce((a, w) => a + w.length + 2, 0);
  let acc = 0;
  const times = words.map(w => { const s = (acc / total) * dur; acc += w.length + 2; return s; });
  const cur = Math.max(0, times.findIndex((s, i) => t >= s && (i === words.length - 1 || t < times[i + 1])));
  const per = 3;                                     // words on screen at once
  const start = Math.floor(cur / per) * per;
  return (
    <div style={{ position: "absolute", top: 1170, left: 40, right: 40, display: "flex", justifyContent: "center" }}>
      <div style={{ fontFamily: "Plex", fontWeight: 600, fontSize: 68, lineHeight: 1.2, textAlign: "center", color: "#fff",
        background: "rgba(14,22,20,.82)", borderRadius: 26, padding: "18px 30px", whiteSpace: "nowrap", maxWidth: 1000 }}>
        {words.slice(start, start + per).map((w, i) => (
          <span key={i} style={{ color: start + i === cur ? C.amber : "#fff", margin: "0 9px", display: "inline-block" }}>{w}</span>
        ))}
      </div>
    </div>
  );
};

const Outro: React.FC<{ url: string }> = ({ url }) => {
  const f = useCurrentFrame(); const { fps } = useVideoConfig();
  const pop = spring({ frame: f, fps, config: { damping: 11, stiffness: 140 } });
  const txt = spring({ frame: f - 8, fps, config: { damping: 16 } });
  return (
    <AbsoluteFill style={{ background: C.cream, alignItems: "center", justifyContent: "center", gap: 40 }}>
      <Img src={staticFile("iggy.png")} style={{ width: 620, transform: `scale(${pop}) translateY(${(1 - pop) * 80}px)` }} />
      <div style={{ fontFamily: "Serif", fontWeight: 700, fontSize: 104, color: C.green, opacity: txt,
        transform: `translateY(${(1 - txt) * 40}px)` }}>{url}</div>
      <div style={{ fontFamily: "Plex", fontWeight: 600, fontSize: 48, color: C.ink, opacity: txt }}>
        Every open Florida bid · <span style={{ color: "#9a5b00" }}>FREE</span>
      </div>
      <div style={{ fontFamily: "Plex", fontWeight: 500, fontSize: 40, color: "#5a6a66", opacity: txt }}>🔗 link in bio</div>
    </AbsoluteFill>
  );
};

export const Reel: React.FC<ReelProps> = (p) => {
  const fps = 30;
  const t0 = p.lines[0].from;
  const end = p.lines[p.lines.length - 1].to - t0;
  return (
    <AbsoluteFill style={{ background: C.ink }}>
      <Fonts />
      {p.lines.map((l, i) => {
        const from = Math.round((l.from - t0) * fps), len = Math.max(1, Math.round((l.to - l.from) * fps));
        return (
          <Sequence key={i} from={from} durationInFrames={len}>
            <Screen src={p.screen} seg={l.screen} dur={l.to - l.from} />
            {l.kicker ? <Kicker text={l.kicker} /> : null}
            <Captions text={l.text} dur={l.to - l.from} />
          </Sequence>
        );
      })}
      <Audio src={staticFile(p.voice)} startFrom={Math.round(t0 * fps)} />
      <Sequence from={Math.round(end * fps)}><Outro url={p.url ?? "floridabids.org"} /></Sequence>
    </AbsoluteFill>
  );
};
