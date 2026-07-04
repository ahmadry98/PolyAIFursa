from img_proc_app import _decode


def test_decode_returns_rgb_image(sample_image):
    original, image_b64 = sample_image

    img = _decode(image_b64)

    assert img.size == original.size
    assert img.mode == "RGB"
