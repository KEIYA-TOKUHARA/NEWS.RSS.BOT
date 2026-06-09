import feedparser
import yaml
import requests
import os
import re
import html
import json
from pathlib import Path
from urllib.parse import urlencode


STATE_FILE = Path("state/posted_urls.txt")
SEARCH_CONFIG_FILE = Path("config/search_queries.yaml")
AI_CONFIG_FILE = Path("config/ai_judgement.yaml")
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


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

    response = requests.get(url, headers=headers, timeout=12)
    response.raise_for_status()

    text = decode_response_content(response)
    text = clean_xml_text(text)

    feed = feedparser.parse(text)
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
                title = clean_display_text(item.get("title", ""))
                link = item.get("link", "")
                summary = item.get("summary", "")

                if not link:
                    continue

                articles.append({
                    "source": name,
                    "source_type": source_type,
                    "title": title,
                    "link": link,
                    "summary": summary
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
    score = judgement["score"]
    importance = judgement["importance"]
    matched_hospitality = "、".join(judgement["matched_hospitality"])
    matched_keywords = "、".join(judgement["matched_keywords"])
    ai_reason = judgement.get("ai_reason")

    message = (
        f"■{category}\n"
        f"■ 重要度 {importance}（{score}点）\n"
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

    for message in messages:
        response = requests.post(
            webhook_url,
            json={"text": message},
            timeout=15
        )
        response.raise_for_status()


def print_source_performance(stats):
    source_stats = stats.get("source_stats", {})
    rows = [
        row for row in source_stats.values()
        if (
            row["fetched"]
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
            f"取得{row['fetched']} / 重複{row['duplicates']} / "
            f"一致{row['matched']} / AI判定{row['ai_screened']} / "
            f"AI除外{row['ai_rejected']} / 投稿{row['posted']}"
        )


def print_run_summary(stats, duplicate_skip_count, matched_count, slack_post_count):
    print("========== 実行サマリー ==========")
    print(f"対象サイト数：{stats['target_sources']}")
    print(f"取得成功サイト数：{stats['success_sources']}")
    print(f"取得失敗サイト数：{stats['failed_sources']}")
    print(f"取得警告サイト数：{stats['warning_sources']}")
    print(f"取得記事数：{stats['total_articles']}")
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

    messages = []
    posted_count_candidates = []
    matched_items = []
    seen_run_urls = set()

    duplicate_skip_count = 0
    matched_count = 0
    ai_used_count = 0

    for article in articles:
        url = article["link"]
        source_name = article["source"]
        source_stats = stats["source_stats"].get(source_name)

        if url in posted_urls or url in seen_run_urls:
            duplicate_skip_count += 1
            if source_stats:
                source_stats["duplicates"] += 1
            continue

        seen_run_urls.add(url)

        judgement = judge_article(
            article["title"],
            article.get("summary", ""),
            filters
        )

        if not judgement:
            continue

        judgement["score"] = score_article(article["title"], judgement)
        judgement["importance"] = importance_label(judgement["score"])

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
            "url": url
        })

    matched_items.sort(
        key=lambda item: (
            item["judgement"]["score"],
            -item["judgement"]["priority"]
        ),
        reverse=True
    )

    for item in matched_items:
        messages.append(build_slack_message(item["article"], item["judgement"]))
        posted_count_candidates.append(item["url"])

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
