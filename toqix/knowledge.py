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
]


# ---------------------------------------------------------------------------
# Lookup — keyword scoring (word-boundary for single words, substring for
# phrases), so "cyberpunk" hits the cyberpunk entry but "cat" never fires
# inside "cathedral".
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def score_entry(text: str, entry: dict) -> tuple[int, int]:
    """(score, matched_chars) of `entry` against raw user text.

    Score weights longer keywords more (specific beats generic); the
    matched_chars total lets callers judge whether the message is
    *mostly* about this one topic.
    """
    norm = _norm(text)
    score = 0
    matched = 0
    for kw in entry["keywords"]:
        k = _norm(kw)
        if not k:
            continue
        if " " in k or "-" in k:
            hit = k in norm
        else:
            hit = re.search(rf"\b{re.escape(k)}\b", norm) is not None
        if hit:
            score += len(k) + (2 if " " in k else 0)
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
