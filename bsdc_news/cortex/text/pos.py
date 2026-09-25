"""A small rule-based part-of-speech tagger.

No trained model, no download: function-word lists + morphological suffixes +
capitalisation + a Brill-style context repair pass. It is accurate enough to find
noun phrases, subjects and verb groups, which is all the writer needs, and it
runs in microseconds per sentence.
"""

import re
from dataclasses import dataclass

from .lemma import lemma

DETERMINERS = {"the", "a", "an", "this", "that", "these", "those", "each", "every",
               "some", "any", "no", "another", "other", "both", "all", "few", "many",
               "much", "several", "such", "what", "which", "whose"}
PREPOSITIONS = {"in", "on", "at", "by", "for", "with", "about", "against", "between",
                "into", "during", "including", "until", "among", "throughout",
                "despite", "towards", "upon", "of", "to", "from", "up", "down", "off",
                "over", "under", "again", "further", "then", "once", "here", "there",
                "when", "where", "why", "how", "after", "before", "above", "below",
                "across", "behind", "beyond", "near", "since", "via", "within", "without"}
PRONOUNS = {"i", "me", "my", "mine", "we", "us", "our", "ours", "you", "your", "yours",
            "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them",
            "their", "theirs", "who", "whom", "which", "that", "this", "these", "those"}
CONJUNCTIONS = {"and", "but", "or", "nor", "so", "yet", "for", "because", "although",
                "while", "if", "unless", "until", "since", "whether", "though", "whereas",
                "once", "than", "that", "as", "after", "before"}
MODALS = {"can", "could", "may", "might", "must", "shall", "should", "will", "would",
          "ought", "need", "dare", "used"}
AUXILIARIES = {"be", "am", "is", "are", "was", "were", "been", "being", "have", "has",
               "had", "do", "does", "did", "get", "gets", "got", "getting"}
NEGATIONS = {"not", "no", "never", "none", "neither", "nor", "nothing", "nobody",
             "nowhere", "hardly", "barely", "scarcely", "seldom", "rarely"}
WH_WORDS = {"what", "when", "where", "who", "whom", "whose", "why", "how", "which"}
# Closed-class vocabulary that morphology alone cannot resolve. "next quarter"
# must not become a noun phrase head, and "the chip ships" must not read as two nouns.
ADJECTIVES = {
    "next", "last", "first", "second", "third", "fourth", "fifth", "new", "old", "big",
    "small", "large", "little", "major", "minor", "key", "main", "top", "high", "low",
    "early", "late", "long", "short", "full", "free", "open", "public", "private",
    "local", "global", "national", "international", "official", "current", "recent",
    "upcoming", "previous", "same", "different", "similar", "various", "several",
    "own", "only", "single", "double", "triple", "daily", "weekly", "monthly", "yearly",
    "annual", "hourly", "wireless", "digital", "physical", "virtual", "mobile",
    "portable", "powerful", "efficient", "affordable", "expensive", "cheap", "fast",
    "slow", "quick", "easy", "hard", "simple", "complex", "advanced", "modern",
    "classic", "popular", "famous", "unknown", "available", "compatible", "secure",
    "safe", "risky", "important", "critical", "essential", "necessary", "optional",
    "additional", "extra", "internal", "external", "temporary", "permanent",
    "immediate", "instant", "rapid", "gradual", "significant", "substantial",
    "considerable", "marginal", "modest", "dramatic", "steep", "sharp", "flat",
    "stable", "volatile", "exclusive", "premium", "budget", "flagship", "native",
}
VERBS_3P = {
    "ships", "runs", "adds", "says", "tells", "sells", "buys", "brings", "builds",
    "sends", "spends", "holds", "keeps", "leaves", "loses", "means", "pays", "reads",
    "meets", "stands", "writes", "drives", "falls", "gives", "gets", "grows", "leads",
    "rides", "rises", "sits", "speaks", "cuts", "puts", "lets", "sets", "hits",
    "costs", "beats", "wins", "draws", "shows", "goes", "does", "has", "makes",
    "takes", "comes", "sees", "knows", "thinks", "finds", "feels", "wants", "needs",
    "hopes", "plans", "aims", "seeks", "looks", "works", "offers", "launches",
    "expands", "improves", "boosts", "raises", "lowers", "opens", "closes", "starts",
    "ends", "joins", "returns", "reveals", "unveils", "confirms", "denies", "admits",
    "warns", "notes", "claims", "reports", "announces", "releases", "updates",
    "upgrades", "supports", "includes", "requires", "allows", "enables", "blocks",
    "limits", "extends", "reduces", "increases", "reaches", "targets",
    "faces", "follows", "precedes", "replaces", "removes", "restores", "fixes",
    "solves", "handles", "manages", "controls", "tracks", "monitors", "measures",
}
# High-frequency news/tech nouns whose endings look adjectival ("battery" ends in
# -y, "assistant" in -ant). A closed list beats a wrong suffix guess every time.
NOUNS = {
    "battery", "batteries", "assistant", "chip", "chips", "chipset", "chipsets",
    "phone", "phones", "screen", "screens", "display", "displays", "device", "devices",
    "model", "models", "price", "prices", "pricing", "launch", "launches", "release",
    "releases", "update", "updates", "upgrade", "upgrades", "feature", "features",
    "version", "versions", "quarter", "quarters", "market", "markets", "report",
    "reports", "plan", "plans", "deal", "deals", "offer", "offers", "support", "work",
    "line", "lines", "product", "products", "service", "services", "system", "systems",
    "platform", "platforms", "network", "networks", "software", "hardware", "camera",
    "cameras", "keyboard", "laptop", "laptops", "tablet", "tablets", "watch", "watches",
    "sensor", "sensors", "processor", "processors", "memory", "storage", "cloud",
    "data", "user", "users", "app", "apps", "site", "sites", "page", "pages", "post",
    "posts", "video", "videos", "image", "images", "photo", "photos", "audio", "sound",
    "music", "game", "games", "team", "teams", "company", "companies", "firm", "firms",
    "brand", "brands", "store", "stores", "shop", "shops", "sales", "revenue", "profit",
    "profits", "growth", "demand", "supply", "cost", "costs", "value", "quality",
    "speed", "size", "sizes", "weight", "unit", "units", "part", "parts", "piece",
    "pieces", "share", "shares", "stock", "stocks", "investor", "investors", "analyst",
    "analysts", "chief", "head", "boss", "owner", "owners", "founder", "founders",
    "customer", "customers", "client", "clients", "partner", "partners", "vendor",
    "vendors", "supplier", "suppliers", "factory", "factories", "plant", "plants",
    "office", "offices", "campus", "city", "cities", "country", "countries", "region",
    "regions", "state", "states", "government", "agency", "agencies", "regulator",
    "regulators", "court", "courts", "law", "laws", "rule", "rules", "policy",
    "policies", "bill", "bills", "tax", "taxes", "tariff", "tariffs", "ban", "bans",
    "probe", "probes", "review", "reviews", "study", "studies", "survey", "surveys",
    "test", "tests", "trial", "trials", "event", "events", "conference", "summit",
    "meeting", "meetings", "call", "calls", "chat", "chats", "message", "messages",
    "email", "emails", "account", "accounts", "password", "passwords", "key", "keys",
    "token", "tokens", "code", "codes", "bug", "bugs", "flaw", "flaws", "patch",
    "patches", "hack", "hacks", "attack", "attacks", "breach", "breaches", "leak",
    "leaks", "scam", "scams", "fraud", "crime", "crimes", "risk", "risks", "threat",
    "threats", "issue", "issues", "problem", "problems", "solution", "solutions",
    "change", "changes", "shift", "shifts", "trend", "trends", "topic", "topics",
    "story", "stories", "news", "press", "media", "article", "articles", "blog",
    "note", "notes", "memo", "memos", "letter", "letters", "document",
    "documents", "file", "files", "folder", "record", "records", "list", "lists",
    "table", "tables", "chart", "charts", "graph", "graphs", "map", "maps", "design",
    "designs", "layout", "interface", "button", "buttons", "menu", "menus", "panel",
    "panels", "board", "boards", "card", "cards", "slot", "slots", "port", "ports",
    "cable", "cables", "adapter", "adapters", "charger", "chargers", "case", "cases",
    "cover", "covers", "strap", "straps", "stand", "stands", "mount", "mounts",
    "year", "years", "month", "months", "week", "weeks", "day", "days", "hour",
    "hours", "minute", "minutes", "second", "seconds", "time", "times", "date",
    "dates", "deadline", "deadlines", "schedule", "timetable", "today", "tomorrow",
    "yesterday", "tonight", "morning", "evening", "night", "summer", "winter",
    "spring", "autumn", "fall", "season", "seasons", "way", "ways", "point", "points",
    "level", "levels", "stage", "stages", "step", "steps", "phase", "phases", "end",
    "ends", "start", "starts", "beginning", "middle", "top", "bottom", "side",
    "sides", "edge", "edges", "centre", "center", "core", "hub", "hubs", "base",
    "bases", "root", "roots", "source", "sources", "origin", "target", "targets",
    "goal", "goals", "aim", "aims", "idea", "ideas", "concept",
    "notion", "view", "views", "opinion", "opinions", "response", "reaction",
    "comment", "comments", "statement", "claim", "claims", "accusation", "allegation",
    "denial", "confirmation", "announcement", "declaration", "promise", "pledge",
    "commitment", "agreement", "contract", "contracts", "license", "licenses",
    "patent", "patents", "trademark", "copyright", "rights", "right", "duty",
    "duties", "role", "roles", "job", "jobs", "career", "careers", "staff",
    "employee", "employees", "worker", "workers", "manager", "managers", "executive",
    "executives", "director", "directors", "president", "chairman", "spokesperson",
    "representative", "official", "officials", "minister", "ministers", "lawmaker",
    "lawmakers", "senator", "senators", "candidate", "candidates", "voter", "voters",
    "election", "elections", "vote", "votes", "poll", "polls", "campaign", "campaigns",
    "war", "wars", "conflict", "conflicts", "strike", "strikes", "protest",
    "protests", "riot", "riots", "crisis", "disaster", "accident", "crash", "fire",
    "flood", "storm", "quake", "earthquake", "pandemic", "outbreak", "virus",
    "vaccine", "drug", "drugs", "medicine", "treatment", "therapy", "patient",
    "patients", "hospital", "hospitals", "doctor", "doctors", "school", "schools",
    "student", "students", "teacher", "teachers", "university", "college", "course",
    "courses", "class", "classes", "exam", "exams", "result", "results", "score",
    "scores", "win", "wins", "loss", "losses", "draw", "match", "matches", "series",
    "tournament", "league", "club", "clubs", "player", "players", "coach", "coaches",
    "film", "films", "movie", "movies", "show", "shows", "episode",
    "episodes", "actor", "actors", "actress", "singer", "band", "artist",
    "artists", "song", "songs", "album", "albums", "book", "books", "author",
    "authors", "reader", "readers", "viewer", "viewers", "listener", "listeners",
    "fan", "fans", "community", "communities", "group", "groups", "org",
    "organisation", "organization", "organisations", "organizations", "division", "divisions", "department", "departments", "branch", "branches",
    "committee", "council", "commission", "forum", "coalition", "alliance", "union", "unions", "association", "society",
    "institute", "institutes", "lab", "labs", "laboratory", "research", "science",
    "scientist", "scientists", "engineer", "engineers", "developer", "developers",
    "programmer", "programmers", "designer", "designers", "writer", "writers",
    "editor", "editors", "journalist", "journalists", "reporter", "reporters",
    "photographer", "creator", "creators", "influencer", "influencers", "expert",
    "experts", "specialist", "specialists", "consultant", "consultants", "advisor",
    "advisers", "critic", "critics", "human", "humans", "person",
    "people", "man", "men", "woman", "women", "child", "children", "kid", "kids",
    "teen", "teens", "adult", "adults", "family", "families", "parent", "parents",
    "mother", "father", "brother", "sister", "friend", "friends", "colleague",
    "neighbour", "neighbor", "citizen", "citizens", "resident", "residents",
    "immigrant", "immigrants", "refugee", "refugees", "tourist", "tourists",
    "traveler", "travellers", "driver", "drivers", "pilot", "pilots", "crew",
    "passenger", "passengers", "consumer", "consumers", "buyer",
    "buyers", "seller", "sellers", "merchant", "merchants", "trader", "traders",
    "shareholder", "shareholders", "bank", "banks", "fund", "funds",
    "loan", "loans", "credit", "debt", "debts", "cash", "money", "currency",
    "currencies", "dollar", "dollars", "euro", "euros", "taka", "rupee", "yen",
    "pound", "pounds", "bitcoin", "crypto", "cryptocurrency", "wallet",
    "exchange", "exchanges", "trade", "trading", "investment", "investments",
    "economy", "economies", "inflation", "recession", "boom", "bubble", "budget",
    "budgets", "spending", "income", "earnings", "wage", "wages", "salary",
    "salaries", "fee", "fees", "rate", "rates", "discount", "discounts", "coupon",
    "coupons", "sale", "promotion", "ads", "ad",
    "advertising", "marketing", "reputation", "identity", "privacy", "security", "safety", "protection", "encryption",
    "authentication", "login", "logins", "signup", "subscription", "subscriptions",
    "membership", "tier", "tiers", "package", "packages", "bundle",
    "bundles", "kit", "kits", "tool", "tools", "utility", "utilities", "helper",
    "extension", "extensions", "plugin", "plugins", "module", "modules", "library",
    "libraries", "framework", "frameworks", "engine", "engines", "runtime",
    "compiler", "kernel", "server", "servers", "browser",
    "browsers", "website", "websites", "webpage", "domain", "domains", "host",
    "hosts", "hosting", "cdn", "api", "apis", "endpoint", "endpoints", "protocol",
    "protocols", "standard", "standards", "spec", "specs", "specification",
    "specifications", "requirement", "requirements", "guideline", "guidelines",
    "regulation", "regulations", "compliance", "audit", "audits",
    "benchmark", "benchmarks", "metric", "metrics", "stat", "stats", "statistic",
    "statistics", "number", "numbers", "figure", "figures", "percentage", "ratio",
    "count", "total", "sum", "average", "mean", "median", "range", "limit",
    "limits", "cap", "caps", "quota", "quotas", "threshold", "thresholds",
    "gap", "gaps", "difference", "differences", "similarity", "distance", "space",
    "area", "areas", "zone", "zones", "territory", "border", "borders",
    "route", "routes", "path", "paths", "road", "roads", "street", "streets",
    "highway", "bridge", "tunnel", "airport", "airports", "station", "stations",
    "harbor", "harbour", "warehouse", "depot", "grid", "grids",
    "power", "energy", "electricity", "fuel", "fuels", "oil", "gas", "solar",
    "wind", "nuclear", "coal", "cell", "cells", "turbine", "turbines", "reactor", "reactors", "emission", "emissions",
    "carbon", "climate", "weather", "temperature", "heat", "cold", "rain",
    "drought", "pollution", "waste", "recycling", "environment", "nature",
    "wildlife", "animal", "animals", "species", "forest", "forests", "ocean",
    "oceans", "sea", "seas", "river", "rivers", "lake", "lakes", "mountain",
    "mountains", "island", "islands", "desert", "valley", "valleys", "planet",
    "planets", "star", "stars", "galaxy", "universe", "orbit", "satellite",
    "satellites", "rocket", "rockets", "mission", "missions", "spacecraft",
    "telescope", "nasa", "spacex", "ai", "ml", "gpu", "cpu", "os", "sdk",
    "ui", "ux", "seo", "crm", "erp", "iot", "ar", "vr", "xr", "5g", "6g",
    "wifi", "bluetooth", "usb", "hdmi", "oled", "lcd", "led", "hbm", "ddr",
    "ssd", "hdd", "ram", "rom", "npu", "tpu", "soc", "lte", "gsm",
}
NOUN_SUFFIXES = ("tion", "sion", "ment", "ness", "ity", "ance", "ence", "ship", "hood",
                 "ism", "ist", "er", "or", "ar", "age", "ure", "dom", "logy", "graphy",
                 "ware", "work", "line", "point", "system", "service", "device")
ADJ_SUFFIXES = ("able", "ible", "ful", "less", "ous", "ive", "al", "ic", "ish", "ary",
                "ent", "ant", "ing", "ed", "y")
ADV_SUFFIXES = ("ly", "wards", "wise")
VERB_SUFFIXES = ("ate", "ify", "ise", "ize", "ise", "en")

_CAMEL = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$")
_INITIALISM_TOKEN = re.compile(r"^(?:[A-Za-z]\.)+$")

# Adjectives whose -er/-est forms would otherwise look like agent nouns:
# "faster" is not a person who "fasts".
COMPARATIVES = {
    "faster", "bigger", "smaller", "cheaper", "larger", "greater", "newer", "older",
    "higher", "lower", "stronger", "weaker", "quicker", "slower", "brighter", "darker",
    "thinner", "thicker", "longer", "shorter", "wider", "narrower", "deeper", "lighter",
    "heavier", "safer", "smarter", "tougher", "easier", "busier", "happier", "cleaner",
    "cooler", "warmer", "hotter", "colder", "softer", "harder", "louder", "quieter",
    "simpler", "better", "worse", "earlier", "later", "closer", "further", "richer",
    "less", "more", "younger", "taller", "tighter", "looser", "sharper", "sleeker",
    "poorer",
}
SUPERLATIVES = {
    "fastest", "biggest", "smallest", "cheapest", "largest", "greatest", "newest",
    "oldest", "highest", "lowest", "strongest", "weakest", "quickest", "slowest",
    "brightest", "darkest", "thinnest", "thickest", "longest", "shortest", "widest",
    "narrowest", "deepest", "lightest", "heaviest", "safest", "smartest", "toughest",
    "easiest", "busiest", "happiest", "cleanest", "coolest", "warmest", "hottest",
    "coldest", "softest", "hardest", "loudest", "quietest", "simplest", "best", "worst",
    "latest", "earliest", "richest", "poorest", "youngest", "tallest", "sleekest",
}


@dataclass
class Tagged:
    token: str
    tag: str
    lemma: str
    index: int
    capitalised: bool = False

    @property
    def is_noun(self) -> bool:
        return self.tag.startswith("NN")

    @property
    def is_verb(self) -> bool:
        return self.tag.startswith("VB")

    @property
    def is_proper(self) -> bool:
        return self.tag in {"NNP", "NNPS"}


def tag_token(token: str, position: int = 0, sentence_start: bool = True) -> str:
    """Assign a Penn-treebank-ish tag to one token."""
    lowered = token.lower()
    if not token:
        return "."
    if re.fullmatch(r"[\d,\.]+%?", token) or re.fullmatch(r"\$[\d,\.]+[mbnk]?", token):
        return "CD"
    if re.fullmatch(r"[^\w\s]+", token):
        return "."
    if lowered in DETERMINERS:
        return "DT"
    if lowered in PRONOUNS:
        return "PRP"
    if lowered in MODALS:
        return "MD"
    if lowered in AUXILIARIES:
        return "VB"
    if lowered in NEGATIONS:
        return "RB"
    if lowered in CONJUNCTIONS:
        return "IN" if lowered not in {"and", "but", "or", "nor", "so", "yet"} else "CC"
    if lowered in PREPOSITIONS:
        return "IN"
    if lowered in WH_WORDS:
        return "WRB"
    if _CAMEL.match(token):
        return "NNP"
    if token.isupper() and len(token) > 1 and not (position == 0 and sentence_start):
        return "NNP"
    if token[0].isupper() and position > 0:
        return "NNP"
    if lowered in NOUNS:
        return "NN"
    if lowered in ADJECTIVES:
        return "JJ"
    if lowered in COMPARATIVES:
        return "JJR"
    if lowered in SUPERLATIVES:
        return "JJS"
    if lowered.endswith(ADV_SUFFIXES) and len(lowered) > 4:
        return "RB"
    if lowered.endswith(NOUN_SUFFIXES) and len(lowered) > 4:
        return "NNS" if lowered.endswith(("ers", "ors", "isms", "ists")) else "NN"
    if lowered.endswith(VERB_SUFFIXES) and len(lowered) > 4:
        return "VB"
    if lowered.endswith("ing") and len(lowered) > 4:
        return "VBG"
    if lowered.endswith("ed") and len(lowered) > 3:
        return "VBD"
    if lowered.endswith(ADJ_SUFFIXES) and len(lowered) > 4:
        return "JJ"
    if lowered.endswith("s") and not lowered.endswith(("ss", "us", "is")):
        return "NNS"
    return "NN"


def tag(tokens: list[str]) -> list[Tagged]:
    """Tag a whole sentence, then repair with simple context rules."""
    tagged = [Tagged(token=token, tag=tag_token(token, i), lemma=lemma(token), index=i,
                     capitalised=bool(token[:1].isupper()))
              for i, token in enumerate(tokens)]
    for i, item in enumerate(tagged):
        previous = tagged[i - 1] if i else None
        following = tagged[i + 1] if i + 1 < len(tagged) else None
        # Determiner + verb/adverb is almost always a noun ("a must", "the why"),
        # but an adjective stays an adjective ("a faster camera").
        if previous and previous.tag == "DT" and item.tag in {"VB", "VBD", "RB"}:
            item.tag = "NN"
        # Modal or auxiliary + word → base verb.
        if (previous and previous.tag in {"MD", "VB"} and previous.lemma in AUXILIARIES | MODALS
                and item.tag.startswith(("NN", "JJ")) and not item.is_proper):
            item.tag = "VB"
        # Third-person verb after a noun or pronoun ("the chip ships", "Apple says").
        if (previous and previous.tag in {"NN", "NNS", "NNP", "NNPS", "PRP", "CC", "RB", "MD"}
                and item.token.lower() in VERBS_3P and not item.is_proper):
            item.tag = "VBZ"
        # Adverb before an adjective/verb keeps its tag; adjective before noun is fine.
        if following and following.tag in {"NN", "NNS", "NNP"} and item.tag == "VBG":
            item.tag = "JJ"
        # Preposition followed by a determiner or proper noun starts a noun phrase.
        if item.tag == "IN" and following and following.tag in {"DT", "NNP"}:
            continue
        # "Apple said" → first token is a proper noun even at sentence start.
        if (i == 0 and item.tag == "NN" and item.capitalised and len(item.token) > 2
                and item.lemma not in AUXILIARIES | MODALS | DETERMINERS):
            item.tag = "NNP"
    return tagged


_CASED_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\-/&\.]*")


def tokenize_cased(sentence: str) -> list[str]:
    """Word tokens with their original capitalisation and no bare punctuation.

    Internal dots survive for initialisms ("U.S."), but a sentence-final period is
    stripped so entity spans and keyphrases never carry punctuation.
    """
    out: list[str] = []
    for token in _CASED_TOKEN.findall(sentence or ""):
        while token.endswith(".") and not _INITIALISM_TOKEN.match(token):
            token = token[:-1]
        if token:
            out.append(token)
    return out


def tag_text(sentence: str) -> list[Tagged]:
    """Convenience: tokenise one sentence (case preserved) and tag it."""
    return tag(tokenize_cased(sentence))


def nouns(tagged: list[Tagged]) -> list[str]:
    return [item.lemma for item in tagged if item.is_noun and item.tag not in {"NNP", "NNPS"}]


def proper_nouns(tagged: list[Tagged]) -> list[str]:
    return [item.token for item in tagged if item.is_proper]


def verbs(tagged: list[Tagged]) -> list[str]:
    return [item.lemma for item in tagged if item.is_verb and item.lemma not in AUXILIARIES]


def main_verbs(tagged: list[Tagged]) -> list[Tagged]:
    """Content verbs: no auxiliaries, no modals."""
    return [item for item in tagged if item.is_verb and item.lemma not in AUXILIARIES | MODALS]


def negated(tagged: list[Tagged]) -> bool:
    return any(item.lemma in NEGATIONS or item.token.lower().endswith("n't") for item in tagged)


def subjects(tagged: list[Tagged]) -> list[str]:
    """Noun tokens before the first content verb — a cheap subject heuristic."""
    out = []
    for item in tagged:
        if item.is_verb and item.lemma not in AUXILIARIES:
            break
        if item.is_noun or item.is_proper:
            out.append(item.token)
    return out
