# StackChan spoken head movement (2026-10-21)

Owner report: "Can you look down?" reached the hub, whose model answered "I can't look down, I'm here on this device." There was
no matcher for movement, only for volume. `bodies/stackchan/head_commands.py` is the matcher and the runner; `turn.py` calls it
right after the volume check, before anything goes to the hub.

## Phrases

| Said | Does |
|---|---|
| look left / right / up / down, turn left / right, "turn your head to the right" | one move; "a little" is about 40 percent of the move, "all the way" about 200 percent |
| look straight, straight ahead, look forward, look at me, face forward, center | back to the rest pose |
| look around | slow sweep left, right, centre |
| nod, say yes | nod twice |
| shake your head, say no | shake twice |
| stay (there) | cancels the return to centre |
| turn around, spin, rotate, dance, wave, walk, jump, look over there | "I can look left, right, up or down." Nothing moves, the hub is not asked. |

Left and right are the robot's own left and right (negative yaw is the robot's left). The match searches the sentence, strips the
same fillers as volume ("please", "can you", "hey"), and only applies to short sentences: a question ("how do I turn right on
red"), a long sentence, or a request to describe what it sees ("look down and tell me what you see") goes to the hub.

## How it moves

The runner sends yaw and pitch through `robot.head.set` (the lease, the e-stop latch and the profile limits all apply) at speed 120
(the profile range is 100 to 150). Centre is yaw 0, pitch 45. A "look" is 45 degrees of yaw or 25 degrees of pitch from centre,
so the largest move ("all the way") is 90 degrees of yaw. After 5 seconds the head returns to centre unless the person says "stay"
or gives another command; the post-turn settle is held off for that time so it does not undo the pose at once.

These are explicit requests, so the ambient head gate does not apply. They have their own limit of 30 commands a minute. If the unit
is charging, the emergency stop is latched, or the move fails, the answer is "I can't move right now." and the hub is not asked.
The firmware's own limit of 20 `set_head_angles` calls a minute (patch 038) still applies below this.
