"""Operator notifications (all free): Telegram bot, Discord and Slack webhooks."""

from __future__ import annotations

from .http import HttpClient
from .log import get_logger
from .utils import truncate

log = get_logger("notify")


class Notifier:
    def __init__(self, settings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http
        self.telegram_token = settings.secret("telegram_bot_token")
        self.telegram_chat = settings.secret("telegram_chat_id")
        self.discord = settings.secret("discord_webhook_url")
        self.slack = settings.secret("slack_webhook_url")
        self.sent: list[str] = []

    @property
    def configured(self) -> list[str]:
        out = []
        if self.telegram_token and self.telegram_chat and self.settings.get("notify.telegram", True):
            out.append("telegram")
        if self.discord and self.settings.get("notify.discord", True):
            out.append("discord")
        if self.slack and self.settings.get("notify.slack", True):
            out.append("slack")
        return out

    def send(self, text: str, *, silent: bool = False) -> None:
        text = truncate(text, 3800)
        for channel in self.configured:
            try:
                if channel == "telegram":
                    resp = self.http.post(
                        f"https://api.telegram.org/bot{self.telegram_token}/sendMessage",
                        json={"chat_id": self.telegram_chat, "text": text, "parse_mode": "HTML",
                              "disable_web_page_preview": True, "disable_notification": silent}, timeout=15)
                elif channel == "discord":
                    resp = self.http.post(self.discord, json={"content": _plain(text)[:1990]}, timeout=15)
                else:
                    resp = self.http.post(self.slack, json={"text": _plain(text)}, timeout=15)
                if resp.status_code < 300:
                    self.sent.append(channel)
                else:
                    log.warning("Notification via %s failed: HTTP %s", channel, resp.status_code)
            except Exception as exc:
                log.warning("Notification via %s failed: %s", channel, exc)

    def run_summary(self, report) -> None:
        if not self.configured:
            return
        published = report.published
        failed = report.fatal_errors or report.warnings_for_notify()
        if not published and not failed:
            return
        lines = [f"<b>{self.settings.site_name}</b> — run {report.run_id}"]
        if published:
            lines.append(f"✅ Published {len(published)} post(s):")
            lines += [f"• <a href=\"{p['post_url']}\">{_html(p['title'])}</a> [{p['provider']}]" for p in published[:10]]
        if report.fatal_errors:
            lines.append("❌ Errors:")
            lines += [f"• {_html(e)}" for e in report.fatal_errors[:5]]
        elif failed:
            lines.append("⚠️ Attention:")
            lines += [f"• {_html(e)}" for e in failed[:5]]
        if report.run_url:
            lines.append(f"<a href=\"{report.run_url}\">Open run logs</a>")
        self.send("\n".join(lines), silent=bool(published and not report.fatal_errors))


def _html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _plain(text: str) -> str:
    import re

    text = re.sub(r"<a href=\"([^\"]+)\">([^<]+)</a>", r"\2 (\1)", text)
    return re.sub(r"</?b>", "**", text).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
