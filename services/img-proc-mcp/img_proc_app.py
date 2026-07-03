import base64
import io
import random
from typing import Literal

from mcp.server.fastmcp import FastMCP
from PIL import Image, ImageFilter

mcp = FastMCP("img-proc")


def _decode(image_b64: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")


def _encode(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@mcp.tool()
def rotate(image_b64: str, angle: float) -> str:
    """Rotate image by angle degrees. Returns base64 PNG."""
    img = _decode(image_b64)
    rotated = img.rotate(angle, expand=True)
    return _encode(rotated)


@mcp.tool()
def flip(image_b64: str, direction: Literal["horizontal", "vertical"]) -> str:
    """Flip image horizontally or vertically. Returns base64 PNG."""
    img = _decode(image_b64)

    if direction == "horizontal":
        flipped = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    elif direction == "vertical":
        flipped = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    else:
        raise ValueError("direction must be horizontal or vertical")

    return _encode(flipped)


@mcp.tool()
def blur(image_b64: str, radius: float = 2.0) -> str:
    """Apply Gaussian blur to an image. Returns base64 PNG."""
    img = _decode(image_b64)
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    return _encode(blurred)


@mcp.tool()
def resize(image_b64: str, width: int, height: int) -> str:
    """Resize image to width x height. Returns base64 PNG."""
    img = _decode(image_b64)
    resized = img.resize((width, height))
    return _encode(resized)


@mcp.tool()
def crop(image_b64: str, left: int, top: int, right: int, bottom: int) -> str:
    """Crop image by bounding box coordinates. Returns base64 PNG."""
    img = _decode(image_b64)
    cropped = img.crop((left, top, right, bottom))
    return _encode(cropped)


@mcp.tool()
def add_noise(image_b64: str, amount: float = 0.05) -> str:
    """Add salt-and-pepper noise. amount should be between 0 and 1."""
    img = _decode(image_b64)
    pixels = img.load()

    width, height = img.size
    total_pixels = width * height
    noisy_pixels = int(total_pixels * amount)

    for _ in range(noisy_pixels):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        pixels[x, y] = (255, 255, 255) if random.random() < 0.5 else (0, 0, 0)

    return _encode(img)


if __name__ == "__main__":
    mcp.run()
