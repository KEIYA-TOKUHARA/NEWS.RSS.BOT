import feedparser, yaml, re

def load_yaml(p):
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)  # 安全な読み込み

conf = load_yaml("config/sources.yaml")
flt  = load_yaml("config/filters.yaml")
inc  = [re.compile(k) for k in flt["include"]]
exc  = [re.compile(k) for k in flt["exclude"]]

def match(text: str) -> bool:
    t = text or ""
    if not any(p.search(t) for p in inc):  # 1) 含める語にヒット必須
        return False
    if any(p.search(t) for p in exc):      # 2) 除外語に当たったら捨てる
        return False
    return True

picked = []
for s in conf["sources"]:
    d = feedparser.parse(s["url"])  # RSS/Atom/RDFに対応
    for e in d.entries:
        blob = " ".join([e.get("title",""), e.get("summary","")])
        if match(blob):
            picked.append(f"[{s['name']}] {e.get('title','(no title)')}  {e.get('link','')}")

for line in picked[:20]:
    print(line)
