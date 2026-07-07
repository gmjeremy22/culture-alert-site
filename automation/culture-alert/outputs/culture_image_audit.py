import json
import sqlite3
import sys
from pathlib import Path

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR.parent / "work"
DB_PATH = BASE_DIR / "culture-alert.sqlite"
REPORT_PATH = BASE_DIR / "image-quality-audit-report.md"
CONTACT_SHEET_PATH = BASE_DIR / "image-quality-contact-sheet.jpg"

sys.path.insert(0, str(BASE_DIR))
import culture_card_gallery  # noqa: E402
from culture_image_utils import MIN_IMAGE_SIDE, fetch_image, image_issue_reasons  # noqa: E402


def image_tile(image, label, width=220, height=320):
    tile = Image.new("RGB", (width, height), "#111111")
    draw = ImageDraw.Draw(tile)
    if image:
        image.thumbnail((width, height - 42), Image.LANCZOS)
        x = (width - image.width) // 2
        y = (height - 42 - image.height) // 2
        tile.paste(image, (x, y))
    else:
        draw.rectangle((18, 60, width - 18, height - 86), outline="#555555", width=2)
        draw.text((34, height // 2 - 10), "no image", fill="#aaaaaa")
    draw.rectangle((0, height - 42, width, height), fill="#000000")
    draw.text((8, height - 34), label[:32], fill="#eeeeee")
    return tile


def make_contact_sheet(samples):
    cols = 4
    tile_w, tile_h = 220, 320
    rows = (len(samples) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tile_w, rows * tile_h), "#050505")
    for index, sample in enumerate(samples):
        label = f"{sample['rank']}. {sample['id']}"
        tile = image_tile(sample.get("image"), label, tile_w, tile_h)
        sheet.paste(tile, ((index % cols) * tile_w, (index // cols) * tile_h))
    sheet.save(CONTACT_SHEET_PATH, quality=88)


def main():
    with sqlite3.connect(DB_PATH) as conn:
        items = culture_card_gallery.load_events(conn, "가족")

    visible_images = [item for item in items if item["imageUrl"]]
    bad_visible = [
        {
            "id": item["id"],
            "institution": item["institution"],
            "title": item["title"],
            "url": item["imageUrl"],
            "reasons": image_issue_reasons(item["imageUrl"]),
        }
        for item in visible_images
        if image_issue_reasons(item["imageUrl"])
    ]

    samples = []
    tiny_visible = []
    fetch_failures = []
    for rank, item in enumerate(visible_images, start=1):
        sample = {
            "rank": rank,
            "id": item["id"],
            "institution": item["institution"],
            "title": item["title"],
            "url": item["imageUrl"],
        }
        try:
            image, content_type, note = fetch_image(item["imageUrl"])
            if image:
                sample["width"], sample["height"] = image.size
                sample["content_type"] = content_type
                sample["image"] = image
                if image.width < MIN_IMAGE_SIDE or image.height < MIN_IMAGE_SIDE:
                    tiny_visible.append(sample)
            else:
                sample["content_type"] = content_type
                sample["note"] = note or "not an image"
        except (OSError, UnicodeError, TimeoutError) as exc:
            sample["error"] = str(exc)
            fetch_failures.append(sample)
        samples.append(sample)

    make_contact_sheet(samples[:24])

    WORK_DIR.mkdir(exist_ok=True)
    (WORK_DIR / "image-audit-samples.json").write_text(
        json.dumps(
            [
                {key: value for key, value in sample.items() if key != "image"}
                for sample in samples
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    lines = [
        "# 이미지 품질 점검 리포트",
        "",
        f"- 카드 수: {len(items)}건",
        f"- 이미지가 있는 카드: {len(visible_images)}건",
        f"- 확실한 로고/아이콘/버튼류 잔존: {len(bad_visible)}건",
        f"- {MIN_IMAGE_SIDE}px 미만 작은 이미지 잔존: {len(tiny_visible)}건",
        f"- 이미지 다운로드 실패: {len(fetch_failures)}건",
        f"- 접촉표: {CONTACT_SHEET_PATH}",
        "",
        "## 확실한 이상 이미지",
        "",
    ]
    if bad_visible:
        for item in bad_visible[:80]:
            reason = ", ".join(item["reasons"])
            lines.append(f"- {item['id']} | {item['institution']} | {item['title']} | {reason} | {item['url']}")
    else:
        lines.append("- 없음")
    lines.extend(["", "## 상위 이미지 샘플", ""])
    for sample in samples[:40]:
        size = (
            f"{sample.get('width')}x{sample.get('height')}"
            if sample.get("width") and sample.get("height")
            else sample.get("note") or sample.get("error") or "확인 불가"
        )
        lines.append(f"- {sample['rank']} | {sample['id']} | {sample['institution']} | {size} | {sample['title']}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"cards={len(items)}")
    print(f"visible_images={len(visible_images)}")
    print(f"bad_visible={len(bad_visible)}")
    print(f"report={REPORT_PATH}")
    print(f"contact_sheet={CONTACT_SHEET_PATH}")


if __name__ == "__main__":
    main()
