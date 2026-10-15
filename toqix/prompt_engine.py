"""TOQIX prompt engine — TOQIX AI's own prompt layer.

Takes a short user prompt (English or Roman Urdu) plus style / aspect /
duration choices and expands it into a detailed, Wan-ready prompt:
subject + action + environment + camera movement + lighting + mood +
quality tokens, together with a matching negative prompt.

Fully deterministic (same input -> same output) and fully local:
dictionaries and templates only, no external calls of any kind.
"""

from __future__ import annotations

import hashlib
import re

from .curriculum import detect_domain, get_domain

# ---------------------------------------------------------------------------
# Roman Urdu -> English (light-touch, content words only)
# ---------------------------------------------------------------------------
# Pure glue words are dropped; content words are translated. Anything the
# dictionary does not know passes through unchanged, so a mixed prompt
# still produces a sensible result.
_URDU_DROP = {
    "hai", "hain", "ka", "ki", "ke", "ko", "mein", "mai", "se", "par",
    "aur", "bhi", "tha", "thi", "ho", "raha", "rahi", "rahe", "ek",
    "yeh", "woh", "kya", "kab", "mera", "meri", "uska", "uski", "apna",
    "apni", "ne", "toh", "bana", "banao", "kar", "raha",
}

_URDU_WORDS = {
    # people
    "ladka": "young man", "ladki": "young woman", "bacha": "child",
    "bachi": "young girl", "aadmi": "man", "aurat": "woman",
    "buddha": "old man", "dost": "friend",
    # animals
    "billi": "cat", "kutta": "dog", "ghora": "horse", "hathi": "elephant",
    "sher": "lion", "cheeta": "cheetah", "bandar": "monkey",
    "parinda": "bird", "chiriya": "sparrow", "machhli": "fish",
    "titli": "butterfly", "kacchua": "turtle", "bhalu": "bear",
    # places / nature
    "pahad": "mountain", "pahar": "mountain", "pahadon": "mountains", "samandar": "ocean",
    "darya": "river", "jheel": "lake", "jangal": "forest",
    "registan": "desert", "gaon": "village", "sheher": "city",
    "ghar": "house", "makan": "building", "pul": "bridge",
    "aasman": "sky", "badal": "clouds", "chand": "moon",
    "suraj": "sun", "taare": "stars", "barish": "rain",
    "barf": "snow", "hawa": "wind", "zameen": "ground",
    "kheet": "field", "bagh": "garden", "phool": "flowers",
    "ped": "tree", "darakht": "tree",
    # objects / vehicles
    "gaari": "car", "gadi": "car", "bus": "bus", "truck": "truck",
    "jahaz": "airplane", "kashti": "boat", "rocket": "rocket",
    "cycle": "bicycle", "ghari": "clock",
    # actions
    "bhaag": "running", "daud": "running", "chal": "walking",
    "naach": "dancing", "nach": "dancing", "gaa": "singing",
    "ro": "crying", "hans": "laughing", "so": "sleeping",
    "tair": "swimming", "ud": "flying", "khel": "playing",
    "kha": "eating", "pee": "drinking", "lad": "fighting",
    "doob": "setting", "doobta": "setting", "doobti": "setting",
    "ubhar": "rising", "ubharta": "rising", "ubharti": "rising",
    "ugta": "rising", "ugti": "rising",
    "nikal": "rising", "nikalta": "rising", "nikalti": "rising",
    # qualities / time
    "sundar": "beautiful", "khubsurat": "beautiful", "bara": "big",
    "chota": "small", "tez": "fast", "dheere": "slow", "naya": "new",
    "purana": "old", "subah": "morning", "shaam": "evening",
    "ghuroob": "sunset", "tulu": "sunrise", "tuloo": "sunrise",
    "maghrib": "dusk",
    "raat": "night", "din": "day", "laal": "red", "neela": "blue",
    "hara": "green", "peela": "yellow", "kala": "black",
    "safed": "white",
}


def _urdu_score(text: str) -> int:
    words = re.findall(r"[a-z]+", text.lower())
    known = sum(1 for w in words if w in _URDU_WORDS or w in _URDU_DROP)
    return known


def translate_roman_urdu(text: str) -> str:
    """Translate known Roman Urdu words; drop glue words; pass the rest
    through untouched. Returns (translated_text)."""
    out: list[str] = []
    for token in re.findall(r"[A-Za-z]+|[^A-Za-z]+", text):
        low = token.lower()
        if low in _URDU_DROP and token.isalpha():
            continue
        if low in _URDU_WORDS and token.isalpha():
            out.append(_URDU_WORDS[low])
        else:
            out.append(token)
    joined = "".join(out)
    return re.sub(r"\s+", " ", joined).strip(" ,") or text.strip()


# ---------------------------------------------------------------------------
# Style presets
# ---------------------------------------------------------------------------
STYLE_PRESETS: dict[str, dict] = {
    "cinematic": {
        "label": "Cinematic Film",
        "tokens": "cinematic film still, anamorphic lens, shallow depth of field, "
                  "dramatic composition, film grain, teal and orange grade",
        "lighting": "cinematic three-point lighting",
    },
    "photorealistic": {
        "label": "Photorealistic",
        "tokens": "photorealistic, ultra detailed skin and textures, shot on a "
                  "35mm camera, natural proportions, lifelike motion",
        "lighting": "natural realistic lighting",
    },
    "anime": {
        "label": "Anime",
        "tokens": "studio anime style, cel shaded, vibrant colors, clean line art, "
                  "expressive characters, sakuga-quality fluid animation",
        "lighting": "bright stylized anime lighting",
    },
    "3d_animation": {
        "label": "3D Animation",
        "tokens": "high-end 3D animated film style, soft subsurface scattering, "
                  "appealing character design, richly detailed sets, global illumination",
        "lighting": "warm studio-quality 3D lighting",
    },
    "vintage_film": {
        "label": "Vintage Film",
        "tokens": "vintage 1970s film footage, warm faded colors, visible film grain, "
                  "slight vignette, nostalgic documentary feel",
        "lighting": "soft period lighting",
    },
    "cyberpunk": {
        "label": "Neon Cyberpunk",
        "tokens": "cyberpunk aesthetic, neon signs, wet reflective streets, "
                  "holographic glow, high contrast night city",
        "lighting": "neon-lit night lighting with volumetric haze",
    },
    "nature_doc": {
        "label": "Nature Documentary",
        "tokens": "BBC-quality nature documentary footage, telephoto lens detail, "
                  "true-to-life animal behaviour, pristine wilderness",
        "lighting": "natural outdoor light",
    },
}
DEFAULT_STYLE = "cinematic"

# ---------------------------------------------------------------------------
# Scene intelligence: keyword-triggered camera / lighting / mood
# ---------------------------------------------------------------------------
_CAMERA_RULES: list[tuple[tuple[str, ...], str]] = [
    (("close", "face", "portrait", "eyes"), "slow push-in close-up shot"),
    (("fly", "flying", "sky", "aerial", "drone"), "sweeping aerial drone shot"),
    (("run", "running", "chase", "race", "fast"), "dynamic tracking shot following the action"),
    (("walk", "walking", "street", "stroll"), "smooth steadicam shot following alongside"),
    (("car", "drive", "driving", "road", "bike", "motorcycle"), "low tracking shot moving with the vehicle"),
    (("ocean", "sea", "beach", "wave", "water", "river", "lake"), "slow cinematic pan across the water"),
    (("dance", "dancing", "party", "music"), "orbiting camera shot circling the subject"),
    (("city", "building", "skyline", "traffic"), "slow crane shot rising over the scene"),
    (("space", "rocket", "moon", "planet", "star"), "slow majestic dolly shot through the scene"),
]

_CAMERA_FALLBACKS = [
    "slow cinematic dolly-in shot",
    "smooth slow-motion tracking shot",
    "gentle steadicam shot with subtle movement",
    "slow crane shot revealing the scene",
]

_LIGHTING_RULES: list[tuple[tuple[str, ...], str]] = [
    (("night", "midnight", "dark"), "moody moonlight with deep shadows"),
    (("sunset", "evening", "dusk", "golden"), "warm golden-hour sunlight"),
    (("sunrise", "dawn", "morning"), "soft fresh morning light"),
    (("rain", "storm", "monsoon"), "overcast stormy light with wet reflections"),
    (("snow", "winter", "frozen"), "crisp cold winter daylight"),
    (("neon", "cyberpunk", "club"), "vibrant neon lighting"),
    (("candle", "fire", "campfire", "lantern"), "warm flickering firelight"),
]

_MOOD_RULES: list[tuple[tuple[str, ...], str]] = [
    (("happy", "joy", "celebrat", "fun", "smile", "laugh"), "joyful, uplifting mood"),
    (("sad", "lonely", "cry", "alone", "miss"), "melancholic, emotional mood"),
    (("scary", "horror", "ghost", "fear", "haunted"), "tense, eerie mood"),
    (("romantic", "love", "wedding", "couple"), "tender romantic mood"),
    (("epic", "battle", "war", "hero", "fight"), "epic, heroic mood"),
    (("peaceful", "calm", "relax", "meditat", "serene"), "peaceful, serene mood"),
]

_BASE_NEGATIVE = (
    "low quality, worst quality, blurry, out of focus, distorted, deformed, "
    "disfigured, extra limbs, extra fingers, missing limbs, morphing, "
    "flickering, jittery motion, static frame, frozen motion, watermark, "
    "logo, text, subtitles, cartoonish proportions (unless requested), "
    "oversaturated, noisy, grainy artifacts, duplicate subjects"
)


def _pick(seq: list[str], seed_text: str) -> str:
    digest = hashlib.md5(seed_text.encode("utf-8")).digest()
    return seq[digest[0] % len(seq)]


def _match_rules(rules, text: str):
    for keywords, value in rules:
        if any(k in text for k in keywords):
            return value
    return None


# ---------------------------------------------------------------------------
# Accuracy layer (v2) — the flag lesson. Small video models garble things
# that have ONE correct real-world form: national flags, emblems, written
# text. When a prompt touches one, spell the correct form out element by
# element inside the prompt itself; it measurably raises the hit rate, and
# the QA gate (frame-check, regenerate-once) catches the rest.
# ---------------------------------------------------------------------------

_FLAG_DESIGNS = [
    (("pakistan",), "the flag of Pakistan, shown accurately: a dark green flag with a white vertical stripe along the hoist side and a large white crescent moon and white five-pointed star centered in the green field, correct colors, correct design"),
    (("india", "indian", "tiranga"), "the flag of India, shown accurately: three horizontal bands of deep saffron orange on top, white in the middle and green at the bottom, with a navy-blue 24-spoke Ashoka Chakra wheel in the center of the white band, correct colors, correct design"),
    (("america", "american", "usa", "united states"), "the flag of the United States, shown accurately: thirteen horizontal red and white stripes with a blue canton in the top-left corner containing white stars, correct colors, correct design"),
    (("britain", "british", "uk", "united kingdom", "union jack"), "the Union Jack flag of the United Kingdom, shown accurately: a blue field with red and white diagonal and straight crosses combined, correct colors, correct design"),
    (("japan", "japanese"), "the flag of Japan, shown accurately: a plain white flag with one solid red circle exactly in the center, correct colors, correct design"),
    (("china", "chinese"), "the flag of China, shown accurately: a solid red flag with five golden-yellow stars in the top-left corner, one large star and four smaller stars, correct colors, correct design"),
    (("turkey", "turkish"), "the flag of Turkey, shown accurately: a solid red flag with a white crescent moon and a white five-pointed star, correct colors, correct design"),
    (("saudi",), "the flag of Saudi Arabia, shown accurately: a solid green flag with white Arabic calligraphy above a white horizontal sword, correct colors, correct design"),
    (("uae", "emirates", "dubai"), "the flag of the United Arab Emirates, shown accurately: three horizontal bands of green, white and black with a red vertical band at the hoist side, correct colors, correct design"),
    (("canada", "canadian"), "the flag of Canada, shown accurately: a white flag with red vertical bars on both sides and one red maple leaf exactly in the center, correct colors, correct design"),
    (("france", "french"), "the flag of France, shown accurately: three equal vertical bands of blue, white and red, correct colors, correct design"),
    (("germany", "german"), "the flag of Germany, shown accurately: three equal horizontal bands of black, red and gold-yellow, correct colors, correct design"),
    (("italy", "italian"), "the flag of Italy, shown accurately: three equal vertical bands of green, white and red, correct colors, correct design"),
    (("brazil", "brazilian"), "the flag of Brazil, shown accurately: a green flag with a large yellow diamond in the center holding a blue globe with white stars and a white banner, correct colors, correct design"),
    (("australia", "australian"), "the flag of Australia, shown accurately: a dark blue flag with the Union Jack in the top-left corner and white stars including one large seven-pointed star, correct colors, correct design"),
    (("palestine", "palestinian"), "the flag of Palestine, shown accurately: three horizontal bands of black, white and green with a red triangle at the hoist side, correct colors, correct design"),
    (("bangladesh",), "the flag of Bangladesh, shown accurately: a green flag with one large red circle slightly left of center, correct colors, correct design"),
]

_TEXT_KEYWORDS = (
    "text", "written", "writing", "words that say", "sign that says",
    "signboard", "logo", "caption", "title card", "likha", "likho",
)

_SUBJECT_KEYWORDS = (
    "panda", "robot", "cat", "dog", "elephant", "lion", "tiger", "fox",
    "owl", "penguin", "whale", "horse", "astronaut", "boy", "girl",
    "man", "woman", "baby", "child", "billi", "kutta", "haathi",
)


def _detail_clauses(low: str) -> tuple[list[str], bool]:
    """Element-by-element accuracy clauses for a lowercased prompt.

    Returns (clauses, wants_text): clauses are appended to the visual
    prompt; wants_text means the negative prompt must stop banning
    text/logos because the user actually asked for them."""
    clauses: list[str] = []
    if "flag" in low or "jhanda" in low or "parcham" in low:
        design = _match_rules(_FLAG_DESIGNS, low)
        if design:
            clauses.append(design)
        else:
            clauses.append(
                "the flag shown clearly, waving naturally, with its "
                "correct real-world colors and design"
            )
    wants_text = any(k in low for k in _TEXT_KEYWORDS)
    if wants_text:
        clauses.append(
            "any text or lettering shown is crisp, correctly spelled, "
            "fully legible and exactly as requested"
        )
    subject = _match_rules(
        [( (k,), k) for k in _SUBJECT_KEYWORDS], low
    )
    if subject:
        clauses.append(
            f"one single {subject} as the main subject, identical "
            "appearance, colors and proportions in every frame"
        )
    return clauses, wants_text


def enhance_prompt(
    user_prompt: str,
    style: str = DEFAULT_STYLE,
    aspect: str = "16:9",
    duration: float = 3,
    domain_id: str | None = None,
    kind: str = "video",
) -> dict:
    """Expand a short user prompt into a Wan-ready prompt + negative prompt.

    The all-in-one curriculum (data/curriculum/domains.json) drives domain
    detection and template choice: a detected (or explicitly chosen) domain
    contributes its default camera/lighting and its extra tokens.

    Returns a dict with: original, translated, enhanced_prompt,
    negative_prompt, camera, lighting, mood, style, domain.
    """
    original = (user_prompt or "").strip()
    if not original:
        raise ValueError("prompt must not be empty")

    # If the text leans Roman Urdu, translate content words first.
    translated = translate_roman_urdu(original) if _urdu_score(original) >= 2 else original
    low = translated.lower()

    domain = get_domain(domain_id) or detect_domain(f"{translated} {original}")

    preset = STYLE_PRESETS.get(style, STYLE_PRESETS[DEFAULT_STYLE])
    camera = (
        _match_rules(_CAMERA_RULES, low)
        or (domain or {}).get("camera_default")
        or _pick(_CAMERA_FALLBACKS, original)
    )
    lighting = (
        _match_rules(_LIGHTING_RULES, low)
        or (domain or {}).get("lighting_default")
        or preset["lighting"]
    )
    mood = _match_rules(_MOOD_RULES, low)

    subject = translated.rstrip(".")

    if kind == "audio":
        # Audio jobs get a simple production template, no visual tokens.
        return {
            "original": original,
            "translated": translated,
            "enhanced_prompt": (
                f"High-quality audio recording: {subject}. "
                "Clear, professionally produced, well-mixed, "
                "no background noise."
            ),
            "negative_prompt": (
                "low quality, distortion, clipping, background noise, "
                "hiss, hum, muffled, echo"
            ),
            "camera": "",
            "lighting": "",
            "mood": mood or "",
            "style": style,
            "domain": domain["id"] if domain else "",
            "kind": kind,
        }

    parts = [
        subject,
        camera,
        lighting,
    ]
    if mood:
        parts.append(mood)
    parts.append(preset["tokens"])
    if domain:
        parts.append(domain["extra_tokens"])
    detail_clauses, wants_text = _detail_clauses(low)
    parts.extend(detail_clauses)
    if kind == "image":
        # Still image: no motion language.
        parts.append("high quality, sharp details, crisp focus, rich detail")
    else:
        parts.append(
            "high quality, sharp details, smooth continuous motion, "
            "consistent subject across frames, physically plausible movement"
        )
    if aspect == "9:16":
        parts.append("vertical composition")
    elif aspect == "1:1":
        parts.append("centered square composition")

    enhanced = ", ".join(p.strip().rstrip(",") for p in parts if p)
    enhanced = enhanced[0].upper() + enhanced[1:] + "."

    negative = _BASE_NEGATIVE
    if wants_text:
        # The user asked FOR text/a logo: stop banning what was requested.
        negative = negative.replace("watermark, logo, text, ", "")
    if style == "photorealistic":
        negative += ", cartoon, anime, CGI look, plastic skin"
    elif style == "anime":
        negative += ", photorealistic, 3d render, live action"

    return {
        "original": original,
        "translated": translated,
        "enhanced_prompt": enhanced,
        "negative_prompt": negative,
        "detail_notes": detail_clauses,
        "camera": camera,
        "lighting": lighting,
        "mood": mood or "",
        "style": style,
        "domain": domain["id"] if domain else "",
        "kind": kind,
    }
