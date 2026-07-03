import base64
import io
import sys
from pathlib import Path

from PIL import Image

IMG_PROC_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMG_PROC_DIR))

from img_proc_app import rotate, flip, blur, resize, crop, add_noise, _decode

def make_test_image_b64(width=100, height=100):
    img = Image.new("RGB", (width, height), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_rotate():
    image_b64 = make_test_image_b64(100, 50)
    result = rotate(image_b64, 90)
    img = _decode(result)
    assert img.size == (50, 100)


def test_flip_horizontal():
    image_b64 = make_test_image_b64()
    result = flip(image_b64, "horizontal")
    img = _decode(result)
    assert img.size == (100, 100)


def test_blur():
    image_b64 = make_test_image_b64()
    result = blur(image_b64, 2.0)
    img = _decode(result)
    assert img.size == (100, 100)


def test_resize():
    image_b64 = make_test_image_b64()
    result = resize(image_b64, 50, 40)
    img = _decode(result)
    assert img.size == (50, 40)


def test_crop():
    image_b64 = make_test_image_b64()
    result = crop(image_b64, 10, 10, 60, 60)
    img = _decode(result)
    assert img.size == (50, 50)


def test_add_noise():
    image_b64 = make_test_image_b64()
    result = add_noise(image_b64, 0.1)
    img = _decode(result)
    assert img.size == (100, 100)