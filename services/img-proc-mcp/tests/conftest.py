import base64
import io
import sys
from pathlib import Path

import pytest
from PIL import Image


IMG_PROC_DIR = Path(__file__).resolve().parents[1]
if str(IMG_PROC_DIR) in sys.path:
    sys.path.remove(str(IMG_PROC_DIR))
sys.path.insert(0, str(IMG_PROC_DIR))


def encode_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def decode_image(image_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")


def make_gradient_image(width: int = 100, height: int = 50) -> Image.Image:
    img = Image.new("RGB", (width, height))

    for y in range(height):
        for x in range(width):
            img.putpixel((x, y), (x % 256, y % 256, (x + y) % 256))

    return img


@pytest.fixture
def sample_image():
    img = make_gradient_image(100, 50)
    return img, encode_image(img)


@pytest.fixture
def square_image():
    img = make_gradient_image(100, 100)
    return img, encode_image(img)
