# Robot vision, bot side (0.2.44)

Home's contract is `docs/design/robot-vision-2026-10-21.md` in the home repo. Home describes a posted picture once and keeps one sentence
for 90 seconds; the description is never returned to the bot, so a question about sight is answered by the hub's own turn, not here.

- Module: `bodies/stackchan/vision_post.py` (`VisionPoster`, `light_bucket`, `mean_luma`). It never raises and logs counts and codes only.
- Scene posts: `StackChanBehavior.post_scene`, from the presence loop. Idle only (no turn, not at night, watching not off). One post at
  most every 10 s when the face count or the brightness bucket changed, once a minute otherwise. A 403 `vision_off` stops everything until
  `robot.vision` changes; `vision_on_demand` stops scene posts only; 429 waits 10 s; 503 waits 60 s.
- Asks: `StackChanBehavior.vision_ask`, called from the turn when the words are a sight question (`SightAnswers.kind`). It posts the newest
  picture (at most 20 s old, because the unit sends no frames during a turn) with `purpose=ask`, waits up to 5 s for Home, and on success
  lets the normal turn answer. On failure the host answers from its own knowledge (a recent face, the brightness bucket).
- Memory: the newest look (jpeg, time, face count, brightness) lives in `StackChanVisionBridge._latest_look` until the next look replaces
  it or a post takes it. It is never written anywhere.
- Light bucket: mean gray of the frame, below 35 dark, below 85 dim, else bright (the unit's light sensor reads 1 to 2 percent of the true
  lux, so it is only the fallback).
