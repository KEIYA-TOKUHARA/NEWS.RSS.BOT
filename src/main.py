import feedparser
import yaml
import requests
import os
from pathlib import Path


STATE_FILE = Path("state/posted_urls.txt")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_posted_urls():
    """投稿済みURL一覧を読み込む"""
    if not STATE_FILE.exists():
        return set()

    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_posted_urls(urls):
    """投稿済みURL一覧を保存する"""
    STATE_FILE.parent.mkdir(exist_ok=True)

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        for url in sorted(urls):
            f.write(url + "\n")


def find_matched_words(text, words):
    """一致したワードを一覧で返す"""
    matched = []

    if not text:
        return matched

    for word in words:
        if word in text:
            matched.append(word)

    return matched


def judge_article(title, summary, filters):
    """
    ニュース記事を判定する。
    条件：
    1. 宿泊施設ワードが含まれる
    2. 除外ワードが含まれない
    3. カテゴリ別案件ワードが含まれる
    """
    text = f"{title} {summary}"

    hospitality_words = filters.get("hospitality_words", [])
    exclude_words = filters.get("exclude_words", [])
    categories = filters.get("categories", {})

    matched_hospitality = find_matched_words(text, hospitality_words)
    matched_exclude = find_matched_words(text, exclude_words)

    # 宿泊施設ワードがなければ除外
    if not matched_hospitality:
        return None

    # 除外ワードがあれば除外
    if matched_exclude:
        return None

    matched_categories = []

    for category_key, category_data in categories.items():
        category_keywords = category_data.get("keywords", [])
        matched_keywords = find_matched_words(text, category_keywords)

        if matched_keywords:
            matched_categories.append({
                "key": category_key,
                "label": category_data.get("label", category_key),
                "priority": category_data.get("priority", 999),
                "matched_keywords": matched_keywords
            })

    # 案件性ワードがなければ除外
    if not matched_categories:
        return None

    # 優先度が高いカテゴリを採用
    matched_categories.sort(key=lambda x: x["priority"])
    best = matched_categories[0]

    return {
        "category": best["label"],
        "matched_hospitality": matched_hospitality,
        "matched_keywords": best["matched_keywords"]
    }


def fetch_articles():
    """RSSから記事を取得する"""
    sources = load_yaml("config/sources.yaml")
    articles = []

    # sources.yaml が sources: の形でも、リスト直書きでも動くようにする
    if isinstance(sources, dict):
        source_list = sources.get("sources", [])
    else:
        source_list = sources

    for source in source_list:
        name = source.get("name", "unknown")
        url = source.get("url")

        if not url:
            continue

        feed = feedparser.parse(url)

        for entry in feed.entries:
            title = entry.get("title", "")
            link = entry.get("link", "")
            summary = entry.get("summary", "")

            if not link:
                continue

            articles.append({
                "source": name,
                "title": title,
                "link": link,
                "summary": summary
            })

    return articles


def build_slack_message(article, judgement):
    """Slack投稿用の本文を作る"""
    title = article["title"]
    link = article["link"]
    source = article["source"]
    category = judgement["category"]
    matched_hospitality = "、".join(judgement["matched_hospitality"])
    matched_keywords = "、".join(judgement["matched_keywords"])

    message = (
        f"■{category}\n"
        f"タイトル：{title}\n"
        f"媒体：{source}\n"
        f"判定理由：{matched_hospitality} × {matched_keywords}\n"
        f"URL：{link}"
    )

    return message


def post_to_slack(messages):
    """Slackに投稿する"""
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


def main():
    filters = load_yaml("config/filters.yaml")
    articles = fetch_articles()

    posted_urls = load_posted_urls()
    new_posted_urls = set(posted_urls)

    messages = []
    posted_count_candidates = []

    for article in articles:
        url = article["link"]

        # すでに投稿済みのURLならスキップ
        if url in posted_urls:
            continue

        judgement = judge_article(
            article["title"],
            article.get("summary", ""),
            filters
        )

        if not judgement:
            continue

        messages.append(build_slack_message(article, judgement))
        posted_count_candidates.append(url)

    if not messages:
        print("新規該当ニュースなし。Slack通知は行いません。")
        return

    print(f"{len(messages)}件の新規ニュースをSlackへ投稿します。")

    post_to_slack(messages)

    # Slack投稿に成功した後だけ、投稿済みURLとして保存
    for url in posted_count_candidates:
        new_posted_urls.add(url)

    save_posted_urls(new_posted_urls)

    print(f"投稿済みURLを {STATE_FILE} に保存しました。")


if __name__ == "__main__":
    main()