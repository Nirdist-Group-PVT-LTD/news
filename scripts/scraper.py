
import json, os, re, time, hashlib, html
from datetime import datetime, timezone
from urllib.parse import urlparse
import feedparser, requests
from bs4 import BeautifulSoup
from dateutil import parser as dtp
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = os.path.dirname(os.path.dirname(__file__))
CONFIG = os.path.join(ROOT, "config", "sources.json")
DATA = os.path.join(ROOT, "data", "items.json")
# DIST = os.path.join(ROOT, "dist")
DIST = os.path.join(ROOT, "docs")

os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)
os.makedirs(DIST, exist_ok=True)

def load_sources():
    with open(CONFIG, "r", encoding="utf-8") as f:
        return json.load(f)

def load_cache():
    if os.path.exists(DATA):
        with open(DATA, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_cache(items):
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def canonical_url(link:str)->str:
    # strip tracking params (basic)
    return re.sub(r"([?&])(utm_[^=]+|fbclid|gclid)=[^&]+", "", link)

def pick_image_from_entry(entry):
    # RSS media tags
    for key in ("media_content", "media_thumbnail", "enclosures"):
        if key in entry and entry[key]:
            try:
                if isinstance(entry[key], list):
                    return entry[key][0].get("url")
                elif isinstance(entry[key], dict):
                    return entry[key].get("url")
            except Exception:
                pass
    return None

def fetch_og_image(url, timeout=8):
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent":"Mozilla/5.0 (compatible; NirdistNewsBot/1.0)"})
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type",""):
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name":"twitter:image"})
        if og and og.get("content"):
            return og["content"]
    except Exception:
        return None
    return None

def to_iso(dt):
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return None

def human_time(dt):
    # show relative-ish time or date
    now = datetime.now(timezone.utc)
    delta = (now - dt).total_seconds()
    if delta < 3600:
        m = int(delta/60)
        return f"{m} min ago" if m >= 1 else "just now"
    if delta < 86400:
        h = int(delta/3600)
        return f"{h} hr ago"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")

def normalize_entry(entry, source_name):
    title = html.unescape(entry.get("title", "")).strip()
    link = canonical_url(entry.get("link","").strip())
    if not (title and link):
        return None

    # Published
    published_dt = None
    for key in ("published", "updated"):
        if entry.get(key):
            try:
                published_dt = dtp.parse(entry[key])
                break
            except Exception:
                pass
    if not published_dt and entry.get("published_parsed"):
        published_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if not published_dt:
        published_dt = datetime.now(timezone.utc)

    # Summary
    summary = BeautifulSoup(entry.get("summary",""), "html.parser").get_text().strip()
    summary = re.sub(r"\s+", " ", summary)[:300]

    # Image
    image = pick_image_from_entry(entry) or fetch_og_image(link)

    return {
        "id": hashlib.sha1(link.encode("utf-8")).hexdigest(),
        "title": title,
        "link": link,
        "source": source_name,
        "summary": summary,
        "image": image,
        "published": to_iso(published_dt),
        "published_human": human_time(published_dt),
    }

def fetch_all(sources):
    items = []
    for s in sources:
        feed_url = s["feed"]
        src_name = s["name"]
        fp = feedparser.parse(feed_url)
        for e in fp.entries[:30]:
            itm = normalize_entry(e, src_name)
            if itm:
                items.append(itm)
        # be polite
        time.sleep(0.5)
    return items

def merge_dedupe(existing, new_items, max_items=500):
    by_id = {i["id"]: i for i in existing}
    for i in new_items:
        by_id[i["id"]] = i
    all_items = list(by_id.values())
    all_items.sort(key=lambda x: x.get("published") or "", reverse=True)
    return all_items[:max_items]

def render_site(items):
    # Jinja env
    env = Environment(
        loader=FileSystemLoader(os.path.join(ROOT, "templates")),
        autoescape=select_autoescape()
    )
    ctx = {
        "title": "Nirdist News — Latest Updates",
        "description": "Automated, aggregated headlines with source links.",
        "updated_at": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M"),
        "items": items
    }
    # index.html
    html_out = env.get_template("index.html.j2").render(**ctx)
    with open(os.path.join(DIST, "index.html"), "w", encoding="utf-8") as f:
        f.write(html_out)

    # JSON feed
    json_feed = {
        "version": "https://jsonfeed.org/version/1.1",
        "title": "Nirdist News",
        "home_page_url": "https://news.nirdist.com.np/",
        "feed_url": "https://news.nirdist.com.np/feed.json",
        "items": [{
            "id": it["id"], "url": it["link"], "title": it["title"],
            "content_text": it.get("summary",""),
            "date_published": it.get("published"),
            "external_url": it["link"]
        } for it in items]
    }
    with open(os.path.join(DIST, "feed.json"), "w", encoding="utf-8") as f:
        json.dump(json_feed, f, ensure_ascii=False, indent=2)

    # robots + favicon + simple sitemap
    with open(os.path.join(DIST, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(open(os.path.join(ROOT, "static", "robots.txt"), "r", encoding="utf-8").read())
    with open(os.path.join(DIST, "favicon.svg"), "w", encoding="utf-8") as f:
        f.write("""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="12" fill="#0ea5e9"/><text x="32" y="40" font-size="28" text-anchor="middle" fill="white" font-family="Arial, Helvetica, sans-serif">N</text></svg>""")

    with open(os.path.join(DIST, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://news.nirdist.com.np/</loc><changefreq>hourly</changefreq></url>
</urlset>""")

    # CNAME for custom domain (Pages reads this from the artifact)
    with open(os.path.join(DIST, "CNAME"), "w", encoding="utf-8") as f:
        f.write("news.nirdist.com.np")

    # prevent Jekyll processing
    with open(os.path.join(DIST, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")

def main():
    sources = load_sources()
    existing = load_cache()
    fetched = fetch_all(sources)
    merged = merge_dedupe(existing, fetched)
    save_cache(merged)
    render_site(merged)

if __name__ == "__main__":
    main()
