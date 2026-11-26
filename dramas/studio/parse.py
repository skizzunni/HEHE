"""Parse a drama script (.md) into a structured shot list.

Output: {"title", "title_cn", "style", "negative", "cast": [...], "scenes": [...]}
Each scene: {"id", "part", "part_title", "heading", "image", "motion",
             "items": [ {"kind": "line"|"system"|"onscreen"|"comments"|"title", ...} ]}
"""
import json
import re
import sys
from pathlib import Path

SPEAKER_RE = re.compile(
    r"""^\*{0,2}([A-Z][A-Z0-9 .'\-]*?)\s*(?:\(([^)]*)\))?\s*:\*{0,2}\s*(.+?)\s*$""")
SKIP_SPEAKERS = {"SFX", "MUSIC", "SFX/MUSIC", "TITLE CARD", "ON-SCREEN TEXT",
                 "ON SCREEN", "NOTE", "EDIT", "VO"}


def clean(text):
    text = text.strip().strip("*").strip()
    text = re.sub(r"\*+", "", text)
    if len(text) >= 2 and text[0] in "\"“'" and text[-1] in "\"”'":
        text = text[1:-1]
    return text.strip().strip('"“”').strip()


def strip_md(text):
    return re.sub(r"[`*_]", "", text).strip()


def parse_cast(lines):
    cast = []
    for ln in lines:
        m = re.match(r"^\|\s*\*\*(.+?)\*\*\s*\|(.*)$", ln)
        if not m:
            continue
        full = m.group(1).strip()
        cols = [c.strip() for c in m.group(2).split("|")]
        cols = [c for c in cols if c != ""]
        appearance = strip_md(cols[-1]) if cols else ""
        en = re.sub(r"[一-鿿]+", "", full).strip()
        cn = "".join(re.findall(r"[一-鿿]+", full))
        low = appearance.lower() + " " + (cols[1].lower() if len(cols) > 1 else "")
        female = bool(re.search(r"\b(woman|girl|noblewoman|grandmother|granny|"
                                r"mother|aunt|she|her|wife|daughter|princess)\b", low))
        male = bool(re.search(r"\b(man|boy|prince|general|emperor|grandfather|"
                              r"father|brother|he|his|husband|son)\b", low))
        gender = "F" if female and not (male and not female) else ("M" if male else "F")
        if female and male:
            # decide by the appearance prompt's first gendered noun
            fm = re.search(r"\b(woman|girl|noblewoman)\b", appearance.lower())
            mm = re.search(r"\b(man|boy|prince|general|emperor)\b", appearance.lower())
            gender = "F" if fm and (not mm or fm.start() < mm.start()) else "M"
        cast.append({"name": en, "cn": cn, "appearance": appearance, "gender": gender,
                     "age": cols[0] if cols else ""})
    return cast


def speaker_to_cast(speaker, cast):
    s = speaker.upper().replace("THE ", "").strip()
    for c in cast:
        n = c["name"].upper()
        parts = n.split()
        if s == n or s in parts or (len(parts) > 1 and s == " ".join(parts[1:])) \
                or (len(parts) > 1 and s == parts[-1]) or n.endswith(s) or s.endswith(n):
            return c["name"]
        if s.replace("GENERAL ", "") in n or s in n:
            return c["name"]
    return None


def parse(path):
    text = Path(path).read_text(encoding="utf-8")
    lines = text.splitlines()
    head = lines[0].lstrip("# ").strip()
    title, _, title_cn = head.partition("|")
    data = {"title": title.strip(), "title_cn": title_cn.strip(), "style": "",
            "negative": "", "cast": [], "scenes": []}

    # sections
    sections = {}
    cur = None
    for ln in lines:
        if ln.startswith("## "):
            cur = ln[3:].strip()
            sections[cur] = []
        elif cur:
            sections[cur].append(ln)

    def sec(prefix):
        for k, v in sections.items():
            if k.lower().startswith(prefix):
                return v
        return []

    style_lines = sec("style lock")
    blob = "\n".join(style_lines)
    ticks = re.findall(r"`([^`]{40,})`", blob)
    if ticks:
        data["style"] = ticks[0].strip()
        if len(ticks) > 1:
            data["negative"] = ticks[1].strip()
    else:
        for ln in style_lines:
            t = strip_md(ln)
            if len(t) > 60 and not data["style"]:
                data["style"] = t
    data["cast"] = parse_cast(sec("cast"))

    scenes = []

    def new_scene(sid, part, ptitle, heading):
        sc = {"id": sid, "part": part, "part_title": ptitle, "heading": heading,
              "image": "", "motion": "", "items": []}
        scenes.append(sc)
        return sc

    def feed(sc, ln):
        s = ln.strip()
        if not s or s == "---":
            return
        if s.startswith("🎬"):
            sc["image"] = strip_md(s.split(":", 1)[1]) if ":" in s else ""
            return
        if s.startswith("🎥"):
            sc["motion"] = strip_md(s.split(":", 1)[1]) if ":" in s else ""
            return
        if s.startswith("💬"):
            body = s.split(":", 1)[1] if ":" in s else s
            red = "red" in s.split(":", 1)[0].lower()
            comments = [clean(c) for c in re.split(r'"\s*/\s*"|”\s*/\s*“', body)]
            comments = [c for c in comments if c]
            sc["items"].append({"kind": "comments", "texts": comments, "red": red})
            return
        m = re.match(r"^\[(SYSTEM|ON SCREEN)[^:]*:\s*(.+?)\]\s*$", s)
        if m:
            kind = "system" if m.group(1) == "SYSTEM" else "onscreen"
            sc["items"].append({"kind": kind, "text": m.group(2).strip()})
            return
        low = strip_md(s).lower()
        if low.startswith("title card:") or low.startswith("on-screen text:"):
            sc["items"].append({"kind": "title", "text": strip_md(s.split(":", 1)[1])})
            return
        m = SPEAKER_RE.match(s)
        if m:
            spk = m.group(1).strip()
            if spk in SKIP_SPEAKERS or spk.startswith("SFX") or spk.startswith("CUT"):
                return
            if spk.startswith("TEXT ON SCREEN"):
                sc["items"].append({"kind": "onscreen", "text": clean(m.group(3))})
                return
            if spk == "CLIFFHANGER":
                spk = "NARRATOR"
            txt = clean(m.group(3))
            if not txt:
                return
            sc["items"].append({"kind": "line", "speaker": spk,
                                "emotion": (m.group(2) or "").strip(),
                                "cast": None if spk == "NARRATOR" else speaker_to_cast(spk, data["cast"]),
                                "text": txt, "cliff": s.startswith("**")})

    cold = sec("cold open")
    if cold:
        sc = new_scene("s00", 0, "Cold Open", "Cold Open")
        for ln in cold:
            feed(sc, ln)

    part, ptitle, sc = 0, "", None
    for ln in sec("script"):
        m = re.match(r"^###\s+Part\s+(\d+)\s*[—\-:]+\s*(.*)$", ln)
        if m:
            part, ptitle = int(m.group(1)), m.group(2).strip()
            continue
        m = re.match(r"^\*\*Scene\s+(\d+)\s*[—\-:]+\s*(.*?)\*\*\s*$", ln.strip())
        if m:
            sc = new_scene("s%02d" % int(m.group(1)), part, ptitle, m.group(2).strip())
            continue
        if sc is not None:
            feed(sc, ln)

    hook = sec("sequel hook")
    if hook:
        sc = new_scene("s99", 7, "Sequel Hook", "Sequel Hook")
        for ln in hook:
            feed(sc, ln)
        if not sc["image"]:
            scenes.pop()

    data["scenes"] = scenes
    return data


if __name__ == "__main__":
    d = parse(sys.argv[1])
    if len(sys.argv) > 2 and sys.argv[2] == "--summary":
        print(d["title"], "|", d["title_cn"])
        print("style:", d["style"][:80])
        print("cast:", [(c["name"], c["gender"]) for c in d["cast"]])
        nl = sum(1 for s in d["scenes"] for i in s["items"] if i["kind"] == "line")
        words = sum(len(i["text"].split()) for s in d["scenes"] for i in s["items"] if i["kind"] == "line")
        unk = {i["speaker"] for s in d["scenes"] for i in s["items"]
               if i["kind"] == "line" and i["speaker"] != "NARRATOR" and not i["cast"]}
        noimg = [s["id"] for s in d["scenes"] if not s["image"]]
        print(f"scenes={len(d['scenes'])} lines={nl} words={words} unmatched={sorted(unk)} noimg={noimg}")
    else:
        print(json.dumps(d, ensure_ascii=False, indent=1))
