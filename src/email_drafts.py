import os
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
GENERIC_FACILITY_NAMES = {
    "ホテル",
    "旅館",
    "宿泊施設",
    "大型リゾート",
    "高級ホテル",
    "ブランドホテル",
    "ホテル取得",
    "ホテル運営",
    "ホテル開業予定",
    "ホテル開発",
    "ホテル開発計画",
    "ホテル旧",
    "ペブルブルック・ホテル",
    "ホテルなど整備へ",
    "ホテルの開発",
    "ホテルの開発がスタート",
    "ホテル沖縄初進出",
    "誕生ホテル",
    "ニュースホテル",
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
    "ニュース",
    "開業",
    "開業予定",
    "開発計画",
    "高級",
    "大型",
    "ブランド",
    "初進出",
    "CEO",
    "トラスト",
    "レストラン",
    "スポーツ",
    "球技",
    "完成",
    "施設",
    "楽しめる",
    "味わう",
    "どんな施設",
    "拠点",
    "相乗効果",
    "観光活性化",
    "株式",
    "相当",
    "税",
    "宿泊税",
    "導入",
    "調査",
    "アンケート",
    "意識調査",
    "準備状況",
    "制度",
    "条例",
    "課税",
    "税率",
    "事業者向け",
    "事業者",
    "宿泊事業者",
    "団体",
    "機構",
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
    "ビル",
    "ビーチ",
)
LOOSE_QUOTED_PREFIXES = (
    "界",
    "星のや",
    "OMO",
    "BEB",
    "ふふ",
)


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
        candidate = clean_facility_candidate(
            name,
            require_topic_word=not is_loose_quoted_entity(name),
        )
        if candidate:
            return candidate

    return ""


def is_loose_quoted_entity(name):
    name = clean_display_text(name).strip()

    if any(name.startswith(prefix) for prefix in LOOSE_QUOTED_PREFIXES):
        return True

    if re.search(r"[A-Z]{2,}", name):
        return True

    if name.endswith("の杜"):
        return True

    return False


def clean_facility_candidate(name, require_topic_word=True):
    name = clean_display_text(name)
    name = re.sub(r"\s*[-|｜].*$", "", name)
    name = re.sub(r"[（）()「」『』【】]", "", name)
    name = re.sub(r"(?:の)?リゾート(?:化|構想|計画)$", "", name)
    name = re.sub(r"(?:の)?(?:大改装|土地取得|新取得|取得)$", "", name)
    if "ランド" in name and name.endswith("リゾート"):
        name = name[:-4]
    name = re.sub(r"本社ビル$", "ビル", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip("、。・:：")

    if name in GENERIC_FACILITY_NAMES:
        return ""

    if any(fragment in name for fragment in GENERIC_FACILITY_FRAGMENTS):
        return ""

    min_length = 4 if require_topic_word else 3
    if len(name) < min_length or len(name) > 40:
        return ""

    if require_topic_word and not any(word in name for word in TOPIC_ENTITY_WORDS):
        return ""

    return name


def extract_facility_name(article):
    title = clean_display_text(article.get("title", ""))
    summary = clean_display_text(article.get("summary", ""))
    text = f"{title}。{summary}"
    quoted = extract_quoted_facility(title)

    if quoted:
        return quoted

    patterns = [
        r"((?:アパホテル|東横イン|ドーミーイン|ホテルマイステイズ|コンフォートホテル|スーパーホテル)[^、。　\s]*)",
        r"(旧[ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30}ビル)",
        r"((?:ホテル|旅館|宿|ヴィラ|グランピング|温泉)[ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30})",
        r"([ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30}(?:ホテル|旅館|宿|ヴィラ|グランピング|温泉))",
        r"([ァ-ヶー一-龥A-Za-z0-9・&＆'’\- ]{2,30}(?:ランド|パーク|リゾート|テーマパーク|水族館))",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            candidate = clean_facility_candidate(match.group(1))
            if candidate:
                return candidate

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
            if is_valid_operator_company(company):
                return company

    return ""


def is_valid_operator_company(company):
    company = clean_display_text(company)

    if not company or len(company) > 30:
        return False

    if any(mark in company for mark in ["「", "」", "『", "』"]):
        return False

    if company in GENERIC_FACILITY_NAMES:
        return False

    if any(fragment in company for fragment in GENERIC_FACILITY_FRAGMENTS):
        return False

    if any(word in company for word in ["ホテル", "旅館", "宿", "ヴィラ", "グランピング", "ビーチ", "ビル"]):
        return company in {"アパホテル", "東横イン", "星野リゾート"}

    return True


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


def normalize_signature(signature):
    if not signature:
        return ""

    signature = str(signature).replace("\\n", "\n").replace("\r\n", "\n")
    lines = [line.rstrip() for line in signature.splitlines()]
    return "\n".join(lines).strip()


def get_signature(config):
    return os.environ.get("EMAIL_SIGNATURE") or config.get("signature", "")


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
        f"■分類：{judgement.get('category', '')}",
        "■記事タイトル",
        clean_display_text(article.get("title", "")),
    ]

    if style.get("include_facility_name", True) and facility_name:
        lines.append(f"■施設名：{facility_name or ''}")

    if style.get("include_operator_company", True) and operator_company:
        lines.append(f"■運営会社：{operator_company or ''}")

    lines.extend([
        "■URL",
        article.get("link", ""),
        "【概要】",
        normalize_summary(extracted.get("summary") or article.get("summary", "")),
    ])

    body = "\n".join(lines).strip()
    signature = normalize_signature(get_signature(config))

    if signature:
        body = f"{body}\n\n{signature}"

    return body


def build_draft(article, judgement, config=None, extracted=None):
    config = config or load_email_draft_config()

    return {
        "to": config.get("to", ""),
        "label": config.get("label", "下書き/ニュース"),
        "subject": build_draft_subject(article, config),
        "body": build_draft_body(article, judgement, config, extracted),
        "dedupe_keys": sorted(get_draft_keys(article)),
    }
