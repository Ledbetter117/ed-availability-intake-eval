#!/usr/bin/env python3
"""Synthetic ED availability-calendar generator.

Renders a filled-in monthly availability calendar to PNG and emits the EXACT
ground-truth JSON alongside it. Every calendar is randomly generated, so labels
are free, perfect, and contain no real data (no PHI, no employer exports).

Difficulty slices:
    clean        typed codes, straight scan
    rotated      photographed at an angle
    lowcontrast  faint scan / poor lighting
    handwritten  pen-filled printed calendar (handwriting font + per-mark jitter;
                 check marks drawn as strokes). Font: Patrick Hand (SIL OFL 1.1,
                 bundled in assets/fonts/).

Usage:
    python3 generate_dataset.py --n 40 [--seed 7] [--out ./data]
"""
import os, json, random, argparse, calendar, datetime
from PIL import Image, ImageDraw, ImageFont

STATUSES = ["AVAILABLE", "AM", "PM", "NIGHT", "UNAVAILABLE"]
CODE = {"AVAILABLE": "✓", "AM": "AM", "PM": "PM", "NIGHT": "NOC", "UNAVAILABLE": "X"}
NOTES = ["no call", "post-nights off", "back from PTO", "float OK", "charge only", "early out"]
GLOBAL = ["No weekends", "Days only", "Max 3 shifts/wk", "No Mondays", "Prefer ICU"]
STYLES = ["clean", "rotated", "lowcontrast", "handwritten"]

HERE = os.path.dirname(os.path.abspath(__file__))
HAND_FONT = os.path.join(HERE, "assets", "fonts", "PatrickHand-Regular.ttf")
INK = (25, 35, 110)  # ballpoint-pen blue


def load_font(size):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()


def load_hand_font(size):
    try:
        return ImageFont.truetype(HAND_FONT, size)
    except Exception:
        return load_font(size)  # graceful fallback; slice becomes typed


def gen_truth(year, month, seed):
    r = random.Random(seed)
    ndays = calendar.monthrange(year, month)[1]
    days = {}
    for d in range(1, ndays + 1):
        wd = datetime.date(year, month, d).weekday()
        w = [0.18, 0.10, 0.12, 0.10, 0.50] if wd >= 5 else [0.30, 0.18, 0.20, 0.12, 0.20]
        status = r.choices(STATUSES, weights=w)[0]
        note = r.choice(NOTES) if r.random() < 0.10 else ""
        days[f"{year:04d}-{month:02d}-{d:02d}"] = {"status": status, "note": note}
    gnotes = [r.choice(GLOBAL)] if r.random() < 0.6 else []
    return {"month": f"{year:04d}-{month:02d}", "days": days, "global_notes": gnotes}


def draw_hand_text(img, xy, text, font, fill, rng):
    """Paste text with hand-drawn jitter: small random offset + rotation."""
    pad = 14
    bbox = font.getbbox(text)
    tw, th = bbox[2] - bbox[0] + 2 * pad, bbox[3] - bbox[1] + 2 * pad
    tile = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    ImageDraw.Draw(tile).text((pad - bbox[0], pad - bbox[1]), text, font=font, fill=fill)
    tile = tile.rotate(rng.uniform(-7, 7), expand=True, resample=Image.BICUBIC)
    img.paste(tile, (xy[0] + rng.randint(-5, 5) - pad, xy[1] + rng.randint(-4, 4) - pad), tile)


def draw_hand_check(img, xy, size, fill, rng):
    """A pen check mark as two strokes (handwriting fonts lack U+2713)."""
    d = ImageDraw.Draw(img)
    x, y = xy[0] + rng.randint(-4, 4), xy[1] + rng.randint(-3, 3)
    s = size
    j = lambda: rng.randint(-2, 2)
    p1 = (x + j(), y + int(s * 0.5) + j())
    p2 = (x + int(s * 0.35) + j(), y + s + j())
    p3 = (x + s + j(), y + j())
    d.line([p1, p2], fill=fill, width=4)
    d.line([p2, p3], fill=fill, width=4)


def render(truth, emp, style, out_png, rng):
    year, month = map(int, truth["month"].split("-"))
    cols, cw, ch, top = 7, 150, 96, 140
    W, H = cols * cw + 40, top + 7 * ch + 40
    bg = (224, 224, 224) if style == "lowcontrast" else (246, 246, 246)
    fg = (110, 110, 110) if style == "lowcontrast" else (20, 20, 20)
    img = Image.new("RGB", (W, H), bg)
    dr = ImageDraw.Draw(img)
    tf, hf, df, cf, nf = load_font(34), load_font(22), load_font(26), load_font(30), load_font(16)
    hand = style == "handwritten"
    hcf, hnf = load_hand_font(36), load_hand_font(22)
    dr.text((20, 18), f"Availability — {emp}", font=tf, fill=fg)
    dr.text((20, 64), f"{calendar.month_name[month]} {year}   Legend: ✓=any  AM  PM  NOC=night  X=off", font=nf, fill=fg)
    if truth["global_notes"]:
        if hand:
            dr.text((20, 92), "Notes: ", font=hf, fill=fg)
            draw_hand_text(img, (100, 90), "; ".join(truth["global_notes"]), hnf, INK, rng)
        else:
            dr.text((20, 92), "Notes: " + "; ".join(truth["global_notes"]), font=hf, fill=fg)
    wd = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    x0, y0 = 20, top
    for c in range(cols):
        dr.rectangle([x0 + c * cw, y0, x0 + (c + 1) * cw, y0 + 34], outline=(90, 90, 90))
        dr.text((x0 + c * cw + 10, y0 + 6), wd[c], font=hf, fill=fg)
    for ri, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)):
        for ci, day in enumerate(week):
            cx, cy = x0 + ci * cw, y0 + 34 + ri * ch
            dr.rectangle([cx, cy, cx + cw, cy + ch], outline=(150, 150, 150))
            if day == 0:
                continue
            dr.text((cx + 6, cy + 4), str(day), font=df, fill=fg)
            cell = truth["days"][f"{year:04d}-{month:02d}-{day:02d}"]
            if hand:
                if cell["status"] == "AVAILABLE":
                    draw_hand_check(img, (cx + cw - 66, cy + 34), 30, INK, rng)
                else:
                    draw_hand_text(img, (cx + cw - 84, cy + 28), CODE[cell["status"]], hcf, INK, rng)
                if cell["note"]:
                    draw_hand_text(img, (cx + 8, cy + ch - 28), cell["note"], hnf, INK, rng)
            else:
                cc = {"UNAVAILABLE": (170, 30, 30), "AVAILABLE": (20, 90, 20)}.get(cell["status"], (20, 20, 120))
                if style == "lowcontrast":
                    cc = fg
                dr.text((cx + cw - 72, cy + 30), CODE[cell["status"]], font=cf, fill=cc)
                if cell["note"]:
                    dr.text((cx + 6, cy + ch - 22), cell["note"], font=nf, fill=fg)
    if style == "rotated":
        img = img.rotate(-4, expand=True, fillcolor=bg)
    img.save(out_png)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(HERE, "data"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    index = []
    for i in range(a.n):
        seed = a.seed + i
        truth = gen_truth(2026, 7, seed)
        truth["employee_id"] = f"EMP-{1000 + seed} (synthetic)"
        truth["render_style"] = STYLES[i % len(STYLES)]
        base = f"sample_{i + 1:02d}_{truth['render_style']}"
        rng = random.Random(seed * 7919)  # separate stream for render jitter; fully reproducible
        render(truth, truth["employee_id"], truth["render_style"], os.path.join(a.out, base + ".png"), rng)
        with open(os.path.join(a.out, base + ".gold.json"), "w") as f:
            json.dump(truth, f, indent=2, ensure_ascii=False)
        index.append(base)
        print(f"wrote {base}.png + {base}.gold.json  (style={truth['render_style']})")
    # echo first sample's truth so a run is self-documenting
    t = json.load(open(os.path.join(a.out, index[0] + ".gold.json")))
    print(f"\n--- {index[0]} ground truth: employee={t['employee_id']} month={t['month']} ---")
    for k in list(t["days"])[:10]:
        print(" ", k, t["days"][k])
    print("  global_notes:", t["global_notes"])


if __name__ == "__main__":
    main()
