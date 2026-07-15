from conftest import decode_image
from img_proc_app import resize


def test_resize_returns_requested_size(square_image):
    _, image_b64 = square_image

    result = resize(image_b64, width=50, height=40)
    img = decode_image(result)

    assert img.size == (50, 40)
    assert img.mode == "RGB"
