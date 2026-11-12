#!/usr/bin/env bash
# Prepare Diana's iPhone files for the template (run from video/):
#   ./prep.sh ~/Downloads/ScreenRecording.MP4 ~/Downloads/voice.m4a
# Screen: HEVC/60fps/1179-1290 wide -> H.264 30 fps 1080 wide (small, fast to render).
# Voice:  -> 48 kHz AAC, loudness-normalized for phones (-14 LUFS), light noise cleanup.
set -euo pipefail
ffmpeg -v error -y -i "$1" -an -vf "scale=1080:-2,fps=30,format=yuv420p" -c:v libx264 -preset veryfast -crf 20 public/screen.mp4
ffmpeg -v error -y -i "$2" -vn -af "highpass=f=80,afftdn=nf=-25,loudnorm=I=-14:TP=-1.5:LRA=11" -ar 48000 -c:a aac -b:a 192k public/voice.m4a
ffprobe -v error -show_entries format=duration -of csv=p=0 public/screen.mp4 | xargs printf "screen: %ss\n"
ffprobe -v error -show_entries format=duration -of csv=p=0 public/voice.m4a | xargs printf "voice:  %ss\n"
