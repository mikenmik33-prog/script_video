"""
Бібліотека стандартизованих промтів руху камери для image-to-video
("Оживити сцену", fal.ai) - надана користувачем.

Gemini (ai.py, _build_script_prompt) для КОЖНОЇ сцени сам обирає один
ключ із CAMERA_MOVEMENTS, що найкраще підходить під дію саме цієї
сцени (а не по черзі підряд) - обраний текстовий опис одразу
підставляється як промт руху в редаговане поле на сторінці результату.
"""

CAMERA_MOVEMENTS = {
    "static_shot": (
        "Camera: locked-off static shot. Movement: hold one fixed camera "
        "position for the full clip. Speed: still and steady. Framing: keep "
        "the same angle, height, lens distance and composition. End: finish "
        "with the same framing and camera position."
    ),
    "pan_right": (
        "Camera: pan right. Movement: rotate the camera horizontally from "
        "left to right from one fixed point. Speed: smooth constant "
        "rotation. Framing: keep the horizon level while new space enters "
        "from the right side of the frame. End: settle on a clear final "
        "composition."
    ),
    "whip_pan_left": (
        "Camera: whip pan left. Movement: rotate rapidly from the starting "
        "direction toward a new target on the left. Speed: fast snap with "
        "brief motion blur during the rotation. Framing: begin on one "
        "readable composition and land on a second readable target. End: "
        "settle into a sharp final frame."
    ),
    "tilt_up": (
        "Camera: tilt up. Movement: rotate the camera upward from one "
        "fixed point. Speed: smooth constant tilt. Framing: keep the "
        "vertical subject or architecture centered as the frame travels "
        "upward. End: land on the upper target."
    ),
    "tilt_down": (
        "Camera: tilt down. Movement: rotate the camera downward from one "
        "fixed point. Speed: smooth constant tilt. Framing: keep the "
        "vertical subject or architecture centered as the frame travels "
        "downward. End: land on the lower target."
    ),
    "slow_zoom_in": (
        "Camera: slow zoom in. Movement: slowly increase lens focal length "
        "toward a tighter frame. Speed: gradual and even. Framing: keep "
        "the main visual target readable as it becomes larger in frame. "
        "End: finish on a stable tighter composition."
    ),
    "slow_zoom_out": (
        "Camera: slow zoom out. Movement: slowly decrease lens focal "
        "length toward a wider frame. Speed: gradual and even. Framing: "
        "keep the main visual target readable as more surrounding space "
        "appears. End: finish on a stable wider composition."
    ),
    "fast_zoom_in": (
        "Camera: fast zoom in. Movement: quickly increase lens focal "
        "length toward the main visual target. Speed: quick decisive "
        "zoom. Framing: keep the target centered or clearly readable "
        "during the scale change. End: finish on a stable tighter "
        "composition."
    ),
    "fast_zoom_out": (
        "Camera: fast zoom out. Movement: quickly decrease lens focal "
        "length away from the main visual target. Speed: quick decisive "
        "zoom. Framing: keep the target readable as the surrounding space "
        "appears. End: finish on a stable wider composition."
    ),
    "crash_zoom_in": (
        "Camera: crash zoom in. Movement: snap the lens rapidly toward "
        "the main visual target. Speed: very fast and punchy. Framing: "
        "keep the target readable through the sudden scale change. End: "
        "land on a bold tighter composition."
    ),
    "crash_zoom_out": (
        "Camera: crash zoom out. Movement: snap the lens rapidly away "
        "from the main visual target. Speed: very fast and punchy. "
        "Framing: keep the target readable as the surrounding space "
        "appears. End: land on a bold wider composition."
    ),
    "dolly_in": (
        "Camera: dolly in. Movement: move the camera physically forward "
        "in a straight line toward the main subject. Speed: smooth "
        "controlled push. Framing: keep camera height, lens direction and "
        "subject position consistent while distance closes. End: finish "
        "in a tighter composition."
    ),
    "dolly_out": (
        "Camera: dolly out. Movement: move the camera physically backward "
        "in a straight line away from the main subject. Speed: smooth "
        "controlled retreat. Framing: keep lens direction and camera "
        "height consistent while more environment enters frame. End: "
        "finish in a wider composition."
    ),
    "truck_right": (
        "Camera: truck right. Movement: move the camera physically to the "
        "right on a straight horizontal path. Speed: smooth constant "
        "lateral travel. Framing: keep the lens facing the same direction "
        "while the scene slides across frame. End: finish on a clean "
        "lateral composition."
    ),
    "truck_left": (
        "Camera: truck left. Movement: move the camera physically to the "
        "left on a straight horizontal path. Speed: smooth constant "
        "lateral travel. Framing: keep the lens facing the same direction "
        "while the scene slides across frame. End: finish on a clean "
        "lateral composition."
    ),
    "pedestal_up": (
        "Camera: pedestal up. Movement: move the entire camera vertically "
        "upward in a straight line. Speed: smooth constant lift. Framing: "
        "keep the lens level and pointed in the same direction during the "
        "vertical move. End: finish with the higher framing clearly "
        "readable."
    ),
    "pedestal_down": (
        "Camera: pedestal down. Movement: move the entire camera "
        "vertically downward in a straight line. Speed: smooth constant "
        "descent. Framing: keep the lens level and pointed in the same "
        "direction during the vertical move. End: finish with the lower "
        "framing clearly readable."
    ),
    "slider_right": (
        "Camera: slider right. Movement: slide the camera a small "
        "distance to the right. Speed: slow controlled constant motion. "
        "Framing: keep foreground, subject and background layers readable "
        "as parallax shifts. End: finish on a refined composition with "
        "the new right-side angle visible."
    ),
    "slider_left": (
        "Camera: slider left. Movement: slide the camera a small distance "
        "to the left. Speed: slow controlled constant motion. Framing: "
        "keep foreground, subject and background layers readable as "
        "parallax shifts. End: finish on a refined composition with the "
        "new left-side angle visible."
    ),
    "push_past": (
        "Camera: push past. Movement: move forward past a visible "
        "foreground object, edge or opening. Speed: smooth forward glide. "
        "Framing: let the foreground pass close to the lens while the "
        "space beyond becomes clearer. End: arrive inside or beyond the "
        "foreground layer."
    ),
    "arc_right": (
        "Camera: arc right. Movement: move on a shallow curved path "
        "around the main subject toward the right side. Speed: smooth "
        "measured curve. Framing: keep distance, height and subject "
        "readability consistent while the angle changes. End: finish "
        "from a new right-side angle."
    ),
    "arc_left": (
        "Camera: arc left. Movement: move on a shallow curved path around "
        "the main subject toward the left side. Speed: smooth measured "
        "curve. Framing: keep distance, height and subject readability "
        "consistent while the angle changes. End: finish from a new "
        "left-side angle."
    ),
    "orbit_clockwise": (
        "Camera: clockwise orbit. Movement: circle clockwise around the "
        "main subject at a consistent radius. Speed: smooth controlled "
        "orbit. Framing: keep the subject centered while the background "
        "rotates around them. End: complete the intended arc or full "
        "circle with stable framing."
    ),
    "orbit_counterclockwise": (
        "Camera: counterclockwise orbit. Movement: circle "
        "counterclockwise around the main subject at a consistent "
        "radius. Speed: smooth controlled orbit. Framing: keep the "
        "subject centered while the background rotates around them. End: "
        "complete the intended arc or full circle with stable framing."
    ),
    "tracking_shot": (
        "Camera: tracking shot. Movement: move through the scene with the "
        "main subject. Speed: match the subject's pace. Framing: keep the "
        "subject consistently readable while the environment moves around "
        "them. End: maintain a clear moving composition."
    ),
    "follow_shot": (
        "Camera: follow shot from behind. Movement: move behind the "
        "subject along their route at shoulder height. Speed: match the "
        "subject's pace. Framing: keep the back, shoulder or head as the "
        "foreground guide while the route ahead stays readable. End: "
        "continue following with the subject leading the frame."
    ),
    "reverse_tracking": (
        "Camera: reverse tracking shot. Movement: move backward in front "
        "of the walking subject. Speed: match the subject's forward pace. "
        "Framing: keep front-facing face and body framing stable as the "
        "background moves behind them. End: hold a clear front-facing "
        "moving composition."
    ),
    "side_tracking": (
        "Camera: side tracking shot. Movement: move parallel beside the "
        "subject along their direction of travel. Speed: match the "
        "subject's motion. Framing: keep the subject in side profile or "
        "three-quarter profile at a stable distance. End: continue the "
        "parallel movement with clear horizontal motion."
    ),
    "low_tracking": (
        "Camera: low tracking shot. Movement: move at ground or "
        "below-waist height alongside the subject's movement path. Speed: "
        "match the subject, footsteps or wheels. Framing: keep the low "
        "detail readable while the ground plane moves through frame. End: "
        "finish with the low perspective clearly maintained."
    ),
    "vehicle_tracking": (
        "Camera: vehicle tracking shot. Movement: move with the vehicle "
        "along its route. Speed: match the vehicle's pace. Framing: keep "
        "the vehicle stable in frame while the road or environment moves "
        "past. End: maintain a clear moving vehicle composition."
    ),
    "chase_shot": (
        "Camera: chase shot. Movement: follow a moving subject quickly "
        "along the action route. Speed: fast, reactive and physically "
        "close. Framing: keep the subject visible while allowing "
        "energetic reframing. End: stay connected to the subject in "
        "motion."
    ),
    "handheld_shot": (
        "Camera: handheld shot. Movement: hold the camera at human "
        "operator height with natural body movement. Speed: responsive "
        "and organic. Framing: keep the subject readable while the frame "
        "has subtle sway and micro-adjustments. End: finish with a "
        "natural handheld composition."
    ),
    "body_mounted": (
        "Camera: body-mounted Snorricam. Movement: keep the camera fixed "
        "relative to the subject's torso or face while the subject moves. "
        "Speed: match the subject's body motion. Framing: keep the "
        "subject close, centered and facing the camera as the background "
        "moves around them. End: finish with the subject still locked in "
        "frame."
    ),
    "crane_up": (
        "Camera: crane up. Movement: travel smoothly upward through open "
        "space. Speed: slow controlled vertical lift. Framing: keep the "
        "subject or location readable as the camera rises. End: finish "
        "with the higher scale clearly visible."
    ),
    "crane_down": (
        "Camera: crane down. Movement: travel smoothly downward through "
        "open space. Speed: slow controlled vertical descent. Framing: "
        "keep the subject or location readable as the camera descends. "
        "End: finish with the lower subject or destination clearly "
        "visible."
    ),
    "drone_push_in": (
        "Camera: drone push in. Movement: fly smoothly forward through "
        "open space toward the subject or destination. Speed: controlled "
        "aerial glide. Framing: keep the route and destination readable "
        "as the camera approaches. End: arrive at a closer aerial "
        "composition."
    ),
    "drone_pull_back": (
        "Camera: drone pull back. Movement: fly smoothly backward away "
        "from the subject or destination. Speed: controlled aerial "
        "retreat. Framing: keep the subject readable as more landscape "
        "appears. End: finish on a wider aerial composition."
    ),
    "helicopter_shot": (
        "Camera: helicopter-style aerial shot. Movement: move from high "
        "altitude along a broad gradual flight path. Speed: steady "
        "controlled aerial motion. Framing: keep the landscape or distant "
        "moving subject readable at wide scale. End: finish on a stable "
        "high-altitude composition."
    ),
    "first_person_view": (
        "Camera: first-person view. Movement: move forward at human eye "
        "height from the character's perspective. Speed: natural walking "
        "or reaching pace. Framing: use visible hands, arms or body edges "
        "as the viewer's physical reference. End: arrive at the next "
        "point of action from the same point of view."
    ),
    "tilt_shift": (
        "Camera: tilt-shift miniature view. Movement: hold or glide from "
        "a high angled view over the scene. Speed: small precise "
        "movement. Framing: keep a narrow band of sharp focus across the "
        "key subject area with soft blur above and below. End: finish "
        "with the miniature-scale view intact."
    ),
    "infinite_zoom": (
        "Camera: infinite zoom. Movement: zoom continuously inward toward "
        "the exact center target. Speed: smooth accelerating zoom. "
        "Framing: keep the circular target centered as it expands. End: "
        "finish when the next visual world fills the frame."
    ),
    "earth_zoom_out": (
        "Camera: earth zoom out. Movement: pull upward from the starting "
        "point through street, city, landscape and planet scale. Speed: "
        "rapid expanding zoom out. Framing: keep the original location "
        "centered as scale grows. End: finish on a planet-scale view with "
        "the starting point still implied at center."
    ),
    "time_lapse": (
        "Camera: locked-camera time-lapse. Movement: hold one fixed "
        "camera position while time moves rapidly forward. Speed: fast "
        "time compression with a stable camera. Framing: keep the same "
        "composition and horizon as motion passes through the frame. End: "
        "finish from the same camera angle with visible passage of time."
    ),
    "pass_through": (
        "Camera: pass-through movement. Movement: move forward toward a "
        "visible object, surface or barrier and continue into the space "
        "beyond. Speed: smooth centered glide. Framing: keep the opening "
        "or surface centered as the transition point. End: arrive inside "
        "the revealed space beyond."
    ),
}

DEFAULT_CAMERA_MOVEMENT = "static_shot"
