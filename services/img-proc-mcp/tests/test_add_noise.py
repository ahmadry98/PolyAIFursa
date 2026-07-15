from conftest import decode_image
from img_proc_app import add_noise


def test_add_noise_returns_same_size(square_image):
    original, image_b64 = square_image

    result = add_noise(image_b64, amount=0.05)
    img = decode_image(result)

    assert img.size == original.size


def test_add_noise_zero_amount_keeps_pixels_unchanged(square_image):
    original, image_b64 = square_image

    result = add_noise(image_b64, amount=0)
    img = decode_image(result)

    assert img.size == original.size
    assert img.getpixel((0, 0)) == original.getpixel((0, 0))
    assert img.getpixel((50, 50)) == original.getpixel((50, 50))
    assert img.getpixel((99, 99)) == original.getpixel((99, 99))
