#!/usr/bin/env python3
"""Mirror Framer's public updates page to RSS and optionally notify a webhook."""

import json
import os
import re
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup
import requests


SOURCE = "https://www.framer.com/updates"
FEED = Path("docs/rss.xml")
HEARTBEAT = Path("heartbeat.txt")
HEADERS = {"User-Agent": "FramerUpdatesRSS/1.0 (+https://github.com/kyetbed/framer-updates-feed)"}


def fetch_updates():
    response = requests.get(SOURCE, headers=HEADERS, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    updates = []
    for section in soup.find_all("section"):
        heading = section.find("h2")
        link = heading.find("a", href=True) if heading else None
        date = section.find("time")
        if not link or not date:
            continue
        url = urljoin(SOURCE, link["href"]).split("?")[0]
        if not url.startswith("https://www.framer.com/updates/"):
            continue
        title = heading.get_text(" ", strip=True)
        raw_date = date.get("datetime") or date.get_text(" ", strip=True)
        try:
            published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        except ValueError:
            published = datetime.strptime(raw_date, "%B %d, %Y")
        published = published.replace(tzinfo=published.tzinfo or timezone.utc)
        paragraphs = [p.get_text(" ", strip=True) for p in section.find_all("p")]
        description = next((p for p in paragraphs if p and not p.startswith("Published ")), title)
        image = section.find("img", src=True)
        image_url = urljoin(SOURCE, image["src"]) if image else ""
        image_url = re.sub(r"https://i\.ytimg\.com/vi_webp/([^/]+)/([^/]+)\.webp$",
                           r"https://i.ytimg.com/vi/\1/\2.jpg", image_url)
        updates.append({"title": title, "url": url, "published": published,
                        "description": re.sub(r"\s+", " ", description)[:1200],
                        "image_url": image_url})
    unique = {item["url"]: item for item in updates}
    if not unique:
        raise RuntimeError("No update entries found; refusing to overwrite the feed")
    return sorted(unique.values(), key=lambda item: item["published"], reverse=True)


def read_feed():
    if not FEED.exists():
        return []
    root = ET.parse(FEED).getroot()
    items = []
    for node in root.findall("./channel/item"):
        fields = {child.tag: child.text or "" for child in node}
        items.append(fields)
    return items


def send_webhook(item, *, test=False):
    webhook = os.getenv("WEBHOOK_URL")
    if not webhook:
        if test:
            raise RuntimeError("WEBHOOK_URL secret is required for a test")
        print("WEBHOOK_URL not set; skipping webhook delivery")
        return
    payload = {
        "event": "framer.update.test" if test else "framer.update.published",
        "test": test,
        "title": item["title"],
        "url": item["url"],
        "published": item["published"].date().isoformat(),
        "description": item["description"],
        "image_url": item["image_url"],
        "guid": item["url"],
    }
    response = requests.post(webhook, json=payload, headers=HEADERS, timeout=30)
    response.raise_for_status()
    print(f"Delivered {'test' if test else 'new update'}: {item['title']}")


def write_feed(items):
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    for tag, value in (("title", "Framer Updates"), ("link", SOURCE),
                       ("description", "Updates published at framer.com/updates"),
                       ("language", "en")):
        ET.SubElement(channel, tag).text = value
    for item in items:
        node = ET.SubElement(channel, "item")
        for tag in ("title", "link", "guid", "pubDate", "description"):
            ET.SubElement(node, tag).text = item[tag]
    ET.indent(rss, space="  ")
    FEED.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(rss).write(FEED, encoding="utf-8", xml_declaration=True)


def main():
    current = fetch_updates()
    test_url = os.getenv("TEST_URL", "").strip()
    if test_url:
        match = next((item for item in current if item["url"] == test_url), None)
        if not match:
            raise RuntimeError(f"Test URL is not one of the currently listed updates: {test_url}")
        send_webhook(match, test=True)
        return

    previous = read_feed()
    previous_urls = {item["link"] for item in previous}
    discovered = [item for item in current if item["url"] not in previous_urls]
    # First run creates the archive without notifying for old posts.
    if previous:
        for item in reversed(discovered):
            send_webhook(item)
    else:
        print(f"Initial seed: {len(discovered)} existing updates; no webhook notifications")

    merged = {item["link"]: item for item in previous}
    for item in current:
        merged[item["url"]] = {
            "title": item["title"], "link": item["url"], "guid": item["url"],
            "pubDate": format_datetime(item["published"]), "description": item["description"],
        }
    ordered = sorted(merged.values(),
                     key=lambda item: datetime.strptime(item["pubDate"], "%a, %d %b %Y %H:%M:%S %z"),
                     reverse=True)
    if discovered or not FEED.exists() or ordered != previous:
        write_feed(ordered)
    print(f"Feed has {len(ordered)} items; {len(discovered) if previous else 0} new")

    # A monthly commit keeps GitHub's scheduled workflow active through quiet periods.
    now = datetime.now(timezone.utc)
    if not HEARTBEAT.exists() or (now - datetime.fromisoformat(HEARTBEAT.read_text().strip())).days >= 30:
        HEARTBEAT.write_text(now.isoformat() + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
