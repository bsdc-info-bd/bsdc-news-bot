import json
from datetime import datetime
from config import CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def get_blogger_service():
    creds = Credentials(None, refresh_token=REFRESH_TOKEN, client_id=CLIENT_ID,
                        client_secret=CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token"
                       )
    return build("blogger", "v3", credentials=creds)

def compose_google_news_schema(title, main_img):
    schema = {
        "@context": "[https://schema.org](https://schema.org)",
        "@type": "NewsArticle",
        "headline": title,
        "image": [main_img],
        "datePublished": datetime.utcnow().isoformat() + "Z",
        "author": {"@type": "Organization", "name": "bsdc news"},
        "publisher": {"@type": "Organization", "name": "bsdc news"},
        "description": title
    }
    return f'<script type="application/ld+json">{json.dumps(schema)}</script>'

def build_final_html(title, body_html, main_img, source_name, source_url):
    schema_json = compose_google_news_schema(title, main_img)
    
    seo_footer = """
    <div style="margin-top: 40px; padding: 22px; background: #f8fafc; border-left: 5px solid #2563eb; border-radius: 8px; font-family: sans-serif;">
        <h4 style="margin:0 0 8px 0; color:#1e293b; font-size: 16px;">About bsdc news</h4>
        <p style="margin:0; color:#475569; font-size:14px; line-height:1.6;">
            <strong>bsdc news</strong> is a digital news engine providing structured coverage on software architecture, web technologies, and tech updates.
        </p>
    </div>
    """

    return f"""
    {schema_json}
    <div style="font-size:17px; line-height:1.85; color:#1e293b; font-family:Georgia, serif;">
        {body_html}
    </div>
    <hr style="border:0; border-top:1px solid #e2e8f0; margin:35px 0;">
    <p style="font-size:12px; color:#94a3b8; font-family:sans-serif;">
        Source: {source_name} | <a href="{source_url}" target="_blank" rel="nofollow noopener noreferrer" style="color:#94a3b8; text-decoration:underline;">Original Article</a>
    </p>
    {seo_footer}
    """
