# Florida Bids: the 7 AM social routine (Mon–Sat)

The scheduled task follows this file every morning. Edit it to change how drafts are written.

## 1. Read today's material
- `git pull`, then read `site/social/today.json` (made by the 5:15 AM run): `stats`, `am`, `pm`,
  `new_today`, `closing_soon`, `video.highlights`, and the card images `site/social/<date>-am.jpg` / `-pm.jpg`.
- If `today.json` isn't for today, the morning run failed: tell Diana, and stop.
- Sunday (`posts_today` false): nothing to do.

## 2. Pick bids people will care about
- Choose bids a small business could actually do: janitorial, landscaping, roofing, trash/hauling,
  repairs, IT, catering, painting, fencing, pest control. Prefer due dates 5+ days away.
- Fun or surprising ones make the best hooks (mosquito spraying by airplane, fishing pier, tree removal).
- Skip junk titles ("View the opportunity »", "DRAFT ATTACHMENT", notices of intent to award).
- **The card must show the same bids as its caption.** If not, run `python -m social.recard` (see its
  docstring), look at the new image, then commit + push `site/social/` before posting.
- The afternoon theme comes from today.json; make its bids fit the theme's promise (e.g. "clean, mow, haul,
  fix" means actual janitorial, landscaping, trash and repair bids).

## 3. Write three drafts
1. **Morning: Facebook** (posted on approval): hook line with today's count, 3–4 bids with emoji + county,
   one line on why it matters. **No URL in the text** (Facebook limits Pages to about 2 link posts a month).
   End with `🔗 Link in the first comment`, plus 3–4 hashtags.
   The link goes in as the first comment: `👉 Every open Florida bid, free: https://floridabids.org`
2. **Morning: Instagram** (posted on approval): the same, shorter. End with `Link in bio 🔗` + 6–8 hashtags.
3. **Afternoon: Facebook** (scheduled 3:00 PM): the theme post. **No URL, no link comment** (it's scheduled).
   The card shows floridabids.org.

## 4. Video script (faceless screen recording + Diana's voice)
30–60 s, about 110–130 words:
- **Hook (first 2 s):** surprising and specific, from today's bids.
- Then one or two real bids from today, what Florida Bids does, one screen action, and the CTA
  ("Don't let your competitor find it first").
- Give it as a table: line · what to record on screen (search terms that really return today's bids) ·
  big on-screen text. Remind her: screen recording with Microphone off, Do Not Disturb on, voice
  separately in Voice Memos with 1 s pauses.
- When she sends the two files: `video/` has the Remotion template (`video/README.md`, `prep.sh`).

## 5. Send, wait, post
- Send everything in one message (both card images + 3 captions + the script), plus a push notification.
- On "approve" (or after her edits):
  - `post.yml` slot=am platforms=facebook caption=<FB text> link_comment=<link comment>
  - `post.yml` slot=am platforms=instagram caption=<IG text>
  - `post.yml` slot=pm platforms=facebook at=15:00 caption=<PM text>
  - Check each run's log; send her the Facebook post link.
- A finished Reel: commit the MP4 to `site/social/reels/`, then `reel.yml` (platforms=both,
  caption without URL, link_comment=<link comment>).
- Never post anything she hasn't approved.
