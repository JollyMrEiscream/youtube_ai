# What makes a technology Short worth finishing

This is the research behind the renderer. It is a briefing, not a guarantee that a video will be recommended or monetized. YouTube ranks each Short on whether people choose it, stick with it, and feel it was worth the time. The pipeline is built to give a viewer a reason to do those three things, and to give a person a review step before anything is public.

## The bar

YouTube's own recommendation guidance says the opening seconds are when someone decides to stay or move on, especially on Shorts. The intro has to pay off the promise immediately. There is no required posting cadence. What the system looks at, once a Short is offered, is whether people choose it, how long they stay (average view duration and percent viewed), and whether they enjoyed it (likes and post-watch surveys).

A Short is vertical. YouTube's creator guide says to shoot 9:16 and to get the point across inside the first few seconds. Shorts can run up to three minutes, but the format people actually finish is much tighter. Google's Shorts ads spec, which describes the same player, says vertical 9:16 beats landscape, only the first 60 seconds play in the Shorts feed for those placements, and spots under 60 seconds match how people use the feed. Sound plus on-screen text is part of that spec, because a Short has to read as well as play.

Jenny Hoyos, talking with YouTube's Shorts product lead in January 2025, put the open even earlier: about one second, built as a small arc of shock or intrigue and then a payoff. She treats a Short as one bit, not a welcome-back intro.

YouTube's own Shorts clip tool burns in captions and lets a creator restyle them. That is the pattern this project follows: words on screen, timed to the voice, with the active word marked, placed in the middle of the frame with side margins so the like column and the bottom title don't cover them.

Cuts are a craft choice, not a number YouTube published. Their retention guidance says to keep curiosity going and to vary the edit. The renderer hard-cuts every few seconds, punches in, and changes the shot, because a single slow zoom on one photo gives people nothing new to look at. That is also the failure mode YouTube names in its monetization rules: image slideshows and videos that feel like the same template.

## What the pipeline does with that

| Finding | Where it shows up |
| --- | --- |
| Hook in the first 1–2 seconds, no greeting | The script prompt and the offline writer both start with a short line. A kinetic title sits on the opening shot for about two seconds. Banned: "welcome back", "let's dive in", "you won't believe". |
| One idea, then a payoff | One story per video. The last card is a payoff line, and the spoken close points at the source instead of begging for a like. |
| About 30–60 seconds, vertical 1080×1920 | Scripts are held to roughly 95–140 words. The frame is 1080×1920. Default batch is 5, not 30, so each one can be watched before it goes up. |
| Words on screen, current word marked | Edge TTS returns word timings. Those become burned-in captions. OpenAI TTS estimates timings from the audio length. |
| Motion, not a slideshow | Each Short pulls real clips (Pexels, Pixabay, or Wikimedia Commons), pans or punch-zooms them, can show the source page, and cuts. A moving type card is the fallback when a search returns nothing, and the log says so. |
| A bed under the voice | A generated music bed ducks while someone is speaking. Drop your own licensed tracks in `assets/music` and those are used instead. |
| Same channel, different videos | Eight profiles rotate hook shape, sentence shape, voice, rate, caption color, music, and pacing. Five videos in a day do not share a profile. |
| A person still decides | Renders land in `output/review/pending`. Upload runs only on approved files, and only up to the daily cap. Skipping review is `SKIP_REVIEW=1` together with `AUTO_UPLOAD=1`. |

## Monetization, said plainly

On July 15, 2025 YouTube renamed its "repetitious content" monetization rule to "inauthentic content." The rule already covered mass-produced and repetitive videos. A channel can reuse an intro. It cannot upload videos that feel interchangeable, or slideshows with the same narration, or stories that only swap a few words. Using AI tools is allowed. Using them to stamp out a template is what the examples warn against. Reviewers look at the channel, not one clever video.

So the variety in this repo is there to stop the obvious failure (five identical cuts with the nouns swapped). It does not make a video "compliant." The review queue is the control that matters: watch the Short, reject the ones that are thin or repetitive, and only then upload. Five a day is the default because that review is possible. Thirty a day is still a config flag, and it is a worse bet against this policy.

The upload path also sets YouTube's synthetic-media flag, and the description says the voice is text-to-speech. The goal is a natural read, not a hidden one.

## Sources

- YouTube Help, "Understand your content performance for YouTube's recommendation system" (hooks in the opening seconds, vary the storytelling, retention). <https://support.google.com/youtube/answer/16559650>
- YouTube Help, "Search & discovery tips" for Shorts (choice, average view duration, percent viewed, satisfaction; no required cadence). <https://support.google.com/youtube/answer/11914225>
- YouTube Blog, "YouTube Shorts deep dive" with Todd Sherman and Jenny Hoyos, January 28, 2025 (about one second to hook, a short arc, one bit per Short). <https://blog.youtube/creator-and-artist-stories/youtube-shorts-deep-dive/>
- YouTube Blog, "Your guide to getting started with YouTube Shorts" (9:16, first few seconds, three-minute cap). <https://blog.youtube/creator-and-artist-stories/your-guide-to-getting-started-with-youtube-shorts/>
- YouTube Help, "Get started creating YouTube Shorts". <https://support.google.com/youtube/answer/10059070>
- YouTube Help, "Video Clips & Shorts in YouTube Studio" (burned-in captions and restyling). <https://support.google.com/youtube/answer/15824265>
- Google Ads Help, "YouTube Shorts ads: Asset specs and best practices" (vertical 9:16, under 60 seconds in the feed, sound and text overlays). This is an ads spec for the same player, not an organic ranking rule. <https://support.google.com/google-ads/answer/16041697>
- YouTube Help, "YouTube channel monetization policies", inauthentic content, updated July 15, 2025. <https://support.google.com/youtube/answer/1311392>
- YouTube Help Community, "Response to creator questions about YPP policies (July 2025)". <https://support.google.com/youtube/thread/356734251>
- Pexels API documentation (free video search, portrait filter, attribution). <https://www.pexels.com/api/documentation/>
- Pixabay API documentation (video search). <https://pixabay.com/api/docs/>
