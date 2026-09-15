from google import genai
from config import GEMINI_KEY
from colorama import Fore

ai_client = genai.Client(api_key=GEMINI_KEY)

def rewrite_with_gemini(title, raw_text):
    prompt = f"""
    You are a senior news editor for 'bsdc news'. Rewrite this raw content into a high-authority, 700+ word, fully structured article optimized for Google News.

    JOURNALISTIC STRUCTURE & RULES:
    1. Output ONLY valid body HTML (<p>, <h2>, <h3>, <ul>, <li>, <strong>, <mark>, blockquote). No <html>, <body>, or ```html wrappers.
    2. Format using traditional news style: Inverted Pyramid, Lead Paragraph, Key Facts, Context, and Expert Outlook.
    3. Remove all original promo links, author tags, and source website names from the article narrative.
    4. Fix all broken sentences, bad line breaks, and messy spaces.
    5. Embed 2-3 clear subheadings (<h2>) and highlight essential takeaways with <mark> tags.

    Headline: {title}
    Source Text:
    {raw_text[:4500]}
    """
    try:
        response = ai_client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        return response.text.replace("```html", "").replace("```", "").strip()
    except Exception as e:
        print(Fore.RED + f"   ⚠️ AI Generation Error: {e}")
        return None
