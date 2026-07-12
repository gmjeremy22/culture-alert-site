import html
import io
import urllib.request
from urllib.parse import quote, unquote, urljoin, urlparse, urlsplit, urlunsplit

from PIL import Image


MIN_IMAGE_SIDE = 300

BAD_IMAGE_TOKENS = (
    "btn_more_report",
    "loading.gif",
    "wis-layout/images/sub/loading",
    "/common/btn/",
    "noimage",
    "no_img",
    "blank.gif",
    "favicon",
    "logo",
    "gnb_logo",
    "header_logo",
    "top-logo",
    "top_logo",
    "bg_logo",
    "preview_logo",
    "icon_sns",
    "sns_",
    "instagram",
    "facebook",
    "twitter",
    "stop_btn",
    "instar_btn",
    "getqrcode",
    "qrcode",
    "common/getqrcode",
    "cursor.png",
    "arrow_up_w",
    "ico_mymenu",
    "img_ban_gnb",
    "infobox-ico",
    "gnb-img_",
    "mark.png",
    "banner_child",
    "top_banner_cancel",
    "i_sang.png",
    "ddp-logo",
    "images/layout/ci.png",
    "sw_img.png",
)

IMAGE_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 culture-alert-image/1.0",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
}


def normalize_image_url(value, base_url=None):
    image = html.unescape(str(value or "")).strip()
    if not image:
        return ""
    if base_url:
        image = urljoin(base_url, image)
    return image


def image_issue_reasons(value):
    image = normalize_image_url(value)
    if not image:
        return ["empty"]
    lower = image.lower()
    if lower.startswith("data:"):
        return ["data-uri"]
    parsed = urlparse(lower)
    path = unquote(parsed.path).lower()
    reasons = []
    if "facebook.com" in parsed.netloc and path.startswith("/tr"):
        reasons.append("facebook pixel")
    if lower.rstrip("/").endswith("/upload/exhibition"):
        reasons.append("empty exhibition upload path")
    reasons.extend(token for token in BAD_IMAGE_TOKENS if token in lower)
    return reasons


def is_bad_image_url(value):
    return bool(image_issue_reasons(value))


def clean_image_url(value, base_url=None):
    image = normalize_image_url(value, base_url)
    if not image or is_bad_image_url(image):
        return None
    return image


def display_image_url(value):
    return clean_image_url(value) or ""


def fetch_image(url, timeout=10, max_bytes=4_000_000):
    parts = urlsplit(url)
    request_url = urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            quote(unquote(parts.path), safe="/%:@"),
            quote(unquote(parts.query), safe="=&;%:+,/?@"),
            parts.fragment,
        )
    )
    request = urllib.request.Request(request_url, headers=IMAGE_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(max_bytes)
        content_type = response.headers.get("content-type", "")
    if "svg" in content_type or url.lower().split("?")[0].endswith(".svg"):
        return None, content_type, "svg"
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGB"), content_type, None


def remote_image_size(url, timeout=10):
    image, content_type, note = fetch_image(url, timeout=timeout)
    if note == "svg":
        return None
    if image is None:
        return None
    return image.width, image.height


def is_small_remote_image(url, min_side=MIN_IMAGE_SIDE, timeout=10):
    size = remote_image_size(url, timeout=timeout)
    return bool(size and (size[0] < min_side or size[1] < min_side))
