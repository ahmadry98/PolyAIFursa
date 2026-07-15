from conftest import decode_image
from img_proc_app import crop


def test_crop_returns_requested_size(square_image):
    _, image_b64 = square_image

    result = crop(image_b64, left=10, top=10, right=60, bottom=60)
    img = decode_image(result)

    assert img.size == (50, 50)


def test_crop_content_starts_at_requested_coordinates(square_image):
    original, image_b64 = square_image

    result = crop(image_b64, left=10, top=10, right=60, bottom=60)
    img = decode_image(result)

    assert img.getpixel((0, 0)) == original.getpixel((10, 10))
    assert img.getpixel((49, 49)) == original.getpixel((59, 59))
