import pytest

from conftest import decode_image
from img_proc_app import flip


def test_flip_horizontal_returns_same_size(square_image):
    original, image_b64 = square_image

    result = flip(image_b64, "horizontal")
    img = decode_image(result)

    assert img.size == original.size


def test_flip_horizontal_moves_right_edge_to_left(square_image):
    original, image_b64 = square_image

    result = flip(image_b64, "horizontal")
    img = decode_image(result)

    assert img.getpixel((0, 0)) == original.getpixel((99, 0))
    assert img.getpixel((99, 0)) == original.getpixel((0, 0))


def test_flip_vertical_returns_same_size(square_image):
    original, image_b64 = square_image

    result = flip(image_b64, "vertical")
    img = decode_image(result)

    assert img.size == original.size


def test_flip_vertical_moves_bottom_edge_to_top(square_image):
    original, image_b64 = square_image

    result = flip(image_b64, "vertical")
    img = decode_image(result)

    assert img.getpixel((0, 0)) == original.getpixel((0, 99))
    assert img.getpixel((0, 99)) == original.getpixel((0, 0))


def test_flip_rejects_invalid_direction(square_image):
    _, image_b64 = square_image

    with pytest.raises(ValueError, match="direction must be horizontal or vertical"):
        flip(image_b64, "diagonal")
