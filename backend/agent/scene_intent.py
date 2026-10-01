import re


def scene_sample(message):
    text = message.strip()
    if not re.search(r'불러|로드|\bload\b|\bopen\b',text,re.I) or re.search(
            r"하지마|하지말|말고|마세요|금지|설명|방법|don't|do not|never|how to",text,re.I):
        return None
    ids = re.findall(r'(?<![A-Za-z0-9_])([A-Za-z][A-Za-z0-9_]{1,127})(?![A-Za-z0-9_])',text)
    ids = [value for value in ids if '_' in value and any(c.isdigit() for c in value)]
    return ids[0] if len(ids)==1 else None
