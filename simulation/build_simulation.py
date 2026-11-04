"""Deterministic paired synthetic calendar generator. Refuses a second build."""
import calendar
import datetime
import hashlib
import json
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
SEED = 2026110301
CODE = {"AVAILABLE": "A", "AM": "AM", "PM": "PM", "NIGHT": "NOC", "UNAVAILABLE": "X", "NOT_SPECIFIED": ""}
NOTES = ["no call", "early out", "float OK", "after 10", "leave at 4", "training", "swap OK", "no overtime"]
GLOBALS = ["Prefer mornings", "One shift per day", "No extra call", "Request one weekend off", "Training pending", "Ask before swapping"]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def font(path, size):
    # No fallback: missing fonts must fail before the corpus is frozen.
    return ImageFont.truetype(str(path), size)


def truth(year, month, rng):
    n = calendar.monthrange(year, month)[1]
    values = list(CODE) + rng.choices(list(CODE), k=n - len(CODE))
    rng.shuffle(values)
    notes = dict(zip(rng.sample(range(1, n + 1), 5), rng.sample(NOTES, 5)))
    return {"month": f"{year:04d}-{month:02d}",
            "days": {f"{year:04d}-{month:02d}-{d:02d}": {"status": values[d-1], "note": notes.get(d, "")} for d in range(1, n + 1)},
            "global_notes": rng.sample(GLOBALS, 2)}


def mark(image, position, text, face, rng, handwritten):
    if not text:
        return
    color = (26, 45, 105)
    if not handwritten:
        ImageDraw.Draw(image).text(position, text, font=face, fill=color)
        return
    box = face.getbbox(text)
    tile = Image.new("RGBA", (box[2] - box[0] + 16, box[3] - box[1] + 16), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((8 - box[0], 8 - box[1]), text, font=face, fill=color)
    tile = tile.rotate(rng.uniform(-3, 3), expand=True, resample=Image.Resampling.BICUBIC)
    image.paste(tile, (position[0] - 8 + rng.randint(-3, 3), position[1] - 8 + rng.randint(-3, 3)), tile)


def render(gold, typed_path, hand_path, handwritten, seed):
    image = Image.new("RGB", (1540, 1280), "white")
    draw = ImageDraw.Draw(image)
    typed = lambda size: font(typed_path, size)
    marks = font(hand_path if handwritten else typed_path, 37 if handwritten else 30)
    notes = font(hand_path if handwritten else typed_path, 27 if handwritten else 22)
    rng = random.Random(seed)
    year, month = map(int, gold["month"].split("-"))
    draw.text((35, 22), "FICTIONAL AVAILABILITY CALENDAR", font=typed(32), fill="black")
    draw.text((35, 70), f"{calendar.month_name[month]} {year}", font=typed(35), fill="black")
    draw.text((35, 124), "Legend: A = AVAILABLE | AM | PM | NOC = NIGHT | X = UNAVAILABLE", font=typed(23), fill="black")
    draw.text((35, 160), "Blank availability mark = NOT_SPECIFIED. Day notes do not change the mark.", font=typed(23), fill="black")
    draw.text((35, 207), "Global notes:", font=typed(24), fill="black")
    for i, text in enumerate(gold["global_notes"]):
        mark(image, (240, 207 + i * 39), text, notes, rng, handwritten)
    x0, y0, width, height = 35, 330, 210, 145
    for col, name in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        draw.text((x0 + col * width + 12, y0 - 40), name, font=typed(25), fill="black")
    for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)):
        for col, day in enumerate(week):
            x, y = x0 + col * width, y0 + row * height
            draw.rectangle((x, y, x + width, y + height), outline=(95, 95, 95), width=2)
            if not day:
                draw.rectangle((x + 2, y + 2, x + width - 2, y + height - 2), fill=(238, 238, 238))
                continue
            draw.text((x + 10, y + 7), str(day), font=typed(26), fill="black")
            cell = gold["days"][f"{gold['month']}-{day:02d}"]
            mark(image, (x + 75, y + 45), CODE[cell["status"]], marks, rng, handwritten)
            mark(image, (x + 12, y + 104), cell["note"], notes, rng, handwritten)
    draw.text((35, 1224), "Synthetic training-style example. No real staff or patient data.", font=typed(20), fill=(70, 70, 70))
    return image


def degrade(image):
    small = image.resize((1109, 922), Image.Resampling.LANCZOS)
    result = small.resize(image.size, Image.Resampling.BICUBIC)
    result = ImageEnhance.Contrast(result).enhance(0.70)
    result = result.filter(ImageFilter.GaussianBlur(0.55))
    return result.rotate(1.25, expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white")


def main():
    if (ROOT / "manifest.json").exists() or (ROOT / "FREEZE.json").exists() or (ROOT / "images").exists():
        raise SystemExit("REFUSED: existing corpus; preserve it and use a new explicitly authorized edition")
    config = json.loads((ROOT / "fonts.json").read_text(encoding="utf-8"))
    typed_path = ROOT / config["typed"]["path"]
    hands = config["handwriting"]
    for entry in [config["typed"], *hands]:
        if sha(ROOT / entry["path"]) != entry["sha256"]:
            raise ValueError("font hash mismatch")
        font(ROOT / entry["path"], 20)
    rng = random.Random(SEED)
    months = []
    for length in (28, 29, 30, 31):
        options = [(y, m) for y in range(2024, 2033) for m in range(1, 13) if calendar.monthrange(y, m)[1] == length]
        months.extend(rng.sample(options, 3))
    rng.shuffle(months)
    (ROOT / "gold").mkdir()
    (ROOT / "images").mkdir()
    rows = []
    gold_rows = []
    for index, (year, month) in enumerate(months):
        cid = f"C{index + 1:02d}"
        gold = truth(year, month, random.Random(SEED + 1000 + index))
        gold_name = f"gold/{cid}.json"
        write_json(ROOT / gold_name, gold)
        hand = hands[index % len(hands)]
        typed = render(gold, typed_path, ROOT / hand["path"], False, SEED + 2000 + index)
        writing = render(gold, typed_path, ROOT / hand["path"], True, SEED + 2000 + index)
        images = {"typed": typed, "handwriting": writing, "degraded": degrade(writing)}
        gold_rows.append({"calendar_id": cid, "gold": gold_name, "month": gold["month"], "days": len(gold["days"]), "font": hand["name"]})
        for condition, image in images.items():
            rid = f"r{rng.getrandbits(64):016x}"
            image_name = f"images/{rid}.png"
            image.save(ROOT / image_name)
            rows.append({"request_id": rid, "calendar_id": cid, "condition": condition, "gold": gold_name,
                         "image": image_name, "image_sha256": sha(ROOT / image_name), "dimensions": list(image.size)})
    if len({r["request_id"] for r in rows}) != 36:
        raise ValueError("request ID collision")
    order = list(rows)
    rng.shuffle(order)
    requests = {"schema": "ed-i-simulation-requests/1", "prompt": "PROMPT.txt", "prompt_sha256": sha(ROOT / "PROMPT.txt"),
                "settings_requested": {"temperature": 0, "max_tokens": 4096, "calls_per_image": 1},
                "requests": [{k: r[k] for k in ("request_id", "image", "image_sha256")} for r in order]}
    write_json(ROOT / "requests.json", requests)
    write_json(ROOT / "manifest.json", {"schema": "ed-i-simulation/1", "seed": SEED,
               "base_commit": "e7d4f28c00b258ff0d9c421e9e696a11840652f8", "calendar_count": 12,
               "image_count": 36, "calendars": gold_rows, "images": rows, "request_order": [r["request_id"] for r in order]})
    files = ["PLAN.md", "PROMPT.txt", "INPUT-CONTRACT.md", "build_simulation.py", "score_simulation.py", "test_simulation.py", "fonts.json", "requests.json", "manifest.json"]
    files.extend(p.relative_to(ROOT).as_posix() for directory in ("assets", "gold", "images") for p in sorted((ROOT / directory).rglob("*")) if p.is_file())
    write_json(ROOT / "FREEZE.json", {"schema": "ed-i-simulation-freeze/1", "frozen_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
               "phase": "before_model_calls", "files": [{"path": name, "sha256": sha(ROOT / name)} for name in sorted(files)]})
    print(json.dumps({"calendars": 12, "images": 36, "freeze_sha256": sha(ROOT / "FREEZE.json"), "requests": str(ROOT / "requests.json")}))


if __name__ == "__main__":
    main()
