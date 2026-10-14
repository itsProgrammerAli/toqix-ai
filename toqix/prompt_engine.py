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
    if style == "photorealistic":
        negative += ", cartoon, anime, CGI look, plastic skin"
    elif style == "anime":
        negative += ", photorealistic, 3d render, live action"

    return {
        "original": original,
        "translated": translated,
        "enhanced_prompt": enhanced,
        "negative_prompt": negative,
        "camera": camera,
        "lighting": lighting,
        "mood": mood or "",
        "style": style,
        "domain": domain["id"] if domain else "",
        "kind": kind,
    }
