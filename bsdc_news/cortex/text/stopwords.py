"""Stopwords: general English plus the noise specific to tech news writing."""

ENGLISH = frozenset(["a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves"])

# Attribution noise that carries no topical signal in tech news.
DOMAIN = frozenset(["said", "says", "say", "saying", "according", "reports", "reported", "report", "reveals", "revealed", "reveal", "announces", "announced", "announcement", "claims", "claimed", "claim", "notes", "noted", "note", "adds", "added", "add", "explains", "explained", "shares", "shared", "share", "tells", "told", "tell", "writes", "wrote", "write", "confirms", "confirmed", "confirm", "per", "via", "latest", "update", "updates", "updated", "story", "article", "post", "blog", "press", "release", "statement", "today", "yesterday", "tomorrow", "week", "weeks", "month", "months", "year", "years", "time", "times", "people", "thing", "things", "lot", "lots", "way", "ways", "kind", "sort", "really", "actually", "basically", "simply", "just", "even", "still", "also", "get", "gets", "got", "make", "makes", "made", "new", "news", "first", "second", "third"])

# Plausible-looking keywords that are too generic to rank for.
GENERIC_TECH = frozenset(["app", "apps", "feature", "features", "device", "devices", "gadget", "gadgets", "tech", "technology", "product", "products", "service", "services", "user", "users", "phone", "phones", "smartphone", "smartphones", "laptop", "laptops", "computer", "computers", "software", "hardware", "internet", "web", "online", "digital", "system", "systems", "platform", "platforms", "company", "companies", "firm", "firms", "startup", "startups", "thing", "things", "stuff", "content", "information", "details", "detail", "things"])

_CONTRACTION_TAIL = ("n't", "'s", "'re", "'ve", "'ll", "'d", "'m")


NON_TOPICAL = frozenset([
    # Modals and reporting verbs: frequent in news prose, useless as keywords, and
    # dangerous as synonyms ("will" must never become a primary keyword).
    "will", "would", "shall", "may", "might", "must", "said", "says", "saying",
    "tell", "tells", "told", "ask", "asks", "asked", "add", "adds", "added",
    "note", "notes", "noted", "explain", "explains", "explained", "confirm",
    "confirms", "confirmed", "report", "reports", "reported", "reportedly",
    "reveal", "reveals", "revealed", "announce", "announces", "announced",
    "claim", "claims", "claimed", "according", "per", "via", "amid", "alongside",
    "plus", "versus", "vs", "etc", "ie", "eg", "also", "however", "therefore",
    "thus", "meanwhile", "additionally", "overall", "respectively", "whether",
    "which", "who", "whom", "whose", "what", "when", "where", "why", "while",
    "since", "until", "unless", "upon", "onto", "toward", "towards", "across",
    "among", "within", "without", "every", "another", "others", "something",
    "anything", "everything", "nothing", "someone", "anyone", "everyone",
    "nobody", "several", "various", "numerous", "many", "much", "both",
    "being", "was", "were", "been", "had", "has", "have", "does", "did",
])


def is_stopword(token: str, *, domain: bool = True) -> bool:
    lowered = token.lower()
    return lowered in ENGLISH or lowered in NON_TOPICAL or (domain and lowered in DOMAIN)


def strip_stopwords(tokens: list[str], *, domain: bool = True) -> list[str]:
    return [token for token in tokens if not is_stopword(token, domain=domain)]


def content_words(tokens: list[str]) -> list[str]:
    """Stopword-free, length-filtered tokens: the basis of every keyword score."""
    return [token for token in tokens
            if not is_stopword(token) and len(token) > 2 and not token.isdigit()]


def expand_contractions(token: str) -> list[str]:
    """\"doesn't\" -> ['does', 'not'] so negation stays visible to sentiment."""
    lowered = token.lower()
    for tail in _CONTRACTION_TAIL:
        if lowered.endswith(tail):
            head = lowered[: -len(tail)]
            return [head, "not"] if tail == "n't" else [head]
    return [lowered]
