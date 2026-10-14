"""TOQIX story engine — real written stories, procedurally assembled.

The series *planner* (agent.py + knowledge.py) produces an OUTLINE —
four beats with the premise pasted into each. That is a plan, not a
story, and users said so. This module is the answer: when someone
asks the agent to WRITE A STORY, this engine assembles an actual
readable short story — a named hero, scenes, dialogue, a setback, a
twist, a climax and an ending — from rich authored fragment
libraries, one per genre.

No LLM, no network, no external APIs (same product constraint as the
rest of TOQIX). The quality lives in the authored fragments: each
genre carries dozens of hand-written prose pieces — openings,
settings, side characters, incidents, attempts, obstacles, dialogue
exchanges, twists, realisations, climaxes, endings — woven together
with slots ({hero}, {name}, {friend}, {place}, {object}).

Guarantees the caller relies on:
  * deterministic for a given seed (random.Random(seed)) — a
    project seed always yields the same story;
  * the raw premise is never pasted into the prose (only the parsed
    hero descriptor is used, which is legitimate narration);
  * no fragment repeats inside one story;
  * assemble() also returns 4 visual `scenes` — one per video part —
    so the story can become a consistent video series.
"""

from __future__ import annotations

import random
import re

# ---------------------------------------------------------------------------
# Hero parsing — turn a loose premise into (name, descriptor, anchor)
# ---------------------------------------------------------------------------
# kind word (EN + Roman Urdu) -> (English noun, name bank key)
_KIND_WORDS: list[tuple[tuple[str, ...], str, str]] = [
    (("astronaut", "spaceman", "cosmonaut"), "astronaut", "astronaut"),
    (("robot", "android", "bot"), "robot", "robot"),
    (("dragon",), "dragon", "dragon"),
    (("fox", "lomri"), "fox", "fox"),
    (("cat", "billi", "kitten", "kitty"), "cat", "cat"),
    (("dog", "kutta", "puppy"), "dog", "dog"),
    (("panda",), "panda", "creature"),
    (("rabbit", "khargosh", "bunny"), "rabbit", "creature"),
    (("bear", "bhalu"), "bear", "creature"),
    (("owl", "ullu"), "owl", "creature"),
    (("elephant", "hathi"), "elephant", "creature"),
    (("lion", "sher"), "lion", "creature"),
    (("tiger",), "tiger", "creature"),
    (("monkey", "bandar"), "monkey", "creature"),
    (("bird", "parinda", "chiriya"), "bird", "creature"),
    (("mouse", "chuha"), "mouse", "creature"),
    (("wolf", "bheriya"), "wolf", "creature"),
    (("frog", "mendak"), "frog", "creature"),
    (("duck", "batakh"), "duck", "creature"),
    (("penguin",), "penguin", "creature"),
    (("horse", "ghora"), "horse", "creature"),
    (("fish", "machli"), "fish", "creature"),
    (("turtle", "kachua"), "turtle", "creature"),
    (("deer", "hiran"), "deer", "creature"),
    (("wizard",), "wizard", "human"),
    (("witch",), "witch", "human"),
    (("princess",), "princess", "girl"),
    (("prince",), "prince", "boy"),
    (("knight",), "knight", "human"),
    (("pirate",), "pirate", "human"),
    (("fairy", "pari"), "fairy", "girl"),
    (("ghost", "bhoot"), "ghost", "creature"),
    (("alien",), "alien", "creature"),
    (("dinosaur", "dino"), "dinosaur", "creature"),
    (("grandmother", "dadi", "nani"), "grandmother", "human"),
    (("grandfather", "dada", "nana"), "grandfather", "human"),
    (("girl", "larki"), "girl", "girl"),
    (("boy", "larka"), "boy", "boy"),
]

_NAME_BANKS: dict[str, list[str]] = {
    "robot": ["Bolt", "Pip", "Nutty", "Cog", "Beep", "Rivet"],
    "cat": ["Milo", "Whiskers", "Moti", "Luna", "Simba", "Mittens"],
    "dog": ["Bruno", "Rocky", "Sheru", "Biscuit", "Rusty", "Peppy"],
    "fox": ["Rusty", "Fenn", "Amber", "Zorro", "Sorrel"],
    "dragon": ["Ember", "Sparky", "Pyro", "Dara", "Ash"],
    "astronaut": ["Zara", "Neil", "Tara", "Asim", "Nova"],
    "girl": ["Zara", "Aisha", "Maya", "Noor", "Hira", "Layla"],
    "boy": ["Ali", "Arham", "Bilal", "Daniyal", "Sami", "Omar"],
    "human": ["Zara", "Ali", "Maya", "Omar", "Tara", "Rafi", "Noor"],
    "creature": ["Pip", "Momo", "Kiki", "Toto", "Nori", "Bibo"],
}

# Adjectives that may sit in front of the hero noun (EN + Roman Urdu
# mapped to their English sense). At most two are kept.
_ADJ_MAP: dict[str, str] = {
    "little": "little", "small": "small", "tiny": "tiny",
    "big": "big", "brave": "brave", "young": "young", "old": "old",
    "clever": "clever", "kind": "kind", "shy": "shy",
    "timid": "timid", "lost": "lost", "lonely": "lonely",
    "curious": "curious", "gentle": "gentle", "wise": "wise",
    "merry": "merry", "sleepy": "sleepy", "hungry": "hungry",
    "quiet": "quiet", "swift": "swift", "chubby": "chubby",
    "magical": "magical", "golden": "golden", "silver": "silver",
    "darpok": "timid", "chhota": "little", "choti": "little",
    "bahadur": "brave", "akela": "lonely", "akeli": "lonely",
    "pyara": "sweet", "pyari": "sweet", "budha": "old",
    "budhi": "old", "jawan": "young",
}

_PLACE_WORDS = {
    "house", "castle", "palace", "forest", "jungle", "village",
    "town", "city", "school", "island", "cave", "mountain", "tower",
    "ship", "garden", "library", "lighthouse", "bakery", "farm",
    "desert", "lake", "bridge", "market", "valley", "hill", "hut",
    "cottage", "mill", "harbour", "harbor", "station", "museum",
}

_NOT_NAMES = {
    "the", "one", "my", "his", "her", "their", "our", "this",
    "that", "when", "then", "once", "very", "little", "small",
}


def _explicit_name(original: str) -> str | None:
    """A name the user actually gave: 'story about Zara',
    'Zara the astronaut', 'named Pip'."""
    m = re.search(r"\bnamed\s+([A-Z][a-z]{1,20})\b", original)
    if m:
        return m.group(1)
    m = re.search(r"\babout\s+([A-Z][a-z]{1,20})\b", original)
    if m and m.group(1).lower() not in _NOT_NAMES:
        return m.group(1)
    m = re.search(r"\b([A-Z][a-z]{1,20})\s+the\s+", original)
    if m and m.group(1).lower() not in _NOT_NAMES:
        return m.group(1)
    bare = original.strip().rstrip(".")
    if re.fullmatch(r"[A-Z][a-z]{1,20}", bare) \
            and bare.lower() not in _NOT_NAMES:
        return bare
    return None


def parse_hero(premise: str, rng: random.Random) -> dict:
    """Extract the hero from a premise.

    Returns {name, descriptor, anchor, setting_hint}. `descriptor`
    is the narrative form ("the little robot"); `anchor` adds the
    role clause when the premise carries one ("the little robot who
    delivers letters") — that is what a series bible stores. When
    the premise names a PLACE instead of a creature ("an old
    house"), a traveller hero is introduced and the place becomes
    the story's setting.
    """
    original = " ".join((premise or "").split()).rstrip(".")
    low = original.lower()
    toks = re.findall(r"[a-z']+", low)
    name = _explicit_name(original)

    noun = bank_key = noun_idx = None
    for words, en_noun, bank in _KIND_WORDS:
        for word in words:
            if word in toks:
                noun, bank_key = en_noun, bank
                noun_idx = toks.index(word)
                break
        if noun:
            break

    setting_hint = ""
    if noun is None:
        # Place premise -> traveller hero, place becomes the setting.
        for i, tok in enumerate(toks):
            if tok in _PLACE_WORDS:
                adjs: list[str] = []
                for t in toks[max(0, i - 2):i]:
                    if t in _ADJ_MAP and _ADJ_MAP[t] not in adjs:
                        adjs.append(_ADJ_MAP[t])
                setting_hint = "the " + " ".join(adjs + [tok])
                break
        noun, bank_key = "traveller", "human"
        descriptor = "the young traveller"
        anchor = descriptor
    else:
        adjs = []
        for t in toks[max(0, noun_idx - 3):noun_idx]:
            mapped = _ADJ_MAP.get(t)
            if mapped and mapped not in adjs:
                adjs.append(mapped)
        descriptor = "the " + " ".join(adjs[:2] + [noun])
        anchor = descriptor
        role_at = low.find(" who ")
        if role_at != -1:
            role = original[role_at:].split(",")[0].strip()
            if 0 < len(role) <= 60:
                anchor = f"{descriptor} {role}"

    if not name:
        name = rng.choice(_NAME_BANKS[bank_key])
    return {
        "name": name,
        "descriptor": descriptor,
        "anchor": anchor,
        "setting_hint": setting_hint,
    }


# ---------------------------------------------------------------------------
# Genre detection
# ---------------------------------------------------------------------------
_GENRE_WORDS: list[tuple[str, tuple[str, ...]]] = [
    ("horror", ("horror", "haunted", "ghost", "scary", "creepy",
                "bhoot", "dar", "darpok", "darawna", "haunting",
                "spooky", "eerie", "witch", "graveyard", "phantom")),
    ("comedy", ("comedy", "funny", "hilarious", "silly", "joke",
                "hasna", "mazahiya", "laugh", "laughter", "giggle")),
    ("sci_fi", ("sci fi", "science fiction", "space", "astronaut",
                "alien", "spaceship", "rocket", "planet", "mars",
                "galaxy", "starship", "moon base", "android",
                "futuristic", "orbit", "nebula")),
    ("kids", ("kids", "children", "bedtime", "cute", "baby",
              "bache", "bachon", "for kids", "little ones",
              "storybook")),
]


def detect_genre(text: str) -> str:
    """Best genre key for a premise; adventure when nothing bites.
    Ties break in list order (horror before comedy before sci-fi)."""
    norm = " " + re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()) + " "
    best_key, best_score = "adventure", 0
    for key, words in _GENRE_WORDS:
        score = 0
        for w in words:
            if f" {w} " in norm or norm.strip().startswith(w):
                score += len(w)
        if score > best_score:
            best_key, best_score = key, score
    return best_key


# ---------------------------------------------------------------------------
# Fragment libraries. Slots: {name} {hero} {friend} {place} {object}
# ({object} is the long phrase, {object_short} the bare noun form).
# Dialogue entries are (first line, reply) — both carry attribution.
# ---------------------------------------------------------------------------
GENRES: dict[str, dict] = {}

GENRES["adventure"] = {
    "label": "Adventure",
    "places": [
        "the village of Bramblewick",
        "the Whispering Forest",
        "the harbour town of Saltmarsh",
        "the valley of the Singing River",
        "the mountain pass of Kargil Heights",
        "the old city of Lantern Rows",
    ],
    "objects": [
        ("brass key", "an old brass key, warm to the touch and humming faintly"),
        ("silver map", "a silver map whose roads redraw themselves at dawn"),
        ("glass lantern", "a glass lantern that burns with blue, steady light"),
        ("wooden flute", "a wooden flute that plays one note all by itself"),
        ("striped scarf", "a striped scarf that always points toward home"),
        ("copper compass", "a copper compass whose needle follows wishes, not north"),
    ],
    "openings": [
        "In {place}, where the mornings smelled of rain and warm bread, there lived {hero} named {name}. {name} was not the biggest or the strongest, but nobody in {place} had a kinder heart — or a worse sense of when to stay safely at home.",
        "{name} was {hero} of {place}, and {name} had one famous habit: saying yes. Yes to every errand, yes to every lost traveller, yes to every door that had never been opened. It was a wonderful habit. It was also how all the trouble started.",
        "Long before the sun climbed over {place}, {hero} named {name} was already awake, polishing the day like a coin. {name} liked plans, warm breakfasts, and the feeling that today — today for certain — something extraordinary would happen.",
        "Everyone in {place} knew {hero} named {name}. They knew the laugh, the wave, the way {name} stopped to help absolutely anybody. What nobody knew was that {name} kept one small, burning wish folded away, the way you keep a letter you are afraid to open.",
        "The day our story begins, {place} was holding its breath. The flags hung still, the river ran quiet, and {hero} named {name} stood at the window with a strange feeling — the feeling that the world had just decided something, and forgotten to tell anyone.",
        "{name}, {hero} of {place}, could fix almost anything: a broken cart, a leaking roof, a quarrel between two stubborn goats. There was only one thing {name} had never managed to fix, and it was the thing {name} wanted most in the world.",
    ],
    "settings": [
        "Beyond the last house, the road bent toward the hills and did not look back, and the grass on either side stood tall enough to hide secrets.",
        "The light that morning was the colour of honey, and every rooftop wore a thin hat of mist that melted as you watched.",
        "From the high path you could see the whole of it — the river shining like a ribbon, the fields patched green and gold, and a road that promised more than it should.",
        "It was the kind of place where every gate creaked a greeting and every window seemed to be listening.",
        "Far off, the mountains kept their snowy counsel, and nearer, the trees leaned together as if they were sharing the same old joke.",
        "The air smelled of woodsmoke and coming rain, and somewhere a bell was counting the hours very slowly, as bells do when something is about to change.",
    ],
    "friends": [
        "Old Marta, the map-keeper with ink-stained fingers",
        "Captain Bruno, a retired sailor with a telescope for an eye",
        "Sister Wren, the bell-ringer of the little chapel",
        "Master Fenwick, the clockmaker who never, ever hurried",
        "Granny Sable, who baked pies for the whole lane",
        "Tomas the ferryman, who knew every bend of the river",
    ],
    "incidents": [
        "Then, before breakfast was even finished, it happened: a breathless messenger arrived with news that made the whole room go quiet. The old road — the only road — had been claimed by trouble, and someone small and brave would have to go. Every eye in the room turned, slowly, to {name}.",
        "It began with a sound nobody could explain: three slow knocks from inside the hill, and then a silence so complete that even the birds stopped. {name} pressed an ear to the ground, and heard, very faintly, the hill knock back.",
        "That afternoon, a stranger's parcel arrived for {name} with no name on it, no string, and no explanation — only {object}, wrapped in cloth that smelled of faraway rain. Tucked beneath it was a note of four words: YOU ARE THE ONE.",
        "The trouble announced itself politely, the way big trouble often does. The river had changed its mind in the night and now ran the wrong way, uphill, carrying boats and bewildered fish toward the mountains — and the oldest law of {place} said only a volunteer could set it right.",
        "At noon the great bell of {place} rang by itself — once, twice, and then a third time, though no hand was on the rope. Everyone knew what the third ring meant, even if nobody liked to say it: the old promise had come due, and it was {name} everyone looked at.",
        "It started, as the best adventures do, with something lost. The dawn itself failed to arrive. The sky stayed the colour of deep water, the roosters were furious, and in the puzzled dark, {name} understood that somebody would have to go and fetch the morning back.",
    ],
    "attempts": [
        "{name} packed a small bag — bread, rope, courage, in that order — and set out before anyone could argue. The first stretch was almost easy, and {name} walked it whistling, which is precisely when a journey likes to test you.",
        "First, {name} tried the sensible way. Sensible questions were asked, sensible maps were unfolded, sensible boots were tied twice. The sensible way got {name} exactly as far as the edge of the unknown, and not one step further.",
        "There was no time to waste, so {name} went straight at the problem the way you dive into cold water — all at once, and slightly out of breath. Halfway in, with the way already growing steep and strange, {name} stopped to ask for directions.",
        "{name} began the way all heroes secretly begin: by pretending to know exactly what they were doing. Shoulders back. Chin up. Map upside down. It took the whole first hour to admit the truth, and the admission, strangely, made everything easier.",
        "With the whole of {place} watching from the gate, {name} took the old path and did not look back — looking back was for later, when there was something worth looking back at. The first real test arrived sooner than expected.",
        "{name} tried the front way first, boldly, and then the side way, carefully, and was just inventing a third way when help of an unexpected sort appeared at the turning of the path.",
    ],
    "obstacles": [
        "Then the way itself turned against {name}. The path that had been there for a hundred years simply... ended, at a wall of thorns taller than a house, humming with bees and old enchantment. Going back was impossible. Going forward was worse. And the light was already failing.",
        "The setback, when it came, came quietly. The bridge was gone — not broken, gone, as if it had only ever been an idea — and the river below ran fast, black and very sure of itself. {name} sat down hard on the far bank of everything planned.",
        "Halfway there, the weather changed its mind. Wind first, then rain like thrown gravel, then a fog so thick that {name} could not see a hand held out at arm's length. Somewhere in that whiteness, something large began to move alongside, keeping perfect pace.",
        "It was the lock that stopped {name} — a door of black oak in the middle of nowhere, with no house around it, no wall, nothing but the door and its enormous iron lock, and a feeling that whatever it guarded had been waiting a very long time for somebody to fail at opening it.",
        "Disaster arrived wearing a small disguise: everything {name} carried was lost in one careless moment — bag, map, and provisions gone down the ravine in a clatter of tin and feathers. Now there was nothing left to rely on but wits, stubbornness, and whatever the road provided.",
        "The hardest part was not the climb or the cold. It was the voice of doubt that arrived at dusk, reasonable and soft, listing all the sensible reasons to turn around — and for one long minute, sitting alone in the gathering dark, {name} believed every word of it.",
    ],
    "dialogues": [
        ('"You are really going through with this?" asked {friend}, studying {name} over the rims of very serious spectacles.',
         '"Somebody has to," said {name}. "And everybody else was looking at the floor."'),
        ('"Turn back while you can," said {friend}, not unkindly. "The road has eaten better heroes than you."',
         '"Then it is lucky," said {name}, shouldering the pack, "that I am not trying to be a better hero. Just a punctual one."'),
        ('"What you are looking for is not lost," said {friend}, tapping the side of a very wise nose. "It is waiting. There is a difference, and the difference is everything."',
         '"Then I had better not keep it waiting," said {name}, and grinned for the first time that day.'),
        ('"One question before you go," said {friend}. "Are you frightened?"',
         '"Completely," admitted {name}. "That is how I know it matters. Nothing that matters was ever done by somebody who felt ready."'),
        ('"Take this," said {friend}, pressing something into {name}\'s hand. "No — do not look now. Open it only when the way is completely lost."',
         '"And if the way is only mostly lost?" asked {name}. "Then walk faster," said {friend}, "and pretend it is a shortcut."'),
        ('"You remind me of someone," said {friend} slowly, as if the memory cost something. "Someone who stood exactly where you are standing, a long time ago."',
         '"What happened to them?" asked {name}. "They came back," said {friend}. "Different — but they came back. They always do, the stubborn ones."'),
    ],
    "twists": [
        "And then {name} saw it — really saw it. The thing everyone had called an enemy was not an enemy at all. The great shape in the fog was old, and lost, and far more frightened than {name} had ever been. It had not been blocking the road. It had been waiting beside it, hoping somebody kind would finally come along.",
        "The discovery, when it came, was almost too simple to believe: the door had never been locked. For a hundred years it had only been stuck — and the whole valley had built a legend around a stiff hinge. {name} leaned one shoulder against the black oak, pushed, and felt a century of fear give way with a sigh.",
        "Here is what nobody in {place} had ever guessed: the trouble and the treasure were the same thing. The river had not run mad — it had run toward help, carrying its strange cargo uphill to the one place, and the one person, who could understand what the water was trying to say.",
        "It was {friend_short} who had been right all along, in the most annoying possible way. The map was not wrong. It was old — and the land itself had moved, politely and completely, while everyone was busy blaming the map.",
        "Then, at the very worst moment, {name} remembered the small thing in the pack — the gift, the warning, the joke that turned out to be neither. It was a key, not to the door, but to the truth: nothing here had ever been a test of strength. It was a test of who would stop, and notice, and stay.",
    ],
    "realizations": [
        "Sitting in the dark with the rain dripping through the leaves, {name} finally understood. The journey had never been about arriving. It was about the moment you stop waiting for somebody braver — and the moment, {name} decided, standing up and wringing out a hat, was now.",
        "Help, when it came, did not arrive with trumpets. It arrived as a memory: the oldest story of {place}, the one told so often it had worn smooth as a pebble — and inside it, hiding in plain sight, every word of it true, was the answer.",
        "{name} stopped, closed both eyes, and listened the way the river listens to its own banks. And there — under the wind, under the fear, under everything — was the small steady sound of the way home, which had been pointing the right direction all along.",
        "It was the failure that taught it. Stripped of the map, the bag, and every sensible plan, {name} discovered the one tool that could not be lost down a ravine: the habit of being kind to strangers — because in this country, strangers kept turning out to be exactly the help required.",
        "Then {friend_short} was simply there — mud to the knees, breathless, furious, wonderful — having followed the whole way at a distance, the way love does when it does not want to interfere. And {name}, who had carried the whole journey alone, learned the journey's last lesson: you never actually did.",
    ],
    "climaxes": [
        "What happened next, {place} would retell for fifty years. With the light failing and the wind rising to a shout, {name} stepped forward, raised {object}, and did the one thing nobody — nobody — had ever thought to try. For a heartbeat, the whole world held still to watch.",
        "The last stretch was the worst of all: steeper, darker, and louder, with every step argued for. {name} climbed anyway — slowly, then steadily, then all at once — and at the very top, with burning arms and a heart like a drum, reached out and did not miss.",
        "It came down, in the end, to one moment and one choice. Run, and be safe and sorry forever — or step forward, shaking, and say the true thing out loud. {name} stepped forward. The silence that followed was the loudest sound in the history of {place}.",
        "Nobody breathed. {name} took the final step onto ground that had defeated a hundred years of heroes, smiled the smile of somebody far too tired to be afraid, and simply — gently, carefully, exactly right — finished what the journey had asked.",
        "The storm broke at the worst possible second, and that, somehow, was the making of it. In the roar and the rain, {name} laughed out loud, gripped {object} with both hands, and held on while the whole sky poured itself out — and when it finally emptied, the thing that had resisted everyone simply let go.",
        "It was not strength that won it. It was timing, and stubbornness, and one small kind word spoken at exactly the right moment — and then {name} was through, past, over, done, standing in the sudden quiet with the whole valley spread out below like a held breath let go at last.",
    ],
    "endings": [
        "{name} came home at golden hour, muddy, magnificent, and starving, to find all of {place} waiting at the gate with lanterns. Nothing about {hero} looked different — and yet everything had changed, the way a river changes a stone: slowly, and for good. And the wish? The wish had quietly come true somewhere along the road, when nobody was watching it.",
        "They say {name} never spoke much about that day. But they also say that ever afterwards, whenever somebody small stood at the edge of something enormous, {name} would simply appear beside them — the way help does — and say: right then. Shall we? And that is how the story goes on, even now.",
        "The feast that night lasted until the stars gave up and went to bed. {name} ate three helpings, told the story twice (it grew a little in the telling, as stories are allowed to do), and slept the deep, dreamless sleep of the truly finished. Some adventures end. This one simply moved into {place} and stayed.",
        "And the strange thing? {name} kept {object} on the shelf by the door ever after — not as a trophy, but as a reminder: that the way through is usually the way nobody tried, and that being small has never once disqualified anybody from being exactly the right size. The end.",
        "Life in {place} went back to normal — better than normal, in the way a mended thing is stronger than a new one. And if you visit, even now, they will point out the road, and the gate, and tell you about {hero} named {name}, who went out afraid and came back certain. Which, when you think about it, is the only souvenir worth having.",
        "Years later, when {name} was old and the story had become a legend with its own opinions, a small visitor would sometimes ask: was it very frightening? And {name} would smile the old smile and say: only until it started. That is the secret of every adventure worth the name. The end.",
    ],
    "scene_lines": [
        "{hero} setting out from {place} at dawn, small pack, hopeful face, wide establishing shot",
        "{hero} facing the first great obstacle on the road to {place}, scale and danger, dramatic low angle",
        "{hero} discovering the hidden truth with {object} glowing in hand, wonder and light breaking through",
        "{hero} returning home to {place} at golden hour, lanterns lit, triumphant warm wide shot",
    ],
}


GENRES["horror"] = {
    "label": "Horror",
    "places": [
        "the lane of shuttered houses at Marrow End",
        "the fog-bound village of Hollowmere",
        "the cliffs above the grey sea at Widow's Point",
        "the pine woods where the path doubles back",
        "the old quarter where the lamps burn backwards",
        "the marsh road that floods at midnight",
    ],
    "objects": [
        ("iron candle", "an iron candle whose flame leans toward secrets"),
        ("bone whistle", "a little bone whistle that sounds frozen, never warm"),
        ("tarnished mirror", "a tarnished mirror that shows rooms a breath too late"),
        ("black ribbon", "a black ribbon, still tied in a careful bow"),
        ("cellar key", "a cellar key, cold as well-water, that fits no known lock"),
        ("paper lantern", "a paper lantern painted with a single watching eye"),
    ],
    "openings": [
        "There are places the map leaves politely blank, and {place} was one of them. {name} — {hero} — had not meant to come here at all. But the road had other ideas, the light was nearly gone, and the last signpost pointed, in peeling paint, directly at the one door still open.",
        "{name} had a rule, and it was a good rule: never arrive anywhere after dark. But rules are for ordinary days, and this had stopped being an ordinary day somewhere around the third wrong turning. By dusk, {hero} {name} stood alone in {place}, telling a brave heart to beat quieter.",
        "It was {friend_short} who first said the name of {place} aloud, and the whole room pretended not to hear it. Later, walking there alone with the mist coming up like breath off cold water, {name} — {hero} — understood why nobody had answered.",
        "The house at the end of {place} had stood empty for thirty years, which is a strange thing to say about a place where the curtains moved. {name}, {hero}, had come only to deliver something and leave quickly. That was the plan. It was a good plan. It lasted until the gate.",
        "Nobody in the village would walk through {place} after the lamps were lit, and nobody would say why, which is the worst kind of warning there is. {name} — {hero} — believed in asking questions. That evening, with the fog shouldering in off the fields, {name} went to ask the place itself.",
        "The letter had no stamp, no name, and only one line inside: COME BEFORE THE MOON IS FULL. {name}, {hero}, read it three times by candlelight, laughed once — the way you laugh at a joke you hope is a joke — and began, very quietly, to pack.",
    ],
    "settings": [
        "The mist did not drift here; it waited. It leaned against the fences and filled the hollows and made every familiar shape look like a stranger deciding whether to speak.",
        "Every window along the way was dark except one, and that one was dark in a different way — the way a held breath is different from sleep.",
        "The silence had layers, like deep water. On top, the small sounds: a gate, a drip, a board settling. Underneath, something older and much more patient.",
        "The moon was thin and the clouds kept crossing it, so the light came and went, came and went, like something signalling — or warning.",
        "Even the crows had left early. That is the detail {name} kept returning to, later. The crows always know. The crows had known for hours.",
        "The road behind looked shorter than it should have, as if the way back were quietly folding itself away, one bend at a time.",
    ],
    "friends": [
        "Widow Ash, who kept the graveyard gate and everyone's secrets",
        "Old Caspian, the lighthouse keeper who never lit the lamp twice",
        "Mother Yew, the herbalist whose shop smelled of rain",
        "Brother Anselm, the gravedigger with the soft voice",
        "Madame Ostra, who read fortunes and refused, point-blank, to read her own",
        "Elias Crowe, the postman who had walked the lane for forty years",
    ],
    "incidents": [
        "It began, precisely, at the moment {name} decided there was nothing to be afraid of. From somewhere above — or below; in that place it was hard to say — came three slow knocks. Then, after a pause long enough to be deliberate, a fourth.",
        "The knocking started on the second night. Not at the door. Doors would have been a comfort. It came from inside the walls, travelling slowly around the room, the way a finger travels around the rim of a glass — and it stopped, every time, directly behind wherever {name} was standing.",
        "First the candle went out, though there was no wind. Then, in the new dark, {name} heard the house do something houses should never do. It sighed. Not the wood settling — {name} knew that sound. This had a shape to it. Almost — almost — a word.",
        "The footprints were the worst of it. They crossed the yard in a clean, unhurried line, in dust that had not been disturbed for thirty years — and there were no footprints coming back. Whatever had walked into that house, in all that time, had never once walked out.",
        "At midnight the mirror showed the room exactly as it was — almost. The chair, the table, the door, all faithful. Only one thing in the reflection was wrong. In the mirror, the door was open. In the room, {name} was quite sure, the door was shut.",
        "It was the crying that did it — faint, and far away, and impossible to ignore once heard. A child, perhaps. Or the wind practising. {name} stood in the dark hall with the candle shaking and made the decision every sensible bone protested: to go and find out.",
    ],
    "attempts": [
        "{name} did the brave things in the brave order: lit every lamp, checked every latch, said every sensible word aloud to the empty rooms. The house listened politely to all of it. Houses are excellent listeners. That is the trouble with houses.",
        "First, {name} tried reason, because reason had never failed before. There would be a draught. There would be a loose board, a trapped bird, an ordinary explanation with its coat still on. {name} went looking for it the way you look for a lost coin — thoroughly, and with rising dread.",
        "There was a job to do and {name} meant to do it quickly: in, deliver, out, and home before the moon topped the trees. The plan survived the gate. It survived the path. It did not survive the front door, which — as {name} raised a hand to knock — opened, slowly, all by itself.",
        "{name} began to keep a notebook, because writing things down makes them smaller. Knocking: walls. Candle: out, no wind. Mirror: WRONG. The notebook worked beautifully right up until the moment {name} found, in handwriting that was almost but not quite familiar, a new entry already written for the following night.",
        "It helped, a little, to talk. So {name} talked — to the rooms, to the stairs, to the whole listening house — the way you talk to a strange dog, calmly and without sudden moves. That was how {name} came to be standing in the hall, mid-sentence, when something upstairs answered.",
        "{name} tried leaving. It is important to say that plainly: {name} tried, sensibly and at once, to leave. The lane, however, had rearranged itself in the dark, and every path out of {place} now arrived, with quiet inevitability, back at the same gate.",
    ],
    "obstacles": [
        "Then the lamps began to go out — not all at once, which would have been honest, but one by one, room by room, each darkening a little nearer than the last. Whatever was putting them out was coming closer at the speed of a story being told. And {name} was the one telling it.",
        "The stairs were the worst of it. Twelve steps up had become, somewhere in the night, very many more than twelve — {name} counted twice, then stopped counting, because the counting was beginning to sound like an invitation. Above, patient as winter, something waited for the counting to stop.",
        "It was the portrait that finally undid the last of the courage. It had hung all evening with its face turned, mercifully, to the wall. Now, in the silence after the bell, {name} found it facing the room — and its eyes, which had been painted shut for a hundred years, were open.",
        "The setback was simple and total: the door {name} had locked — locked, barred, and wedged with a chair — stood open. Not broken open. Opened, from the inside, by someone who had taken their time. And the chair, the chair was set neatly back at the table, as if for a guest.",
        "Half the night was gone when {name} understood the true shape of the trap. The house did not want to keep {name} out. It never had. The house wanted to keep {name} in — and it had been practising, patiently, for thirty empty years.",
        "The voice was the final test, because the voice was kind. It knew the names kindness would use. It asked, so gently, only to be let the rest of the way in — and every instinct {name} owned pulled two ways at once: toward mercy, and toward the slamming of the door.",
    ],
    "dialogues": [
        ('"You should not have come after dark," said {friend}, locking a door that had no visible lock. "Nobody comes after dark. That is rather the point of the place."',
         '"Then tell me what it wants," said {name}, and {friend} smiled the saddest smile in the world. "Oh, my dear. It wants to be KNOWN. Everything here only ever wants that."'),
        ('"Thirty years I have kept this gate," said {friend}, "and I will tell you the only rule that matters. If it calls you by your name — do not answer the first time."',
         '"And the second time?" whispered {name}. "There is no second time," said {friend}, "if you do not answer the first."'),
        ('"It is not evil," said {friend}, unexpectedly. "That is what nobody understands. It is LONELY. Loneliness that old stops knowing how to ask politely."',
         '"Then I am sorry for it," said {name} slowly. "But I am not staying to keep it company." "No," said {friend}. "They never do. That is rather why it is lonely."'),
        ('"You heard it too, then," said {friend}, watching {name}\'s face instead of the window. "The knocking."',
         '"Three times," said {name}. "And a fourth, after." {friend} went very still. "Then it is counting YOU now," they said. "It used to count the stairs."'),
        ('"Take this," said {friend}, and pressed {object} into {name}\'s hands. "Not for protection. For proof. So that when you come back — and you will come back — you will know it was real."',
         '"And if I do not come back?" asked {name}. {friend} considered this with terrible honesty. "Then I shall keep it by the gate," they said, "with the others."'),
        ('"Why does nobody leave this place?" asked {name}, as the mist pressed its face to the glass. "Oh, they leave," said {friend}. "They leave every morning. That is the thing nobody tells you."',
         '"Then what—" began {name}. "They come back every night," said {friend}. "All of them. Even the ones who swear. Especially the ones who swear."'),
    ],
    "twists": [
        "The truth, when {name} finally stood still long enough to see it, was not the one the village feared. The knocking was not something trying to get in. It was something that had been locked in — a long time ago, by frightened people — knocking, politely and endlessly, to get out.",
        "It was the mirror that told it, in the end. The reflection that lagged a breath behind was not a haunting. It was a warning, repeated for thirty years to an empty room: the room in the mirror was the room as it would be — one moment from now — if {name} opened the wrong door.",
        "Here is what the house had been hiding, under all its sighs and knockings: it was not haunted by the dead at all. It was haunted by a promise — an old, kind, unfinished promise, made by someone who never came back to keep it. And the house, faithful as a dog, had been keeping it for them ever since.",
        "Then {name} understood the footprints at last. Nothing had walked into the house and failed to walk out. It was the other way around. Something had been walking out, every night for thirty years, and standing in the yard, and looking back at the windows — waiting to be invited into its own home.",
        "The voice that had begged so gently to be let in was never at the door. It was behind {name} the whole time — in the one room nobody ever searched: the room of things packed away and never unpacked, where the past of {place} sat in boxes, patiently being forgotten.",
    ],
    "realizations": [
        "It was {friend_short}'s words that came back, in the worst moment, like a hand in the dark: it wants to be KNOWN. And {name} understood, at last, that fear is only ever half the message. The other half is the part that has been waiting, all this time, to be answered properly.",
        "Sitting with a back against the door and the dark pressing its weight from the other side, {name} made the discovery that saves people in stories like this: the house could sigh, and knock, and wait — but it could not open a door that was held shut by somebody who had decided, calmly and completely, to hold it.",
        "{name} stopped running then — not from courage, but from arithmetic. Every corridor in this place led back to the same hall. The way out, therefore, was not a direction. It was the one room {name} had been avoiding all night. It had been the way out since the beginning. It was simply the way nobody wanted to take.",
        "The realization came with the striking of the clock: the haunting had a schedule. Midnight to the small hours, every night, like a shift being worked. Whatever did this was not chaos. It was duty. And things that work from duty can be met — at the appointed hour, in the appointed place — by somebody who is ready.",
        "It helped — it helped enormously — to say the true thing out loud. 'I am frightened,' {name} told the listening dark, 'and I am staying anyway.' Somewhere in the walls of the house, something that had fed on unspoken fear for thirty years paused, uncertain, like a musician who has lost the tune.",
    ],
    "climaxes": [
        "At the appointed hour, {name} did the thing the whole night had been building toward: opened the avoided door, wide, on purpose, with {object} raised like a small brave star. What stood on the other side had waited thirty years for that door — and what it did next, {name} would remember on the far side of old age.",
        "Midnight came up the stairs like a tide. {name} stood in the hall with the candle lit and every lamp in the house burning — a whole house blazing against the dark, defiant as a lighthouse — and when the knocking came, three times and a fourth, {name} did the unthinkable. {name} knocked back.",
        "It ended the way storms end: all at once, after the worst of it. The voice rose, the lamps bent, the whole house leaned into its haunting like a ship into a wave — and {name}, small and shaking and still, somehow, standing, spoke the name of the thing. Its true name. The one it had been waiting to hear.",
        "There was no running left in the night, so {name} turned, and faced it, and let it come. It came up out of the dark like the answer to a thirty-year question — and stopped. An arm's length away. Close enough that {name} could see, at last, what it actually was. And seeing it was the end of the fear, though not in the way anyone expects.",
        "The last door was not locked either. It was held — by habit, by sorrow, by thirty years of nobody knocking from the friendly side. {name} knocked. Politely. Three times, and then, after a pause, a fourth. And from inside, with a sound like a sob learning to be a laugh, something knocked back.",
        "When the haunting rose to its height — every door, every stair, every mirror in the house alive with it at once — {name} did the simplest and most terrible thing available to the living. {name} stayed. Stayed, and watched, and witnessed, and did not look away. Witnessing, it turns out, is a kind of mercy the dead will cross a house for.",
    ],
    "endings": [
        "Dawn came the way it comes after such nights: greyly, gently, and entirely without apology. The house stood in it looking smaller, and older, and — for the first time in thirty years — merely empty. {name} walked down the lane in the first light with {object} in hand, and did not look back until the gate, which was exactly once.",
        "They say the house is quiet now. Curtains still. Lamps lit in their proper order, by living hands. But they also say that once a year, on the right night, there comes a knock at the gate of {place} — three times, and then, politely, a fourth — and that {name}, even now, even old, always answers it. Some doors you keep. The end.",
        "{name} never told the whole of it. Some of it was not {name}'s to tell. But the village noticed the changes: the lamps of the old house, lit again. Smoke in its chimney. And a garden, in time, that grew the way gardens grow around houses that are being forgiven. The end.",
        "It is still there, of course. Places like that do not stop existing; they stop waiting. {name} left before noon with the whole bright day opening up like a road being unrolled, and if the heart was still beating hard, it was beating at the ordinary speed of the living — which, after that night, felt like the most beautiful speed in the world.",
        "And the strangest part? {name} missed it. Not the terror — nobody misses the terror. But there are people who have stood in a haunted place and been, for one night, the most necessary person in the world, and ordinary Tuesdays feel thin gruel after that. {name} kept {object} by the door ever after. Just in case the knocking ever came again. The end.",
        "The official story is that {name} delivered what needed delivering and came home before breakfast, and that is true, as far as official stories go. But sometimes, at the end of the lane, when the mist comes up like breath off cold water, {hero} still walks the old path — slowly, without fear — keeping a promise of {name}'s own now: that nothing in {place} will ever have to knock unanswered again.",
    ],
    "scene_lines": [
        "{hero} arriving at {place} at dusk, mist rising, one window lit, ominous wide shot",
        "{hero} inside the dark house with a single candle, shadows on the walls, tense close framing",
        "{hero} confronting the presence in the doorway, {object} raised, light splitting the darkness",
        "{hero} walking out of {place} at dawn, house quiet behind, pale first light, relief and mystery",
    ],
}


GENRES["comedy"] = {
    "label": "Comedy",
    "places": [
        "the village of Upper Giggleswick",
        "the market town of Much Ado",
        "the seaside pier at Wobbly-on-Sea",
        "the grand and slightly crooked Hotel Magnifique",
        "the village green of Little Snoring",
        "the famous and infamous railway station of Puddle Junction",
    ],
    "objects": [
        ("runaway hat", "a runaway hat with a mind entirely of its own"),
        ("self-stirring teapot", "a self-stirring teapot that stirs itself at the worst moments"),
        ("echoing trumpet", "an echoing trumpet that repeats everything, louder and ruder"),
        ("pair of squeaky shoes", "a pair of squeaky shoes, audible in three counties"),
        ("enormous ribbon", "an enormous ribbon, first prize, non-refundable"),
        ("clockwork cake", "a clockwork cake, ticking ominously and deliciously"),
    ],
    "openings": [
        "{name} — {hero} of {place} — had a talent, and the talent was this: if a thing could possibly go wrong in a funny way, it went wrong for {name}, in front of witnesses, usually including someone important. This story is about the day the talent outdid itself.",
        "It was a beautiful morning in {place}, the kind of morning that makes you suspicious. {name}, {hero}, had a plan for the day, and the plan was simple, sensible, and doomed. But {name} did not know that yet. {name} was humming.",
        "Everyone agreed that {name} meant well. Teachers said it, neighbours said it, once — memorably — a magistrate said it. {name}, {hero} of {place}, meant SO well that the meaning-well had a way of catching fire, falling over, and landing in the mayor's soup. Today was going to be a day like that.",
        "{name} woke up with a Feeling. Not a bad feeling — worse: a Confident Feeling. {hero} {name} had never once survived a Confident Feeling with dignity intact, and the record, on this bright and fateful morning in {place}, was not about to improve.",
        "The whole thing started because {name} wanted to help. That was the beginning, the middle, and — as the whole of {place} would be saying by dinner — unmistakably the problem. {name}, {hero}, helped the way weather happens: completely, and to everyone at once.",
        "There is a photograph of that morning that still hangs in {place}, slightly crooked, and everyone in it is pointing. At the centre of the pointing stands {name}, {hero}, holding {object} and wearing the expression of someone who has just understood everything, several minutes too late. Here is how it happened.",
    ],
    "settings": [
        "It was market day, which meant the whole town was out, dressed up, and armed with opinions.",
        "The square had been polished within an inch of its life. Bunting. Brass band. A mayor in a chain of office so heavy it had its own weather.",
        "Someone had laid on sunshine specially, the way caterers lay on sandwiches, and there was not a cloud booked until Thursday.",
        "Every shop bell in the street rang as you passed, so that walking down it sounded like being applauded by cutlery.",
        "Preparations had reached the dangerous stage where everything is ready except the people, who were ready in entirely the wrong direction.",
        "The air smelled of fried onions, hot sugar, and occasion. Judges were expected. Dignity was expected. Neither survived the hour.",
    ],
    "friends": [
        "Mayor Primm, who practised his wave in a mirror",
        "Mrs. Featherstone, the judge of jams, feared in four counties",
        "Sergeant Bellow, the loudest policeman in the history of quiet towns",
        "Old Mr. Crumb, the baker, philosopher, and suspect",
        "Miss Lavinia Lark, the newspaper reporter, who missed NOTHING",
        "Professor Wobble, inventor, optimist, and repeat offender",
    ],
    "incidents": [
        "Then the announcement was made, and the whole square turned to look. The Honour — the Great, Ancient, Once-a-Year Honour — had fallen, by a process nobody fully understood (and everybody immediately disputed), on {name}. {name} accepted with a bow. The bow knocked over a flagpole. It was that kind of Honour.",
        "It started with a simple mistake, the best kind. {name} was handed the wrong envelope — the IMPORTANT envelope, the sealed one, the one marked IN NO CIRCUMSTANCES OPEN THIS BEFORE THE CEREMONY. {name}, being helpful, and the seal being loose, and the moment being the moment — opened it.",
        "At exactly eleven o'clock, {object} entered {name}'s life, uninvited, unstoppable, and — as would become clear — completely in charge. {name} merely happened to be attached to it.",
        "The trouble arrived in the form of a compliment. 'You are the only one I can trust with this,' said the most important person in {place}, handing {name} a responsibility so fragile that stronger people had fainted near it. {name}, thrilled to the marrow, accepted on the spot.",
        "Nobody ever found out how the goat got involved. Goats, in stories like this, simply materialise where they will do the most good, and by good I mean harm. What is certain is that at noon precisely, the goat took one look at {name}, one look at the ceremony, and made a decision.",
        "It began as the smallest possible favour: hold this, watch that, stand here, don't move. Four instructions. {name} — who could juggle engagements, emergencies, and once an actual wedding — took the four instructions into the square like a general taking four soldiers into battle. By lunch, all four were lost.",
    ],
    "attempts": [
        "{name} prepared the way only {name} could: thoroughly, sincerely, and with several diagrams. The diagrams were beautiful. The diagrams were also, in a way that would matter enormously, upside down.",
        "First, {name} tried to Fix It quietly, before anybody noticed. This is the stage of the disaster that historians call The Cover-Up, and it involved a ladder, a curtain, and a decision about the goat that seemed sensible at the time.",
        "{name} apologised to everyone individually and in alphabetical order, which took until two o'clock and included two people who had not been involved and one who had not been born in this town. Then, squaring the shoulders, {name} went back in to make it right.",
        "The rehearsal went perfectly. It is important to establish this. Every step, every word, every timing — flawless. {name} glowed. The committee glowed. Somewhere, fate was quietly moving all the furniture.",
        "Armed with a list, a whistle, and the total confidence of somebody who has learned nothing from experience, {name} marched into the square to take charge. The square, it must be said, had been taken charge of before. It knew things.",
        "{name} came up with a Plan B so brilliant that witnesses wept. It required timing, teamwork, and a wheelbarrow. Plan A had required none of these things, which — with hindsight, the only sight available — was rather the point of Plan A.",
    ],
    "obstacles": [
        "Then came the cascade. Every story like this has one — the moment where fixing the first thing breaks the second, the second startles the third, and the third involves the band. {name} stood at the centre of it, conducting, entirely by accident, an orchestra of consequences.",
        "The setback wore a false moustache and called itself a solution. By the time {name} realised that the new problem was the old problem, plus custard, the situation had achieved what experts call Escape Velocity. It was no longer possible to stop it. It was only possible to aim it.",
        "Halfway through, the weather joined in — and weather, in {place}, is not a bystander. The wind took the bunting, the bunting took the hats, the hats took the square, and {name} took the blame, which had been individually addressed and marked FRAGILE.",
        "The catastrophe, when it peaked, was magnificent. Ask anyone. There are drawings. {name} — knees soaked, dignity in a previous postcode, still holding {object} — did the only thing left to a hero in such a moment. {name} kept going. It is astounding what keeping going can do. It is also, occasionally, the problem.",
        "It is a law of the universe that just before the worst moment, somebody says: 'Well — at least it can't get any worse.' Somebody said it. The universe, which had been waiting with its coat off, rolled up its sleeves. What happened next is still the first story told to visitors in {place}.",
        "The lowest moment arrived, as lowest moments do, in complete silence — the awful hush after the crash, when even the band has stopped, and several hundred people are looking at one person. {name} looked back at them. Somewhere, distantly, a single squeak escaped from {object}, like a period at the end of a sentence.",
    ],
    "dialogues": [
        ('"I can explain everything," said {name}, to {friend}, who had arrived at a run.',
         '"I am certain you can," said {friend}, removing a cabbage leaf from an official hat. "I have read your explanations before. They are serialised."'),
        ('"How — and I ask this as a friend and a public official — how is it EVERY time?" demanded {friend}.',
         '"Talent," said {name} weakly. "And timing. Mostly timing. The talent is just timing that has dressed up."'),
        ('"Nobody panic!" cried {name}, standing on a chair, holding {object} above the crowd. "I have everything under control!"',
         '"That," observed {friend} to the crowd, in the tone of a translator, "is what he says instead of DUCK."'),
        ('"You do realise," said {friend} carefully, "that there is a difference between HELPING and whatever THIS is?"',
         '"Of course," said {name}, from inside the situation. "Helping is what this is called afterwards. If it works."'),
        ('"In my defence," said {name}, "nobody told me the rope was attached to anything."',
         '"{name}," said {friend}, with the patience of geology, "the rope was attached to EVERYTHING. That is what made it a rope."'),
        ('"Well?" said {friend}, surveying the aftermath, the band, and the goat. "Say something."',
         '"I would like the record to show," said {name}, "that I began the day with clean shoes and a simple plan." The record, to its credit, showed it.'),
    ],
    "twists": [
        "And then — in the silence, in the wreckage, with the day utterly and magnificently ruined — somebody laughed. Not a snicker. A great, helpless, window-rattling laugh. It was the mayor. And the mayor's laugh was the loose thread of the whole world, because once HE laughed, {place} understood what {name} never had: the day hadn't been ruined at all. It had been IMPROVED.",
        "Here is what nobody had checked: the Honour was not a prize. It was a punishment left over from 1743, invented for the town's worst nuisance, and the entire solemn ceremony was — by ancient and hilarious law — a roast. {name} had not ruined the most important day of the year. {name} had finally performed it correctly.",
        "The twist arrived wearing the mayor's own boots: the disaster had done, in forty minutes of chaos, what three years of committee meetings could not. The square was cleared, the fountain was fixed, the feud was over (both parties having united, briefly, in falling into it), and {friend} — surveying it all — began, slowly, to take notes for next year.",
        "It turned out the goat had an owner, and the owner had a plan, and the plan — which involved scaring a certain stuffy official out of a certain stuffy decision — had required exactly one chaotic, unstoppable, gloriously timed interruption. The goat was a professional. {name}, all unknowing, had merely been its finest ever assistant.",
        "Then {name} found the note — the ORIGINAL note, the one that explained everything, folded into the wrong envelope a hundred years of tradition ago. The ceremony was never meant to be solemn. It was meant to be this. The founders of {place} had been, to a man, comedians — and they had been waiting a century for somebody to do it properly.",
    ],
    "realizations": [
        "Standing in the beautiful wreckage, {name} had the thought that changes people (when it doesn't simply finish them): perhaps the plan was never the point. Perhaps the point was being the sort of person who shows up, stays in it, and doesn't leave when it gets ridiculous. {name} adjusted what was left of a hat, and stayed.",
        "It was {friend_short} who said it, in the end, handing {name} a towel with the air of a surrender ceremony: 'You are the only person I know who can fall UP a flight of stairs.' And {name}, considering the day honestly, decided to take it as the compliment it almost was.",
        "The realization came with the cleanup, as realizations do — arriving with the brooms. Help isn't a performance. It doesn't need diagrams. It needs a person who will hold the ladder AND admit the wobble. {name} swept, and apologised, and — this was new — laughed first.",
        "{name} understood it all of a sudden, watching the town laugh together — really laugh, the feud forgotten, the band playing, the children delirious: nobody would remember a perfect ceremony. But THIS? This they would tell on their deathbeds. Perfection is forgettable. Joy is not. {name} had not failed the day. {name} had accidentally been its author.",
        "Then the oldest person in {place} took {name} aside, with the ceremony of someone imparting a state secret: 'Forty years I have waited for somebody to do what you did today.' 'By accident?' said {name}. 'By NATURE,' said the elder. 'Accident is just nature with its hat off.' And somehow, that settled it.",
    ],
    "climaxes": [
        "The finale — because of course there was a finale; the day had been rehearsing for it since breakfast — arrived all at once: the band, the goat, the bells, the ribbon, the weather, and {name}, surfing the whole glorious catastrophe on {object} like a banner, into the exact centre of the square, at the exact stroke of noon, to the sound of several hundred people being, despite everything, delighted.",
        "What {name} did next is taught to children. Faced with total disaster, one working shoe, and an audience — {name} bowed. Bowed like it had ALL been the act. Bowed like the chaos was choreography. And the square, given the choice between scandal and theatre, chose as one person — theatre. The applause reached the next county.",
        "It came down to the toast. The whole day balanced on it: one speech, one chance, one famous {name} disaster between {place} and glory. {name} stood. Opened the important envelope. Read it exactly as written — including, by glorious accident, the stage directions. The square did not so much laugh as detonate.",
        "The last disaster was the biggest and the best: everything that could fall, fell — in sequence, in rhythm, in what the band later insisted was four-four time. It was less an accident than a premiere. And {name}, at the centre of the symphony, took the final pratfall so perfectly, so completely, so obviously-on-purpose, that the judges gave it marks.",
        "Somebody had to save the day, and the somebody, by process of elimination, geography, and goat, was {name}. So {name} saved it the only way left: completely, theatrically, and backwards — turning the whole ruined ceremony into the best street party in the recorded history of {place}, using nothing but nerve, timing, and the last unbroken thing in the square.",
        "In the end it took one sentence. {name} climbed onto the fountain — history records the fountain — raised {object} to the sky, and shouted the truest words ever spoken at a ceremony: 'WE MEANT TO DO THAT.' The roar that followed has been measured. It lifted hats in the next town.",
    ],
    "endings": [
        "And so the worst day became the best story, which is the usual arrangement, though nobody tells the hero in advance. {name} was forgiven everything, awarded something shiny, and banned — formally, in writing, forever — from ever helping again. {name} frames the ban to this day, next to the ribbon. The end.",
        "They made it annual. Of course they made it annual — towns like money, and chaos, properly seasoned, is money. And every year, on the day, {place} looks for somebody helpful, somebody heartfelt, somebody with exactly {name}'s gift, and finds them, and steps back, and lets history repeat itself. {name} judges now. The judging is very safe. Usually.",
        "{name} went home with clean shoes (a miracle outshining all others), a pocketful of apologies accepted, and a reputation transformed from menace to monument. And if, on quiet mornings, {name} still wakes with a Feeling — well. {place} has learned to keep a mop, a ladder, and a brass band on standby. The end.",
        "The photograph hangs crooked still, but the caption underneath was changed by order of the mayor. It used to say DISASTER. It now says: THE DAY {name} SAVED THE CEREMONY. Underneath, in smaller letters, someone has added: NO, REALLY. And underneath that, in {name}'s own writing: 'I would like the record to show I began with a simple plan.' The end.",
        "Years later, grandchildren would ask {name} how it felt, being at the centre of the most famous day in the history of {place}. And {name} — {hero}, hero of the hour, legend by lunch — would smile the smile of the truly seasoned. 'Sticky,' {name} would say. 'It felt extremely sticky. Now — who wants to hear about the goat?' The end.",
        "And the moral, if this story insists on having one (and {name}, for the record, insists it does NOT), is simply this: the world does not need more perfect people. It has plenty of plans. It needs the ones who show up with their whole heart, make the glorious mess, stay to sweep it, and laugh first. {name} is available, by the way. Book early. The end.",
    ],
    "scene_lines": [
        "{hero} arriving proudly at {place} on a festive morning, bunting and crowd, bright wide shot",
        "{hero} at the centre of glorious chaos in {place}, everything tipping at once, dynamic comedy framing",
        "{hero} holding {object} aloft as the crowd realises it is delighted, laughter and sunshine, mid shot",
        "{hero} celebrated as a hero in {place} at sunset, cheering crowd, warm triumphant wide shot",
    ],
}

GENRES["kids"] = {
    "label": "Kids & Family",
    "places": [
        "the sunny village of Marigold Lane",
        "the Whispering Woods, where the trees tell jokes",
        "the little harbour of Puddle Bay",
        "the hill of Buttercup Meadows",
        "the cosy town of Buttonwood",
        "the garden at the end of Rainbow Road",
    ],
    "objects": [
        ("singing seed", "a singing seed that hums when it is happy"),
        ("rainbow umbrella", "a rainbow umbrella that only opens for kind people"),
        ("tiny golden bell", "a tiny golden bell that rings for new friends"),
        ("paper boat", "a paper boat, folded with love, that never sinks"),
        ("glowing pebble", "a glowing pebble, warm as a held hand"),
        ("magic watering can", "a magic watering can that pours exactly enough"),
    ],
    "openings": [
        "Once upon a sunny morning in {place}, there lived {hero} named {name}. {name} was small, and kind, and very curious — the very best combination — and today, {name} could feel in the tips of the toes that something wonderful was going to happen.",
        "{name} was {hero} who lived in {place}, in a cosy little home with a round door and a window full of flowers. {name} liked warm milk, soft adventures, and helping friends — and best of all, {name} liked days that began with a surprise.",
        "In {place}, where the grass is green and the clouds are shaped like animals, there lived {hero} called {name}. {name} had a big heart, a brave little smile, and one special wish that twinkled like a star every night before sleep.",
        "This is the story of {name}, {hero} of {place}, who was not the fastest, or the strongest, or the loudest — but who had the kindest hands in the whole village, and everyone, even the grumpy old hedgehog, agreed about that.",
        "Every morning, {name} — {hero} of {place} — woke up, stretched, and said the same happy words: 'What lovely thing will happen today?' And every morning, the day tried its very best to answer. Today, it had a truly special answer ready.",
        "Once there was {hero} named {name}, who lived in {place} under a big friendly tree. {name} loved stories, and songs, and the smell of rain — and most of all, {name} loved finding new friends in surprising places.",
    ],
    "settings": [
        "The sun was shining like a smile, the flowers were nodding in the breeze, and the whole world smelled of warm grass and breakfast.",
        "Butterflies did their slow, happy dances over the flowers, and the birds sang the morning song that everybody knows and nobody taught them.",
        "The path wound through the flowers like a ribbon, past the pond where the frogs say 'bong' instead of 'ribbit', because they are fancy.",
        "Everything was green and gold and gentle, and the shadows were the soft kind — the kind that are nice to sit in with a friend.",
        "A little stream sang as it went, telling the pebbles all the news of the hills, and the pebbles, who love news, sparkled.",
        "The clouds were round and white and slow, like sheep taking an afternoon stroll across the sky.",
    ],
    "friends": [
        "Granny Moth, who knits scarves for the whole forest",
        "Old Barnaby the bear, who tells the best stories and naps between sentences",
        "Pippa the sparrow, who knows every roof and every secret",
        "Professor Hoot the owl, who is very wise and a little bit sleepy",
        "Tilly the turtle, who is slow, and steady, and always right on time",
        "Bramble the hedgehog, who is grumpy on the outside and jam in the middle",
    ],
    "incidents": [
        "Then, just after breakfast, it happened! A tiny voice — the tiniest voice {name} had ever heard — called out from the flowers: 'Help! Oh please, somebody help!' {name} dropped everything. Helping is what {name} did best, and somebody small needed it right away.",
        "That very morning, {name} found something amazing: {object}, half-hidden under a leaf, shining in the sun. And the moment {name} picked it up, a wonderful, buzzy, anything-can-happen feeling fizzed all the way from nose to toes.",
        "It started when the music stopped. Every morning, the garden woke to the dawn song — but today there was no song at all, only quiet. The flowers drooped. The birds shuffled their feet. Somewhere, the dawn song was lost, and somebody had to find it.",
        "A new friend arrived that day — small, lost, and trying very hard not to cry. Everyone was kind, but everyone was busy too. {name} looked at the little stranger's wobbly lip, and made a big decision in a small, warm heart: 'You can stay with me,' {name} said. 'I will help you.'",
        "The rain came at the wrong time — puddle-rain, splish-rain, the kind that cancels picnics and soaks socks — and all the little plans of {place} were washed into the gutters. But wait. Listen. Under the sound of the rain, something small was calling.",
        "That morning, the oldest friend in {place} had a problem too big for one pair of hands, and was too proud — and too shy — to ask. But {name} noticed. Noticing is a kind of magic, and {name} had it in both eyes.",
    ],
    "attempts": [
        "{name} helped straight away, the very best way {name} knew how: with both hands, a big smile, and a heart going thump-thump-thump. It was going very well. It was ALMOST finished. And then — oh dear — then came the tricky part.",
        "First, {name} tried the quick way. Quick ways are fun! Quick ways are fast! Quick ways, unfortunately, are usually the wrong way wearing a speedy hat. {name} discovered this at the usual moment: the middle.",
        "{name} made a plan, because plans are good: step one, step two, step three, HELPED! {name} did step one beautifully. Step two went splendidly. Step three... step three had not read the plan.",
        "'Do not worry,' said {name}, rolling up sleeves in the way that means business. 'I am going to help, and I am going to keep helping until it is helped.' And {name} set to work, humming the working song.",
        "{name} tried being strong first — heave! ho! — and then tried being clever, with levers and string and a very serious face. The problem listened to both tries politely, the way problems do, and stayed exactly as it was. Hmm.",
        "Off went {name}, skipping down the path with a basket of good ideas, asking everyone along the way. Some ideas were big. Some ideas were small. One idea involved the moon, and had to be gently set aside. But {name} kept asking, and kept going.",
    ],
    "obstacles": [
        "But then — oh no — the trouble got bigger. The path was blocked, the day was slipping away, and the problem, which had started the size of a pebble, now felt as big as a mountain. {name} sat down for one small minute, and had one small wobble, the way even the bravest hearts do.",
        "Halfway there, it all went wrong at once: the wind blew, the basket tipped, and the helping-things scattered EVERYWHERE. {name} looked at the mess, and the mess looked at {name}, and for a moment, a hot, prickly, give-up feeling prickled behind the eyes.",
        "The worst moment came quietly, the way worst moments do. {name} had tried and tried, and it still was not fixed, and the little voice that says 'I can't' sat down right in the middle of the road and crossed its arms. {name} almost — almost — listened to it.",
        "Then the sky forgot to be kind. The clouds bumped together, the light went grey, and the first fat drops went plip, plip, PLOP — right on the very spot where {name} was working. Helping in the rain is helping turned up to hard, everyone knows that.",
        "Oh, it was so nearly done! And then the last piece — the important piece, the finishing piece — rolled away down the hill, bounce, bounce, bounce, into the one place it should never roll: the deep, dark, rustling middle of the bramble patch.",
        "{name} tried one more time, and it didn't work, and that was the hardest 'didn't work' of all, because it was the last idea in the basket. The basket was empty. The day was nearly over. And the problem was still there, waiting, like it had all the time in the world.",
    ],
    "dialogues": [
        ('"I do not know if I can do this," said {name}, very quietly.',
         '"Then do it the way you do everything," said {friend}, kindly. "One small piece at a time. Mountains are just very big piles of small pieces, you know."'),
        ('"Why do you help everyone?" asked {friend}, watching {name} work.',
         '"Because helping is what hands are FOR," said {name}, surprised. "What else would I do with them? Wave? I can wave AND help." And {name} waved, and helped, at the same time.'),
        ('"Are you frightened?" asked {friend}, looking at the big, dark, rustly brambles.',
         '"A bit," said {name} honestly. "But frightened and brave can be in the same tummy at the same time. My tummy has room." {friend} nodded. "Mine too," they said. "Let us take our tummies together."'),
        ('"You came back!" cried {friend}. "Everyone said the rain would stop you!"',
         '"Rain is just the sky helping the flowers," said {name}, dripping and grinning. "It would be rude to let it do ALL the helping."'),
        ('"Take this," said {friend}, giving {name} {object}. "It has been waiting for the right helper."',
         '"For me?" said {name}, eyes round as moons. "But I am so SMALL." "Small," said {friend}, "is the size that fits through the little doors. And the little doors are where the important helping happens."'),
        ('"I made a mess," said {name}, looking at the scattered, splattered everything.',
         '"Then we shall un-mess it together," said {friend}, rolling up enormous sleeves. "A mess shared is a mess halved. A friend shared is a joy doubled. That is the maths of friends, and it is always right."'),
    ],
    "twists": [
        "And then {name} saw it — the secret that had been there all along! The thing that looked like the biggest problem was actually the best luck in disguise. The bramble patch, the deep dark rustly one? Something small and lost was hiding inside it, and it had been waiting for {name} this whole time.",
        "Just then, the loveliest thing happened: all the friends {name} had ever helped came hurrying down the path — one, two, three, a whole parade of them! Because kindness is never lost, you see. It just goes visiting, and comes back when you need it most.",
        "Here is the secret the whole garden knew except {name}: the problem did not need to be pushed, or pulled, or fixed with a tool. It needed to be ASKED. Politely. In the right words. And {name}, who was the kindest asker in {place}, knew exactly the right words.",
        "Then {name} remembered! The song — the story — the thing {friend_short} had said a hundred times that suddenly made perfect sense, like a key turning in a lock. The answer had been in {name}'s pocket of memory all along, warm and waiting.",
        "And do you know what? The big scary rustling in the brambles was not scary at all. It was just lonely. It had been making big noises with a small heart, hoping somebody would be brave enough to come close and say hello. And somebody — somebody named {name} — was.",
    ],
    "realizations": [
        "{name} sat down in the grass, took a deep breath — in through the nose, out through the mouth, the way the wise ones teach — and thought very carefully. And the careful thought said: I do not have to do this alone. I never did. Asking for help is helping too.",
        "It was the littlest friend who showed the way — doing the enormous job one tiny piece at a time, hum-hum-humming all the while. {name} watched, and understood: big jobs are only small jobs holding hands. {name} picked up one small piece. Then another.",
        "Then {name} remembered the most important thing of all: nobody had ever said the helping had to be perfect. It only had to be kind. {name} stood up, brushed off the grass, and smiled the smile of someone who knows the secret now.",
        "{name} looked at the empty basket and had the best idea of the whole day — the idea that had been hiding inside all the other ideas. The basket was empty because the ideas had all been given away. And given-away ideas grow back doubled. {name} just had to go and ask the friends.",
        "The answer came the quiet way answers come to kind hearts: not in a shout, but in a whisper. {friend_short}'s voice, remembered at exactly the right moment: 'The little doors, {name}. Look for the little doors.' And there — small, round, and exactly {name}-sized — was a little door.",
    ],
    "climaxes": [
        "Then came the biggest moment of all! Everyone held hands — and paws, and wings, and leaves — and together, with a one, and a two, and a THREE, they did the enormous thing that nobody could do alone. And it WORKED. Oh, how it worked! The sun came out like applause!",
        "{name} took a deep breath, thought of all the friends, and did the brave thing — small, and quick, and kind, all at the same time. For one whole heartbeat, nobody in {place} breathed. And then — YES! — the problem gave a great big sigh and turned into the solution, just like that.",
        "It was time. {name} stepped up to the very hardest part, with {object} shining and every friend watching and the whole garden holding its breath — and {name} did it. Not perfectly. Not tidily. But completely, and kindly, and JUST in time, which is the very best way of all.",
        "Higher and higher, faster and faster, braver and braver — {name} went, with the friends calling encouragement below and the wind saying 'you can, you can, you CAN' — until, with one last great big effort, {name} reached it. REACHED IT! And the cheering could be heard in the next valley!",
        "And so, in the golden light of nearly-evening, with everyone helping and nobody left out, the great big impossible job got done — piece by piece, friend by friend, giggle by giggle — until there was nothing left of it but smiles. {name} had done it. No — THEY had done it. Which is even better.",
        "The very last piece clicked into place with the happiest sound in the world: CLICK. {name} froze. The friends froze. The garden froze. And then everyone was hugging and hopping and cheering at once, because it was DONE — done, done, done — and the sound of the cheering rolled over {place} like a wave of warm honey.",
    ],
    "endings": [
        "And that night, tucked up warm and happy, {name} thought about the day — the worry, the rain, the friends, the finish. 'Helping is hard,' {name} whispered to the stars, 'and hard is not the same as bad. Hard is just where the good stories live.' And {name} slept, and dreamed of little doors. The End.",
        "There was a feast, of course — berry feast, honey feast, with songs and stories and a speech by {friend} that made everyone laugh and cry in the SAME minute, which is the best kind of speech. And {name}, full of berries and happiness, was the guest of honour. The End.",
        "From that day on, whenever anybody in {place} had a problem too big for one pair of hands, they knew just what to do: they went to find {name}. And {name}, {hero} with the kindest hands in the village, always said the same happy words: 'Let us do it together.' The End.",
        "The garden was peaceful again, the song was back, and everything shone a little brighter for having been mended with kindness. {name} kept {object} in a special place by the window — to remember that small is strong, kind is brave, and friends make everything possible. The End.",
        "And if you walk through {place} today, you might still see {name} — {hero} — helping somebody, somewhere, with both hands and a big smile. And if YOU ever have a problem that feels too big, you know the secret now, don't you? Do it one small piece at a time — and never, ever alone. The End.",
        "The stars came out one by one, like the garden lighting its evening lamps. {name} yawned a great big yawn, waved goodnight to all the friends, and went home under the friendly moon — tired, happy, and ready for tomorrow. Because tomorrow, in {place}, there would be somebody new to help. There always is. The End.",
    ],
    "scene_lines": [
        "{hero} setting out happily from {place} on a sunny morning, flowers and butterflies, cheerful wide shot",
        "{hero} facing a big problem in {place}, worried face, friends gathering behind, warm storybook framing",
        "{hero} discovering the happy secret with {object} shining bright, wonder and golden light",
        "{hero} celebrating with all the friends in {place} at sunset, feast and laughter, joyful wide shot",
    ],
}


GENRES["sci_fi"] = {
    "label": "Sci-Fi",
    "places": [
        "the orbital station Meridian Ring",
        "the domed city of New Karachi on Mars",
        "the generation ship Astraea, ninety years from home",
        "the ice moon of Europa's bright side",
        "the skyport of Alto Station",
        "the terraforming fields of the Red Valley",
    ],
    "objects": [
        ("singing crystal", "a singing crystal that hums in harmonics no machine can make"),
        ("seed vault key", "a seed vault key, heavier than it looks, warm from living soil"),
        ("star chart", "a star chart drawn by hand, with one star circled twice"),
        ("memory pearl", "a memory pearl that holds a whole ocean in miniature"),
        ("signal lantern", "a signal lantern built to be seen from another world"),
        ("clockwork star", "a clockwork star that ticks once a year, on the dot"),
    ],
    "openings": [
        "Ninety years out from Earth, on the generation ship Astraea — or under a dome on Mars, or wherever the maps of {place} say we are — there lived {hero} named {name}. {name} had never seen Earth. {name} had seen its pictures ten thousand times, which is not the same thing, and some days the difference itched like a too-small suit.",
        "{name} was {hero} of {place}, third generation, born between stars. {name} knew every corridor, every hum of the great engines, every shortcut the official deck plans pretended did not exist. What {name} did not know — what nobody aboard knew — was what the ship had been keeping secret for ninety years.",
        "The registry of {place} lists {hero} {name} as crew: competent, punctual, unremarkable in every file. The registry is wrong, the way registries often are. It leaves out the illegal garden, the hand-drawn star charts, and the fact that {name} was the only soul aboard who still asked the oldest question: what if we are not alone out here?",
        "On the morning our story starts, the alarms of {place} did something they had never done in ninety years: they stayed silent, one beat too long, like a held breath. {name} — {hero}, on duty, mid-breakfast — felt it in the teeth before the instruments admitted it. Something had found them. Or something had finally answered.",
        "{name} had a job nobody thanked and everybody needed, the way it goes with the best jobs. {hero} of {place}: keeper of small systems, fixer of quiet failures, the first call when the ship cleared its throat at 3 a.m. And it was at 3 a.m., naturally, that the call of the century came.",
        "Every child of {place} learns two histories: the one in the archives, and the one the old ones tell with the lights low. {name} — {hero} — believed the archives. Believed them completely, right up until the night the bulkhead behind Bay Nine began, very softly, to transmit.",
    ],
    "settings": [
        "Beyond the viewport, the stars did not twinkle. They watched, the way they have watched every ship that ever presumed to cross the dark.",
        "The corridors smelled of warm metal, green growing things, and ninety years of other people's dinners.",
        "Gravity here was a courtesy — nine-tenths honest, with the missing tenth reminding you, gently and always, exactly where you were.",
        "Earth hung in the schoolroom as a picture: blue, improbable, and so heavily defended by distance that the children treated it the way children treat dragons — half beloved, half disbelieved.",
        "The engines sang their one low note through the deck plates, the note every child of the ship falls asleep inside, the note that means: still flying, still falling, still home.",
        "Out past the hull, the dark was absolute and crowded at once — a hundred billion suns, and not one of them close enough to warm your hands.",
    ],
    "friends": [
        "Chief Engineer Okafor, who speaks to the engines like family",
        "Archivist Sen, keeper of the Earth films and all forbidden questions",
        "Dr. Ibarra, the ship's doctor, who has delivered three generations",
        "Old Pilot Reyes, who flew the ship when the ship was young",
        "Botanist Amara, who grows a garden no manifest admits to",
        "Comms Officer Vale, who has listened to the dark for forty years",
    ],
    "incidents": [
        "The signal arrived at 03:12, in the middle of {name}'s shift, on a frequency older than the ship. It was not noise. Noise does not repeat. Noise does not — and the hair on {name}'s arms stood up as the trace drew itself a third time — noise does not repeat in prime numbers, wait for an answer, and then repeat again.",
        "It began in Bay Nine, behind a bulkhead that had been sealed since launch: a sound like a hand, knocking. Slowly. Politely. Ninety years sealed, and something on the other side had, apparently, only just decided to knock. The work order {name} received said, in full: INVESTIGATE. DO NOT OPEN. In that order.",
        "The discovery was almost an accident: a manifest, misfiled for ninety years, listing cargo the ship was never supposed to carry — and a vault, mid-ship, that appears on no plan, drawing power no audit could find. {name} read the last line twice. PRIORITY: THE PASSENGERS MUST NEVER KNOW. Underneath, in pencil, in a dead hand: they already suspect.",
        "First the stars went wrong. Not out — wrong. {name} caught it because {name} actually LOOKED, the old way, out of a real viewport: the constellations had shifted, subtly, impossibly, as if the whole sky had been picked up and set down an inch to the left. The navigators' instruments, consulted an hour later, agreed with the sky. The ship was not where the ship was supposed to be.",
        "It was supposed to be a routine EVA — ninety minutes outside, tethered, boring, the way spacewalks should be. Then {name}'s glove brushed the hull and came away dusted with something that glittered wrong, and the hull cameras showed what no briefing ever mentioned: scratches. Long, deliberate, parallel. Made recently. Made from outside.",
        "The vault opened itself at the changing of the watch, the way a held breath lets go. No alarm. No code broken. Just a door that had waited ninety years for this exact shift, this exact witness — {name}, {hero}, standing alone in the corridor with a cup of tea going cold — and behind the door, lit soft as morning: {object}.",
    ],
    "attempts": [
        "{name} reported it first, through channels, the way the manual demands. The manual had no chapter for this. Channels took six hours to produce an answer, and the answer was a masterpiece of its kind: a form, requesting that the anomaly kindly describe itself in triplicate. {name} filed the form. Then {name} went back to Bay Nine alone.",
        "First, {name} tried the instruments — every scanner, every probe, every listening thing the ship possessed. The instruments agreed with each other beautifully, which is what instruments do right before they are all wrong together. So {name} did the oldest science there is: went, and looked, and listened, with the original equipment.",
        "{name} started with the archives, because Archivist Sen always said the past is just the future with the labels worn off. What {name} found there was worse than nothing: gaps. Careful, deliberate, ninety-year-old gaps — pages razored out with love, logs that ended mid-sentence, a whole history with its heart cut out.",
        "The official approach having failed at the speed of paperwork, {name} tried the unofficial one: a quiet word, in the right corridor, to the one person aboard who might know. It is astonishing what the right corridor knows. It is more astonishing what it charges: everything, it turned out, had a price, and the price was the truth.",
        "{name} built the receiver by hand, from salvage and stubbornness, because the ship's own array was — as the polite phrase goes — administratively unavailable. Three nights of work. Two burnt fingers. One antenna made from a decommissioned flag pole and pure spite. On the third night, it sang.",
        "There was no version of this that went through committees, so {name} went around them — carefully, legally-ish, and at 3 a.m., when the ship belongs to the people who actually run it. The work took all night and most of the next day, and by the end of it {name} knew two things: the anomaly was real, and it was patient.",
    ],
    "obstacles": [
        "Then the ship itself seemed to close ranks. Doors that had always opened required codes that had never existed. Logs rewrote themselves between one reading and the next. And a message arrived on {name}'s private channel, from an account that did not exist, saying the truest and worst thing possible: YOU ARE NOT THE FIRST TO ASK. STOP ASKING.",
        "The setback came from the one direction {name} had not fortified: the people. Word travels a closed ship faster than light. By dinner, everyone knew a version — none of them true, all of them believed — and {name} stood in the canteen holding a tray while ninety years of neighbours quietly decided what {name} was.",
        "Halfway into the work, the power budget ran out — or was run out. The vault, the receiver, the whole fragile apparatus went dark at a stroke, and the dark was total and administrative. Somewhere above {name}'s pay grade, somebody had chosen, deliberately, to un-know what {name} knew.",
        "It was the distance that broke things, in the end — light-minutes of it, the cruellest physics there is. The signal, whatever it was, was ANSWERING. But every exchange took longer, and each answer arrived stranger, and {name} understood with a chill that the conversation was not with something far away. The delay was deliberate. It was getting closer.",
        "The failure, when it came, was public and total and complete: the demonstration collapsed in front of the council, the readings flatlined, the receiver sang only static, and {name} — who had staked everything on being right — stood in the ringing silence of being, apparently, wrong. Apparently. The static, {name} noticed even then, had a rhythm.",
        "They took {name}'s access. Then they took the tools. Then, with great courtesy, they took the shifts — a rest, a kindness, a removal. {name} sat in the quiet of an enforced holiday with empty hands and one unforgotten fact burning like a coal: the knocking in Bay Nine had not stopped. It had changed rhythm. It was counting.",
    ],
    "dialogues": [
        ('"I have listened to the dark for forty years," said {friend}, "and I will tell you what the dark is, {name}. The dark is patient. It can afford to be. We are the ones on a schedule."',
         '"Then we had better answer it on our schedule," said {name}, "before it loses patience — or finds it."'),
        ('"You know what they will say," said {friend}. "Contamination of the record. A third-generation fever dream."',
         '"Let them say it," said {name}. "Fevers do not knock in prime numbers, {friend}. And dreams do not leave scratches on the hull."'),
        ('{friend} turned {object} over slowly, with the reverence of long training. "Do you understand what this is?" they asked at last.',
         '"A message," said {name}. "Ninety years old and still warm." "{name}," said {friend} gently, "it is not a message. It is an ANSWER. Somebody out there has been waiting for US to finish asking the question."'),
        ('"If I show you the real archive," said {friend}, in the corridor where the cameras forget to look, "there is no un-seeing it. The ship you grew up on ends. Another one begins."',
         '"The ship I grew up on has a vault in it that knocks," said {name}. "Show me." {friend} looked at {name} for a long moment. "You are your great-grandmother\'s child," they said, "and that is not entirely a compliment. Come."'),
        ('"Why me?" asked {name}. "There are officers. Scientists. A whole council of people with actual authority."',
         '"Because authority asks what a thing will cost," said {friend}, "and you — you ask what a thing MEANS. The ship has been waiting ninety years for the second kind of question."'),
        ('"The passengers must never know," recited {friend}, like a catechism learned at a grandmother\'s knee. "That is the first law of this ship. It kept us alive for ninety years."',
         '"Did it?" asked {name}. "Or did it keep us ALONE for ninety years? There is a difference, {friend}. There is all the difference there is."'),
    ],
    "twists": [
        "Here is what ninety years of secrecy had hidden, folded inside the ship like a letter in a book: the voyage's great secret — the thing in the vault, the razored logs, the knocking — was never a threat carried aboard. It was a passenger. The oldest passenger. The one the mission was actually FOR, sleeping the whole voyage through, waiting for the generation that would finally knock back.",
        "The truth surfaced the way deep things surface — slowly, then all at once. The signal was not coming from outside the ship. It was coming from the ship — from the parts of it sealed at launch, broadcasting a question into the dark for ninety years, in the voices of the first crew. And something, out there in the black, had recently begun — politely, in prime numbers — to answer on the ship's behalf.",
        "It was {friend_short} who finally said it plainly, in the archive, with the razored logs open like wounds: the founders had not hidden a danger. They had hidden a CHOICE. Arrive and knock, or pass by in silence forever — a decision too large for one frightened generation, gift-wrapped in secrecy and posted down the years to the first crew brave enough to open it. To {name}.",
        "Then the static resolved, and everything {name} thought was true rotated ninety degrees. The scratches on the hull, the shifted stars, the closing delay — it was not something approaching the ship. It was the ship's own shadow-self in the dark: a sister vessel, launched in secret a year behind, carrying the other half of everything — the other archive, the other garden, the other answer. Lost for ninety years. Signalling, now, with dying power, in prime numbers, for help.",
        "The final page of the archive was not razored. It was worse: it was written to {name}. Not by name — by description, by duty roster, by the shape of a question only one crew member per generation ever asks. THE KEEPER OF SMALL SYSTEMS WILL FIND THIS. DO NOT BE AFRAID OF THE KNOCKING. IT IS ONLY US, it said, in the handwriting of the founding captain. IT IS ONLY US, STILL ABOARD, STILL WAITING TO BE LET INTO THE LIGHT.",
    ],
    "realizations": [
        "The realisation came in the small hours, the way the true ones always do: the ship had never been a vehicle. A vehicle goes somewhere. The ship was a TIME CAPSULE with engines — a message in a bottle, crewed by the descendants of the senders, addressed to whoever the universe turned out to contain. And {name}, holding the bottle's secret at last, got to decide what the reply would be.",
        "{name} sat with the dead receiver and the rhythmic static and understood the thing the council never would: evidence was never going to be enough. Some doors only open to a decision. The ship's founders had known it. Ninety years of children had been raised, deliberately, inside a question — and a question is not answered with instruments. It is answered by somebody stepping forward.",
        "It was the garden that cracked it — Amara's impossible, illegal garden, growing green in the dark of a ship that officially had no soil to spare. Proof, rooted and leafing, that the crew had never once obeyed the whole of the law: they had kept the living things alive anyway, in secret, at cost, for ninety years. {name} looked at the green and thought: we are not a crew that surrenders our passengers. We never were.",
        "Sitting in the enforced quiet, {name} finally read the pattern of the knocking — really read it, the way {friend} reads the engines. It was not counting down. It was counting UP. Generations. One long knock for the first crew, two for the second — a roll call of the whole voyage, patient as geology, waiting for the generation that would answer present. Ours, {name} thought. It is waiting for ours.",
        "Then {name} did the bravest maths there is. Ninety years of silence had kept the ship safe, and ninety years of silence had cost it — the garden, the archive, the truth, each other. Safety, compounded over a century, becomes its own kind of wreck. {name} stood up, in the quiet, and chose the risk with open eyes, the way the founders, whatever else they hid, had clearly hoped somebody would.",
    ],
    "climaxes": [
        "The council chamber had not been built for what walked into it that morning: {name}, uninvited, unwashed, carrying {object} and ninety years of razored truth. What happened next is still argued about in the corridors — but every version agrees on the ending. The vote was taken standing up. The vault would open. The ship would knock back. And the dark, the patient dark, was finally going to get its answer.",
        "It came down to one corridor, one door, and one generation keeping its nerve. {name} stood at the vault with the whole ship watching on every screen — children, elders, the council, the ghosts in the archive — placed one hand on metal sealed before their grandparents were born, and knocked. Three times. Slowly. The way you knock on the door of family. And from inside, after ninety years, with the whole ship holding its breath — something knocked back.",
        "The launch of the answer was not a missile or a flare. It was the garden — Amara's garden, carried to the observation blister pod by pod, green under the stars, and {name}'s voice on the open channel, reading the names of the lost ship's crew from the restored archive, one by one, into the dark, the way you call roll for family you have never met. Halfway down the list, shaking, the dark answered.",
        "When the sister ship's signal failed at last — mid-word, mid-cry — the council froze the way councils do, and it was {name} who moved: out the lock in the patched suit, across the dark on a tether and a prayer, with the other ship's dying lights ahead and the whole of two crews watching. What {name} carried across that gap was not equipment. It was the archive's last page, and a hand to hold out. It was enough. It was exactly, gloriously enough.",
        "Nobody had rehearsed the first words. Ninety years of secrecy, and the founders had left everything planned except the sentence. So when the channel opened and the other side — human, hoarse, ninety years lost — said '...is anyone... is anyone there...', it was {name} who leaned into the microphone of history and said the words that would be carved over the airlock forever: 'We are here. We have always been here. Hold on.'",
        "The signal lantern had been built by children, from salvage, as a school project — a toy. {name} took it to the highest blister of the ship, set it against the dark the way you set a candle in a window for the lost, and lit it. It burned — small, defiant, impossible — a handmade star. And out in the black, impossibly far and suddenly near, another light, much older, blinked. Twice. The code of the lost: I SEE YOU.",
    ],
    "endings": [
        "The ship is different now — everyone says so, walking the corridors a little taller. The archive stands open. The garden has a manifest number and a waiting list. And at 03:12 every year, by a law nobody remembers passing, the whole ship goes quiet for one minute and listens to the dark together. It has never, since {name}'s watch, been only dark. The end.",
        "They gave {name} the worst punishment a grateful ship could devise: a title, a ceremony, and permanent first watch on the listening array — the job, in other words, that {name} was born for. And some nights, when the channel sighs with distant weather, {name} still answers on the open frequency, for any lost thing listening: 'Meridian traffic, this is {name}. You are not alone. Say again.' The end.",
        "Earth is still ninety years of pictures. The sister ship is ninety days of burning engines, closing like a held breath let out at last. Between them lies a channel that never closes now — voices, seeds, star charts, arguments about music — and at the heart of it, in the ship's new charter, one line in a founder's hand, restored to the first page where it always belonged: THE PASSENGERS MUST ALWAYS KNOW. {name} reads it on duty, sometimes aloud. Just to hear it in the air. The end.",
        "The vault stands open these days, and children are taken to see it on school trips, where they are solemn for whole minutes at a time. What is inside is for them to discover — that is rather the point. But the plaque by the door is public, and it names the crew of the opening, and the keeper of small systems who knocked. Below the names, one line: THEY ASKED WHAT IT MEANT. The end.",
        "Old {name} — and it takes a paragraph to get used to writing that — still takes tea at 3 a.m. in the corridor by Bay Nine, where the knocking used to be. The bay is a garden now. The tea is terrible. The visitors come from both ships, and the stories take all night, and nobody, in either crew, would have it any other way. Ninety years the dark was patient. It took one person to answer it. It always only ever takes one. The end.",
        "And the registry of {place} was amended, in the end, by Archivist Sen's own hand. Where it once read 'competent, punctual, unremarkable', it now says what it should have said all along: CREW — KEEPER OF SMALL SYSTEMS — FIRST TO KNOCK BACK. Filed under N, for {name}. Filed under F, for First. The end.",
    ],
    "scene_lines": [
        "{hero} on duty in a vast starship corridor at night, listening at a sealed door, moody cinematic wide shot",
        "{hero} discovering {object} glowing inside a hidden vault, wonder and awe, shafts of light",
        "{hero} standing before the ship's council holding the forbidden evidence, tense dramatic framing",
        "{hero} gazing out at a second distant ship's lights answering in the dark, hopeful epic wide shot",
    ],
}

# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
_TITLE_NOUNS = ("Adventure", "Journey", "Day", "Errand", "Morning",
                "Voyage")


def _place_short(place: str) -> str:
    text = place
    if text.startswith("the "):
        text = text[4:]
    text = text.split(",")[0]
    if " of " in text:
        text = text.rsplit(" of ", 1)[1]
    return text.title()


def _make_title(rng: random.Random, name: str, obj_short: str,
                place: str) -> str:
    style = rng.randrange(4)
    if style == 0:
        return f"The {name} and the {obj_short.title()}"
    if style == 1:
        poss = name + ("'" if name.endswith("s") else "'s")
        return f"{poss} Big {rng.choice(_TITLE_NOUNS)}"
    if style == 2:
        adj = rng.choice(("Secret", "Wonderful", "Curious",
                          "Amazing", "Singing"))
        return f"The {adj} {obj_short.title()}"
    return f"{name} in the {_place_short(place)}"


def assemble(premise: str, genre: str | None = None,
             seed: int | None = None) -> dict:
    """Assemble a complete short story for `premise`.

    genre: a GENRES key ("adventure"/"horror"/"comedy"/"kids"/
    "sci_fi") or None to detect it from the premise. seed: pass a
    project's seed for a stable story; None = fresh randomness.
    Returns {title, story, scenes, name, hero, anchor, genre}.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    key = genre if genre in GENRES else detect_genre(premise)
    lib = GENRES[key]

    hero_info = parse_hero(premise, rng)
    name = hero_info["name"]
    friend = rng.choice(lib["friends"])
    place = hero_info["setting_hint"] or rng.choice(lib["places"])
    obj_short, obj_phrase = rng.choice(lib["objects"])
    ctx = {
        "name": name,
        "hero": hero_info["descriptor"],
        "friend": friend,
        "friend_short": friend.split(",")[0].strip(),
        "place": place,
        "object": obj_phrase,
        "object_short": obj_short,
    }

    def fmt(text: str) -> str:
        return text.format(**ctx)

    pools: dict[str, list] = {}

    def pick(category: str):
        """Draw without replacement within this story."""
        if category not in pools:
            pools[category] = list(lib[category])
        pool = pools[category]
        return pool.pop(rng.randrange(len(pool)))

    def dialogue() -> str:
        first, reply = pick("dialogues")
        return fmt(first) + " " + fmt(reply)

    paragraphs = [
        fmt(pick("openings")) + " " + fmt(pick("settings")),
        fmt(pick("incidents")),
        fmt(pick("attempts")) + " " + dialogue(),
        fmt(pick("obstacles")),
        fmt(pick("twists")),
        fmt(pick("realizations")) + " " + dialogue(),
        fmt(pick("climaxes")),
        fmt(pick("endings")),
    ]
    # Attribution polish: inside one paragraph, the friend's full
    # descriptor ("Old Marta, the map-keeper…") is used once; later
    # mentions in the same paragraph use the short form ("Old
    # Marta") so dialogue does not read like a stuck record.
    short_friend = friend.split(",")[0].strip()

    def dedup_friend(text: str) -> str:
        if short_friend == friend or friend not in text:
            return text
        head, sep, tail = text.partition(friend)
        return head + sep + tail.replace(friend, short_friend)

    paragraphs = [dedup_friend(p) for p in paragraphs]
    scenes = [fmt(line) for line in lib["scene_lines"]]
    return {
        "title": _make_title(rng, name, obj_short, place),
        "story": "\n\n".join(paragraphs),
        "scenes": scenes,
        "name": name,
        "hero": hero_info["descriptor"],
        "anchor": hero_info["anchor"],
        "genre": key,
    }
