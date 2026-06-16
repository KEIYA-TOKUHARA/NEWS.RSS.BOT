import feedparser
import yaml
import requests
import os
import re
import html
import json
import hashlib
import time
import calendar
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl


STATE_FILE = Path("state/posted_urls.txt")
STATE_KEYS_FILE = Path("state/posted_keys.txt")
SEARCH_CONFIG_FILE = Path("config/search_queries.yaml")
AI_CONFIG_FILE = Path("config/ai_judgement.yaml")
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
MAX_SLACK_POSTS_PER_RUN = int(os.environ.get("MAX_SLACK_POSTS_PER_RUN", "30"))
SLACK_POST_INTERVAL_SECONDS = float(os.environ.get("SLACK_POST_INTERVAL_SECONDS", "1.0"))
MAX_ARTICLE_AGE_DAYS = int(os.environ.get("MAX_ARTICLE_AGE_DAYS", "3"))
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_PARAMS = {
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "ref",
    "ref_src",
    "feature",
}
MEDIA_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".avif",
    ".svg",
    ".bmp",
)
GOOGLE_NEWS_RESOLVE_CACHE = {}
GENERIC_FACILITY_NAMES = {
    "ホテル",
    "旅館",
    "宿泊施設",
    "ホテル取得",
    "ホテル運営",
    "ホテルなど整備へ",
    "ホテルの開発",
    "ホテルの開発がスタート",
    "グランピング空間",
}
GENERIC_FACILITY_FRAGMENTS = (
    "など",
    "取得",
    "運営",
    "整備",
    "知見",
    "空間",
    "開発がスタート",
    "大チャンス",
)
TOPIC_ENTITY_WORDS = (
    "ホテル",
    "旅館",
    "宿",
    "ヴィラ",
    "グランピング",
    "温泉",
    "ランド",
    "パーク",
    "リゾート",
    "テーマパーク",
    "水族館",
)
LODGING_ENTITY_WORDS = (
    "ホテル",
    "旅館",
    "宿",
    "ヴィラ",
    "グランピング",
    "温泉",
)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_ai_config():
    if not AI_CONFIG_FILE.exists():
        return {"enabled": False}

    config = load_yaml(AI_CONFIG_FILE) or {}
    return config.get("ai_judgement", {"enabled": False})


def build_google_news_rss_url(query, hl="ja", gl="JP", ceid="JP:ja", recent_window=None):
    if recent_window and "when:" not in query:
        query = f"{query} when:{recent_window}"

    params = {
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid
    }
    return f"{GOOGLE_NEWS_RSS_BASE}?{urlencode(params)}"


def load_search_sources():
    if not SEARCH_CONFIG_FILE.exists():
        return []

    config = load_yaml(SEARCH_CONFIG_FILE) or {}
    google_news = config.get("google_news", {})
    defaults = google_news.get("defaults", {})
    queries = google_news.get("queries", [])

    sources = []

    for item in queries:
        if isinstance(item, str):
            name = item
            query = item
        else:
            name = item.get("name") or item.get("query")
            query = item.get("query")

        if not query:
            continue

        sources.append({
            "name": f"Google News検索: {name}",
            "url": build_google_news_rss_url(
                query=query,
                hl=defaults.get("hl", "ja"),
                gl=defaults.get("gl", "JP"),
                ceid=defaults.get("ceid", "JP:ja"),
                recent_window=defaults.get("recent_window")
            ),
            "source_type": "search",
            "query_name": name
        })

    return sources


def init_source_stats(name, source_type):
    return {
        "name": name,
        "source_type": source_type,
        "fetched": 0,
        "media_skipped": 0,
        "stale_skipped": 0,
        "duplicates": 0,
        "matched": 0,
        "ai_screened": 0,
        "ai_rejected": 0,
        "posted": 0
    }


def load_posted_urls():
    if not STATE_FILE.exists():
        return set()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def load_posted_keys():
    keys = set()

    if STATE_KEYS_FILE.exists():
        with open(STATE_KEYS_FILE, "r", encoding="utf-8") as f:
            keys.update(line.strip() for line in f if line.strip())

    for url in load_posted_urls():
        keys.add(url_dedupe_key(url))

    return keys


def save_posted_urls(urls):
    STATE_FILE.parent.mkdir(exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for url in sorted(urls):
            f.write(url + "\n")


def save_posted_keys(keys):
    STATE_KEYS_FILE.parent.mkdir(exist_ok=True)

    with open(STATE_KEYS_FILE, "w", encoding="utf-8") as f:
        for key in sorted(keys):
            f.write(key + "\n")


def canonicalize_url(url):
    if not url:
        return ""

    parts = urlsplit(url.strip())
    path = re.sub(r"/+", "/", parts.path)
    path = re.sub(r"^/articles/([^/]+)/images/.*$", r"/articles/\1", path)

    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_PARAMS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query_items.append((key, value))

    query = urlencode(query_items)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def is_google_news_url(url):
    parts = urlsplit(url)
    return parts.netloc.lower() == "news.google.com" and "/rss/articles/" in parts.path


def decode_google_news_url(url):
    if url in GOOGLE_NEWS_RESOLVE_CACHE:
        return GOOGLE_NEWS_RESOLVE_CACHE[url]

    headers = {"User-Agent": "Mozilla/5.0 (compatible; hospitality-news-bot/1.0)"}
    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()
    text = response.text

    article_id_match = re.search(r'data-n-a-id="([^"]+)"', text)
    timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', text)
    signature_match = re.search(r'data-n-a-sg="([^"]+)"', text)

    if not (article_id_match and timestamp_match and signature_match):
        GOOGLE_NEWS_RESOLVE_CACHE[url] = url
        return url

    article_id = article_id_match.group(1)
    timestamp = int(timestamp_match.group(1))
    signature = signature_match.group(1)
    request_payload = [[
        "Fbv4je",
        json.dumps([
            "garturlreq",
            [
                [
                    "ja", "JP",
                    ["FINANCE_TOP_INDICES", "WEB_TEST_1_0_0"],
                    None, None, 1, 1, "JP:ja", None, 180,
                    None, None, None, None, None, 0, None, None,
                    [timestamp, 0]
                ],
                "ja", "JP", 1, [2, 3, 4, 8], 1, 0,
                "655000234", 0, 0, None, 0
            ],
            article_id,
            timestamp,
            signature
        ]),
        None,
        "generic"
    ]]
    body = "f.req=" + urlencode({"": json.dumps([request_payload])})[1:]

    resolved_response = requests.post(
        "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je",
        headers={
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": headers["User-Agent"]
        },
        data=body,
        timeout=12
    )
    resolved_response.raise_for_status()
    urls = re.findall(r'https?://[^"\\\]]+', resolved_response.text)
    resolved_url = urls[0] if urls else url
    GOOGLE_NEWS_RESOLVE_CACHE[url] = resolved_url
    return resolved_url


def resolve_article_url(url):
    canonical_url = canonicalize_url(url)

    if not is_google_news_url(canonical_url):
        return canonical_url

    try:
        return canonicalize_url(decode_google_news_url(canonical_url))
    except Exception:
        return canonical_url


def is_media_url(url):
    if not url:
        return False

    path = urlsplit(url).path.lower()

    if path.endswith(MEDIA_EXTENSIONS):
        return True

    media_path_patterns = (
        r"/images?/",
        r"/photos?/",
        r"/photo-gallery/",
        r"/photogallery/",
        r"/gallery/",
    )

    return any(re.search(pattern, path) for pattern in media_path_patterns)


def is_photo_title(title):
    title = clean_display_text(title)
    photo_patterns = (
        r"^写真\d+/\d+",
        r"^画像\d+/\d+",
        r"^写真：",
        r"^画像：",
        r"写真一覧",
        r"画像一覧",
        r"フォトギャラリー",
    )
    return any(re.search(pattern, title) for pattern in photo_patterns)


def is_media_article(title, url):
    return is_photo_title(title) or is_media_url(url)


def clean_article_title(title):
    title = clean_display_text(title)
    title = re.sub(r"^写真\d+/\d+[｜|:：]\s*", "", title)
    title = re.sub(r"^画像\d+/\d+[｜|:：]\s*", "", title)
    return title.strip()


def normalize_title_for_key(title):
    title = clean_display_text(title)
    title = re.sub(r"\s*[-|｜]\s*(Yahoo!ニュース|PR TIMES|日本経済新聞|Impress Watch).*$", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip().lower()


def title_dedupe_key(title):
    normalized = normalize_title_for_key(title)

    if not normalized:
        return ""

    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    return f"title:{digest}"


def normalize_topic_entity(name):
    name = clean_display_text(name)
    name = re.sub(r"\s*[-|｜].*$", "", name)
    name = re.sub(r"[（）()「」『』【】]", "", name)
    name = re.sub(r"(?:の)?リゾート(?:化|構想|計画)$", "", name)
    name = re.sub(r"(?:の)?(?:大改装|土地取得|新取得|取得)$", "", name)
    if "ランド" in name and name.endswith("リゾート"):
        name = name[:-4]
    name = re.sub(r"\s+", "", name)
    name = name.strip("、。・:：")

    if name in GENERIC_FACILITY_NAMES:
        return ""

    if any(fragment in name for fragment in GENERIC_FACILITY_FRAGMENTS):
        return ""

    if len(name) < 4 or len(name) > 40:
        return ""

    if not any(word in name for word in TOPIC_ENTITY_WORDS):
        return ""

    return name.lower()


def extract_topic_entity_for_key(article):
    title = clean_display_text(article.get("title", ""))
    summary = clean_display_text(article.get("summary", ""))
    text = f"{title} {summary}"

    quoted_names = re.findall(r"[「『]([^」』]+)[」』]", text)
    for name in quoted_names:
        normalized = normalize_topic_entity(name)
        if normalized:
            return normalized

    patterns = [
        r"((?:アパホテル|東横イン|ドーミーイン|ホテルマイステイズ|コンフォートホテル|スーパーホテル)[^、。　\s]*)",
        r"((?:ホテル|旅館|宿|ヴィラ|グランピング|温泉)[ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30})",
        r"([ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30}(?:ホテル|旅館|宿|ヴィラ|グランピング|温泉))",
        r"([ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30}(?:ランド|パーク|リゾート|テーマパーク|水族館))",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            normalized = normalize_topic_entity(match.group(1))
            if normalized:
                return normalized

    return ""


def topic_entity_dedupe_key(article):
    topic_entity = extract_topic_entity_for_key(article)

    if not topic_entity:
        return ""

    digest = hashlib.sha256(topic_entity.encode("utf-8")).hexdigest()[:20]
    return f"topic:{digest}"


def legacy_facility_dedupe_key(article):
    topic_entity = extract_topic_entity_for_key(article)

    if not topic_entity:
        return ""

    if not any(word in topic_entity for word in LODGING_ENTITY_WORDS):
        return ""

    digest = hashlib.sha256(topic_entity.encode("utf-8")).hexdigest()[:20]
    return f"facility:{digest}"


def url_dedupe_key(url):
    canonical = canonicalize_url(url)
    parts = urlsplit(canonical)
    key = f"{parts.netloc}{parts.path}"

    if parts.query:
        key = f"{key}?{parts.query}"

    return f"url:{key}"


def article_dedupe_keys(article):
    keys = {url_dedupe_key(article.get("link", ""))}
    title_key = title_dedupe_key(article.get("title", ""))
    topic_entity_key = topic_entity_dedupe_key(article)
    legacy_facility_key = legacy_facility_dedupe_key(article)

    if title_key:
        keys.add(title_key)

    if topic_entity_key:
        keys.add(topic_entity_key)

    if legacy_facility_key:
        keys.add(legacy_facility_key)

    return keys


def clean_xml_text(text):
    if not text:
        return ""
    return re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", text)


def normalize_encoding_name(encoding):
    if not encoding:
        return None

    enc = encoding.lower().strip()

    if enc in ["cp51932", "x-euc-jp", "eucjp", "euc-jp"]:
        return "euc_jp"

    if enc in ["shift_jis", "shift-jis", "sjis", "cp932"]:
        return "cp932"

    return enc


def decode_response_content(response):
    candidates = []

    if response.encoding:
        candidates.append(response.encoding)

    if response.apparent_encoding:
        candidates.append(response.apparent_encoding)

    candidates.extend(["utf-8", "euc_jp", "cp932", "shift_jis"])

    tried = set()

    for enc in candidates:
        enc = normalize_encoding_name(enc)

        if not enc or enc in tried:
            continue

        tried.add(enc)

        try:
            return response.content.decode(enc, errors="ignore")
        except Exception:
            continue

    return response.content.decode("utf-8", errors="ignore")


def strip_tags(text):
    if not text:
        return ""

    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_display_text(text):
    """Slack表示用にHTMLエンティティやタグを整える"""
    if not text:
        return ""

    text = strip_tags(text)
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def make_summary(summary, max_chars=350):
    """RSS概要を社内共有用に整える"""
    summary = clean_display_text(summary)

    if not summary:
        return "概要取得なし"

    if len(summary) > max_chars:
        return summary[:max_chars].rstrip() + "…"

    return summary


def extract_tag(block, tag):
    pattern = rf"<{tag}[^>]*>(.*?)</{tag}>"
    m = re.search(pattern, block, flags=re.I | re.S)

    if not m:
        return ""

    value = m.group(1)
    value = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", value, flags=re.S)
    return strip_tags(value)


def fallback_extract_items(text):
    items = []
    blocks = re.findall(r"<item\b.*?</item>", text, flags=re.I | re.S)

    for block in blocks:
        title = extract_tag(block, "title")
        link = extract_tag(block, "link")
        summary = extract_tag(block, "description")

        if not title or not link:
            continue

        items.append({
            "title": title,
            "link": link,
            "summary": summary
        })

    return items


def parsed_time_to_timestamp(parsed_time):
    if not parsed_time:
        return None

    try:
        return calendar.timegm(parsed_time)
    except (OverflowError, TypeError, ValueError):
        return None


def is_stale_article(article, max_age_days=MAX_ARTICLE_AGE_DAYS):
    if max_age_days <= 0:
        return False

    published_ts = article.get("published_ts")

    if not published_ts:
        return False

    max_age_seconds = max_age_days * 24 * 60 * 60
    return published_ts < time.time() - max_age_seconds


def parse_feed_items(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; hospitality-news-bot/1.0)"
    }

    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()

    text = decode_response_content(response)
    text = clean_xml_text(text)

    feed = feedparser.parse(text)
    entries = getattr(feed, "entries", [])

    if entries:
        parsed_items = []
        for entry in entries:
            published_parsed = (
                entry.get("published_parsed")
                or entry.get("updated_parsed")
            )
            parsed_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "") or entry.get("description", ""),
                "published_ts": parsed_time_to_timestamp(published_parsed),
            })

        return parsed_items, getattr(feed, "bozo", 0), getattr(feed, "bozo_exception", None)

    fallback_items = fallback_extract_items(text)

    if fallback_items:
        return fallback_items, 1, "fallback_extract_items"

    return [], getattr(feed, "bozo", 0), getattr(feed, "bozo_exception", "entriesなし")


def find_matched_words(text, words):
    matched = []

    if not text:
        return matched

    for word in words:
        if word in text:
            matched.append(word)

    return matched


def judge_article(title, summary, filters):
    full_text = f"{title} {summary}"

    hospitality_words = filters.get("hospitality_words", [])
    exclude_words = filters.get("exclude_words", [])
    categories = filters.get("categories", {})

    matched_exclude = find_matched_words(full_text, exclude_words)

    if matched_exclude:
        return None

    matched_categories = []

    for category_key, category_data in categories.items():
        category_keywords = category_data.get("keywords", [])
        title_hospitality_required = category_data.get("title_hospitality_required", False)

        if title_hospitality_required:
            matched_hospitality = find_matched_words(title, hospitality_words)

            if not matched_hospitality:
                continue

            matched_keywords = find_matched_words(full_text, category_keywords)
        else:
            matched_hospitality = find_matched_words(full_text, hospitality_words)

            if not matched_hospitality:
                continue

            matched_keywords = find_matched_words(full_text, category_keywords)

        if matched_keywords:
            matched_categories.append({
                "key": category_key,
                "label": category_data.get("label", category_key),
                "priority": category_data.get("priority", 999),
                "matched_hospitality": matched_hospitality,
                "matched_keywords": matched_keywords
            })

    if not matched_categories:
        return None

    matched_categories.sort(key=lambda x: x["priority"])
    best = matched_categories[0]

    return {
        "category_key": best["key"],
        "category": best["label"],
        "priority": best["priority"],
        "matched_hospitality": best["matched_hospitality"],
        "matched_keywords": best["matched_keywords"]
    }


def score_article(title, judgement):
    score = max(40, 105 - judgement["priority"] * 10)
    title_matches = (
        find_matched_words(title, judgement["matched_hospitality"])
        + find_matched_words(title, judgement["matched_keywords"])
    )

    if title_matches:
        score += min(10, len(set(title_matches)) * 3)

    return min(score, 100)


def importance_label(score):
    if score >= 90:
        return "S"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B"
    return "C"


def attribute_label(judgement):
    category = judgement.get("category", "")
    prefix = category.split("：", 1)[0]

    if prefix in {"S", "A", "B", "C"}:
        return f"{prefix}案件"

    importance = judgement.get("importance", "C")
    return f"{importance}案件"


def attribute_rank(judgement):
    return attribute_label(judgement).replace("案件", "")


def select_items_for_posting(items, max_items):
    quotas = {
        "S": 12,
        "A": 7,
        "B": 6,
        "C": 5
    }
    selected = []
    selected_ids = set()

    for rank, quota in quotas.items():
        rank_items = [
            item for item in items
            if attribute_rank(item["judgement"]) == rank
        ]

        for item in rank_items[:quota]:
            selected.append(item)
            selected_ids.add(id(item))

    if len(selected) < max_items:
        for item in items:
            if id(item) in selected_ids:
                continue

            selected.append(item)
            selected_ids.add(id(item))

            if len(selected) >= max_items:
                break

    return selected[:max_items]


def get_ai_enabled(ai_config):
    return bool(ai_config.get("enabled")) and bool(os.environ.get("OPENAI_API_KEY"))


def build_ai_prompt(article, judgement, ai_config):
    criteria = ai_config.get("criteria", {})
    title = clean_display_text(article.get("title", ""))
    summary = make_summary(article.get("summary", ""), max_chars=700)

    return (
        "あなたは宿泊業界向けニュースBotの二次判定担当です。\n"
        "以下の記事候補が、宿泊施設向けの営業・業界把握に有用か判定してください。\n"
        "必ずJSONだけを返してください。\n\n"
        f"対象: {criteria.get('target', '')}\n"
        f"除外: {criteria.get('reject', '')}\n\n"
        f"媒体: {article.get('source', '')}\n"
        f"タイトル: {title}\n"
        f"概要: {summary}\n"
        f"キーワード分類: {judgement.get('category', '')}\n"
        f"キーワード判定理由: "
        f"{'、'.join(judgement.get('matched_hospitality', []))} × "
        f"{'、'.join(judgement.get('matched_keywords', []))}\n\n"
        "返すJSON形式:\n"
        "{\n"
        '  "relevant": true,\n'
        '  "score": 0,\n'
        '  "importance": "S",\n'
        '  "reason": "30文字以内の理由",\n'
        '  "summary": "60文字以内の要約"\n'
        "}\n"
        "scoreは0-100、importanceはS/A/B/Cのいずれか。"
    )


def call_openai_json(prompt, ai_config):
    api_key = os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return None

    model = os.environ.get("OPENAI_MODEL") or ai_config.get("model", "gpt-4.1-mini")

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You return strict JSON only. No markdown."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"}
    }

    response = requests.post(
        OPENAI_CHAT_COMPLETIONS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=ai_config.get("timeout_seconds", 20)
    )
    response.raise_for_status()

    content = response.json()["choices"][0]["message"]["content"]
    return json.loads(content)


def normalize_ai_result(result):
    if not isinstance(result, dict):
        return None

    raw_relevant = result.get("relevant")
    if isinstance(raw_relevant, str):
        relevant = raw_relevant.strip().lower() in {"true", "yes", "1", "relevant"}
    else:
        relevant = bool(raw_relevant)

    try:
        score = int(result.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    score = max(0, min(score, 100))
    importance = str(result.get("importance") or importance_label(score)).upper()

    if importance not in {"S", "A", "B", "C"}:
        importance = importance_label(score)

    return {
        "relevant": relevant,
        "score": score,
        "importance": importance,
        "reason": clean_display_text(str(result.get("reason", "")))[:60],
        "summary": clean_display_text(str(result.get("summary", "")))[:100]
    }


def ai_judge_article(article, judgement, ai_config):
    prompt = build_ai_prompt(article, judgement, ai_config)
    result = call_openai_json(prompt, ai_config)
    return normalize_ai_result(result)


def apply_ai_result(judgement, ai_result):
    judgement["ai"] = ai_result
    judgement["score"] = ai_result["score"]
    judgement["importance"] = ai_result["importance"]
    judgement["attribute"] = attribute_label(judgement)

    if ai_result.get("summary"):
        judgement["ai_summary"] = ai_result["summary"]

    if ai_result.get("reason"):
        judgement["ai_reason"] = ai_result["reason"]


def fetch_articles():
    sources = load_yaml("config/sources.yaml")
    articles = []

    if isinstance(sources, dict):
        source_list = sources.get("sources", [])
    else:
        source_list = sources

    source_list = source_list + load_search_sources()

    stats = {
        "target_sources": len(source_list),
        "success_sources": 0,
        "failed_sources": 0,
        "warning_sources": 0,
        "total_articles": 0,
        "ai_enabled": False,
        "ai_screened": 0,
        "ai_rejected": 0,
        "ai_errors": 0,
        "source_stats": {},
        "failed_source_details": [],
        "warning_source_details": []
    }

    for source in source_list:
        name = source.get("name", "unknown")
        url = source.get("url")
        source_type = source.get("source_type", "rss")
        stats["source_stats"][name] = init_source_stats(name, source_type)

        if not url:
            stats["failed_sources"] += 1
            stats["failed_source_details"].append(f"{name}: URLなし")
            continue

        try:
            items, bozo, bozo_exception = parse_feed_items(url)

            if not items:
                stats["failed_sources"] += 1
                stats["failed_source_details"].append(f"{name}: {bozo_exception or 'entriesなし'}")
                continue

            if bozo:
                stats["warning_sources"] += 1
                stats["warning_source_details"].append(f"{name}: {bozo_exception or 'RSS警告'}")

            entry_count = 0

            for item in items:
                title = clean_article_title(item.get("title", ""))
                link = canonicalize_url(item.get("link", ""))
                summary = item.get("summary", "")

                if not link:
                    continue

                if is_stale_article(item):
                    stats["source_stats"][name]["stale_skipped"] += 1
                    continue

                if is_media_article(title, link):
                    stats["source_stats"][name]["media_skipped"] += 1
                    continue

                articles.append({
                    "source": name,
                    "source_type": source_type,
                    "title": title,
                    "link": link,
                    "summary": summary,
                    "published_ts": item.get("published_ts"),
                })

                entry_count += 1

            stats["success_sources"] += 1
            stats["total_articles"] += entry_count
            stats["source_stats"][name]["fetched"] = entry_count

        except Exception as e:
            stats["failed_sources"] += 1
            stats["failed_source_details"].append(f"{name}: {e}")

    return articles, stats


def build_slack_message(article, judgement):
    title = clean_display_text(article["title"])
    link = article["link"]
    source = article["source"]
    summary = judgement.get("ai_summary") or make_summary(article.get("summary", ""))

    category = judgement["category"]
    attribute = judgement.get("attribute") or attribute_label(judgement)
    matched_hospitality = "、".join(judgement["matched_hospitality"])
    matched_keywords = "、".join(judgement["matched_keywords"])
    ai_reason = judgement.get("ai_reason")

    message = (
        f"■{category}\n"
        f"■ 案件属性 {attribute}\n"
        f"■ 記事タイトル {title}\n"
        f"■ URL {link}\n"
        f"■ 媒体 {source}\n"
        f"■ 判定理由 {matched_hospitality} × {matched_keywords}"
        + (f" / AI: {ai_reason}" if ai_reason else "")
        + "\n"
        f"【概要】 {summary}"
    )

    return message


def post_to_slack(messages):
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL が設定されていません。")

    for index, message in enumerate(messages):
        response = requests.post(
            webhook_url,
            json={"text": message},
            timeout=15
        )

        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "3"))
            time.sleep(retry_after)
            response = requests.post(
                webhook_url,
                json={"text": message},
                timeout=15
            )

        response.raise_for_status()

        if index < len(messages) - 1:
            time.sleep(SLACK_POST_INTERVAL_SECONDS)


def create_email_drafts(selected_items):
    try:
        from email_drafts import (
            build_draft,
            load_drafted_keys,
            load_email_draft_config,
            save_drafted_keys,
        )
        from gmail_api import create_draft, has_runtime_token
    except ModuleNotFoundError:
        from src.email_drafts import (
            build_draft,
            load_drafted_keys,
            load_email_draft_config,
            save_drafted_keys,
        )
        from src.gmail_api import create_draft, has_runtime_token

    config = load_email_draft_config()

    if not config.get("enabled"):
        return 0, 0

    if not has_runtime_token():
        print("Gmail token 未設定のため、下書き作成はスキップします。")
        return 0, 0

    drafted_keys = load_drafted_keys()
    new_drafted_keys = set(drafted_keys)
    max_drafts = int(config.get("max_drafts_per_run", 10) or 0)
    created_count = 0
    error_count = 0

    for item in selected_items:
        if max_drafts > 0 and created_count >= max_drafts:
            break

        article = item["article"]
        draft = build_draft(article, item["judgement"], config=config)
        draft_keys = set(draft.get("dedupe_keys", []))

        if draft_keys & drafted_keys or draft_keys & new_drafted_keys:
            continue

        try:
            create_draft(
                to=draft["to"],
                subject=draft["subject"],
                body=draft["body"],
                label_name=draft.get("label"),
            )
            created_count += 1
            new_drafted_keys.update(draft_keys)
        except Exception as e:
            error_count += 1
            print(f"Gmail下書き作成失敗: {article.get('title', '')} / {e}")

    if new_drafted_keys != drafted_keys:
        save_drafted_keys(new_drafted_keys)

    return created_count, error_count


def print_source_performance(stats):
    source_stats = stats.get("source_stats", {})
    rows = [
        row for row in source_stats.values()
        if (
            row["fetched"]
            or row["media_skipped"]
            or row["stale_skipped"]
            or row["duplicates"]
            or row["matched"]
            or row["ai_screened"]
            or row["ai_rejected"]
            or row["posted"]
        )
    ]

    if not rows:
        return

    rows.sort(key=lambda row: (row["posted"], row["matched"], row["fetched"]), reverse=True)

    print("---------- 取得元別パフォーマンス TOP20 ----------")
    for row in rows[:20]:
        print(
            f"{row['name']} [{row['source_type']}]: "
            f"取得{row['fetched']} / 画像除外{row['media_skipped']} / "
            f"古い記事除外{row['stale_skipped']} / "
            f"重複{row['duplicates']} / "
            f"一致{row['matched']} / AI判定{row['ai_screened']} / "
            f"AI除外{row['ai_rejected']} / 投稿{row['posted']}"
        )


def print_run_summary(stats, duplicate_skip_count, matched_count, slack_post_count):
    media_skip_count = sum(
        row["media_skipped"] for row in stats.get("source_stats", {}).values()
    )
    stale_skip_count = sum(
        row["stale_skipped"] for row in stats.get("source_stats", {}).values()
    )

    print("========== 実行サマリー ==========")
    print(f"対象サイト数：{stats['target_sources']}")
    print(f"取得成功サイト数：{stats['success_sources']}")
    print(f"取得失敗サイト数：{stats['failed_sources']}")
    print(f"取得警告サイト数：{stats['warning_sources']}")
    print(f"取得記事数：{stats['total_articles']}")
    print(f"画像URL除外数：{media_skip_count}")
    print(f"古い記事除外数：{stale_skip_count}")
    print(f"重複スキップ数：{duplicate_skip_count}")
    print(f"条件一致数：{matched_count}")
    print(f"AI判定：{'有効' if stats.get('ai_enabled') else '無効'}")
    print(f"AI判定数：{stats.get('ai_screened', 0)}")
    print(f"AI除外数：{stats.get('ai_rejected', 0)}")
    print(f"AIエラー数：{stats.get('ai_errors', 0)}")
    print(f"Slack投稿数：{slack_post_count}")

    print_source_performance(stats)

    if stats["warning_source_details"]:
        print("---------- 取得警告サイト ----------")
        for detail in stats["warning_source_details"]:
            print(detail)

    if stats["failed_source_details"]:
        print("---------- 取得失敗サイト ----------")
        for detail in stats["failed_source_details"]:
            print(detail)

    print("==================================")


def main():
    filters = load_yaml("config/filters.yaml")
    ai_config = load_ai_config()
    ai_enabled = get_ai_enabled(ai_config)
    ai_limit = int(ai_config.get("max_items_per_run", 0) or 0)
    min_ai_score_to_post = int(ai_config.get("min_score_to_post", 0) or 0)
    articles, stats = fetch_articles()
    stats["ai_enabled"] = ai_enabled

    posted_urls = load_posted_urls()
    new_posted_urls = set(posted_urls)
    posted_keys = load_posted_keys()
    new_posted_keys = set(posted_keys)

    messages = []
    posted_count_candidates = []
    posted_key_candidates = []
    email_draft_candidates = []
    matched_items = []
    seen_run_keys = set()

    duplicate_skip_count = 0
    matched_count = 0
    ai_used_count = 0

    for article in articles:
        url = article["link"]
        dedupe_keys = article_dedupe_keys(article)
        source_name = article["source"]
        source_stats = stats["source_stats"].get(source_name)

        if (
            url in posted_urls
            or dedupe_keys & posted_keys
            or dedupe_keys & seen_run_keys
        ):
            duplicate_skip_count += 1
            if source_stats:
                source_stats["duplicates"] += 1
            continue

        seen_run_keys.update(dedupe_keys)

        judgement = judge_article(
            article["title"],
            article.get("summary", ""),
            filters
        )

        if not judgement:
            continue

        judgement["score"] = score_article(article["title"], judgement)
        judgement["importance"] = importance_label(judgement["score"])
        judgement["attribute"] = attribute_label(judgement)

        matched_count += 1
        if source_stats:
            source_stats["matched"] += 1

        if ai_enabled and (ai_limit <= 0 or ai_used_count < ai_limit):
            ai_used_count += 1
            stats["ai_screened"] += 1
            if source_stats:
                source_stats["ai_screened"] += 1

            try:
                ai_result = ai_judge_article(article, judgement, ai_config)

                if ai_result:
                    apply_ai_result(judgement, ai_result)

                    if (
                        not ai_result["relevant"]
                        or ai_result["score"] < min_ai_score_to_post
                    ):
                        stats["ai_rejected"] += 1
                        if source_stats:
                            source_stats["ai_rejected"] += 1
                        continue
            except Exception as e:
                stats["ai_errors"] += 1
                stats["warning_source_details"].append(
                    f"{source_name}: AI判定失敗 {e}"
                )

        if source_stats:
            source_stats["posted"] += 1

        matched_items.append({
            "article": article,
            "judgement": judgement,
            "url": url,
            "dedupe_keys": dedupe_keys
        })

    matched_items.sort(
        key=lambda item: (
            item["judgement"]["score"],
            -item["judgement"]["priority"]
        ),
        reverse=True
    )

    selected_items = select_items_for_posting(matched_items, MAX_SLACK_POSTS_PER_RUN)

    if len(matched_items) > len(selected_items):
        print(
            f"Slack投稿上限により "
            f"{len(matched_items)}件中{len(selected_items)}件を投稿します。"
        )

    for item in selected_items:
        article = item["article"]
        resolved_url = resolve_article_url(item["url"])
        article["link"] = resolved_url

        if is_media_article(article["title"], resolved_url):
            continue

        resolved_keys = article_dedupe_keys(article)

        if resolved_keys & new_posted_keys:
            continue

        messages.append(build_slack_message(article, item["judgement"]))
        posted_count_candidates.append(resolved_url)
        posted_key_candidates.extend(resolved_keys)
        new_posted_keys.update(resolved_keys)
        email_draft_candidates.append({
            "article": article,
            "judgement": item["judgement"],
        })

    if not messages:
        save_posted_keys(new_posted_keys)
        print_run_summary(
            stats=stats,
            duplicate_skip_count=duplicate_skip_count,
            matched_count=matched_count,
            slack_post_count=0
        )
        print("新規該当ニュースなし。Slack通知は行いません。")
        return

    print(f"{len(messages)}件の新規ニュースをSlackへ投稿します。")

    post_to_slack(messages)

    email_draft_count, email_draft_error_count = create_email_drafts(email_draft_candidates)

    if email_draft_count or email_draft_error_count:
        print(
            f"Gmail下書き作成: {email_draft_count}件"
            f" / 失敗{email_draft_error_count}件"
        )

    for url in posted_count_candidates:
        new_posted_urls.add(url)

    for key in posted_key_candidates:
        new_posted_keys.add(key)

    save_posted_urls(new_posted_urls)
    save_posted_keys(new_posted_keys)

    print(f"投稿済みURLを {STATE_FILE} に保存しました。")
    print(f"投稿済み判定キーを {STATE_KEYS_FILE} に保存しました。")

    print_run_summary(
        stats=stats,
        duplicate_skip_count=duplicate_skip_count,
        matched_count=matched_count,
        slack_post_count=len(messages)
    )


if __name__ == "__main__":
    main()
