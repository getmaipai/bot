# Robot vision, bot side (0.2.44)

Home's contract is `docs/design/robot-vision-2026-10-21.md` in the home repo. Home describes a posted picture once and keeps one sentence
for 90 seconds; the description is never returned to the bot, so a question about sight is answered by the hub's own turn, not here.

- Module: `bodies/stackchan/vision_post.py` (`VisionPoster`, `light_bucket`, `mean_luma`). It never raises and logs counts and codes only.
- Scene posts: `StackChanBehavior.post_scene`, from the presence loop. Idle only (no turn, not at night, watching not off). Each post is a
  model call on Home, so the default is slow: every 60 s if a tiny gray thumbnail differs from the last posted one (mean change of 6 or
  more), at once when the brightness bucket changes (never inside Home's 10 s floor), and every 5 minutes even if nothing changed. A 403
  `vision_off` stops everything until `robot.vision` changes; `vision_on_demand` stops scene posts only; after a 429 or 503 the
  intervals double (up to ten times) and reset on a success.
- Asks: `StackChanBehavior.vision_ask`, called from the turn for "see me" and "looking at" questions (`SightAnswers.kind`); light questions are answered by the host from the frame brightness and never call the model. It posts the newest
  picture (at most 90 s old, `ASK_MAX_AGE_S`: the unit sends no frames during a turn, so back-to-back turns only have the picture from
  before the first one; 20 s found none, 2026-11-12) with `purpose=ask`, waits up to 5 s for Home, and on success lets the normal turn
  answer. The log says the picture's age, face count and light bucket. On failure the host answers from its own knowledge (a recent
  face, the brightness bucket) and says "I couldn't get a good look just now. Ask me again in a moment." (`sight.NO_LOOK`).
- On since 2026-11-12 (owner): the poster is created whenever the robot is paired; the `robot.vision` device setting is the only switch
  (the 2026-10-22 hold, `PICTURE_POSTS_ENABLED`, is gone).
- Memory: the newest look (jpeg, time, face count, brightness) lives in `StackChanVisionBridge._latest_look` until the next look replaces
  it or a post takes it. It is never written anywhere.
- Light bucket: the 90th percentile of gray over a strided sample of the frame (`scene_luma`, the brightness of the picture's lit part):
  below 50 dark, below 110 dim, else bright. Measured on the unit 2026-11-12: the owner in a dark hoodie filling the frame in a lit room
  gave a mean of 52 to 69 (which the old mean rule called dim) and a 90th percentile of 151 to 171 (bright); a covered lens or an unlit
  room pulls the percentile down with everything else. A picture with no detail (mean step between neighbouring sample pixels under
  3.5: a covered lens is a flat grey fog under auto exposure, mean 120, measured the same day; an arm against the lens a flat dark one)
  has no light level at all: auto exposure makes its brightness meaningless. The unit's light sensor (about 5 to 16 lux in that lit
  room, 1 to 2 percent of the true value) decides then, and a reading under 1.5 means dark whatever the camera's gain shows. The
  per-minute camera line in the log ends with the light level and bucket, or "the picture has no detail".
- Movement, the second presence signal (owner finding 2026-11-12: at the desk the camera sees an arm or a shoulder and no face, so faces
  alone said "nobody"): `presence_watch.motion_fraction` compares the tiny gray thumbnails of two consecutive looks cell by cell after
  taking out the picture-wide brightness step (the median change, so auto exposure is not movement); a twentieth of the picture changed
  by more than 12 of 255 counts as movement (`StackChanVisionBridge.motion_age`). "Can you see me?" with no face but movement in the last
  30 s answers "something is moving right in front of me, is that you?" (`sight.MOVING`); the minute line counts the looks with
  movement and the largest share. Movement never moves the head and is never sent to Home.
- Posting: a post that Home does not answer within 12 s (its Look can take 8 s under load) counts as unreachable and waits 10 s like a
  refusal before the next frame, instead of posting again at once.
