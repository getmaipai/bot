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
  has no light level at all: auto exposure makes its brightness meaningless. The unit's light sensor decides then. It reads 1 to 2
  percent of the true lux and sits behind the screen glass, so the screen's own glow keeps it at a floor: 6.4 (ch0=3) with the room
  lights off and with the lens covered, 9.3 to 16.4 in the lit office (measured 2026-11-12; once the rest routine dimmed the screen
  the lights-off reading fell to 0.0 and the frames went solid black, while the first lights-off frames at full screen brightness were
  the same grey fog as covered ones). So a picture with no detail plus a sensor under 8 is a dark room; with no detail and a higher sensor reading the
  robot cannot tell (something is over the lens in a lit room) and says so; a sensor under 1.5 is dark whatever the camera shows. The
  per-minute camera line in the log ends with the light level and bucket, or "the picture has no detail, sensor N (dark ...)".
- Movement, the second presence signal (owner finding 2026-11-12: at the desk the camera sees an arm or a shoulder and no face, so faces
  alone said "nobody"): `presence_watch.motion_fraction` compares the tiny gray thumbnails of two consecutive looks cell by cell after
  taking out the picture-wide brightness step (the median change, so auto exposure is not movement); 8 percent of the picture changed
  by more than 20 of 255 counts as movement (the empty lit office measured at most 1 percent, the owner still at his desk 7 to 31) (`StackChanVisionBridge.motion_age`). "Can you see me?" with no face but movement in the last
  30 s answers "something is moving right in front of me, is that you?" (`sight.MOVING`); the minute line counts the looks with
  movement and the largest share. Movement never moves the head and is never sent to Home.
- Posting: a post that Home does not answer within 12 s (its Look can take 8 s under load) counts as unreachable and waits 10 s like a
  refusal before the next frame, instead of posting again at once.
- Looking around (`head_search.py`, owner requests 2026-11-12, "natural, not annoying"; the 2026-10-20 "head still while charging or at
  idle level still" rule no longer holds these back, owner-approved 2026-11-12: the head gate treats them as responses, idle wandering
  and the settle stay ambient). Quiet, every move through the head gate, never mid-reply, asleep or at night, stopped the instant a face
  is seen (following takes over, no return move) or a touch arrives, otherwise a slow return to the resting pose. (a) For a face, when no
  face was seen for 5 s and the picture suggests a person: it differs from the learned empty room (`presence_watch.SceneBaseline`, blended
  in slowly while nobody seems there; measured 2026-11-12: the owner at the desk differs in 61 to 77 percent of the picture, the empty
  office in 1 to 10; the rule is 25 percent of cells by more than 30 of 255), or it moved in the last 5 s, or it is flat in a lit room.
  Poses: a glance 12 degrees up, then 22 up, then 25 left and 25 right, one eased move at the servo's slowest setting (speed 100) and a
  pause at each pose (1.6 s a pose, about six seconds in all). A look that found nobody waits 1, then 3, then 10 minutes before the next;
  a face resets the wait. Proven on the unit 2026-11-12 16:53 with no wave: "differs from the empty room in 34%", glance 12, look 22,
  "found a face at x 0.69, y 0.13" after 2.5 s. (b) Someone speaking (listen start): the head turns toward a face seen in the last 60 s,
  else glances 15 degrees up briskly (speed 130) and looks again right after the reply; the camera is paused while the unit listens and
  speaks (firmware 069), so the face is found after the reply, not during it. (c) Before concluding dark: left 25, right 25, up 15; detail
  seen in any of those means something is in front of the camera and the light is "cannot tell" for 5 minutes, none confirms dark for
  10 minutes; until the look is done a flat picture is not yet "dark" (`StackChanBehavior.light_now`); while resting or at night the sensor
  alone decides. The log says "StackChan looking around (reason): yaw N, pitch M up from level" per pose and why each look started and
  stopped. Every value is at the top of `head_search.py` and `presence_watch.py`.
- Phantom pets ("it keeps smiling", 2026-11-12): firmware patch 080 makes a weak run (reading 1) need 32 samples and marks weak
  presses `strong=0`; `head_touch_filter.py` already drops a lone weak event unless it repeats within 4.5 s.
- Person, then face, then follow (2026-11-12, owner design): the Look detector (YOLOX-nano, the shared robot asset) runs beside YuNet on
  the same frames (`vision/look_fast.py`, `vision_bridge._fast_pass`), and `bodies/stackchan/person_tracker.py` turns its person box
  into the head moves: aim, face search above a still body, follow. With the model loaded it replaces the ambient look around above;
  the design, the constants and the frame budget are in `stackchan-person-then-face-2026-11-12.md`.
