import feedparser
import json
from datetime import datetime, timedelta

FEEDS = [
    "https://www.housingwire.com/feed/",
    "https://www.thetruthaboutmortgage.com/feed/",
    "https://www.keepingcurrentmatters.com/feed/",
    "https://www.cnbc.com/id/10000115/device/rss/rss.html",
    "https://www.redfin.com/news/feed/",
    "https://themortgagereports.com/feed",
    "https://www.mortgagenewsdaily.com/rss/full",
    "https://feeds.feedburner.com/inmannews"
]

def fetch_recent_entries(hours=24):
    cutoff = datetime.now() - timedelta(hours=hours)
    all_entries = []
    for url in FEEDS:
        feed = feedparser.parse(url)
        for entry in feed.entries:
            pub = datetime(*entry.published_parsed[:6]) if hasattr(entry, 'published_parsed') else None
            if pub and pub > cutoff:
                all_entries.append({
                    "title": entry.title,
                    "summary": entry.get("summary", ""),
                    "link": entry.link,
                    "published": pub.isoformat()
                })
    return all_entries

if __name__ == "__main__":
    entries = fetch_recent_entries()
    with open("daily_news.json", "w") as f:
        json.dump(entries, f, indent=2)
    print(f"Pulled {len(entries)} entries")