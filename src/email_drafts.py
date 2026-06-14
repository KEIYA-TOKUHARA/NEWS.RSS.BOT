import re
from pathlib import Path

try:
    from main import (
        article_dedupe_keys,
        clean_display_text,
        load_yaml,
        make_summary,
    )
except ModuleNotFoundError:
    from src.main import (
        article_dedupe_keys,
        clean_display_text,
        load_yaml,
        make_summary,
    )


CONFIG_FILE = Path("config/email_drafts.yaml")
DRAFTED_KEYS_FILE = Path("state/drafted_keys.txt")


def load_email_draft_config():
    if not CONFIG_FILE.exists():
        return {"enabled": False}

    config = load_yaml(CONFIG_FILE) or {}
    return config.get("email_drafts", {"enabled": False})


def load_drafted_keys():
    if not DRAFTED_KEYS_FILE.exists():
        return set()

    with open(DRAFTED_KEYS_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_drafted_keys(keys):
    DRAFTED_KEYS_FILE.parent.mkdir(exist_ok=True)

    with open(DRAFTED_KEYS_FILE, "w", encoding="utf-8") as f:
        for key in sorted(keys):
            f.write(key + "\n")


def get_draft_keys(article):
    return article_dedupe_keys(article)


def clean_subject_title(title):
    title = clean_display_text(title)
    title = re.sub(r"^【ＰＲ記事】\s*", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def build_draft_subject(article, config):
    prefix = config.get("subject_prefix", "【ニュース】")
    title = clean_subject_title(article.get("title", ""))
    return f"{prefix}{title}"


def extract_quoted_facility(title):
    title = clean_display_text(title)
    quoted_names = re.findall(r"[「『]([^」』]+)[」』]", title)

    for name in quoted_names:
        if any(word in name for word in ["ホテル", "旅館", "宿", "ヴィラ", "グランピング"]):
            return name

    return ""


def extract_facility_name(article):
    title = clean_display_text(article.get("title", ""))
    quoted = extract_quoted_facility(title)

    if quoted:
        return quoted

    patterns = [
        r"(アパホテル[^、\s]+)",
        r"((?:ホテル|旅館|宿|ヴィラ|グランピング)[^、。　\s]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            return match.group(1).strip()

    return ""


def extract_operator_company(article):
    title = clean_subject_title(article.get("title", ""))
    patterns = [
        r"^(アパホテル)",
        r"^(星野リゾート)",
        r"^(東横イン)",
        r"^(ルートイン)",
        r"^(共立メンテナンス)",
        r"^([^、。]+?)(?:、|は).{0,30}(?:取得|開業|運営|リブランド|プレオープン)",
    ]

    for pattern in patterns:
        match = re.search(pattern, title)
        if match:
            company = match.group(1).strip()
            if len(company) <= 30:
                return company

    return ""


def normalize_summary(summary):
    summary = make_summary(summary)
    forbidden_phrases = [
        "該当します",
        "と考えられます",
        "可能性があります",
        "判定しました",
        "営業機会",
    ]

    for phrase in forbidden_phrases:
        summary = summary.replace(phrase, "")

    return summary.strip()


def build_draft_body(article, judgement, config=None, extracted=None):
    config = config or load_email_draft_config()
    extracted = extracted or {}
    style = config.get("body_style", {})

    facility_name = extracted.get("facility_name", "")
    operator_company = extracted.get("operator_company", "")

    if style.get("include_facility_name", True) and not facility_name:
        facility_name = extract_facility_name(article)

    if style.get("include_operator_company", True) and not operator_company:
        operator_company = extract_operator_company(article)

    lines = [
        "■分類",
        judgement.get("category", ""),
        "",
        "■記事タイトル",
        clean_display_text(article.get("title", "")),
        "",
    ]

    if style.get("include_facility_name", True):
        lines.extend([
            "■施設名",
            facility_name or "",
            "",
        ])

    if style.get("include_operator_company", True):
        lines.extend([
            "■運営会社",
            operator_company or "",
            "",
        ])

    lines.extend([
        "■URL",
        article.get("link", ""),
        "",
        "■媒体",
        article.get("source", ""),
        "",
        "【概要】",
        normalize_summary(extracted.get("summary") or article.get("summary", "")),
    ])

    return "\n".join(lines).strip()


def build_draft(article, judgement, config=None, extracted=None):
    config = config or load_email_draft_config()

    return {
        "to": config.get("to", ""),
        "label": config.get("label", "下書き/ニュース"),
        "subject": build_draft_subject(article, config),
        "body": build_draft_body(article, judgement, config, extracted),
        "dedupe_keys": sorted(get_draft_keys(article)),
    }
