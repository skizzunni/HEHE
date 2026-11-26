#!/usr/bin/env python3
"""AI C-drama studio: script .md -> finished MP4 (16:9 main cut + 9:16 Shorts per Part).

Steps (each cached on disk, so re-running resumes where it stopped):
  refs      character reference portraits (one per cast member)
  images    2 stills per scene (wide + close), using the character refs for face consistency
  tts       one audio file per spoken line (Gemini TTS, a voice per character)
  video     Veo image-to-video for the key scenes (budgeted with --veo N)
  assemble  Ken Burns + Veo clips + narration + burned-in subtitles/overlays -> MP4
  shorts    one vertical Short per Part

Usage:
  python3 studio.py models                         # list available Gemini models
  python3 studio.py all ../03-ceo-divorce-regret.md --veo 16
  python3 studio.py all ../03-ceo-divorce-regret.md --dry   # placeholders, no API spend
Auth: the x-goog-api-key header is injected by the environment's network secret,
or set GEMINI_API_KEY.
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import time
import wave
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from parse import parse  # noqa: E402

API = "https://generativelanguage.googleapis.com/v1beta"
MODELS = {
    "image": os.environ.get("STUDIO_IMAGE_MODEL", "gemini-2.5-flash-image"),
    "tts": os.environ.get("STUDIO_TTS_MODEL", "gemini-2.5-flash-preview-tts"),
    "veo": os.environ.get("STUDIO_VEO_MODEL", "veo-3.1-fast-generate-preview"),
}
FPS = 30
W, H = 1920, 1080
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"

FEMALE_VOICES = ["Kore", "Leda", "Aoede", "Despina", "Callirrhoe", "Autonoe", "Erinome",
                 "Laomedeia", "Achernar", "Vindemiatrix", "Sulafat", "Pulcherrima"]
MALE_VOICES = ["Charon", "Puck", "Fenrir", "Orus", "Iapetus", "Umbriel", "Algieba",
               "Alnilam", "Schedar", "Achird", "Sadaltager", "Rasalgethi", "Enceladus"]
ELDER_F, ELDER_M = "Gacrux", "Algenib"

# ----------------------------------------------------------------------------- API


def headers():
    h = {"Content-Type": "application/json"}
    if os.environ.get("GEMINI_API_KEY"):
        h["x-goog-api-key"] = os.environ["GEMINI_API_KEY"]
    return h


def post(url, body, tries=6):
    delay = 8
    for attempt in range(tries):
        try:
            r = requests.post(url, headers=headers(), json=body, timeout=300)
        except requests.RequestException as e:
            err = str(e)
        else:
            if r.ok:
                return r.json()
            err = f"{r.status_code} {r.text[:400]}"
            if r.status_code in (400, 401, 403, 404):
                raise RuntimeError(err)
        print(f"   retry {attempt + 1}/{tries}: {err[:160]}", flush=True)
        time.sleep(delay)
        delay = min(delay * 2, 120)
    raise RuntimeError(err)


def list_models():
    r = requests.get(f"{API}/models?pageSize=1000", headers=headers(), timeout=60)
    r.raise_for_status()
    for m in r.json().get("models", []):
        print(m["name"].split("/")[-1], "|", ",".join(m.get("supportedGenerationMethods", [])))


def gen_image(prompt, refs, out):
    parts = []
    for label, path in refs:
        parts.append({"text": f"Reference photo of {label} (keep this exact face, hair and look):"})
        parts.append({"inline_data": {"mime_type": "image/png",
                                      "data": base64.b64encode(Path(path).read_bytes()).decode()}})
    parts.append({"text": prompt})
    body = {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"],
                                 "imageConfig": {"aspectRatio": "16:9"}}}
    for attempt in range(3):
        js = post(f"{API}/models/{MODELS['image']}:generateContent", body)
        for cand in js.get("candidates", []):
            for p in cand.get("content", {}).get("parts", []):
                d = p.get("inlineData") or p.get("inline_data")
                if d and d.get("data"):
                    raw = base64.b64decode(d["data"])
                    tmp = out.with_suffix(".raw")
                    tmp.write_bytes(raw)
                    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), str(out)])
                    tmp.unlink()
                    return
        print(f"   no image returned ({json.dumps(js)[:200]}), retrying", flush=True)
        time.sleep(5)
    raise RuntimeError(f"image generation failed for {out.name}")


def gen_tts(text, voice, direction, out):
    prompt = f"{direction}: {text}" if direction else text
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {
                                     "prebuiltVoiceConfig": {"voiceName": voice}}}}}
    js = post(f"{API}/models/{MODELS['tts']}:generateContent", body)
    d = js["candidates"][0]["content"]["parts"][0]["inlineData"]
    pcm = base64.b64decode(d["data"])
    rate = int(re.search(r"rate=(\d+)", d.get("mimeType", "rate=24000")).group(1))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def gen_veo(prompt, image, out):
    inst = {"prompt": prompt,
            "image": {"bytesBase64Encoded": base64.b64encode(Path(image).read_bytes()).decode(),
                      "mimeType": "image/png"}}
    params = {"aspectRatio": "16:9", "durationSeconds": 8, "personGeneration": "allow_adult"}
    url = f"{API}/models/{MODELS['veo']}:predictLongRunning"
    try:
        op = post(url, {"instances": [inst], "parameters": params})
    except RuntimeError as e:
        if "400" not in str(e):
            raise
        params.pop("personGeneration")
        op = post(url, {"instances": [inst], "parameters": params})
    name = op["name"]
    t0 = time.time()
    while True:
        time.sleep(10)
        st = requests.get(f"{API}/{name}", headers=headers(), timeout=60).json()
        if st.get("done"):
            break
        if time.time() - t0 > 900:
            raise RuntimeError("veo timed out")
    if "error" in st:
        raise RuntimeError(f"veo error: {st['error']}")
    resp = st.get("response", {})
    samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
               or resp.get("generatedVideos") or [])
    if not samples:
        raise RuntimeError(f"veo returned no video (maybe filtered): {json.dumps(st)[:300]}")
    uri = samples[0]["video"]["uri"]
    r = requests.get(uri, headers=headers(), timeout=300, allow_redirects=True)
    r.raise_for_status()
    out.write_bytes(r.content)

# ----------------------------------------------------------------------------- helpers


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:6])}...\n{p.stderr[-1500:]}")
    return p.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "csv=p=0", str(path)]).strip())


def slug(path):
    return Path(path).stem


def h8(s):
    return hashlib.sha1(s.encode()).hexdigest()[:8]


def pmap(fn, jobs, workers):
    errors = []
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(fn, j): j for j in jobs}
        for f in cf.as_completed(futs):
            try:
                f.result()
            except Exception as e:  # keep going; report at the end
                errors.append(f"{futs[f]}: {e}")
                print("   ERROR", str(e)[:300], flush=True)
    return errors


def mentions(sc_text, cast):
    """Cast members referenced in an image prompt, in order of appearance."""
    found = []
    low = sc_text.lower()
    for c in cast:
        names = [c["name"].lower()] + [p.lower() for p in c["name"].split() if len(p) > 3]
        first = c["name"].split()[-1].lower()
        names.append(first)
        pos = min([low.find(n) for n in names if low.find(n) >= 0] or [-1])
        if pos >= 0:
            found.append((pos, c))
    return [c for _, c in sorted(found, key=lambda x: x[0])]


def placeholder(out, label, color):
    txt = re.sub(r"[^A-Za-z0-9 ,.\-]", "", label)[:60]
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
         f"color=c={color}:s={W}x{H}", "-frames:v", "1", "-vf",
         f"drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
         f"text='{txt}':fontcolor=white:fontsize=44:x=(w-tw)/2:y=(h-th)/2", str(out)])

# ----------------------------------------------------------------------------- project


class Project:
    def __init__(self, script, dry=False):
        self.script = Path(script).resolve()
        self.d = parse(self.script)
        self.dry = dry
        self.dir = BUILD / (slug(script) + ("-dry" if dry else ""))
        for sub in ("refs", "img", "tts", "veo", "seg", "out"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        (self.dir / "shots.json").write_text(json.dumps(self.d, ensure_ascii=False, indent=1))
        self.voices = self.assign_voices()

    # --- voices
    def assign_voices(self):
        f, m = list(FEMALE_VOICES), list(MALE_VOICES)
        v = {}
        for c in self.d["cast"]:
            age = int((re.findall(r"\d+", c["age"]) or ["30"])[0])
            if age >= 65:
                v[c["name"]] = ELDER_F if c["gender"] == "F" else ELDER_M
            else:
                v[c["name"]] = (f if c["gender"] == "F" else m).pop(0)
        lead = self.d["cast"][0]["name"]
        v["NARRATOR"] = v[lead]
        return v

    def voice_for(self, item):
        if item["speaker"] == "NARRATOR":
            return self.voices["NARRATOR"]
        if item["cast"]:
            return self.voices[item["cast"]]
        spk = item["speaker"]
        fem = re.search(r"MOTHER|AUNT|NURSE|MAID|GRAN|WOMAN|GIRL|MADAME|LADY|HOSTESS|SISTER", spk)
        pool = ["Zephyr", "Sadachbia"] if fem else ["Zubenelgenubi", "Sadaltager", "Achird"]
        return pool[int(h8(spk), 16) % len(pool)]

    def direction(self, item):
        emo = item["emotion"]
        if item["speaker"] == "NARRATOR":
            base = ("Narrate in an intimate, gripping first-person storytelling voice, "
                    "like a dramatic audiobook")
            return base + (f", {emo}" if emo else "")
        return f"Say it as a drama actor, {emo}" if emo else "Say it as a drama actor, natural and expressive"

    # --- jobs
    def lines(self):
        for sc in self.d["scenes"]:
            for i, it in enumerate(sc["items"]):
                if it["kind"] == "line":
                    yield sc, i, it

    def tts_path(self, sc, i):
        return self.dir / "tts" / f"{sc['id']}_{i:02d}.wav"

    def img_path(self, sc, k):
        return self.dir / "img" / f"{sc['id']}_{k}.png"

    def ref_path(self, c):
        return self.dir / "refs" / (re.sub(r"\W+", "_", c["name"]).strip("_") + ".png")

    def veo_scenes(self, n):
        sc = [s for s in self.d["scenes"] if s["image"]]
        if n <= 0:
            return []
        must = [sc[0]]  # cold open
        parts = {}
        for s in sc:
            parts.setdefault(s["part"], []).append(s)
        for p, ss in sorted(parts.items()):
            if 1 <= p <= 6:
                must.append(ss[-1])  # cliffhanger scene of each Part
        hot = re.compile(r"slap|kneel|stand|rise|reveal|mask|throw|shatter|explode|burst|"
                         r"tear|turn|grab|run|fall|kiss|embrace|snow|rain|door|fire", re.I)
        rest = [s for s in sc if s not in must]
        rest.sort(key=lambda s: -len(hot.findall(s["motion"] + " " + s["image"])))
        picked = must + rest
        chosen = {s["id"] for s in picked[:n]}
        return [s for s in sc if s["id"] in chosen]

    # --- steps
    def step_refs(self):
        style = self.d["style"]
        def job(c):
            out = self.ref_path(c)
            if out.exists():
                return
            print(f" ref  {c['name']}", flush=True)
            if self.dry:
                return placeholder(out, c["name"], "0x334455")
            gen_image(f"Character reference portrait: {c['appearance']}. Medium close-up, "
                      f"facing camera, neutral soft studio background, even lighting, the "
                      f"whole head and shoulders visible. {style}. No text.", [], out)
        return pmap(job, self.d["cast"], 3)

    def step_images(self):
        style, cast = self.d["style"], self.d["cast"]
        jobs = []
        for sc in self.d["scenes"]:
            if not sc["image"]:
                continue
            jobs.append((sc, "a"))
            jobs.append((sc, "b"))
        def job(j):
            sc, k = j
            out = self.img_path(sc, k)
            if out.exists():
                return
            print(f" img  {sc['id']}{k}", flush=True)
            if self.dry:
                return placeholder(out, f"{sc['id']}{k} {sc['heading']}",
                                   "0x2a1f3d" if k == "a" else "0x3d1f2a")
            who = mentions(sc["image"], cast)[:3]
            refs = [(c["name"], self.ref_path(c)) for c in who if self.ref_path(c).exists()]
            shot = ("Wide cinematic establishing shot showing the full scene"
                    if k == "a" else
                    "Closer emotional shot of the same moment: medium close-up on the main "
                    "character's face and expression, same setting, lighting and outfits")
            prompt = (f"{shot}. Scene: {sc['image']}. {style}. 16:9 film frame, "
                      f"no text, no subtitles, no watermark. Avoid: {self.d['negative']}")
            gen_image(prompt, refs, out)
        return pmap(job, jobs, 4)

    def step_tts(self):
        def job(j):
            sc, i, it = j
            out = self.tts_path(sc, i)
            if out.exists():
                return
            if self.dry:
                secs = max(1.2, len(it["text"].split()) / 2.6)
                run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                     "anullsrc=r=24000:cl=mono", "-t", f"{secs:.2f}", str(out)])
                return
            print(f" tts  {sc['id']}_{i:02d} [{self.voice_for(it)}] {it['text'][:50]}", flush=True)
            gen_tts(it["text"], self.voice_for(it), self.direction(it), out)
        return pmap(job, list(self.lines()), 4)

    def step_video(self, n):
        if self.dry:
            return []
        def job(sc):
            out = self.dir / "veo" / f"{sc['id']}.mp4"
            img = self.img_path(sc, "a")
            if out.exists() or not img.exists():
                return
            print(f" veo  {sc['id']}  {sc['motion'][:60]}", flush=True)
            prompt = (f"{sc['motion']} Cinematic Chinese drama shot, subtle realistic motion, "
                      f"keep faces consistent. No text, no subtitles, no music.")
            gen_veo(prompt, img, out)
        return pmap(job, self.veo_scenes(n), 2)

    # --- assembly
    def scene_timeline(self, sc):
        """Lay out a scene: returns (duration, audio_clips[(path,start)], events[...])."""
        t = 0.35
        clips, events, pending = [], [], []
        for i, it in enumerate(sc["items"]):
            if it["kind"] == "line":
                p = self.tts_path(sc, i)
                if not p.exists():
                    continue
                d = duration(p)
                for ev in pending:
                    ev["start"] = t
                    events.append(ev)
                pending = []
                clips.append((p, t))
                events.append({"kind": "line", "start": t, "end": t + d, "text": it["text"],
                               "narr": it["speaker"] == "NARRATOR"})
                t += d + (1.0 if it.get("cliff") else 0.3)
            else:
                ev = dict(it)
                ev["start"] = t
                pending.append(ev)
        if pending:
            for ev in pending:
                ev["start"] = t
                events.append(ev)
            t += 3.0
        dur = max(t + 0.2, 3.5)
        for ev in events:
            if ev["kind"] != "line":
                ev["end"] = min(ev["start"] + (6.0 if ev["kind"] == "comments" else 3.5), dur)
        return dur, clips, events

    def render_scene(self, sc, idx, dur, clips):
        out = self.dir / "seg" / f"{sc['id']}.mp4"
        key = h8(json.dumps([dur, [str(c) for c in clips], self.dry]))
        stamp = out.with_suffix(".key")
        if out.exists() and stamp.exists() and stamp.read_text() == key:
            return out
        veo = self.dir / "veo" / f"{sc['id']}.mp4"
        a, b = self.img_path(sc, "a"), self.img_path(sc, "b")
        if not a.exists():
            a = b if b.exists() else None
        if not b.exists():
            b = a
        pieces = []  # (kind, src, seconds)
        if veo.exists():
            vd = min(duration(veo), dur)
            pieces.append(("veo", veo, vd))
            if dur - vd > 0.05:
                pieces.append(("kb", b, dur - vd))
        elif dur > 8 and a is not None:
            pieces += [("kb", a, dur / 2), ("kb", b, dur / 2)]
        else:
            pieces.append(("kb", a, dur))
        vparts = []
        for j, (kind, src, secs) in enumerate(pieces):
            p = self.dir / "seg" / f"{sc['id']}_v{j}.mp4"
            frames = max(1, round(secs * FPS))
            if kind == "veo":
                vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
                      f"fps={FPS},setsar=1")
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-an", "-vf", vf,
                     "-frames:v", str(frames), "-c:v", "libx264", "-preset", "veryfast",
                     "-crf", "18", "-pix_fmt", "yuv420p", str(p)])
            elif src is None:
                run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                     f"color=c=black:s={W}x{H}:r={FPS}", "-frames:v", str(frames),
                     "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)])
            else:
                mode = (idx * 2 + j) % 4
                zin = f"1+0.12*on/{frames}"
                zout = f"1.12-0.12*on/{frames}"
                z = zout if mode == 1 else (zin if mode in (0, 3) else "1.10")
                cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
                if mode == 2:
                    cx = f"(iw-iw/zoom)*on/{frames}"
                if mode == 3:
                    cy = f"(ih-ih/zoom)*(0.3+0.4*on/{frames})"
                vf = (f"scale={W * 2}:{H * 2}:force_original_aspect_ratio=increase,"
                      f"crop={W * 2}:{H * 2},zoompan=z='{z}':x='{cx}':y='{cy}':d={frames}:"
                      f"s={W}x{H}:fps={FPS},setsar=1")
                run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(src),
                     "-vf", vf, "-frames:v", str(frames), "-c:v", "libx264", "-preset",
                     "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", str(p)])
            vparts.append(p)
        # audio: narration clips + Veo ambience (ducked)
        inputs, filt, mix = [], [], []
        for k, (p, start) in enumerate(clips):
            inputs += ["-i", str(p)]
            filt.append(f"[{k + 1}:a]aresample=48000,adelay={int(start * 1000)}:all=1[a{k}]")
            mix.append(f"[a{k}]")
        if veo.exists():
            k = len(clips)
            has_audio = "audio" in run(["ffprobe", "-v", "error", "-show_entries",
                                        "stream=codec_type", "-of", "csv=p=0", str(veo)])
            if has_audio:
                inputs += ["-i", str(veo)]
                filt.append(f"[{k + 1}:a]aresample=48000,volume=0.22[a{k}]")
                mix.append(f"[a{k}]")
        k = len(inputs) // 2 + 1
        inputs += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"]
        mix.append(f"[{k}:a]")
        filt.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=longest,"
                    f"atrim=0:{dur:.3f},apad=whole_dur={dur:.3f}[aout]")
        lst = self.dir / "seg" / f"{sc['id']}_list.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in vparts))
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
            + inputs + ["-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[aout]",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
                        "-ac", "2", "-t", f"{dur:.3f}", str(out)])
        stamp.write_text(key)
        return out

    def title_card(self, secs=3.5):
        out = self.dir / "seg" / "title.mp4"
        if not out.exists():
            run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                 f"color=c=black:s={W}x{H}:r={FPS}", "-f", "lavfi", "-i",
                 "anullsrc=r=48000:cl=stereo", "-t", str(secs), "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000", "-ac", "2", str(out)])
        return out, secs

    def step_assemble(self, shorts=True):
        scenes = [s for s in self.d["scenes"] if s["image"] or s["items"]]
        timeline, events_all, t = [], [], 0.0
        part_spans = {}
        for idx, sc in enumerate(scenes):
            dur, clips, events = self.scene_timeline(sc)
            seg = self.render_scene(sc, idx, dur, clips)
            if idx == 0 or sc["part"] != scenes[idx - 1]["part"]:
                if 1 <= sc["part"] <= 6:
                    events.insert(0, {"kind": "part", "start": 0.2, "end": 2.8,
                                      "text": f"PART {sc['part']}  ·  {sc['part_title']}"})
            timeline.append(seg)
            for ev in events:
                e = dict(ev, start=ev["start"] + t, end=ev["end"] + t)
                events_all.append(e)
            part_spans.setdefault(sc["part"], [t, t])[1] = t + dur
            part_spans[sc["part"]][1] = t + dur
            t += dur
            if sc["id"] == "s00":  # title card right after the cold open
                card, secs = self.title_card()
                timeline.append(card)
                events_all.append({"kind": "maintitle", "start": t, "end": t + secs,
                                   "text": self.d["title"], "cn": self.d["title_cn"]})
                t += secs
            print(f" seg  {sc['id']}  {dur:5.1f}s  (total {t / 60:4.1f} min)", flush=True)
        lst = self.dir / "seg" / "all.txt"
        lst.write_text("".join(f"file '{p.name}'\n" for p in timeline))
        raw = self.dir / "seg" / "joined.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
             "-c", "copy", str(raw)])
        ass = self.dir / "out" / "main.ass"
        ass.write_text(build_ass(events_all, W, H), encoding="utf-8")
        srt = self.dir / "out" / f"{slug(self.script)}.srt"
        srt.write_text(build_srt(events_all), encoding="utf-8")
        final = self.dir / "out" / f"{slug(self.script)}.mp4"
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-vf",
             f"ass={ass}:fontsdir=/usr/share/fonts,fade=t=in:st=0:d=0.6",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
             "-movflags", "+faststart", str(final)])
        print(f"\n DONE  {final}  ({duration(final) / 60:.1f} min)", flush=True)
        (self.dir / "out" / "spans.json").write_text(json.dumps(
            {"parts": part_spans, "events": events_all}, ensure_ascii=False))
        if shorts:
            self.step_shorts(final, part_spans, events_all)
        return final

    def step_shorts(self, final, spans, events):
        """One 9:16 Short per Part: blurred-fill background, full frame in the middle."""
        SW, SH = 1080, 1920
        for p in range(1, 7):
            if p not in spans:
                continue
            a, b = spans[p]
            if p == 1 and 0 in spans:
                a = spans[0][0]  # Part 1 short starts with the cold open
            b = min(b, a + 179)  # YouTube Shorts limit is 3 minutes
            evs = [dict(e, start=e["start"] - a, end=e["end"] - a) for e in events
                   if e["start"] >= a and e["start"] < b]
            evs.append({"kind": "maintitle", "start": b - a, "end": b - a + 2.5,
                        "text": "Full story on my channel", "cn": ""})
            ass = self.dir / "out" / f"short{p}.ass"
            ass.write_text(build_ass(evs, SW, SH), encoding="utf-8")
            out = self.dir / "out" / f"{slug(self.script)}_short_part{p}.mp4"
            raw = self.dir / "seg" / "joined.mp4"
            fg_h = int(SW * 9 / 16)
            vf = (f"[0:v]split[bg][fg];[bg]scale=-2:{SH},crop={SW}:{SH},boxblur=24:2,"
                  f"eq=brightness=-0.15[bgb];[fg]scale={SW}:{fg_h}[fgs];"
                  f"[bgb][fgs]overlay=0:(H-h)/2,tpad=stop_mode=clone:stop_duration=2.5,"
                  f"ass={ass}:fontsdir=/usr/share/fonts[v]")
            run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                 "-i", str(raw), "-filter_complex", vf, "-map", "[v]", "-map", "0:a",
                 "-af", "apad=pad_dur=2.5,loudnorm=I=-14:TP=-1.5:LRA=11",
                 "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)])
            print(f" short {out.name}  {duration(out):.0f}s", flush=True)

# ----------------------------------------------------------------------------- subtitles

EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿️‍]")


def esc(s):
    s = EMOJI.sub("", s).replace("{", "(").replace("}", ")").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


def ts(t):
    t = max(0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def wrap(text, n):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > n and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    return "\\N".join(lines)


def build_ass(events, w, h):
    vertical = h > w
    fs = 64 if vertical else 54
    sub_mv = int(h * 0.27) if vertical else 70
    wrapn = 30 if vertical else 52
    styles = [
        # name, font, size, primary, outline, back, bold, italic, borderstyle, outline, shadow, align, mv
        ("Narr", "DejaVu Sans", fs, "&H00FFFFFF", "&H00000000", "&H96000000", -1, 0, 1, 3.2, 1.5, 2, sub_mv),
        ("Dial", "DejaVu Sans", fs, "&H0080EBFF", "&H00000000", "&H96000000", -1, 0, 1, 3.2, 1.5, 2, sub_mv),
        ("Sys", "DejaVu Sans Mono", int(fs * 0.8), "&H00FFF2B0", "&H00FF9A2E", "&HB4401A00", -1, 0, 3, 14, 0, 8, int(h * 0.12)),
        ("Scr", "DejaVu Sans Mono", int(fs * 0.72), "&H00FFFFFF", "&H00000000", "&HA0000000", -1, 0, 3, 10, 0, 7, 50),
        ("Cmt", "DejaVu Sans", int(fs * 0.78), "&H0037C8FF", "&H00102030", "&H00000000", -1, 0, 1, 2.5, 1, 7, 0),
        ("CmtR", "DejaVu Sans", int(fs * 0.9), "&H002020FF", "&H00000000", "&H00000000", -1, 0, 1, 3, 2, 7, 0),
        ("Part", "DejaVu Serif", int(fs * 0.7), "&H00E0E0E0", "&H00000000", "&H00000000", -1, -1, 1, 2, 1, 8, int(h * 0.05)),
        ("Title", "Noto Serif CJK SC", int(fs * 1.6), "&H00FFFFFF", "&H00000000", "&H00000000", -1, 0, 1, 2, 2, 5, 0),
    ]
    out = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
           "WrapStyle: 2", "", "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
           "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
           "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]
    if vertical:  # Shorts: put subtitles in the band under the centred 16:9 frame
        styles = [st[:11] + (8, int(h * 0.67)) if st[0] in ("Narr", "Dial") else st
                  for st in styles]
    for n, f, s, pc, oc, bc, b, i, bs, o, sh, al, mv in styles:
        out.append(f"Style: {n},{f},{s},{pc},&H000000FF,{oc},{bc},{b},{i},0,0,100,100,0,0,"
                   f"{bs},{o},{sh},{al},60,60,{mv},1")
    out += ["", "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    rng = random.Random(7)
    for e in events:
        st, en = ts(e["start"]), ts(e["end"])
        k = e["kind"]
        if k == "line":
            style = "Narr" if e["narr"] else "Dial"
            out.append(f"Dialogue: 0,{st},{en},{style},,0,0,0,,{wrap(esc(e['text']), wrapn)}")
        elif k == "system":
            out.append(f"Dialogue: 2,{st},{en},Sys,,0,0,0,,{{\\fad(250,250)}}"
                       f"{wrap('[ SYSTEM ]  ' + esc(e['text']), int(wrapn * 1.1))}")
        elif k == "onscreen":
            out.append(f"Dialogue: 2,{st},{en},Scr,,0,0,0,,{{\\fad(200,200)}}"
                       f"{wrap(esc(e['text']), int(wrapn * 1.2))}")
        elif k == "title":
            out.append(f"Dialogue: 3,{st},{en},Title,,0,0,0,,{{\\fad(300,300)\\fs{int(fs * 1.1)}}}"
                       f"{wrap(esc(e['text']), 34)}")
        elif k == "part":
            out.append(f"Dialogue: 1,{st},{en},Part,,0,0,0,,{{\\fad(300,400)}}{esc(e['text'])}")
        elif k == "maintitle":
            cn = f"\\N{{\\fs{int(fs * 1.0)}\\c&H0050C8FF&}}{esc(e['cn'])}" if e.get("cn") else ""
            out.append(f"Dialogue: 3,{st},{en},Title,,0,0,0,,{{\\fad(400,400)}}"
                       f"{wrap(esc(e['text']), 30 if not vertical else 18)}{cn}")
        elif k == "comments":
            dur = max(2.0, e["end"] - e["start"])
            top = int(h * (0.30 if vertical else 0.08))
            band = int(h * (0.22 if vertical else 0.38))
            style = "CmtR" if e.get("red") else "Cmt"
            for j, c in enumerate(e["texts"]):
                s0 = e["start"] + j * 0.55
                y = top + int((j * 0.27 + rng.random() * 0.12) % 1.0 * band)
                txt = esc(c)
                tw = len(txt) * fs * 0.45
                if e.get("red"):
                    out.append(f"Dialogue: 4,{ts(s0)},{ts(s0 + dur)},{style},,0,0,0,,"
                               f"{{\\an5\\pos({w // 2},{int(h * 0.45)})\\fad(150,300)}}{txt}")
                else:
                    out.append(f"Dialogue: 4,{ts(s0)},{ts(s0 + dur)},{style},,0,0,0,,"
                               f"{{\\move({w + 20},{y},{-int(tw) - 40},{y})}}{txt}")
    return "\n".join(out) + "\n"


def build_srt(events):
    rows, n = [], 0
    for e in events:
        if e["kind"] != "line":
            continue
        n += 1
        f = lambda t: f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d},{int(t * 1000 % 1000):03d}"
        rows.append(f"{n}\n{f(e['start'])} --> {f(e['end'])}\n{e['text']}\n")
    return "\n".join(rows)

# ----------------------------------------------------------------------------- CLI


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["models", "refs", "images", "tts", "video", "assemble", "all", "voices"])
    ap.add_argument("script", nargs="?")
    ap.add_argument("--veo", type=int, default=16, help="number of scenes to animate with Veo")
    ap.add_argument("--dry", action="store_true", help="placeholders instead of API calls")
    ap.add_argument("--no-shorts", action="store_true")
    a = ap.parse_args()
    if a.step == "models":
        return list_models()
    pr = Project(a.script, dry=a.dry)
    print(f"== {pr.d['title']}  ({len(pr.d['scenes'])} scenes)  -> {pr.dir}", flush=True)
    if a.step == "voices":
        return print(json.dumps(pr.voices, indent=1))
    errs = []
    if a.step in ("refs", "all"):
        errs += pr.step_refs()
    if a.step in ("images", "all"):
        errs += pr.step_images()
    if a.step in ("tts", "all"):
        errs += pr.step_tts()
    if a.step in ("video", "all"):
        errs += pr.step_video(a.veo)
    if errs:
        print(f"\n{len(errs)} generation errors (re-run to retry):", *errs[:20], sep="\n  ")
        if a.step == "all":
            print("Assembling anyway with what exists.")
    if a.step in ("assemble", "all"):
        pr.step_assemble(shorts=not a.no_shorts)


if __name__ == "__main__":
    main()
