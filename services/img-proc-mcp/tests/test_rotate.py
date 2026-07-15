from conftest import decode_image
from img_proc_app import rotate


def test_rotate_90_degrees_swaps_width_and_height(sample_image):
    _, image_b64 = sample_image

    result = rotate(image_b64, angle=90)
    img = decode_image(result)

    assert img.size == (50, 100)


def test_rotate_zero_degrees_keeps_size(sample_image):
    original, image_b64 = sample_image

    result = rotate(image_b64, angle=0)
    img = decode_image(result)

    assert img.size == original.size
