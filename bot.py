# -*- coding: utf-8 -*-
"""
Khabarino - تک فایل bot.py
خبرخوان فارسی Bale

ویژگی‌ها:
- فقط خبر از منابع فارسی مشخص
- جلوگیری از تکرار خبر
- بازنویسی/ترجمه فارسی با Gemini در صورت وجود کلید
- هشتگ فارسی و موضوعی
- حداکثر یک عکس اصلی + یک ویدیو
- اگر عکس قابل ارسال نباشد، متن ارسال می‌شود
- ارسال پشت سر هم بدون تأخیر مصنوعی
- بدون requirements.txt؛ فقط Python 3.10+
"""

import os, re, json, time, html, hashlib
import urllib.request, urllib.parse, urllib.error
import xml.etree.ElementTree as ET

# ===================== تنظیمات =====================

BALE_TOKEN = os.getenv("91271977:HcpkSOrGvvC8Gli3qKNxP_z4wr86rFh9NRI", "").strip()
BALE_CHAT_ID = os.getenv("@KhabarinoNews", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "300"))
MAX_NEWS_PER_SCAN = int(os.getenv("MAX_NEWS_PER_SCAN", "30"))
STATE_FILE = "khabarino_state.json"
MAX_SEEN = 2500

# فقط منابع فارسی
SOURCE_DOMAINS = [
    "irna.ir",
    "isna.ir",
    "mehrnews.com",
    "tasnimnews.com",
    "khabaronline.ir",
    "tabnak.ir",
]

def make_feed(domain):
    q = urllib.parse.quote(f"site:{domain}")
    return f"https://news.google.com/rss/search?q={q}&hl=fa&gl=IR&ceid=IR:fa"

FEEDS = [make_feed(x) for x in SOURCE_DOMAINS]

HASHTAGS = {
    "ورزش": "#ورزش #اخبار",
    "اقتصاد": "#اقتصاد #اخبار",
    "فناوری": "#فناوری #تکنولوژی #اخبار",
    "سیاسی": "#سیاست #اخبار",
    "بین‌الملل": "#بین_الملل #اخبار",
    "اجتماعی": "#اجتماعی #اخبار",
    "حوادث": "#حوادث #اخبار",
    "فرهنگی": "#فرهنگ #اخبار",
    "علم": "#علم #اخبار",
    "سلامت": "#سلامت #اخبار",
    "عمومی": "#اخبار",
}

# ===================== ابزار =====================

def clean_text(s):
    if not s:
        return ""
    s = html.unescape(str(s))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"https?://\S+", "", s)
    return re.sub(r"\s+", " ", s).strip()

def http_get(url, timeout=20):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Chrome/120 Mobile Safari/537.36",
            "Accept-Language": "fa,en;q=0.7",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def http_json(url, payload, timeout=40):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def key_for(text):
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]

# ===================== حافظه =====================

def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"seen": []}
    except Exception:
        return {"seen": []}

def save_state():
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"seen": list(SEEN)[-MAX_SEEN:]}, f, ensure_ascii=False)
    except Exception as e:
        print("[STATE ERROR]", e)

SEEN = set(load_state().get("seen", []))

# ===================== RSS =====================

def parse_rss(raw):
    root = ET.fromstring(raw)
    out = []

    for item in root.iter():
        tag = item.tag.lower().split("}")[-1]
        if tag not in ("item", "entry"):
            continue

        def child(names):
            for c in list(item):
                ct = c.tag.lower().split("}")[-1]
                if ct in names:
                    return clean_text(c.text or "")
            return ""

        title = child({"title"})
        desc = child({"description", "summary", "content"})
        link = ""

        for c in list(item):
            ct = c.tag.lower().split("}")[-1]
            if ct == "link":
                link = c.attrib.get("href", "") or clean_text(c.text or "")
                if link:
                    break

        if not link:
            link = child({"guid", "id"})

        if title and link:
            out.append({
                "title": title,
                "description": desc,
                "url": link.strip(),
            })

    return out

def fetch_news():
    unique = {}

    for feed in FEEDS:
        try:
            items = parse_rss(http_get(feed))
            print("[RSS OK]", len(items))
            for item in items:
                unique[key_for(item["url"])] = item
        except Exception as e:
            print("[RSS ERROR]", e)

    return list(unique.values())[:MAX_NEWS_PER_SCAN]

# ===================== موضوع =====================

def detect_topic(text):
    t = text.lower()

    rules = {
        "ورزش": ["فوتبال","ورزش","لیگ","جام","بازیکن","تیم","مربی","بسکتبال","والیبال","پرسپولیس","استقلال"],
        "اقتصاد": ["اقتصاد","دلار","یورو","طلا","سکه","بورس","بانک","تورم","قیمت","بازار","نفت","ارز"],
        "فناوری": ["فناوری","تکنولوژی","هوش مصنوعی","موبایل","گوشی","سامسونگ","اپل","گوگل","اینترنت","ربات"],
        "سیاسی": ["رئیس جمهور","دولت","مجلس","وزیر","انتخابات","سیاست","مذاکره","تحریم","وزارت"],
        "بین‌الملل": ["آمریکا","اروپا","روسیه","چین","اسرائیل","جهان","بین‌الملل","سازمان ملل"],
        "حوادث": ["حادثه","تصادف","آتش سوزی","زلزله","سیل","انفجار","نجات","مفقود"],
        "فرهنگی": ["سینما","فیلم","تلویزیون","موسیقی","هنرمند","فرهنگ","کتاب","جشنواره"],
        "علم": ["علم","پژوهش","دانشمند","فضا","ناسا","کشف","آزمایش"],
        "سلامت": ["سلامت","بیماری","درمان","پزشک","دارو","بیمارستان"],
        "اجتماعی": ["اجتماعی","جامعه","مدرسه","دانشگاه","آموزش","خانواده","کارگر","مسکن"],
    }

    for topic, words in rules.items():
        if any(w.lower() in t for w in words):
            return topic
    return "عمومی"

# ===================== عکس و ویدیو =====================

def extract_media(article_url):
    image = ""
    video = ""

    try:
        text = http_get(article_url).decode("utf-8", errors="ignore")

        image_patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        ]
        video_patterns = [
            r'<meta[^>]+property=["\']og:video(?::url)?["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::url)?["\']',
            r'<video[^>]+src=["\']([^"\']+)',
            r'<source[^>]+src=["\']([^"\']+)',
        ]

        for p in image_patterns:
            m = re.search(p, text, re.I)
            if m:
                image = html.unescape(m.group(1).strip())
                break

        for p in video_patterns:
            m = re.search(p, text, re.I)
            if m:
                video = html.unescape(m.group(1).strip())
                break

        def absolute(u):
            if not u:
                return ""
            if u.startswith("//"):
                return "https:" + u
            if u.startswith("/"):
                p = urllib.parse.urlparse(article_url)
                return f"{p.scheme}://{p.netloc}{u}"
            return u

        image = absolute(image)
        video = absolute(video)

    except Exception as e:
        print("[MEDIA ERROR]", e)

    return image, video

# ===================== Gemini =====================

def rewrite_with_gemini(title, desc, topic):
    """
    حالت بدون API:
    چون API هوش مصنوعی نداریم، خبر فارسی را بدون ترجمه/بازنویسی خارجی
    منتشر می‌کنیم. متن تمیز و کوتاه می‌شود و موضوع از روی کلمات تشخیص داده می‌شود.
    """
    title = clean_text(title)
    desc = clean_text(desc)

    # اگر توضیح خیلی کوتاه/بی‌فایده است، فقط تیتر را نگه می‌داریم.
    if len(desc) < 20:
        desc = "برای مشاهده جزئیات خبر، منبع اصلی را باز کنید."

    return title, desc

# ===================== کپشن =====================

def build_caption(title, summary, topic):
    title = clean_text(title)
    summary = clean_text(summary)

    if len(title) > 180:
        title = title[:177] + "..."
    if len(summary) > 900:
        summary = summary[:897] + "..."

    return f"📰 {title}\n\n{summary}\n\n{HASHTAGS.get(topic, '#اخبار')}"

# ===================== Bale =====================

def bale_post(method, data):
    if not BALE_TOKEN:
        return None

    url = f"https://tapi.bale.ai/bot{BALE_TOKEN}/{method}"

    try:
        return http_json(url, data, timeout=30)
    except Exception as e:
        print("[BALE ERROR]", method, e)
        return None

def send_text(text):
    return bale_post("sendMessage", {
        "chat_id": BALE_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    })

def send_photo(url, caption):
    return bale_post("sendPhoto", {
        "chat_id": BALE_CHAT_ID,
        "photo": url,
        "caption": caption,
    })

def send_video(url, caption):
    return bale_post("sendVideo", {
        "chat_id": BALE_CHAT_ID,
        "video": url,
        "caption": caption,
    })

# ===================== پردازش خبر =====================

def process_item(item):
    news_id = key_for(item["url"])

    if news_id in SEEN:
        return False

    title = clean_text(item.get("title", ""))
    desc = clean_text(item.get("description", ""))

    if not title:
        return False

    # حذف موارد واضحاً تبلیغاتی
    bad = ["رپورتاژ", "تبلیغات", "فروش ویژه", "قرعه کشی", "اسپانسر"]
    if any(x in (title + " " + desc) for x in bad):
        SEEN.add(news_id)
        return False

    topic = detect_topic(title + " " + desc)
    title, desc = rewrite_with_gemini(title, desc, topic)
    caption = build_caption(title, desc, topic)

    image, video = extract_media(item["url"])

    sent = False

    # یک عکس + کپشن در همان پیام
    if image:
        r = send_photo(image, caption)
        if r and r.get("ok"):
            sent = True
        else:
            print("[PHOTO SKIP]", image)

    # اگر عکس نشد، متن را بفرست
    if not sent:
        r = send_text(caption)
        if r and r.get("ok"):
            sent = True
        else:
            print("[TEXT ERROR]", r)

    # حداکثر یک ویدیو
    if video:
        r = send_video(video, caption)
        if not (r and r.get("ok")):
            print("[VIDEO SKIP]", video)

    if sent:
        SEEN.add(news_id)
        save_state()
        print("[SENT]", title)
        return True

    return False

# ===================== شروع =====================

def main():
    if not BALE_TOKEN or not BALE_CHAT_ID:
        print("=" * 60)
        print("❌ تنظیمات ناقص است.")
        print("در GitHub Secrets این دو مورد را بساز:")
        print("BALE_TOKEN")
        print("BALE_CHAT_ID")
        print("این نسخه بدون API هوش مصنوعی کار می‌کند.")
        print("=" * 60)
        return

    print("=" * 60)
    print("🔥 KHABARINO تک فایل ONLINE")
    print("📰 منابع فارسی:", ", ".join(SOURCE_DOMAINS))
    print("📸 حداکثر 1 عکس | 🎥 حداکثر 1 ویدیو")
    print("🇮🇷 خروجی فارسی")
    print("=" * 60)

    while True:
        try:
            items = fetch_news()
            sent = 0

            for item in items:
                if sent >= MAX_NEWS_PER_SCAN:
                    break
                if process_item(item):
                    sent += 1

            print("[CYCLE DONE] sent =", sent)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print("[MAIN ERROR]", e)

        time.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    main()
