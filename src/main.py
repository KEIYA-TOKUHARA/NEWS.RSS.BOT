import feedparser
import yaml
import requests
import os
import re
import html
from pathlib import Path


STATE_FILE = Path("state/posted_urls.txt")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_posted_urls():
    if not STATE_FILE.exists():
        return set()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted_urls(urls):
    STATE_FILE.parent.mkdir(exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for url in sorted(urls):
            f.write(url + "\n")


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


def parse_feed_items(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; hospitality-news-bot/1.0)"
    }

    feed = feedparser.parse(url)
    entries = getattr(feed, "entries", [])

    if entries:
        parsed_items = []
        for entry in entries:
            parsed_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "") or entry.get("description", "")
            })

        return parsed_items, getattr(feed, "bozo", 0), getattr(feed, "bozo_exception", None)

    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()

    text = decode_response_content(response)
    text = clean_xml_text(text)

    feed2 = feedparser.parse(text)
    entries2 = getattr(feed2, "entries", [])

    if entries2:
        parsed_items = []
        for entry in entries2:
            parsed_items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", "") or entry.get("description", "")
            })

        return parsed_items, getattr(feed2, "bozo", 0), getattr(feed2, "bozo_exception", None)

    fallback_items = fallback_extract_items(text)

    if fallback_items:
        return fallback_items, 1, "fallback_extract_items"

    return [], getattr(feed2, "bozo", 0), getattr(feed2, "bozo_exception", "entriesなし")


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
        "category": best["label"],
        "matched_hospitality": best["matched_hospitality"],
        "matched_keywords": best["matched_keywords"]
    }


def fetch_articles():
    sources = load_yaml("config/sources.yaml")
    articles = []

    if isinstance(sources, dict):
        source_list = sources.get("sources", [])
    else:
        source_list = sources

    stats = {
        "target_sources": len(source_list),
        "success_sources": 0,
        "failed_sources": 0,
        "warning_sources": 0,
        "total_articles": 0,
        "failed_source_details": [],
        "warning_source_details": []
    }

    for source in source_list:
        name = source.get("name", "unknown")
        url = source.get("url")

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
                title = clean_display_text(item.get("title", ""))
                link = item.get("link", "")
                summary = item.get("summary", "")

                if not link:
                    continue

                articles.append({
                    "source": name,
                    "title": title,
                    "link": link,
                    "summary": summary
                })

                entry_count += 1

            stats["success_sources"] += 1
            stats["total_articles"] += entry_count

        except Exception as e:
            stats["failed_sources"] += 1
            stats["failed_source_details"].append(f"{name}: {e}")

    return articles, stats


def build_slack_message(article, judgement):
    title = clean_display_text(article["title"])
    link = article["link"]
    source = article["source"]
    summary = make_summary(article.get("summary", ""))

    category = judgement["category"]
    matched_hospitality = "、".join(judgement["matched_hospitality"])
    matched_keywords = "、".join(judgement["matched_keywords"])

    message = (
        f"■{category}\n"
        f"■ 記事タイトル {title}\n"
        f"■ URL {link}\n"
        f"■ 媒体 {source}\n"
        f"■ 判定理由 {matched_hospitality} × {matched_keywords}\n"
        f"【概要】 {summary}"
    )

    return message


def post_to_slack(messages):
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    if not webhook_url:
        raise RuntimeError("SLACK_WEBHOOK_URL が設定されていません。")

    for message in messages:
        response = requests.post(
            webhook_url,
            json={"text": message},
            timeout=15
        )
        response.raise_for_status()


def print_run_summary(stats, duplicate_skip_count, matched_count, slack_post_count):
    print("========== 実行サマリー ==========")
    print(f"対象サイト数：{stats['target_sources']}")
    print(f"取得成功サイト数：{stats['success_sources']}")
    print(f"取得失敗サイト数：{stats['failed_sources']}")
    print(f"取得警告サイト数：{stats['warning_sources']}")
    print(f"取得記事数：{stats['total_articles']}")
    print(f"重複スキップ数：{duplicate_skip_count}")
    print(f"条件一致数：{matched_count}")
    print(f"Slack投稿数：{slack_post_count}")

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
    articles, stats = fetch_articles()

    posted_urls = load_posted_urls()
    new_posted_urls = set(posted_urls)

    messages = []
    posted_count_candidates = []

    duplicate_skip_count = 0
    matched_count = 0

    for article in articles:
        url = article["link"]

        if url in posted_urls:
            duplicate_skip_count += 1
            continue

        judgement = judge_article(
            article["title"],
            article.get("summary", ""),
            filters
        )

        if not judgement:
            continue

        matched_count += 1
        messages.append(build_slack_message(article, judgement))
        posted_count_candidates.append(url)

    if not messages:
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

    for url in posted_count_candidates:
        new_posted_urls.add(url)

    save_posted_urls(new_posted_urls)

    print(f"投稿済みURLを {STATE_FILE} に保存しました。")

    print_run_summary(
        stats=stats,
        duplicate_skip_count=duplicate_skip_count,
        matched_count=matched_count,
        slack_post_count=len(messages)
    )


if __name__ == "__main__":
    main()