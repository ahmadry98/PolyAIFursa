from conftest import decode_image
from img_proc_app import blur


def test_blur_returns_same_size(square_image):
    original, image_b64 = square_image

    result = blur(image_b64, radius=2.0)
    img = decode_image(result)

    assert img.size == original.size
    assert img.mode == "RGB"
