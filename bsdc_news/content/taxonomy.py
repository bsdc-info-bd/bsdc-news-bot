"""Automatic categorisation and Blogger labels (keyword based, deterministic)."""

from __future__ import annotations

import re

from ..dedupe import keywords

DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "AI": ["ai", "artificial intelligence", "openai", "chatgpt", "gpt", "gemini", "claude", "anthropic",
           "llm", "machine learning", "copilot", "deepmind", "neural", "chatbot", "generative", "agent",
           "mistral", "llama", "grok", "perplexity", "nvidia h", "model"],
    "Cybersecurity": ["security", "hack", "hacker", "hackers", "breach", "ransomware", "malware",
                      "vulnerability", "zero-day", "exploit", "phishing", "cve", "cyber", "spyware",
                      "patch", "botnet", "ddos", "data leak", "stolen"],
    "Mobile": ["iphone", "android", "smartphone", "pixel", "galaxy", "samsung", "ios", "phone",
               "oneplus", "xiaomi", "motorola", "foldable", "tablet", "ipad", "wearable", "watch"],
    "Gadgets": ["laptop", "gadget", "headphones", "earbuds", "camera", "tv", "console", "playstation",
                "xbox", "nintendo", "switch", "macbook", "chromebook", "monitor", "keyboard", "drone",
                "review", "smart home", "speaker"],
    "Software": ["windows", "macos", "linux", "app", "apps", "update", "software", "browser", "chrome",
                 "firefox", "open source", "github", "developer", "programming", "python", "api",
                 "microsoft", "office", "cloud", "aws", "azure", "database"],
    "Business": ["startup", "funding", "raises", "ipo", "acquisition", "acquires", "merger", "revenue",
                 "earnings", "valuation", "layoffs", "stock", "shares", "investors", "ceo", "billion",
                 "antitrust", "lawsuit", "regulator", "ftc", "eu commission", "market"],
    "Science": ["nasa", "space", "spacex", "rocket", "satellite", "mars", "moon", "telescope",
                "climate", "physics", "quantum", "research", "scientists", "study", "biology", "fusion"],
    "Automotive": ["tesla", "ev", "electric vehicle", "electric car", "battery", "rivian", "byd",
                   "self-driving", "autonomous", "waymo", "charging", "car", "cars", "lucid"],
    "Gaming": ["game", "games", "gaming", "steam", "esports", "playstation", "xbox", "nintendo",
               "epic games", "fortnite", "gta", "valve"],
    "Internet": ["google", "meta", "facebook", "instagram", "whatsapp", "tiktok", "youtube", "x.com",
                 "twitter", "reddit", "social media", "search", "streaming", "netflix", "spotify"],
    "Bangladesh": ["bangladesh", "dhaka", "bangladeshi", "bdix", "btrc", "grameenphone", "robi",
                   "banglalink", "chattogram", "bkash"],
}

# Brands/products we promote to their own label when present
ENTITY_LABELS = [
    "OpenAI", "ChatGPT", "Google", "Gemini", "Apple", "iPhone", "Microsoft", "Windows", "Samsung",
    "Android", "Meta", "Amazon", "Nvidia", "Tesla", "SpaceX", "Intel", "AMD", "Qualcomm", "Anthropic",
    "Claude", "Xiaomi", "Sony", "Nintendo", "TikTok", "YouTube", "Netflix", "Linux", "GitHub", "Pixel",
    "Galaxy", "Huawei", "OnePlus", "Starlink", "NASA", "WhatsApp", "Instagram", "Bangladesh",
]


class Taxonomy:
    def __init__(self, settings) -> None:
        cats = dict(DEFAULT_CATEGORIES)
        custom = getattr(settings, "categories", {}) or {}
        for name, words in custom.items():
            if isinstance(words, list):
                cats[name] = [w.lower() for w in words]
        self.categories = cats
        self.max_labels = int(settings.get("publishing.labels_max", 6))
        self.default_labels = list(settings.get("publishing.default_labels", ["Tech News"]))

    def classify(self, title: str, text: str = "", hint: str = "") -> str:
        title_l = title.lower()
        body_l = (text or "")[:3000].lower()
        title_kw = keywords(title)
        best, best_score = "", 0.0
        for cat, words in self.categories.items():
            score = 0.0
            for w in words:
                if " " in w or "-" in w or "." in w:
                    if w in title_l:
                        score += 3
                    score += 0.5 * min(3, body_l.count(w))
                else:
                    if w in title_kw:
                        score += 3
                    score += 0.5 * min(3, len(re.findall(rf"\b{re.escape(w)}\b", body_l)))
            if score > best_score:
                best, best_score = cat, score
        if best_score >= 2:
            return best
        return hint if hint and hint != "Technology" else (best or hint or "Technology")

    def labels(self, title: str, text: str, category: str, ai_tags: list[str] | None = None,
               source: str = "") -> list[str]:
        out: list[str] = []

        def add(label: str) -> None:
            label = re.sub(r"[,<>&\"]", "", label).strip()
            if 2 <= len(label) <= 40 and label.lower() not in {x.lower() for x in out}:
                out.append(label)

        for d in self.default_labels:
            add(d)
        if category:
            add(category)
        body = (text or "")[:4000]
        # Entities named in the headline always become labels; entities from the body only when they
        # are a real subject of the story (mentioned at least twice), not a passing reference.
        for entity in ENTITY_LABELS:
            pattern = rf"\b{re.escape(entity)}\b"
            if re.search(pattern, title) or (len(re.findall(pattern, body)) >= 2 and len(out) < 4):
                add(entity)
        for tag in ai_tags or []:
            if len(tag.split()) <= 3:
                add(tag.title() if tag.islower() else tag)
        return out[: self.max_labels]
