import io
import importlib.util
import multiprocessing

import numpy as np
from PIL import Image, ImageEnhance

# ── Availability flags — use find_spec so we don't pay import cost at startup ──
HAS_CV2     = importlib.util.find_spec("cv2")     is not None
HAS_MOVIEPY = importlib.util.find_spec("moviepy") is not None

# ── Supported file types ───────────────────────────────────────────────────────
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".webp"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}

_N_WORKERS = max(2, multiprocessing.cpu_count())


def distort_audio(samples: np.ndarray, amount: float) -> np.ndarray:
    if amount < 0.01:
        return samples
    gain = 1.0 + amount * 20.0
    return np.clip(samples * gain, -1.0, 1.0)


def apply_deep_fry(
    img: Image.Image,
    brightness: float,
    contrast: float,
    sharpness: float,
    saturation: float,
    noise: float,
    jpeg_quality: int,
) -> Image.Image:
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    if img.mode == "RGBA":
        img = img.convert("RGB")

    img = ImageEnhance.Brightness(img).enhance(brightness)
    img = ImageEnhance.Contrast(img).enhance(contrast)
    img = ImageEnhance.Color(img).enhance(saturation)
    img = ImageEnhance.Sharpness(img).enhance(sharpness)

    if noise > 0.001:
        arr = np.array(img, dtype=np.float32)
        grain = np.random.normal(0.0, noise * 80.0, arr.shape).astype(np.float32)
        arr = np.clip(arr + grain, 0, 255).astype(np.uint8)
        img = Image.fromarray(arr)

    if jpeg_quality < 95:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=jpeg_quality, subsampling=2)
        buf.seek(0)
        img = Image.open(buf).copy()

    return img


def apply_deep_fry_cv2(
    bgr: np.ndarray,
    brightness: float,
    contrast: float,
    sharpness: float,
    saturation: float,
    noise: float,
    jpeg_quality: int,
) -> np.ndarray:
    import cv2  # lazy — cached in sys.modules after first call

    img = bgr.astype(np.float32)

    if brightness != 1.0:
        img *= brightness

    if contrast != 1.0:
        img = (img - 128.0) * contrast + 128.0

    img = np.clip(img, 0, 255).astype(np.uint8)

    if saturation != 1.0:
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation, 0, 255)
        img = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    if sharpness != 1.0:
        blur_sigma = 2.0
        blurred = cv2.GaussianBlur(img, (0, 0), blur_sigma)
        if sharpness > 1.0:
            img = cv2.addWeighted(img, sharpness, blurred, -(sharpness - 1.0), 0)
        else:
            img = cv2.addWeighted(img, sharpness, blurred, 1.0 - sharpness, 0)

    if noise > 0.001:
        grain = np.random.normal(0.0, noise * 80.0, img.shape).astype(np.float32)
        img = np.clip(img.astype(np.float32) + grain, 0, 255).astype(np.uint8)

    if jpeg_quality < 95:
        _, enc = cv2.imencode(".jpg", img,
                               [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)])
        img = cv2.imdecode(enc, cv2.IMREAD_COLOR)

    return img
