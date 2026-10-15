"""TOQIX knowledge base — real creation expertise, shipped as local data.

The TOQIX Agent's brain is a deterministic state machine (agent.py).
This module is its *knowledge*: curated, hand-authored entries about
styles, camera language, lighting, prompt craft, voices and how TOQIX
itself works — plus idea seeds for every curriculum domain and genre
story templates for the series planner.

Everything here is plain data + a tiny keyword scorer. No LLM calls, no
network, no external APIs — same question, same answer, every time.

Public surface used by agent.py:
    ENTRIES                       list of {id, keywords, answer}
    lookup(text)                  best entry dict or None
    match_ratio(text, entry)      how strongly `text` is *just* this topic
    IDEA_SEEDS                    bucket id -> {label, match, ideas[3]}
    find_idea_bucket(text)        best seed bucket or None
    random_idea_bucket()          a random seed bucket
    STORY_TEMPLATES               genre -> {label, match, beats[4]}
    find_template(text)           best template (adventure by default)
"""

from __future__ import annotations

import random
import re

# ---------------------------------------------------------------------------
# Q&A entries — styles, camera, lighting, know-how
# ---------------------------------------------------------------------------
ENTRIES: list[dict] = [
    # ---- style presets -------------------------------------------------
    {
        "id": "style_cinematic",
        "keywords": ["cinematic", "cinematic style", "film style",
                     "movie style", "film look", "hollywood"],
        "answer": "Cinematic is the classic film look: dramatic "
                  "composition, shallow depth of field, gentle film grain "
                  "and a teal-and-orange grade. It is the safest all-round "
                  "style — if you are not sure what to pick for a video, "
                  "pick cinematic.",
    },
    {
        "id": "style_photorealistic",
        "keywords": ["photorealistic", "photorealism", "realistic style",
                     "real looking", "photo real", "hyperrealistic"],
        "answer": "Photorealistic makes the output look like real camera "
                  "footage — natural skin, real textures, true proportions. "
                  "Use it for people, daily life and anything that must feel "
                  "believable rather than stylized.",
    },
    {
        "id": "style_anime",
        "keywords": ["anime", "manga", "ghibli", "anime style"],
        "answer": "Anime is the Japanese animation look: cel shading, "
                  "clean line art, big expressive eyes and vibrant colors. "
                  "Great for character stories, school scenes and anything "
                  "that should feel like a Studio Ghibli or TV anime frame.",
    },
    {
        "id": "style_3d_animation",
        "keywords": ["3d animation", "3d style", "pixar", "cgi",
                     "animated film", "3d animated"],
        "answer": "3D Animation is the Pixar-style look: soft, rounded "
                  "characters, rich detailed sets and warm studio lighting. "
                  "Perfect for kids' stories, mascots and friendly "
                  "characters that need to charm in every part.",
    },
    {
        "id": "style_vintage_film",
        "keywords": ["vintage", "vintage film", "retro film", "old film",
                     "70s film", "nostalgic"],
        "answer": "Vintage Film looks like 1970s footage: warm faded "
                  "colors, visible grain and a soft vignette at the edges. "
                  "Use it for memories, old-city stories and anything that "
                  "should feel nostalgic and timeless.",
    },
    {
        "id": "style_cyberpunk",
        "keywords": ["cyberpunk", "cyberpunk style", "neon cyberpunk",
                     "neon punk", "sci-fi neon"],
        "answer": "Cyberpunk is a neon-soaked future city look: glowing "
                  "signs, wet reflective streets, haze and high-contrast "
                  "night colors. Use it for sci-fi stories, rainy city "
                  "nights and anything futuristic and moody.",
    },
    {
        "id": "style_nature_doc",
        "keywords": ["nature documentary", "nature doc", "documentary",
                     "documentary style", "wildlife documentary",
                     "bbc style"],
        "answer": "Nature Documentary mimics BBC wildlife footage: "
                  "telephoto detail, true-to-life animal behaviour and "
                  "pristine wilderness light. Best for animals, mountains, "
                  "oceans and calm scenic videos.",
    },
    {
        "id": "style_noir",
        "keywords": ["noir", "film noir", "noir style", "detective style"],
        "answer": "Noir is black-and-white (or near it) with hard shadows, "
                  "blinds-and-rain light and a detective-story mood. Use "
                  "it for crime, mystery and moody night scenes — mention "
                  "'noir' in your style to get that look.",
    },
    {
        "id": "style_horror",
        "keywords": ["horror style", "horror look", "scary style",
                     "horror film"],
        "answer": "The horror look is about dread, not gore: pale "
                  "moonlight, deep shadows, empty spaces and slow "
                  "creeping camera moves. Say 'horror' in your prompt or "
                  "style and keep scenes quiet — silence is scarier than "
                  "noise.",
    },
    {
        "id": "style_comedy",
        "keywords": ["comedy style", "comedy look", "funny style",
                     "sitcom"],
        "answer": "Comedy looks bright and playful: cheerful colors, "
                  "expressive faces and slightly exaggerated timing. It "
                  "works best with a character who keeps failing in funny "
                  "ways — bright light keeps the mood light.",
    },
    {
        "id": "style_vaporwave",
        "keywords": ["vaporwave", "synthwave", "80s aesthetic",
                     "retrowave"],
        "answer": "Vaporwave is a dreamy 80s internet aesthetic: pink and "
                  "purple gradients, chrome, palm trees and old-computer "
                  "glow. Lovely for music visuals, loops and anything "
                  "that should feel like a retro dream.",
    },
    {
        "id": "style_watercolor",
        "keywords": ["watercolor", "watercolour", "painting style",
                     "painted look", "storybook"],
        "answer": "Watercolor looks like a hand-painted storybook: soft "
                  "edges, colors bleeding gently into paper-white light. "
                  "Beautiful for kids' tales, poems and calm, gentle "
                  "scenes.",
    },
    {
        "id": "style_pixel_art",
        "keywords": ["pixel art", "pixel", "8-bit", "8 bit", "retro game",
                     "16-bit"],
        "answer": "Pixel art is the retro-game look: chunky visible "
                  "pixels, limited colors and charming sprite-like "
                  "motion. Fun for game-style stories, loops and playful "
                  "shorts.",
    },
    # ---- camera language ----------------------------------------------
    {
        "id": "cam_closeup",
        "keywords": ["close-up", "close up", "closeup", "close shot"],
        "answer": "A close-up fills the frame with a face or a small "
                  "detail. It is the shot for emotion — use it at the "
                  "most important moment of a scene, when the viewer "
                  "should feel what the character feels.",
    },
    {
        "id": "cam_wide",
        "keywords": ["wide shot", "wide angle", "establishing shot",
                     "long shot", "wide view"],
        "answer": "A wide shot shows the whole place at once — the "
                  "character small inside a big world. Use it to open a "
                  "scene so viewers know where they are, or to make a "
                  "landscape feel epic.",
    },
    {
        "id": "cam_drone",
        "keywords": ["drone", "aerial", "drone shot", "aerial shot",
                     "top view", "birds eye", "bird's eye"],
        "answer": "A drone (aerial) shot flies above the scene, looking "
                  "down or sweeping forward over rooftops, rivers and "
                  "roads. It instantly makes a video feel big and "
                  "expensive — great for openings, travel and nature.",
    },
    {
        "id": "cam_dolly",
        "keywords": ["dolly", "push-in", "push in", "dolly shot",
                     "push-in shot"],
        "answer": "A dolly or push-in slowly moves the camera toward the "
                  "subject. It builds tension and importance — the classic "
                  "move for a reveal, a realization, or a scary moment "
                  "getting closer.",
    },
    {
        "id": "cam_tracking",
        "keywords": ["tracking", "tracking shot", "follow shot",
                     "steadicam", "follow cam"],
        "answer": "A tracking shot moves alongside or behind the subject "
                  "as they move — walking, running, driving. It keeps the "
                  "energy alive and puts the viewer right next to the "
                  "action.",
    },
    {
        "id": "cam_slowmo",
        "keywords": ["slow motion", "slow-motion", "slow mo", "slowmo"],
        "answer": "Slow motion stretches a split second into a whole "
                  "moment: a dive, a splash, a punch, hair in the wind. "
                  "Use it for the single most beautiful or dramatic beat "
                  "of a scene — not for everything.",
    },
    {
        "id": "cam_timelapse",
        "keywords": ["timelapse", "time-lapse", "time lapse"],
        "answer": "A timelapse squeezes hours into seconds: clouds "
                  "racing, crowds flowing, day melting into night. "
                  "Perfect for showing change, journeys and busy city "
                  "life.",
    },
    {
        "id": "cam_pov",
        "keywords": ["pov", "point of view", "first person", "pov shot"],
        "answer": "A POV shot shows the scene through the character's "
                  "own eyes — hands reaching, feet walking, the world "
                  "rushing at you. It is the most immersive shot there "
                  "is; great for rides, chases and discoveries.",
    },
    {
        "id": "cam_orbit",
        "keywords": ["orbit", "orbit shot", "circling shot", "360 shot",
                     "around shot"],
        "answer": "An orbit shot circles around the subject while they "
                  "stay centered — heroic, stylish and full of energy. "
                  "Use it for character introductions, products and "
                  "celebration moments.",
    },
    # ---- lighting & mood ----------------------------------------------
    {
        "id": "light_golden",
        "keywords": ["golden hour", "golden light", "sunset light",
                     "sunrise light"],
        "answer": "Golden hour is the warm light just after sunrise or "
                  "before sunset — long shadows, glowing skin, everything "
                  "looks beautiful. When in doubt, 'golden hour' in a "
                  "prompt makes almost any outdoor scene prettier.",
    },
    {
        "id": "light_neon",
        "keywords": ["neon light", "neon lights", "neon", "neon glow"],
        "answer": "Neon light is colored glow from signs and tubes — "
                  "pink, cyan, purple on wet streets and night faces. It "
                  "is the signature of cyberpunk and night-city scenes: "
                  "futuristic, stylish and a little lonely.",
    },
    {
        "id": "light_moonlight",
        "keywords": ["moonlight", "moonlit", "moon light"],
        "answer": "Moonlight is cool blue-silver light: quiet, romantic "
                  "or eerie depending on the scene. Use it for night "
                  "stories, secrets and anything dreamlike.",
    },
    {
        "id": "light_shadows",
        "keywords": ["dramatic shadows", "low-key", "low key",
                     "deep shadows", "chiaroscuro", "shadowy"],
        "answer": "Dramatic shadows (low-key lighting) hide half the "
                  "frame in darkness and light only what matters. It is "
                  "the language of mystery, horror and serious drama — "
                  "what you cannot see scares or intrigues the viewer.",
    },
    {
        "id": "light_soft",
        "keywords": ["soft light", "soft lighting", "diffused light",
                     "gentle light"],
        "answer": "Soft light is gentle and flattering — like window "
                  "light on a cloudy day, with no harsh shadows. Use it "
                  "for people, food, family scenes and anything warm and "
                  "kind.",
    },
    # ---- creation know-how --------------------------------------------
    {
        "id": "how_prompt",
        "keywords": ["good prompt", "write a prompt", "prompt formula",
                     "better prompt", "prompt tips", "how to write",
                     "prompt kaise", "prompt likhna", "strong prompt"],
        "answer": "The formula for a strong prompt is: SUBJECT + ACTION "
                  "+ PLACE + LIGHT + CAMERA. Example: 'a fisherman "
                  "(subject) mending his net (action) on a misty pier "
                  "(place) at golden hour (light), slow push-in "
                  "(camera)'. Say \"improve: \" before any rough idea and "
                  "I will rebuild it with this formula.",
    },
    {
        "id": "how_aspect",
        "keywords": ["aspect ratio", "ratio", "16:9", "9:16", "1:1",
                     "vertical video", "which ratio", "kis ratio"],
        "answer": "Aspect ratio is the shape of the frame. 16:9 is wide "
                  "— for YouTube, TV and films. 9:16 is tall — for "
                  "phones, Reels, TikTok and Shorts. 1:1 is square — for "
                  "social posts. Pick the ratio for where the video will "
                  "be watched, and a series keeps one ratio throughout.",
    },
    {
        "id": "how_duration",
        "keywords": ["duration", "how long", "video length",
                     "how many seconds", "kitne seconds", "length of"],
        "answer": "Each part here is a short clip of about 2–5 seconds, "
                  "so think in moments, not whole scenes: one action, "
                  "one feeling per part. A series of many short parts "
                  "tells the full story — that is exactly what I am "
                  "built for.",
    },
    {
        "id": "how_consistency",
        "keywords": ["consistent", "consistency", "same character",
                     "same face", "ek jaisa", "consistency kaise"],
        "answer": "A series stays consistent with three locks: the exact "
                  "same character description (the anchor), the same "
                  "style, and the same seed in every part. Change any one "
                  "of them and the character drifts — so I lock all "
                  "three when your series starts and reuse them "
                  "automatically.",
    },
    {
        "id": "how_seed",
        "keywords": ["seed", "what is seed", "seed kia", "seed kya"],
        "answer": "A seed is the starting number a generator uses to "
                  "make its choices. Same seed + same description = a "
                  "very similar result, which is why your series keeps "
                  "one fixed seed — it helps your character look like "
                  "themselves in every part.",
    },
    {
        "id": "how_voices",
        "keywords": ["voice", "voices", "voice characters", "which voice",
                     "awaaz", "konsi awaaz", "voice actor"],
        "answer": "TOQIX has six voices. Ava — warm female, friendly "
                  "narration and stories. Emma — British female, classy "
                  "explainers. Michael — deep male, trailers and "
                  "documentaries. George — British male, serious "
                  "storytelling. Sky — young female, energetic social "
                  "clips. Adam — casual male, vlogs and everyday talk. "
                  "An audio series keeps one voice in every part.",
    },
    {
        "id": "how_agent",
        "keywords": ["how do you work", "agent", "how does the agent",
                     "series work", "agent kaise", "how series"],
        "answer": "I am the TOQIX Agent: I run whole SERIES with one "
                  "consistent character. You describe the character once, "
                  "pick a style and a kind (video, image or audio), then "
                  "send scenes — 'Part 1: ...', 'Part 2: ...' — and I "
                  "queue each part with the same character, style and "
                  "seed locked in.",
    },
    {
        "id": "how_studio",
        "keywords": ["studio", "studio mode", "one-off", "single video",
                     "normal mode"],
        "answer": "The Studio is for one-off creations: one prompt, one "
                  "video, image or audio clip — no character to "
                  "remember. Use me (the Agent) instead when you want a "
                  "series where the same character returns in every "
                  "part.",
    },
    {
        "id": "how_capabilities",
        "keywords": ["what can you do", "your features", "capabilities",
                     "help", "what do you do", "kya kar sakte",
                     "tum kya kar", "features"],
        "answer": "I can: run a consistent series (describe a character "
                  "once, then send scenes); answer creation questions "
                  "like 'what is a drone shot?'; give you ideas ('give "
                  "me a horror idea'); improve rough prompts ('improve: "
                  "a cat walking'); and plan a whole series ('plan a "
                  "series about a lost robot'). Try any of them!",
    },
    {
        "id": "how_it_works",
        "keywords": ["how it works", "how are videos made", "kaise banta",
                     "generation", "how does generation work",
                     "where is my video"],
        "answer": "When you send a scene, I turn it into a polished "
                  "director's prompt and queue the job. TOQIX's own GPU "
                  "system then generates the clip and it appears in your "
                  "Creations feed — watch the percentage on the card "
                  "while it renders.",
    },
    # ---- AI video craft (2026-10-15 expansion) -------------------------
    {
        "id": "craft_action_verbs",
        "keywords": ["action verbs", "strong verbs", "one action",
                     "verbs in prompt", "clear action"],
        "answer": "Give your subject ONE clear action with a strong "
                  "verb: 'sprints', 'pours', 'unfolds', 'leaps' beat "
                  "'moves' or 'goes'. One action per clip keeps the "
                  "motion clean — a second action belongs in the "
                  "next part.",
    },
    {
        "id": "craft_camera_angles",
        "keywords": ["camera angle", "angles", "low angle",
                     "high angle", "over the shoulder",
                     "over-the-shoulder", "eye level"],
        "answer": "Camera angle is where the viewer stands. A low "
                  "angle looks up and makes a subject powerful or "
                  "heroic; a high angle looks down and makes them "
                  "small or vulnerable; over-the-shoulder puts you "
                  "behind a character, sharing what they see; eye "
                  "level is neutral and honest.",
    },
    {
        "id": "craft_depth_field",
        "keywords": ["depth of field", "shallow focus", "bokeh",
                     "blurred background", "focus pull"],
        "answer": "Depth of field is how much of the frame is sharp. "
                  "A shallow depth of field keeps the subject crisp "
                  "and melts the background into soft blur (bokeh) — "
                  "the portrait and product look. Deep focus keeps "
                  "everything sharp, better for landscapes and "
                  "action.",
    },
    {
        "id": "craft_frame_rate",
        "keywords": ["frame rate", "fps", "frames per second",
                     "24 fps", "smoothness"],
        "answer": "Frame rate is how many still images play each "
                  "second. Cinema uses 24 fps for its classic motion "
                  "feel; more frames look smoother and more 'video'. "
                  "TOQIX clips are delivered at 16 frames per second, "
                  "smoothed with frame interpolation so motion reads "
                  "cleanly without huge files.",
    },
    {
        "id": "craft_drift",
        "keywords": ["character changes", "face changes",
                     "character drift", "character different",
                     "why does the character change",
                     "character badal jata", "chehra badal"],
        "answer": "Characters drift because every clip is generated "
                  "fresh — the model re-imagines the face each time "
                  "unless it is pinned down. The fix is an anchor: "
                  "the exact same character description, style and "
                  "seed in every part. That is what a TOQIX series "
                  "locks in for you automatically.",
    },
    {
        "id": "craft_negative",
        "keywords": ["negative prompt", "avoid in prompt",
                     "exclude", "what not to show",
                     "dont want in video"],
        "answer": "Telling the model what to leave out works best "
                  "when you name it plainly inside the prompt: 'an "
                  "empty street, no crowd, no text on screen'. Short, "
                  "concrete exclusions beat long lists — and one "
                  "clear positive description always beats five "
                  "negatives.",
    },
    {
        "id": "craft_lighting_terms",
        "keywords": ["rim light", "backlight", "backlit",
                     "three point lighting", "three-point lighting",
                     "lighting terms", "key light"],
        "answer": "Three terms unlock most lighting talk. The key "
                  "light is the main source shaping the face. A rim "
                  "light glows from behind and outlines the subject — "
                  "the heroic edge. Backlight puts the source behind "
                  "the subject entirely, giving silhouettes and "
                  "glowing haze.",
    },
    {
        "id": "craft_color_grade",
        "keywords": ["color grade", "colour grade", "color palette",
                     "colour palette", "teal and orange",
                     "color grading"],
        "answer": "A color grade is the palette poured over the whole "
                  "image: teal-and-orange is the blockbuster recipe "
                  "(cool shadows, warm skin), pastels feel gentle and "
                  "dreamy, desaturated grays feel serious. Name a "
                  "palette in your prompt and the whole scene obeys "
                  "it.",
    },
    {
        "id": "craft_composition",
        "keywords": ["rule of thirds", "composition", "framing",
                     "frame a shot", "shot composition"],
        "answer": "The rule of thirds: imagine the frame split into a "
                  "3x3 grid and place your subject on a line or "
                  "crossing, not dead center. Off-center subjects "
                  "feel alive and cinematic; center framing is for "
                  "symmetry, confrontation and comedy deadpan.",
    },
    {
        "id": "craft_movement",
        "keywords": ["frozen video", "static video", "no movement",
                     "movement in prompt", "describe motion",
                     "video ruk", "hilti nahi"],
        "answer": "If a clip looks frozen, the prompt probably "
                  "described a photograph, not a moment. Add motion "
                  "in layers: the subject acts ('turns and waves'), "
                  "the world moves ('rain falls, flags flutter'), "
                  "and the camera travels ('slow push-in'). One "
                  "moving layer is enough — three make it sing.",
    },
    {
        "id": "craft_text_video",
        "keywords": ["text in video", "words in video",
                     "gibberish text", "writing in video",
                     "sign in video", "text on screen"],
        "answer": "AI video is unreliable at written words — signs "
                  "and captions often come out as gibberish "
                  "lettering. If text truly matters, keep it to a "
                  "few big, exact words in quotes; the safer craft "
                  "is to add titles and captions yourself afterwards "
                  "in an editor, where they stay perfect.",
    },
    {
        "id": "craft_one_beat",
        "keywords": ["too much happening", "one clip one beat",
                     "multiple scenes one clip", "busy prompt",
                     "too many actions", "too many things",
                     "crowded"],
        "answer": "One short clip can hold one or two beats — a "
                  "single action with a small reaction. Stuff three "
                  "scenes into one prompt and the model drops most "
                  "of them. Split extra beats into the next part; a "
                  "series of focused clips always beats one crowded "
                  "clip.",
    },
    {
        "id": "craft_style_mix",
        "keywords": ["mix styles", "two styles", "combining styles",
                     "mixed style", "style conflict"],
        "answer": "Do not mix contradictory styles in one prompt — "
                  "'anime photorealistic noir' fights itself and "
                  "the output turns muddy. Pick one style per "
                  "creation (and keep it for the whole series); "
                  "contrast belongs between scenes, not inside one "
                  "look.",
    },
    {
        "id": "craft_opening_shot",
        "keywords": ["opening shot", "first shot", "start of a scene",
                     "how to open a scene"],
        "answer": "Open with the place, then arrive at the person: a "
                  "wide shot establishes where we are, and the next "
                  "part moves in closer. For very short clips skip "
                  "the geography and open on the most striking frame "
                  "— the action already happening.",
    },
    {
        "id": "craft_quiet_scenes",
        "keywords": ["quiet scene", "silence in video",
                     "peaceful scene", "calm scene", "slow scene"],
        "answer": "Quiet scenes are a craft of their own: little "
                  "motion, soft light, one small sound-worthy detail "
                  "— dripping water, a turning page. Ask for 'calm, "
                  "minimal movement' and let the music bed carry the "
                  "feeling; stillness reads as confidence, not "
                  "emptiness.",
    },
    {
        "id": "craft_weather_mood",
        "keywords": ["weather in scene", "rain scene", "storm scene",
                     "weather mood", "fog scene"],
        "answer": "Weather is free mood. Rain means reflection and "
                  "loneliness, fog means mystery and hiding, snow "
                  "means purity or hardship, hard sun means honesty "
                  "and heat. Name the weather in your prompt — it "
                  "sets the emotional temperature of a scene.",
    },
    # ---- TOQIX itself — what it is, how it works ------------------------
    {
        "id": "toqix_what",
        "keywords": ["what is toqix", "about toqix", "toqix ai"],
        "answer": "TOQIX AI is a creation studio: type a prompt and "
                  "it makes short videos, images and spoken "
                  "voiceovers. I am its Agent — I run series where "
                  "the same character returns in every part, write "
                  "stories, suggest ideas and answer creation "
                  "questions. TOQIX is built on open AI models that "
                  "are tested and upgraded over time.",
    },
    {
        "id": "identity_who_built",
        "keywords": ["who built you", "who made you", "who created you",
                     "who built toqix", "who made toqix",
                     "your creator", "who developed you"],
        "answer": "I was built by TOQIX AI. TOQIX was founded and "
                  "built by Touqeer — known as Mr ALI — an independent "
                  "creator who designed this studio so anyone can "
                  "turn a simple prompt into videos, images and "
                  "voiceovers. I am the assistant he built into it.",
    },
    {
        "id": "make_video_steps",
        "keywords": ["how to make a video", "make a video",
                     "create a video", "how do i make"],
        "answer": "Making a video takes three steps: describe your "
                  "scene in one or two sentences, pick a style and "
                  "the frame shape (16:9 wide or 9:16 tall), then "
                  "send it. TOQIX writes the director's version of "
                  "your prompt, renders the clip, and it lands in "
                  "your Creations — usually within a few minutes.",
    },
    {
        "id": "how_long_takes",
        "keywords": ["how long does it take", "how much time",
                     "render time", "waiting time"],
        "answer": "Most videos are ready within a few minutes. Each "
                  "one is rendered frame by frame, so a 10-second "
                  "video takes longer than a short one, and a busy "
                  "queue can add a little wait. The percentage on "
                  "your creation's card shows exactly where it is.",
    },
    {
        "id": "durations_ten",
        "keywords": ["10 seconds", "10 second", "ten seconds",
                     "longer video", "heavy video", "lambi video"],
        "answer": "Videos can be 2, 3, 4, 5 or 10 seconds. A "
                  "10-second video is built as two connected scenes "
                  "— a setup, then the payoff — joined into one "
                  "clip, with one music bed across the whole thing. "
                  "It takes a little longer to render, and it is "
                  "the closest thing here to a complete mini-scene.",
    },
    {
        "id": "kinds_overview",
        "keywords": ["what can you make", "what kinds",
                     "types of creations", "can you make images",
                     "can you make audio", "sirf video"],
        "answer": "TOQIX makes four kinds of things: videos (2–10 "
                  "seconds), images, audio voiceovers (your words "
                  "spoken in one of six voices), and — through me, "
                  "the Agent — planned series that combine them "
                  "part by part with one consistent character.",
    },
    {
        "id": "privacy_private",
        "keywords": ["private", "privacy", "who can see",
                     "is my data safe", "data private"],
        "answer": "Your creations are private to your account. When "
                  "you are signed in, only you can see your videos, "
                  "images and audio — other users cannot browse or "
                  "open them. Whether you download and share a "
                  "creation anywhere else is entirely your choice.",
    },
    {
        "id": "zoo_plain",
        "keywords": ["which model", "what model", "models used",
                     "model zoo", "konsa model", "which ai model"],
        "answer": "TOQIX does not rely on one model — it keeps a "
                  "small team of open AI models, one specialist "
                  "each: one for video, one for images, one for "
                  "voices, one for music and one for chatting. Each "
                  "job is routed to the right specialist, and when "
                  "a better open model passes testing, it joins the "
                  "team.",
    },
    {
        "id": "quality_honest",
        "keywords": ["quality difference", "why quality",
                     "not as good", "compared to veo",
                     "quality kaisi hai"],
        "answer": "The biggest commercial tools run enormous "
                  "private models, so their raw detail is ahead "
                  "right now. TOQIX runs open models and closes the "
                  "gap with craft: stronger prompts, locked "
                  "characters, sound on every video and tested "
                  "model upgrades. The trade-off is honest: TOQIX "
                  "is free, private, and improving in the open.",
    },
    {
        "id": "cost_free",
        "keywords": ["is it free", "free hai", "price", "cost",
                     "muft", "fees lagti", "charges"],
        "answer": "Yes — TOQIX is free to use. There is no payment "
                  "step between you and creating: sign in, write a "
                  "prompt, and your video, image or voiceover is on "
                  "its way.",
    },
    {
        "id": "signin_account",
        "keywords": ["sign in", "sign up", "login", "my account",
                     "google account", "account banana"],
        "answer": "You sign in with your Google account — one tap, "
                  "no new password to remember. Signing in is what "
                  "keeps your creations private and tied to you, so "
                  "your videos and series are there when you come "
                  "back.",
    },
    {
        "id": "download_creations",
        "keywords": ["download", "save my video", "download kaise",
                     "save creation", "download karna"],
        "answer": "Open any creation from your Creations feed — it "
                  "opens in a big player — and use its Download "
                  "button to save the file to your device. From "
                  "there you can share it anywhere: YouTube, "
                  "WhatsApp, wherever your audience is.",
    },
    {
        "id": "regen_fix",
        "keywords": ["wrong result", "bad output", "not happy",
                     "redo", "generate again", "dobara banao",
                     "galat bana"],
        "answer": "If a result misses, do not just retry the same "
                  "words — sharpen them. Name the subject, the one "
                  "action and the place precisely, or say 'improve:' "
                  "and I will rebuild the prompt for you. In a "
                  "series the character anchor stays locked, so a "
                  "retried scene keeps the same character.",
    },
    {
        "id": "mobile_use",
        "keywords": ["on my phone", "mobile", "phone par",
                     "mobile se", "phone use"],
        "answer": "TOQIX works right in your phone's browser — same "
                  "site, same sign-in, same creations. For phone "
                  "viewing, the tall 9:16 shape is the natural "
                  "pick; everything you make on desktop is here "
                  "too, and the other way around.",
    },
    {
        "id": "languages_input",
        "keywords": ["roman urdu", "urdu mein", "prompt in urdu",
                     "language support", "hindi mein", "urdu prompt"],
        "answer": "You can write to me in English or in Roman Urdu — "
                  "I understand both, and I will answer in the "
                  "language you used. Prompts for videos and images "
                  "also work in Roman Urdu; the site itself stays in "
                  "English so everything is in one place.",
    },
    {
        "id": "improve_loops",
        "keywords": ["improve itself", "self improving",
                     "self-improving", "keep improving",
                     "does it learn", "get better over time"],
        "answer": "TOQIX improves in rounds, not by magic: new "
                  "research feeds its creation guides, every "
                  "production lesson becomes a permanent prompt "
                  "rule, better open models are tested and adopted, "
                  "and — only with a creator's consent — creations "
                  "can train future versions. Nothing changes "
                  "silently; every improvement is tested first.",
    },
    {
        "id": "styles_list",
        "keywords": ["what styles", "styles list", "which styles",
                     "all styles", "list of styles"],
        "answer": "The main styles are: cinematic, photorealistic, "
                  "anime, 3D animation, vintage film, cyberpunk and "
                  "nature documentary — plus noir, horror, comedy, "
                  "vaporwave, watercolor and pixel art. One style "
                  "per series keeps every part looking like one "
                  "family.",
    },
    {
        "id": "series_what",
        "keywords": ["what is a series",
                     "what does series mean", "series meaning"],
        "answer": "A series is one story told in parts, with the "
                  "SAME character in every part. You describe the "
                  "character once; then each scene you send becomes "
                  "Part 1, Part 2, Part 3 — same face, same style, "
                  "same voice. It is how short clips become a real "
                  "story instead of separate moments.",
    },
    # ---- creator & viral know-how ---------------------------------------
    {
        "id": "viral_general",
        "keywords": ["viral", "go viral", "viral kaise", "viral karna",
                     "viral hone", "how to go viral",
                     "makes a video viral", "video viral"],
        "answer": "No one can promise viral — but the videos that "
                  "spread share a pattern: a hook in the first 2 "
                  "seconds (result first, no intro), a length people "
                  "finish (25–30 seconds for a story Short), one "
                  "clear idea, captions in the exact spoken words, "
                  "and a character or series viewers return for. "
                  "Post steadily, watch what people rewatch, and "
                  "make more of that.",
    },
    {
        "id": "viral_hook",
        "keywords": ["hook", "first 2 seconds", "first seconds",
                     "viral hook", "hook kya hai", "pehle seconds"],
        "answer": "A Short is won or lost in the first 2 seconds — "
                  "that is when viewers decide to stay or swipe. "
                  "Start mid-action or show the result first, with "
                  "the premise in big on-screen words. No greeting, "
                  "no logo, no slow build-up: the hook IS the first "
                  "frame.",
    },
    {
        "id": "viral_shorts_length",
        "keywords": ["shorts length", "how long should a short",
                     "short video length", "viral length",
                     "best length for shorts", "short kitna lamba",
                     "shorts kitne seconds", "short ki length",
                     "how long should a youtube short"],
        "answer": "For a story Short, 25–30 seconds is the sweet "
                  "spot: long enough for a three-beat story "
                  "(trouble, help, payoff), short enough that "
                  "people finish it and watch again. Completion and "
                  "replays matter more than raw seconds — a finished "
                  "20-second Short beats an abandoned 40-second "
                  "one.",
    },
    {
        "id": "viral_series_grow",
        "keywords": ["series or one-off", "grow subscribers",
                     "grow a channel", "channel grow", "one-offs",
                     "series vs single"],
        "answer": "One-off videos can win reach, but series win "
                  "subscribers. A recurring character gives viewers "
                  "someone to return for — number the parts, leave a "
                  "small thread open ('Part 3 tomorrow'), and the "
                  "audience starts asking for the character by name. "
                  "That is when a channel becomes a habit.",
    },
    {
        "id": "viral_captions",
        "keywords": ["captions", "subtitles", "caption kaise",
                     "add captions"],
        "answer": "Captions should say EXACTLY the words being "
                  "spoken or shown — never a summary, never "
                  "different words. Many people watch on mute, so "
                  "burn captions in yourself in an editor instead of "
                  "letting a generator invent on-screen text. "
                  "Caption, hook text and speech must agree, or "
                  "viewers feel cheated and leave.",
    },
    {
        "id": "viral_titles",
        "keywords": ["video title", "catchy title", "title kaise",
                     "write a title", "title"],
        "answer": "A title is the hook's second copy: put the "
                  "premise first, keep it under about 55 characters, "
                  "and use at most one emoji. Name the character or "
                  "series for returning viewers, and tease the twist "
                  "without lying about it — 'He found a baby deer… "
                  "then THIS happened' under-delivers next to naming "
                  "the twist.",
    },
    {
        "id": "viral_asmr",
        "keywords": ["asmr", "satisfying video", "satisfying",
                     "asmr video"],
        "answer": "AI ASMR — impossible things being cut, crushed "
                  "or poured, in perfect loops — is one of the "
                  "biggest formats on the internet (hundreds of "
                  "millions of views). The catch: glass fruit is "
                  "saturated. Win by inventing a NEW impossible "
                  "material — ice honeycomb, sandstone melon, cloud "
                  "bread — with crisp sound and a seamless loop.",
    },
    {
        "id": "viral_pov_format",
        "keywords": ["pov history", "pov videos", "pov format",
                     "history pov", "wake up in"],
        "answer": "POV history — 'POV: you wake up in Pompeii, 79 "
                  "AD' — puts the viewer inside a moment, first "
                  "person, peril in frame one, one true fact as the "
                  "payoff. The best of these earn tens of millions "
                  "of views, but audiences fact-check them: keep "
                  "the history broadly right and frame it as a "
                  "recreation.",
    },
    {
        "id": "viral_character_vlog",
        "keywords": ["character vlog", "vlog", "recurring character",
                     "mascot series", "character series"],
        "answer": "The strongest format right now is the "
                  "recurring-character vlog: one invented character, "
                  "one voice, one familiar setting, filming "
                  "themselves doing everyday things — breakfast, a "
                  "chore, a small disaster. Characters like that "
                  "have earned millions of views in days because "
                  "every episode advertises the next one.",
    },
    {
        "id": "viral_cadence",
        "keywords": ["how often to post", "posting daily",
                     "posting", "upload schedule", "kitni videos roz",
                     "post karna"],
        "answer": "Consistency beats bursts. If you post several "
                  "Shorts a day, space them hours apart so each one "
                  "gets its own fair test with viewers, and rotate "
                  "formats instead of uploading five near-identical "
                  "videos — repetition is what platforms punish and "
                  "audiences tire of. Retire any format whose "
                  "viewers keep swiping away.",
    },
    {
        "id": "viral_engagement",
        "keywords": ["more comments", "engagement", "more shares",
                     "comments kaise", "get comments"],
        "answer": "Comments and shares are designed, not hoped for: "
                  "end on a cliffhanger, ask a forced-choice "
                  "question ('Team A or Team B?'), pin a comment "
                  "asking for Part 2, and make the last frame rhyme "
                  "with the first so the replay feels seamless. "
                  "Surprising, send-to-a-friend facts earn shares "
                  "better than any request to share.",
    },
    {
        "id": "viral_fake_real",
        "keywords": ["fake rescue", "fake video", "channel banned",
                     "fake trailer", "fake allowed", "rescue video",
                     "fake cctv"],
        "answer": "Never pass fiction off as real. Fake rescues, "
                  "fake CCTV and fake 'official' trailers presented "
                  "as genuine have gotten big channels terminated — "
                  "deception, not AI itself, is the offence. The "
                  "durable version is openly fictional storytelling: "
                  "invented characters, clearly a story, labelled as "
                  "AI-made where the platform asks.",
    },
    {
        "id": "viral_loop",
        "keywords": ["loop video", "seamless loop", "loopable",
                     "replay", "loop kaise"],
        "answer": "A clean loop makes the end flow into the "
                  "beginning so viewers watch twice without "
                  "noticing — and replays are a powerful signal. "
                  "Design for it: end on the same frame, motion or "
                  "sound you started with, and keep the clip "
                  "rhythmic. Satisfying and ASMR formats live on "
                  "loops.",
    },
    {
        "id": "viral_hashtags",
        "keywords": ["hashtags", "hashtag", "how many tags",
                     "tags for shorts"],
        "answer": "Keep hashtags lean: #Shorts plus two or three "
                  "specific tags that name your niche or character. "
                  "More hashtags do not help and can look like spam; "
                  "the title, the first frame and the watch-through "
                  "do the real work.",
    },
    # ---- sound: music beds & voices --------------------------------------
    {
        "id": "sound_music_bed",
        "keywords": ["music in video", "background music",
                     "sound bed", "music bed", "music",
                     "video mein music"],
        "answer": "Every TOQIX video now ships with a music bed — "
                  "background music generated to fit your scene and "
                  "mixed under the picture. A fight gets epic drums "
                  "and brass, the ocean gets soft piano over waves, "
                  "a forest gets gentle ambient tones with birds. "
                  "Sound is half the feeling of a video; silence was "
                  "never the plan.",
    },
    {
        "id": "sound_vs_voice",
        "keywords": ["voiceover vs music", "music or voice",
                     "narration or music", "voice and music"],
        "answer": "Music and voice do different jobs. The music bed "
                  "sits UNDER a video and carries mood — it has no "
                  "words. A voiceover SPEAKS your words: that is an "
                  "audio creation, read by one of the six TOQIX "
                  "voices. A series can pair them — a video part "
                  "for the eyes, an audio part for the story told "
                  "aloud.",
    },
    {
        "id": "sound_choose",
        "keywords": ["choose the music", "change the music",
                     "music style", "music mood", "kaisi music"],
        "answer": "You steer the music with your prompt's mood. The "
                  "bed is composed from what your scene is about — "
                  "ask for a calm river at dawn and the music turns "
                  "gentle; ask for a storm battle and it turns "
                  "intense. Name the feeling ('peaceful', 'tense', "
                  "'joyful') and the sound follows the picture.",
    },
    {
        "id": "audio_tts_kind",
        "keywords": ["text to speech", "voiceover", "tts",
                     "audio creation", "speech banana"],
        "answer": "An audio creation turns your written words into "
                  "speech: pick one of the six voices, send the "
                  "text, and TOQIX reads it aloud as a finished "
                  "audio clip. It is how narrations, story readings "
                  "and announcements are made here — separate from "
                  "videos, which carry a music bed instead.",
    },
    {
        "id": "sound_dialogue_video",
        "keywords": ["talking video", "characters speak",
                     "dialogue in video", "video mein dialogue",
                     "bolti video"],
        "answer": "TOQIX videos carry music and mood rather than "
                  "spoken dialogue — the characters do not lip-sync "
                  "lines. When your story needs words spoken aloud, "
                  "make an audio part with one of the six voices "
                  "and pair it with the video part in your series: "
                  "picture from one, voice from the other.",
    },
    # ---- creative help: stories, characters, poems, scripts --------------
    {
        "id": "story_structure",
        "keywords": ["story structure", "three acts",
                     "story likhna", "kahani structure",
                     "plot structure"],
        "answer": "Every working story has three movements: SETUP "
                  "(who and where, something wanted), CONFLICT "
                  "(something blocks it, stakes rise), PAYOFF (the "
                  "attempt, the turn, the feeling lands). For short "
                  "series I plan it as four beats — Hook, Problem, "
                  "Twist, Payoff — one beat per part.",
    },
    {
        "id": "story_endings",
        "keywords": ["cliffhanger", "story ending", "ending kaise",
                     "kahani ka end", "end a story"],
        "answer": "Endings come in two honest kinds. A payoff ending "
                  "closes the loop — the problem resolves and the "
                  "feeling lands; best for standalone stories. A "
                  "cliffhanger stops one breath BEFORE the answer "
                  "and promises the next part; best inside a series, "
                  "and only fair if the next part truly comes.",
    },
    {
        "id": "dialogue_tips",
        "keywords": ["dialogue", "write dialogue",
                     "dialogues kaise", "conversation likhna",
                     "lines likhna"],
        "answer": "Good dialogue is short and loaded: one speaker, "
                  "one or two lines, each line wanting something. "
                  "Let characters interrupt, dodge and imply instead "
                  "of explaining — real people rarely say exactly "
                  "what they mean. Read it aloud; if you run out of "
                  "breath, the line is too long.",
    },
    {
        "id": "genre_list",
        "keywords": ["genres", "genre list", "types of stories",
                     "story genres", "kahani ki types"],
        "answer": "The story genres to play with: adventure, "
                  "horror, comedy, romance, fantasy, sci-fi, "
                  "mystery, drama and tales for kids — each with its "
                  "own mood and rules. TOQIX series plans are built "
                  "on genre templates, so naming a genre ('a horror "
                  "series about…') gives your story a proven "
                  "skeleton.",
    },
    {
        "id": "character_design",
        "keywords": ["character design", "design a character",
                     "character banana", "character kaisa ho",
                     "create a character"],
        "answer": "Design a character in three strokes: one clear "
                  "silhouette (shape readable at a glance), one "
                  "signature detail (a red scarf, a cracked visor — "
                  "the thing every part repeats), and one want (what "
                  "they chase in every story). Describe all three "
                  "in the same words every time and the character "
                  "stays themselves.",
    },
    {
        "id": "story_hero",
        "keywords": ["good hero", "hero character", "protagonist",
                     "villain", "acha villain"],
        "answer": "A hero needs a want and a flaw: something they "
                  "chase, and the weakness that keeps costing them. "
                  "A good villain is the hero's mirror — same want, "
                  "opposite method — and believes their own story. "
                  "Give both one specific detail (a habit, a scar, "
                  "a saying) and audiences remember them.",
    },
    {
        "id": "poetry_haiku",
        "keywords": ["haiku", "haiku kya", "haiku poem"],
        "answer": "A haiku is a tiny poem of three lines — five "
                  "syllables, seven, five — holding one clear image "
                  "from nature and a small turn at the end. Its "
                  "power is what it leaves out: one moment, felt "
                  "completely. Ask me and I will write you one.",
    },
    {
        "id": "poetry_sonnet",
        "keywords": ["sonnet", "sonnet kya", "sonnet poem"],
        "answer": "A sonnet is a 14-line poem with a steady rhythm "
                  "and one argument that turns — the 'volta' — "
                  "usually near the end, closing in a rhyming pair "
                  "of lines. Shakespeare made it famous for love; "
                  "it works for any feeling that changes its mind "
                  "halfway through.",
    },
    {
        "id": "poetry_ghazal",
        "keywords": ["ghazal", "ghazal kya", "ghazal hai"],
        "answer": "A ghazal is a chain of couplets — each sher "
                  "stands alone like a pearl — bound by one rhyme "
                  "(qafia) and a repeated refrain word (radif) at "
                  "every couplet's end. Its classic subjects are "
                  "love, longing and separation, which is why it "
                  "lives so deeply in Urdu poetry.",
    },
    {
        "id": "script_format",
        "keywords": ["script format", "screenplay",
                     "script kaise likhe", "script likhna"],
        "answer": "A script page has three building blocks: a scene "
                  "heading ('INT. KITCHEN — MORNING' or 'EXT. "
                  "RIVER — DUSK'), action lines in the present "
                  "tense describing only what the camera sees, and "
                  "dialogue set under the speaker's name. Keep "
                  "action visual and dialogue short — film shows, "
                  "it does not tell.",
    },
    {
        "id": "writers_block",
        "keywords": ["writers block", "no ideas",
                     "idea nahi aa raha", "soojh nahi"],
        "answer": "Writer's block breaks with a collision: take a "
                  "character and give them the wrong problem "
                  "(a fish afraid of water), or ask 'what if' about "
                  "something ordinary (what if the moon visited a "
                  "village?). Small and specific beats big and "
                  "vague — or say 'give me an idea' and I will "
                  "hand you three.",
    },
    {
        "id": "story_setting",
        "keywords": ["setting", "worldbuilding", "story world",
                     "duniya banana"],
        "answer": "A setting is a character too: give your world "
                  "one rule everyone obeys, one sensory signature "
                  "(a smell, a sound, a color), and one place the "
                  "story keeps returning to. Readers forgive simple "
                  "plots in worlds that feel smelled, heard and "
                  "lived in.",
    },
    {
        "id": "story_title",
        "keywords": ["choose a title", "story title",
                     "kahani ka naam", "kahani ka title"],
        "answer": "Name a story last, not first: take its strangest "
                  "image or its central question and make that the "
                  "title ('The Night the Moon Came Down'). Avoid "
                  "summaries — a title should promise a feeling or a "
                  "mystery, and it should be short enough to "
                  "remember after one hearing.",
    },
    # ---- Roman-Urdu answers (owner questions, full RU replies) -------------
    {
        "id": "toqix_kya_ru",
        "keywords": ["toqix kya hai", "toqix kia hai", "toqix kya",
                     "toqix ai kya"],
        "answer": "TOQIX AI aik creation studio hai: aap sirf "
                  "prompt likhte hain aur ye chhoti videos, images "
                  "aur awaaz wale voiceovers bana deta hai. Main is "
                  "ka Agent hoon — main aap ki series chalata hoon "
                  "jis mein aik hi character har part mein waisa hi "
                  "rehta hai, kahaniyan likhta hoon aur sawalon ke "
                  "jawab deta hoon.",
    },
    {
        "id": "identity_ru",
        "keywords": ["kis ne banaya", "tumhein kis ne banaya",
                     "toqix kis ne banaya", "banaya kis ne"],
        "answer": "Mujhe TOQIX AI ne banaya hai — ye platform "
                  "Touqeer (Mr ALI) ne design aur build kiya hai, "
                  "taake koi bhi sirf aik prompt se video, image ya "
                  "voiceover bana sake. Main unhi ka banaya hua "
                  "TOQIX Agent hoon, aur aap ki khidmat ke liye "
                  "haazir hoon — farmaiye, kya banayein?",
    },
    {
        "id": "video_banana_ru",
        "keywords": ["video kaise banaye", "video kaise banta",
                     "video banana hai", "video banani"],
        "answer": "Video banana asaan hai: pehle apne character ya "
                  "scene ko aik jumlay mein describe karein, phir "
                  "style chunein (cinematic aam tor par behtareen "
                  "hai), phir ratio aur length select karein. Scene "
                  "bhejne par main usay queue kar deta hoon aur "
                  "video chand minute mein aap ki Creations mein aa "
                  "jati hai.",
    },
    {
        "id": "time_ru",
        "keywords": ["kitna time lagta hai", "kitni der lagti",
                     "time kitna lagta", "kitna time lagega"],
        "answer": "Aam tor par aik video chand minute mein tayyar "
                  "ho jati hai. System usay frame by frame render "
                  "karta hai, is liye 10 second wali lambi video "
                  "par thora zyada waqt lagta hai; agar aagay queue "
                  "ho to kuch minute aur lag sakte hain. Card par "
                  "percentage se aap ko pata chalta rehta hai ke "
                  "video kahan tak pohanchi.",
    },
    {
        "id": "styles_ru",
        "keywords": ["styles konsi", "konsi styles",
                     "style kya kya", "styles kya hain"],
        "answer": "Styles mein cinematic (film jaisi look), "
                  "photorealistic (bilkul asal jaisi), anime, 3D "
                  "animation, vintage film, cyberpunk aur nature "
                  "documentary shamil hain — aur noir, horror, "
                  "comedy, watercolor waghera bhi. Aik series mein "
                  "aik hi style rakhein taake har part aik jaisa "
                  "lage.",
    },
    {
        "id": "voices_ru",
        "keywords": ["awaazein konsi", "konsi awaazein",
                     "awaaz ki list", "awaazein kya",
                     "voice konsi hai"],
        "answer": "TOQIX mein chhe (6) awaazein hain: Ava — garam "
                  "female, kahaniyon ke liye; Emma — British "
                  "female, classy explainers ke liye; Michael — "
                  "gehri male awaaz, trailers aur documentaries ke "
                  "liye; George — British male; Sky — jawan "
                  "female, social clips ke liye; Adam — casual "
                  "male, vlogs ke liye. Aik audio series mein aik "
                  "hi awaaz rehti hai.",
    },
    {
        "id": "privacy_ru",
        "keywords": ["mera data private", "data private hai",
                     "mera data mehfooz", "koi aur dekh sakta",
                     "privacy hai kya"],
        "answer": "Aap ki creations sirf aap ki hain. Sign in ke "
                  "baad jo kuch aap banate hain wo sirf aap ko "
                  "dikhta hai — koi doosra user aap ki videos, "
                  "images ya audio nahi dekh sakta. Share karna ya "
                  "na karna aap ka apna faisla hai.",
    },
    {
        "id": "series_kya_ru",
        "keywords": ["series kya hai", "series kia hai",
                     "series matlab", "series kya hoti"],
        "answer": "Series matlab aik hi character ki kai parts wali "
                  "kahani: aap character aik dafa describe karte "
                  "hain, phir 'Part 1:', 'Part 2:' likh kar scenes "
                  "bhejte rehte hain. Main har part mein wahi "
                  "character, wahi style aur wahi seed lock kar "
                  "deta hoon, taake character har part mein aik "
                  "jaisa lage.",
    },
    {
        "id": "prompt_ru",
        "keywords": ["prompt kaise likhe", "prompt kaise likho",
                     "acha prompt kaise", "prompt likhna hai"],
        "answer": "Ache prompt ka formula hai: SUBJECT + ACTION + "
                  "PLACE + LIGHT + CAMERA. Misaal: 'aik kashti "
                  "chalane wala (subject) apni kashti bandh raha "
                  "hai (action) dhund wale kinare par (place) "
                  "sunahri roshni mein (light), slow push-in "
                  "(camera)'. Koi rough idea ho to 'improve:' "
                  "likhein, main usay is formula se bana dunga.",
    },
    {
        "id": "capabilities_ru",
        "keywords": ["tum kya kar sakte ho", "kya kar sakte ho",
                     "kya kya kar sakte", "tum kya kar sakte"],
        "answer": "Main ye kar sakta hoon: aik hi character wali "
                  "series chalana (character aik dafa describe "
                  "karein, phir scenes bhejte jayein); creation ke "
                  "sawalon ke jawab dena; ideas dena; rough prompt "
                  "ko behtar banana; aur poori series plan karna. "
                  "Kuch bhi keh kar dekhein!",
    },
    # ---- generation techniques (wave 2, 2026-10-15) -------------------
    # Video craft techniques — our own proven production practice.
    {
        "id": "tech_camera_vocab",
        "keywords": ["camera moves", "camera movements",
                     "types of camera moves", "list of camera moves",
                     "pan shot", "tilt shot", "crane shot",
                     "handheld shot", "locked off shot", "static shot",
                     "whip pan", "rack focus", "camera moves konsi"],
        "answer": "The working camera vocabulary: PAN turns the "
                  "camera left/right on a fixed base; TILT tips it "
                  "up/down; CRANE rises over the scene; HANDHELD "
                  "adds human micro-shake (urgent, real); a LOCKED "
                  "OFF shot never moves — the scene moves instead; "
                  "a WHIP PAN is a fast blurred turn, pure energy; "
                  "RACK FOCUS travels the sharpness from foreground "
                  "to background; DOLLY ZOOM pushes in while "
                  "zooming out, stretching space (the vertigo "
                  "shot). Name ONE per shot — two moves at once "
                  "usually means neither lands.",
    },
    {
        "id": "tech_shot_sequence",
        "keywords": ["shot sequence", "shot order", "order of shots",
                     "coverage", "wide medium close", "shot sizes",
                     "shots kaise lagaye"],
        "answer": "Plan shots as a ladder: WIDE shows the place, "
                  "MEDIUM puts the person inside it, CLOSE-UP lands "
                  "the feeling or the detail. That wide-to-close "
                  "progression is the classic coverage order — "
                  "reverse it (detail first, place revealed last) "
                  "for mystery. Keep screen direction steady: a "
                  "subject travelling left-to-right should keep "
                  "travelling that way in the next shot, or the "
                  "viewer feels the world flip. In a series, each "
                  "part is one rung of the ladder.",
    },
    {
        "id": "tech_transitions",
        "keywords": ["transition", "transitions between shots",
                     "match cut", "cut from one shot",
                     "transition kaise"],
        "answer": "A cut feels smooth when something carries across "
                  "it: MOTION (the subject exits right and enters "
                  "right in the next shot), SHAPE (a match cut — a "
                  "round moon becomes a round wheel), SOUND (the "
                  "next scene's sound arrives a breath before its "
                  "picture), or a WIPE (the subject passes the lens "
                  "and its darkness covers the change). In a series, "
                  "end a part mid-motion and open the next part on "
                  "the same motion — the join disappears.",
    },
    {
        "id": "tech_first_frame",
        "keywords": ["first frame", "opening frame",
                     "first frame important",
                     "video ki pehli frame"],
        "answer": "A generator builds the whole clip outward from "
                  "its opening frame — so describe frame one like a "
                  "finished photograph: subject placed, light set, "
                  "the action already beginning. 'A man in a city' "
                  "drifts anywhere; 'low angle: a fisherman "
                  "silhouetted against a huge orange sunrise, "
                  "mid-cast' anchors everything that follows. In a "
                  "series, open each part near where the last part "
                  "closed.",
    },
    {
        "id": "tech_motion_physics",
        "keywords": ["realistic motion", "physics in video",
                     "unnatural movement", "motion looks fake",
                     "looks unnatural", "weight in motion",
                     "harkat ajeeb lagti"],
        "answer": "Motion reads fake when WEIGHT is missing. Give "
                  "actions their consequences: heavy steps land "
                  "with dust and a small body dip, fabric and hair "
                  "lag a beat behind the body, water splashes "
                  "outward and falls back, a runner leans into the "
                  "turn. Name the effect, not just the action — "
                  "'stomps, dust bursting at every step' beats "
                  "'walks heavily' every time.",
    },
    {
        "id": "tech_hands_faces",
        "keywords": ["hands look wrong", "extra fingers",
                     "weird hands", "bad hands", "face artifacts",
                     "hands in video", "haath galat bante"],
        "answer": "Hands and distant faces are where generators "
                  "slip first — extra fingers, melting features. "
                  "Work around it: keep hands busy with a prop "
                  "(holding a cup, gripping a rail), prefer medium "
                  "shots over tiny crowd faces, avoid counting "
                  "gestures and intricate hand choreography, and "
                  "make important faces LARGE in the frame. If a "
                  "hand moment truly matters, make it the shot "
                  "itself — big, simple and slow.",
    },
    {
        "id": "tech_environment_life",
        "keywords": ["background looks dead", "lifeless scene",
                     "scene feels empty", "background movement",
                     "secondary motion", "mahol zinda"],
        "answer": "A scene feels alive when the BACKGROUND moves "
                  "too: leaves trembling, distant traffic passing, "
                  "smoke curling, curtains breathing. This "
                  "secondary motion is the difference between a "
                  "filmed place and a painted backdrop. Add ONE "
                  "background layer to the prompt ('a busy market "
                  "behind her, flags fluttering') — cheap words, "
                  "huge realism. Two layers at most, or the "
                  "subject gets lost in its own world.",
    },
    {
        "id": "tech_prompt_length",
        "keywords": ["prompt too long", "how long should a prompt be",
                     "prompt length", "prompt kitna lamba",
                     "lamba prompt", "short prompt or long"],
        "answer": "Aim for a few tight sentences per shot. Too "
                  "short and the model guesses — and guesses bland. "
                  "Too long and the later clauses quietly get "
                  "dropped: the EARLIEST strong instruction wins, "
                  "so front-load the subject and the action and "
                  "put decoration last. If a detail truly matters "
                  "it belongs in the first two sentences; "
                  "everything after that is seasoning.",
    },
    {
        "id": "tech_specifics",
        "keywords": ["too many adjectives", "vague prompt",
                     "generic words", "prompt is not working",
                     "too vague", "adjectives in prompt"],
        "answer": "Adjectives are the weakest words in a prompt: "
                  "'epic, beautiful, amazing, stunning' tell the "
                  "model almost nothing it can draw. Trade each one "
                  "for something observable — not 'a beautiful "
                  "garden' but 'a garden of red roses and white "
                  "jasmine after rain, wet petals shining'. "
                  "Concrete nouns and strong verbs are what "
                  "generators actually obey.",
    },
    {
        "id": "tech_fastlane",
        "keywords": ["draft first", "test before final",
                     "iterate the prompt", "quick draft",
                     "save time rendering", "pehle draft"],
        "answer": "Professionals draft cheap and finish big: make "
                  "the short, rough version FIRST to lock the idea, "
                  "the framing and the words — then spend the real "
                  "render only on the version that already works. "
                  "Nine out of ten failures are prompt failures, "
                  "and a draft exposes them at a fraction of the "
                  "cost. Iterate the TEXT, not the render.",
    },
    {
        "id": "tech_qa_checklist",
        "keywords": ["check my video", "quality check", "qa check",
                     "verify the output", "frame check",
                     "galti kaise check", "output check karna"],
        "answer": "Before sharing any generation, check three "
                  "frames: the FIRST (does it open on the "
                  "promise?), a MIDDLE one (subject right? flags, "
                  "text and hands correct?) and the LAST (does it "
                  "end clean?). Then watch once through for motion "
                  "and sound. A wrong detail earns ONE regeneration "
                  "with the fix spelled out more explicitly; still "
                  "wrong, change the idea — not your luck. A wrong "
                  "video never ships.",
    },
    {
        "id": "tech_seed_variation",
        "keywords": ["try variations", "different version same scene",
                     "variation of a scene", "seed change karke",
                     "same scene new version"],
        "answer": "To explore a scene without losing it, keep every "
                  "word of the prompt and change ONLY the seed — "
                  "you get sibling versions of the same idea and "
                  "the best one wins. To stay consistent, do the "
                  "opposite: keep the seed locked. And change one "
                  "variable at a time — alter the words AND the "
                  "seed together and you can never tell what fixed "
                  "(or broke) the result.",
    },
    {
        "id": "tech_color_script",
        "keywords": ["color script", "colour script",
                     "what is a color script",
                     "palette across scenes",
                     "colors across a series", "rangon ki planning"],
        "answer": "A color script plans the palette ACROSS a whole "
                  "story before you generate: warm golds while "
                  "things go well, cold blues when danger comes, "
                  "and one accent color that belongs to your hero. "
                  "It is how separate clips start feeling like one "
                  "film. Decide the journey of colors first — then "
                  "each prompt just names its scene's stop on that "
                  "journey.",
    },
    {
        "id": "tech_vertical_composition",
        "keywords": ["vertical framing", "compose for vertical",
                     "9:16 composition", "vertical video composition",
                     "portrait framing"],
        "answer": "Compose FOR the tall frame instead of cropping a "
                  "wide idea into it: stack the world vertically "
                  "(foreground low, subject in the middle, sky or "
                  "ceiling high), keep the hero near the center "
                  "column where phone viewers actually look, and "
                  "leave a little room above heads. Wide group "
                  "scenes fight the tall frame; single heroes and "
                  "tall subjects — towers, waterfalls, giants — "
                  "love it.",
    },
    # ---- image craft techniques --------------------------------------
    {
        "id": "img_prompt_basics",
        "keywords": ["image prompt", "good image prompt",
                     "photo prompt", "tasveer ka prompt",
                     "tasveer ka prompt kaise",
                     "prompt for an image", "still image prompt"],
        "answer": "A still image wants MORE frozen detail than a "
                  "video prompt, not less: subject + specific "
                  "details (materials, textures, small props) + "
                  "environment + light + the photographic look "
                  "(lens, film, editorial). Nothing moves, so every "
                  "word should describe what can be SEEN in one "
                  "frame. One subject described richly beats three "
                  "subjects described thinly.",
    },
    {
        "id": "img_lens_language",
        "keywords": ["lens words", "portrait lens", "macro photo",
                     "focal length", "telephoto look",
                     "which lens words"],
        "answer": "Borrow the photographer's lens words — they are "
                  "precise style instructions: an 85mm-style lens "
                  "flatters portraits with creamy background blur; "
                  "a 24mm wide lens dramatizes spaces and "
                  "stretches edges; MACRO opens tiny worlds in huge "
                  "detail (insects, droplets, textures); TELEPHOTO "
                  "compresses distance, stacking layers like "
                  "mountains piled behind a city. Name the lens, "
                  "get the look.",
    },
    {
        "id": "img_negative_space",
        "keywords": ["negative space", "leading lines",
                     "photo composition", "symmetry in a photo",
                     "minimal photo"],
        "answer": "Three composition tools beyond the rule of "
                  "thirds: LEADING LINES — roads, rails and rivers "
                  "that walk the viewer's eye to your subject; "
                  "NEGATIVE SPACE — deliberate emptiness around the "
                  "subject, which makes it feel important, calm "
                  "and expensive; and SYMMETRY — a mirrored frame "
                  "for order, ceremony or unease. Pick ONE per "
                  "image: composition tricks fight each other too.",
    },
    {
        "id": "img_text_flags",
        "keywords": ["text in image", "logo in image",
                     "flag in image", "words in image",
                     "image have text",
                     "spelling in image", "jhanda image mein"],
        "answer": "Images hold text and emblems better than video "
                  "does — but only when you SPELL the job: quote "
                  "the exact words, keep them few and big, and "
                  "describe flags element by element (field color, "
                  "stripes, the symbol and where it sits). 'A flag "
                  "of Pakistan' is a wish; 'dark green flag, white "
                  "stripe at the hoist, white crescent and star in "
                  "the center' is an instruction. Verify the "
                  "result before you share it.",
    },
    {
        "id": "img_product_shot",
        "keywords": ["product photo", "good product photo",
                     "product shot", "product image",
                     "ecommerce photo", "product ki photo"],
        "answer": "Product shots follow a recipe: ONE hero product, "
                  "large and near-centered; a clean or softly "
                  "blurred background that cannot compete; a "
                  "surface with a gentle reflection under it; "
                  "softbox-style light from one side so materials "
                  "read (matte, glossy, metallic); and the label "
                  "facing the camera, spelled exactly. Lifestyle "
                  "clutter belongs in a second image, not in the "
                  "hero.",
    },
    {
        "id": "img_portrait",
        "keywords": ["portrait tips", "portrait photo",
                     "good portrait", "face photo tips",
                     "insaan ki photo"],
        "answer": "Portraits live or die on eyes and light: put the "
                  "eyes in the top third and in sharp focus, ask "
                  "for catchlights (the tiny sparkle in the eyes) "
                  "and soft window-style light, and describe skin "
                  "as REAL — 'natural skin texture, fine detail' — "
                  "so it never turns plastic. A shallow, "
                  "portrait-lens blur behind the face flatters "
                  "almost everyone.",
    },
    {
        "id": "img_consistency",
        "keywords": ["consistent images", "same character in images",
                     "images of the same character",
                     "image consistency", "images mein consistency",
                     "images mein consistency kaise",
                     "hero image first"],
        "answer": "For a SET of images with one character, generate "
                  "the hero image first — the clearest, most "
                  "detailed portrait — then reuse its EXACT subject "
                  "description, the same style and the same seed "
                  "in every following prompt, changing only the "
                  "scene. Without a reference image, the description "
                  "IS the anchor: never paraphrase it between "
                  "images, because paraphrases drift.",
    },
    {
        "id": "img_detail_level",
        "keywords": ["image looks blurry", "sharper image",
                     "more detail in image", "image detail",
                     "tasveer saaf kaise"],
        "answer": "Blur and mush usually mean the prompt spread its "
                  "detail too thin: too many subjects, tiny faces "
                  "in a crowd, text too small to draw. Concentrate "
                  "instead: fewer subjects, bigger in frame, "
                  "detail words attached to the SUBJECT "
                  "('weathered leather, brass buckles') rather "
                  "than to the whole scene, and nothing important "
                  "smaller than a thumbprint in the frame.",
    },
    # ---- audio: voice & music techniques ------------------------------
    {
        "id": "tts_punctuation",
        "keywords": ["punctuation in voiceover", "pauses in speech",
                     "voice pacing", "comma pause",
                     "speech mein pause"],
        "answer": "In spoken audio, punctuation IS the acting: "
                  "commas give a micro-pause, full stops a full "
                  "breath, an ellipsis (…) a trailing, thinking "
                  "pause, and a question mark lifts the end of the "
                  "line. Write the voice script the way it should "
                  "SOUND — short lines, one thought each — and put "
                  "a line break wherever the speaker should "
                  "breathe. If a sentence needs two breaths, it is "
                  "two sentences.",
    },
    {
        "id": "tts_emphasis",
        "keywords": ["emphasis in the voice", "add emphasis",
                     "stress a word", "voice emphasis",
                     "zor de kar bolna"],
        "answer": "To make one word land, do not shout — set it up: "
                  "put the important word at the END of the "
                  "sentence, or write it in CAPITALS for a firmer "
                  "stress, and keep capitals rare (one per "
                  "paragraph) or everything sounds shouted. "
                  "Structure is the stronger tool: 'We did not "
                  "lose. We LEARNED.' carries its own emphasis.",
    },
    {
        "id": "tts_numbers",
        "keywords": ["numbers in voiceover", "voice reads numbers",
                     "dates in audio", "numbers spoken wrong",
                     "number kaise bulwaye"],
        "answer": "A voice reads numbers literally, so write them "
                  "as you want them HEARD: years as 'twenty "
                  "twenty-six', big figures in words ('two "
                  "million'), phone-style numbers digit by digit "
                  "with spaces, and decimals spelled out ('three "
                  "point five'). Test the first line before "
                  "generating a long script — a wrong number means "
                  "rewriting the text, not the voice.",
    },
    {
        "id": "tts_script_length",
        "keywords": ["voiceover script", "long audio script",
                     "script for narration", "words per minute",
                     "audio script kitna lamba"],
        "answer": "Spoken English runs about 150 words a minute, "
                  "so plan scripts by the clock: 30 seconds is "
                  "roughly 75 words, one minute roughly 150. Keep "
                  "lines breath-sized (under about twenty words), "
                  "and for long narrations split the text into "
                  "parts — an audio series in one voice stays "
                  "consistent AND lets you fix a single part "
                  "without redoing everything.",
    },
    {
        "id": "tts_voice_casting",
        "keywords": ["voice for a trailer", "voice casting",
                     "best voice for narration", "voice for stories",
                     "trailer ke liye konsi awaaz"],
        "answer": "Cast the voice like an actor: deep Michael for "
                  "trailers and big announcements, warm Ava for "
                  "stories and friendly narration, Emma when it "
                  "should feel classy and precise, George for "
                  "serious tales, Sky for young energetic social "
                  "clips, Adam for casual everyday talk. Match the "
                  "voice to the JOB first; your personal favorite "
                  "comes second.",
    },
    {
        "id": "music_formula",
        "keywords": ["describe the music", "music prompt words",
                     "music description", "how to describe music",
                     "music words", "music kaise describe"],
        "answer": "Describe any music — a video's bed or a music "
                  "request — with four ingredients: GENRE "
                  "(cinematic orchestra, lo-fi, folk), INSTRUMENTS "
                  "(soft piano, heavy drums, strings), MOOD "
                  "(peaceful, tense, triumphant) and TEMPO "
                  "(slow and spacious, driving and urgent). 'Sad "
                  "music' is a wish; 'slow solo piano, sparse and "
                  "melancholic, lots of space between the notes' "
                  "is a recipe a generator can actually cook.",
    },
    {
        "id": "music_tempo",
        "keywords": ["music tempo", "music energy",
                     "music build up", "fast music slow music",
                     "tempo kya rakhe"],
        "answer": "Tempo is the heartbeat of a clip: slow and "
                  "spacious for awe, grief and luxury; a steady "
                  "pulse for journeys and work; fast and driving "
                  "for chases, sports and celebration. For anything "
                  "longer than a moment, describe the ARC too — "
                  "enters quietly under the opening, builds "
                  "through the middle, resolves on the last frame. "
                  "Music that starts at full energy has nowhere "
                  "to go.",
    },
    {
        "id": "sound_ambience",
        "keywords": ["sound effects", "ambience sounds",
                     "background sounds", "sfx in video",
                     "environment sounds", "mahol ki awaazein"],
        "answer": "Music tells the FEELING; ambience tells the "
                  "PLACE. Name the environment's own sounds "
                  "alongside a scene — rain on a tin roof, a "
                  "market crowd's murmur, café chatter and "
                  "cutlery, wind through pines. Even tucked "
                  "quietly under the music, one true ambient layer "
                  "makes a generated scene feel occupied instead "
                  "of rendered.",
    },
    # ---- Omni Flash techniques (Google Flow's model — technique
    # Q&A; TOQIX does not run Omni, its craft transfers) -----------------
    {
        "id": "omni_what",
        "keywords": ["omni flash", "what is omni",
                     "omni flash kya hai", "gemini omni",
                     "omni model"],
        "answer": "Omni Flash (Gemini Omni) is Google's video model "
                  "inside Flow — unusual because it both GENERATES "
                  "clips and EDITS existing video by conversation, "
                  "with native sound and dialogue. TOQIX does not "
                  "run it; I teach its techniques because they are "
                  "the current state of the art, and most of them "
                  "— restating the subject in full, one camera "
                  "move, surgical edits — make prompts better on "
                  "every model, including ours.",
    },
    {
        "id": "omni_settings",
        "keywords": ["duration and resolution", "omni settings",
                     "omni duration setting", "omni mein duration",
                     "settings not prompt"],
        "answer": "On Omni Flash, length, resolution and frame "
                  "shape are SETTINGS you pick in the composer — "
                  "not words inside the prompt. Writing 'make it "
                  "12 seconds' in the prompt does not change any "
                  "setting; it only confuses the composition. "
                  "Clips run 3–10 seconds, shapes are wide 16:9 or "
                  "tall 9:16 only, and 720p is the native render "
                  "(upscaling happens afterwards). Set the dials "
                  "first, then write the prompt for the shot "
                  "itself.",
    },
    {
        "id": "omni_editing",
        "keywords": ["omni editing", "edit a video with omni",
                     "conversational editing",
                     "keep everything else the same",
                     "omni se edit"],
        "answer": "Omni's signature skill is editing by "
                  "conversation: keep the clip, describe ONE "
                  "change, and add 'Keep everything else the "
                  "same.' Short and surgical wins — 'make the sky "
                  "sunset orange, keep everything else the same' — "
                  "because long, descriptive edit prompts cause "
                  "changes you never asked for. One or two changes "
                  "per turn, check the result, then continue: "
                  "each turn builds on the last.",
    },
    {
        "id": "omni_dialogue",
        "keywords": ["dialogue in omni", "dialogue in omni flash",
                     "omni dialogue",
                     "speaker says", "omni mein dialogue",
                     "talking characters omni"],
        "answer": "Omni writes speech into the clip itself with "
                  "one syntax: name the speaker and quote the line "
                  "— Speaker says: 'We have to go, now.' Keep it "
                  "to at most two short lines per clip and add a "
                  "delivery note ('whispers', 'flat and tired') — "
                  "long speeches and overlapping speakers fall "
                  "apart. Name the music and room sound too, or "
                  "ask for 'No music, just room tone': silence is "
                  "also a choice you must state.",
    },
    {
        "id": "omni_single_shot",
        "keywords": ["omni invents cuts", "inventing cuts",
                     "single continuous shot",
                     "no scene cuts", "omni one shot"],
        "answer": "Left alone, Omni likes to direct: it invents "
                  "cuts and extra shots. When you want ONE take, "
                  "say so in the prompt — 'in a single continuous "
                  "shot, no scene cuts' — and write for a single "
                  "take: one camera move, one or two action beats, "
                  "and the subject restated in full, because the "
                  "model does not carry your last clip's "
                  "description into a new generation.",
    },
    {
        "id": "omni_references",
        "keywords": ["reference images", "omni references",
                     "reference images omni",
                     "omni character consistency",
                     "flow characters"],
        "answer": "In Omni and Flow, consistency comes from "
                  "references: give each reference ONE job and say "
                  "the job in words ('the woman in the reference "
                  "image', 'use this only for the jacket's "
                  "color'). One to three references is the sweet "
                  "spot — more makes generations slower and "
                  "stranger. A voice needs a face: pair a voice "
                  "with a character image. And for a seamless "
                  "move, give a first frame AND a last frame and "
                  "let the model travel between them.",
    },
    {
        "id": "omni_negatives",
        "keywords": ["omni negative prompt", "negative prompt field",
                     "omni mein negative", "in-prompt negatives"],
        "answer": "Omni has NO negative-prompt box — exclusions "
                  "are plain sentences inside the prompt: 'no "
                  "on-screen text, no captions, no subtitles', "
                  "'no dialogue', 'do not show the drawing'. The "
                  "same honesty applies in reverse: if a sign or "
                  "title must appear, quote its exact words, or "
                  "expect invented lettering. On models WITH a "
                  "negative field (like ours) the field does this "
                  "job — and the craft of choosing three crisp "
                  "exclusions is identical.",
    },
    {
        "id": "omni_extend_intent",
        "keywords": ["omni scene extension", "extend a clip omni",
                     "omni intent prompting", "omni clip barhana"],
        "answer": "Two Omni habits worth stealing: (1) EXTEND, "
                  "don't restart — a good clip can be extended in "
                  "roughly 10-second steps (up to about 40 "
                  "seconds), the model reading the previous "
                  "ending for continuity — the same reason TOQIX "
                  "series parts open where the last part closed. "
                  "(2) State INTENT and spend your detail on "
                  "looks: clear direction plus rich aesthetic "
                  "guidance beats over-specified physics and "
                  "facts, which mostly waste the prompt.",
    },
    # ---- Seedance & multi-shot technique (ByteDance's closed model
    # made this grammar famous; TOQIX teaches the craft, honestly) -----
    {
        "id": "seed_what",
        "keywords": ["seedance", "what is seedance",
                     "seedance kya hai", "bytedance video model"],
        "answer": "Seedance is ByteDance's top video model family, "
                  "famous for NATIVE multi-shot storytelling: one "
                  "prompt can hold two or three real cuts — wide, "
                  "medium, close-up — with the same subject, style "
                  "and mood carried across all of them. It is a "
                  "closed model, so TOQIX does not run it; what "
                  "we take from it is its prompt grammar, which is "
                  "public craft and makes our own scenes and "
                  "series parts sharper.",
    },
    {
        "id": "seed_multishot_structure",
        "keywords": ["multi-shot prompt", "multi shot prompt",
                     "multishot structure", "shot 1 shot 2",
                     "multi shot prompt kaise",
                     "multi shot kaise likhe"],
        "answer": "The multi-shot prompt structure used by "
                  "advanced video models (Seedance made it "
                  "famous): label the shots — 'Shot 1:', 'Shot "
                  "2:' — and give EACH shot one primary action, "
                  "one camera move and its own sound cue, with "
                  "the character described identically in every "
                  "shot. On TOQIX the same grammar becomes a "
                  "series — one shot per part, the same anchor "
                  "text everywhere — or a 10-second video, which "
                  "is built as exactly two such shots.",
    },
    {
        "id": "seed_timecodes",
        "keywords": ["timed segments", "time ranges in prompt",
                     "0-3s prompt", "timecoded prompt",
                     "timecode shots"],
        "answer": "Instead of shot labels, you can pin beats to "
                  "TIME: '0–3s: close-up, the letter is opened. "
                  "3–6s: cut to her face, she smiles.' Models with "
                  "strong instruction-following (Seedance "
                  "popularized this) honor the ranges — and the "
                  "discipline helps on any model: it forces you "
                  "to budget seconds per beat, and a beat that "
                  "does not fit its seconds gets cut on paper "
                  "instead of on screen.",
    },
    {
        "id": "seed_camera_literal",
        "keywords": ["precise camera words", "camera terms literal",
                     "seedance camera language",
                     "rack focus technique", "term plus result"],
        "answer": "Seedance-style prompting treats camera words as "
                  "LITERAL instructions, not vibes: 'dynamic "
                  "camera' means nothing to a lens, 'slow "
                  "dolly-in' means everything. For a niche move, "
                  "give the term PLUS its visible result — 'rack "
                  "focus: the foreground leaves blur as the face "
                  "behind them comes clear' — so even a model "
                  "that half-knows the term can draw the outcome. "
                  "One move per shot, and pace it: slow, medium "
                  "or fast.",
    },
    {
        "id": "seed_shot_size_first",
        "keywords": ["state the shot size", "shot size up front",
                     "wide medium close progression",
                     "shot size first", "framing first"],
        "answer": "State the shot size UP FRONT in every shot "
                  "('Close-up: …', 'Wide shot: …') — the model "
                  "fixes the framing from the first words and "
                  "stops re-centering mid-take. Across a sequence "
                  "the classic progression runs wide → medium → "
                  "close-up, walking the viewer from place to "
                  "person to feeling. Naming each part's size "
                  "keeps that ladder deliberate instead of "
                  "random.",
    },
    {
        "id": "seed_continuity_cuts",
        "keywords": ["continuity across cuts",
                     "consistent across shots",
                     "same grade every shot",
                     "cuts mein continuity"],
        "answer": "Multi-shot work stays believable when the "
                  "INVARIANTS are repeated, not assumed: the same "
                  "character description word-for-word, the same "
                  "wardrobe, the same palette and lighting "
                  "direction in every shot — with the global "
                  "settings stated once at the top, before Shot "
                  "1. Anything first mentioned in shot three "
                  "cannot retroactively fix shot one. This is "
                  "exactly the anchor a TOQIX series locks for "
                  "you automatically.",
    },
    {
        "id": "seed_director_brief",
        "keywords": ["director's shot brief", "shot brief structure",
                     "directors brief order", "brief style prompt",
                     "prompt order seedance"],
        "answer": "Write the prompt as a director's SHOT BRIEF, in "
                  "this order: (1) subject + one action — the "
                  "kinetic core everything hangs on; (2) camera — "
                  "size, move, angle; (3) scene, style and "
                  "lighting; (4) sound — a cue or a quoted line; "
                  "(5) constraints LAST, as guardrails. Short and "
                  "structured beats long and poetic: a model "
                  "honors its earliest strong instruction, so "
                  "the order IS the priority list.",
    },
    {
        "id": "seed_onetake_vs_cuts",
        "keywords": ["one take or cuts", "single take vs cuts",
                     "cuts ya one take", "no cuts prompt",
                     "continuous take seedance"],
        "answer": "Decide the grammar before writing: CUTS "
                  "(labelled shots) tell a story in angles and "
                  "beats; a ONE-TAKE ('single continuous take, no "
                  "cuts') sells immersion and one unbroken move. "
                  "Asking for neither gets you the model's "
                  "default habits — drifting between the two. "
                  "State the choice in the first line and repeat "
                  "it in the constraints at the end.",
    },
]


# ---------------------------------------------------------------------------
# Lookup — keyword scoring (word-boundary for single words, substring for
# phrases), so "cyberpunk" hits the cyberpunk entry but "cat" never fires
# inside "cathedral".
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    s = " ".join((text or "").lower().split())
    # Roman-Urdu spelling fold: many users write "hay" where the
    # keywords use "hai" (same word, two spellings). Fold the
    # message and the keywords identically so both sides meet.
    return re.sub(r"\bhay\b", "hai", s)


def score_entry(text: str, entry: dict) -> tuple[int, int]:
    """(score, matched_chars) of `entry` against raw user text.

    Score weights longer keywords more (specific beats generic); the
    matched_chars total lets callers judge whether the message is
    *mostly* about this one topic.
    """
    norm = _norm(text)
    score = 0
    matched = 0
    tokens = set(norm.split())
    for kw in entry["keywords"]:
        k = _norm(kw)
        if not k:
            continue
        if " " in k or "-" in k:
            hit = k in norm
            if hit:
                score += len(k) + 2
                matched += len(k)
            elif (" " in k and len(k.split()) >= 4
                    and all(w in tokens for w in k.split())):
                # Word-set match (4+ word phrases only — shorter
                # phrases like "make a video" are too generic to
                # trust scattered): the keyword's words are all
                # here but not adjacent ("how long should a YOUTUBE
                # short" vs keyword "how long should a short").
                # Scores the phrase length without the exact-phrase
                # bonus, so an exact phrase elsewhere still wins.
                score += len(k)
                matched += len(k)
        else:
            hit = re.search(rf"\b{re.escape(k)}\b", norm) is not None
            if hit:
                score += len(k)
                matched += len(k)
    return score, matched


def lookup(text: str) -> dict | None:
    """Best knowledge entry for `text`, or None when nothing fits."""
    best: dict | None = None
    best_score = 0
    for entry in ENTRIES:
        score, _ = score_entry(text, entry)
        if score > best_score:
            best, best_score = entry, score
    if best is None or best_score < 3:
        return None
    return best


def match_ratio(text: str, entry: dict) -> float:
    """Fraction of the (normalized) message covered by this entry's
    keywords — a strong short topic like "drone shot" scores ~1.0,
    a long scene that merely mentions one scores low."""
    norm = _norm(text)
    if not norm:
        return 0.0
    _, matched = score_entry(text, entry)
    return matched / max(len(norm), 1)


# ---------------------------------------------------------------------------
# Idea seeds — 3 per curriculum domain (from data/curriculum/domains.json)
# plus genre buckets users actually ask for. `match` words route free
# text ("horror video ka idea do") to the right bucket.
# ---------------------------------------------------------------------------
IDEA_SEEDS: dict[str, dict] = {
    "nature_landscapes": {
        "label": "Nature & Landscapes",
        "match": ["nature", "landscape", "mountain", "forest", "valley",
                  "waterfall", "pahad", "jangal", "meadow"],
        "ideas": [
            "A lone hiker crosses a misty mountain ridge at sunrise as "
            "clouds drift through the valley below",
            "A waterfall pours into a green jungle pool while sunlight "
            "breaks through the rain-washed leaves",
            "Golden light sweeps across a wildflower meadow as a river "
            "winds toward snow-capped peaks",
        ],
    },
    "ocean_weather": {
        "label": "Ocean & Weather",
        "match": ["ocean", "sea", "weather", "beach", "rain", "storm",
                  "snow", "samandar", "barish", "barf"],
        "ideas": [
            "Ocean waves crash over dark rocks as a storm rolls in "
            "under a dramatic sky",
            "Gentle snowfall settles over a frozen lake at dusk while "
            "distant lights flicker on",
            "A single sailboat crosses a calm sea beneath towering "
            "golden clouds at sunset",
        ],
    },
    "cities_streets": {
        "label": "Cities & Streets",
        "match": ["city", "street", "urban", "bazaar", "market",
                  "sheher", "traffic", "downtown"],
        "ideas": [
            "A busy bazaar lane glows with shop lights as crowds weave "
            "between rickshaws in the evening",
            "Rain turns a neon city street into a mirror of color as "
            "one umbrella crosses the frame",
            "A rooftop view sweeps over a waking city as the first "
            "buses roll through golden streets",
        ],
    },
    "people_daily_life": {
        "label": "People & Daily Life",
        "match": ["people", "daily life", "family", "life", "ghar",
                  "dost", "friends", "school", "everyday"],
        "ideas": [
            "A grandmother teaches her grandchild to roll dough in a "
            "sunny kitchen full of laughter",
            "School friends race out of the gates at the end of the "
            "day, bags bouncing, pure joy",
            "An old shopkeeper opens his tiny store at dawn, arranging "
            "everything with quiet pride",
        ],
    },
    "animals": {
        "label": "Animals",
        "match": ["animal", "animals", "cat", "dog", "horse", "bird",
                  "wildlife", "billi", "kutta", "ghora", "sher"],
        "ideas": [
            "A cheetah sprints across golden grassland, dust flying, in "
            "smooth slow motion",
            "A kitten chases a ball of yarn across a wooden floor and "
            "tumbles into a sunbeam",
            "A parrot spreads its rainbow wings and glides over a "
            "misty jungle river at dawn",
        ],
    },
    "food": {
        "label": "Food & Cooking",
        "match": ["food", "cooking", "khana", "chai", "biryani",
                  "kitchen", "chef", "eat"],
        "ideas": [
            "Steam rises from a fresh plate of biryani as a spoon lifts "
            "the first fragrant bite",
            "A street chef tosses vegetables in a flaming wok, sparks "
            "and sizzle in close-up",
            "Hot chai pours in a long stream into a clay cup, steam "
            "curling in the morning light",
        ],
    },
    "sports": {
        "label": "Sports & Action",
        "match": ["sports", "sport", "cricket", "football", "action",
                  "khel", "race", "match"],
        "ideas": [
            "A batsman launches a powerful six as the stadium crowd "
            "erupts under floodlights",
            "A swimmer dives into a blue pool in slow motion, water "
            "exploding around her",
            "Two friends race bicycles down a coastal road at sunset, "
            "laughing into the wind",
        ],
    },
    "vehicles": {
        "label": "Vehicles & Transport",
        "match": ["vehicle", "vehicles", "car", "train", "transport",
                  "gaari", "jahaz", "kashti", "bike"],
        "ideas": [
            "A red sports car speeds along a coastal highway as the "
            "sun sets over the sea",
            "A passenger train crosses a high bridge over a green "
            "valley, whistle echoing",
            "A wooden boat drifts through morning fog toward a "
            "lantern-lit harbor",
        ],
    },
    "space_scifi": {
        "label": "Space & Sci-Fi",
        "match": ["space", "sci-fi", "scifi", "astronaut", "rocket",
                  "moon", "chand", "robot", "future"],
        "ideas": [
            "An astronaut plants a glowing flag on the moon with "
            "Earth shining in the black sky",
            "A rocket lifts off at dawn, trailing fire and smoke over "
            "a silent desert",
            "A small robot wakes up alone in a futuristic city and "
            "looks at the stars",
        ],
    },
    "fantasy": {
        "label": "Fantasy & Magic",
        "match": ["fantasy", "magic", "jadoo", "dragon", "castle",
                  "wizard", "fairy", "pari"],
        "ideas": [
            "A dragon soars over a medieval castle at twilight, wings "
            "catching the last light",
            "A young wizard opens a glowing spell book and the forest "
            "lights up with fireflies",
            "A tiny fairy village glows inside a hollow tree as "
            "fireflies drift past",
        ],
    },
    "anime_cartoon": {
        "label": "Anime & Cartoon",
        "match": ["anime", "cartoon", "manga", "animation", "animated"],
        "ideas": [
            "An anime girl with a red scarf stands on a grassy hill as "
            "the wind lifts her hair",
            "A cartoon panda and a tiny robot build a toy rocket "
            "together in a sunny garden",
            "A cheerful cartoon train puffs through candy-colored hills "
            "full of waving animals",
        ],
    },
    "architecture": {
        "label": "Architecture & Places",
        "match": ["architecture", "building", "places", "masjid",
                  "mosque", "house", "makan", "bridge", "pul"],
        "ideas": [
            "A white marble mosque glows in morning light as birds "
            "circle its dome",
            "A modern glass skyscraper reflects a dramatic sunset "
            "while the city lights switch on",
            "An old stone bridge arches over a turquoise river between "
            "two sleepy villages",
        ],
    },
    "festivals_culture": {
        "label": "Festivals & Culture",
        "match": ["festival", "culture", "eid", "wedding", "shaadi",
                  "celebration", "diwali", "naach", "party"],
        "ideas": [
            "Families celebrate Eid in a courtyard glowing with lights, "
            "sweets and laughter",
            "A wedding procession dances through the street with "
            "drummers and falling flower petals",
            "Hundreds of lanterns rise into the night sky over a "
            "cheering festival crowd",
        ],
    },
    "business_tech": {
        "label": "Business & Technology",
        "match": ["business", "tech", "technology", "office", "daftar",
                  "startup", "kaam", "computer"],
        "ideas": [
            "A young engineer tests a robot arm in a bright modern "
            "laboratory",
            "A startup team celebrates around a glass table as their "
            "app launches on a big screen",
            "A craftsman guides a glowing laser cutter through metal "
            "in a high-tech workshop",
        ],
    },
    "abstract_art": {
        "label": "Abstract & Art",
        "match": ["abstract", "art", "rang", "colors", "surreal",
                  "paint", "ink", "dream"],
        "ideas": [
            "Colorful ink blooms and swirls in clear water in slow "
            "motion, forming flowers of color",
            "Golden particles gather into a glowing mandala that "
            "breathes in the darkness",
            "Ribbons of blue and purple light flow like silk over a "
            "black mirror floor",
        ],
    },
    # ---- genre buckets --------------------------------------------------
    "horror": {
        "label": "Horror",
        "match": ["horror", "scary", "haunted", "ghost", "bhoot", "dar",
                  "darawna", "fear", "creepy", "haunting"],
        "ideas": [
            "A lone traveler reaches an abandoned house at dusk — and "
            "one window is lit",
            "Footsteps echo down an empty hospital corridor as the "
            "lights flicker one by one",
            "A little girl's balloon drifts by itself toward the dark "
            "end of a silent street",
        ],
    },
    "comedy": {
        "label": "Comedy",
        "match": ["comedy", "funny", "hasna", "mazahiya", "joke",
                  "humorous", "hilarious", "mazak"],
        "ideas": [
            "A pompous cat tries to look majestic and slides off the "
            "sofa in slow disgrace",
            "A delivery rider races a mischievous pigeon that keeps "
            "stealing his route map",
            "A grandpa tries a VR headset for the first time and "
            "fights an imaginary dragon in the kitchen",
        ],
    },
    "adventure": {
        "label": "Adventure",
        "match": ["adventure", "quest", "journey", "safar", "explore",
                  "khoj", "expedition", "treasure"],
        "ideas": [
            "A young explorer finds a glowing map inside her "
            "grandfather's old trunk",
            "Two friends raft down a wild river toward a waterfall of "
            "mist and rainbows",
            "A lighthouse keeper rows out at dawn to a mysterious "
            "island that was not there yesterday",
        ],
    },
    "romance": {
        "label": "Romance",
        "match": ["romance", "romantic", "love", "mohabbat", "pyaar",
                  "ishq"],
        "ideas": [
            "Two strangers keep meeting at the same rainy bus stop "
            "until one day both bring umbrellas for each other",
            "A letter delivered fifty years late finally brings two "
            "old sweethearts to the same park bench",
            "A street musician plays one song every evening for the "
            "florist across the road",
        ],
    },
    "kids": {
        "label": "Kids & Family",
        "match": ["kids", "children", "bache", "bachon", "child",
                  "cute story", "bedtime"],
        "ideas": [
            "A baby elephant learns to trumpet and startles itself "
            "every single time",
            "A little star falls into a garden and a firefly helps it "
            "climb back to the sky",
            "A puppy and a duckling become best friends and share one "
            "very small umbrella",
        ],
    },
}


def _bucket_score(text: str, bucket: dict) -> int:
    norm = _norm(text)
    score = 0
    for word in bucket["match"]:
        w = _norm(word)
        if " " in w:
            if w in norm:
                score += len(w) + 2
        elif re.search(rf"\b{re.escape(w)}\b", norm):
            score += len(w)
    return score


def find_idea_bucket(text: str) -> dict | None:
    """The idea bucket whose match words best fit `text`, or None."""
    best: dict | None = None
    best_score = 0
    for bucket in IDEA_SEEDS.values():
        score = _bucket_score(text, bucket)
        if score > best_score:
            best, best_score = bucket, score
    return best if best_score > 0 else None


def random_idea_bucket() -> dict:
    return random.choice(list(IDEA_SEEDS.values()))


# ---------------------------------------------------------------------------
# Story templates — genre series outlines for the planner.
# Each has exactly 4 beats (Hook -> Problem -> Twist -> Payoff); {hero}
# is replaced with the series character / premise when a plan is built.
# ---------------------------------------------------------------------------
STORY_TEMPLATES: dict[str, dict] = {
    "adventure": {
        "label": "Adventure",
        "match": ["adventure", "quest", "journey", "safar", "explore",
                  "khoj", "expedition"],
        "beats": [
            "{hero} sets out at dawn with a hopeful heart, unaware of "
            "the adventure waiting ahead",
            "{hero} runs into a big problem that blocks the way — and "
            "help is nowhere in sight",
            "The twist: {hero} discovers the problem was hiding a "
            "secret ally and a hidden path all along",
            "{hero} reaches the goal as the sky turns gold, changed "
            "forever by the journey",
        ],
    },
    "horror": {
        "label": "Horror",
        "match": ["horror", "scary", "haunted", "ghost", "bhoot", "dar",
                  "darawna", "creepy"],
        "beats": [
            "{hero} arrives somewhere quiet — far too quiet — as the "
            "light begins to fade",
            "Strange sounds begin, and {hero} slowly realizes "
            "something here is very wrong",
            "The twist strikes: the danger was much closer to {hero} "
            "than anyone imagined",
            "At dawn {hero} escapes — but one chilling detail shows "
            "it is not truly over",
        ],
    },
    "comedy": {
        "label": "Comedy",
        "match": ["comedy", "funny", "hasna", "mazahiya", "joke",
                  "humorous", "hilarious"],
        "beats": [
            "{hero} starts an ordinary day full of confidence, with "
            "one tiny, foolproof plan",
            "Everything goes wrong for {hero} in the silliest way "
            "possible, one disaster after another",
            "The twist: the biggest mistake {hero} made accidentally "
            "fixes everyone else's problem",
            "{hero} celebrates the unlikely win, having learned "
            "absolutely nothing at all",
        ],
    },
    "kids": {
        "label": "Kids & Family",
        "match": ["kids", "children", "bache", "bachon", "child",
                  "bedtime", "cute"],
        "beats": [
            "{hero} finds something magical on an ordinary sunny "
            "morning",
            "{hero} tries to help a new friend — and makes a funny "
            "little mess instead",
            "The twist: the mess turns out to be exactly what the "
            "friend needed most",
            "{hero} and friends celebrate together under a rainbow "
            "sky, happy and safe",
        ],
    },
}

_BEAT_LABELS = ("Hook", "Problem", "Twist", "Payoff")


def beat_labels() -> tuple[str, ...]:
    return _BEAT_LABELS


def find_template(text: str) -> dict:
    """Closest genre template for `text`; adventure when unsure."""
    best: dict | None = None
    best_score = 0
    for template in STORY_TEMPLATES.values():
        score = 0
        norm = _norm(text)
        for word in template["match"]:
            w = _norm(word)
            if re.search(rf"\b{re.escape(w)}\b", norm):
                score += len(w)
        if score > best_score:
            best, best_score = template, score
    return best if best is not None else STORY_TEMPLATES["adventure"]
