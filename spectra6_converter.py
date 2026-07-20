"""Conversion d'images RGB vers la palette six couleurs Spectra 6."""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from PIL import Image


IMAGE_SIZE = (800, 480)
BINARY_SIZE = IMAGE_SIZE[0] * IMAGE_SIZE[1]

BLACK_INDEX = 0
WHITE_INDEX = 1

# L'ordre est celui attendu par le firmware EE04 : un octet contient
# directement l'index de la couleur correspondante.
SPECTRA6_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),        # 0 : noir
    (255, 255, 255),  # 1 : blanc
    (255, 0, 0),      # 2 : rouge
    (255, 255, 0),    # 3 : jaune
    (0, 255, 0),      # 4 : vert
    (0, 0, 255),      # 5 : bleu
)

WEATHER_PROTECTED_BOX = (500, 40, 779, 319)
BOTTOM_PROTECTED_BOX = (0, 360, 799, 479)
DEFAULT_LUMINANCE_THRESHOLD = 180
DEFAULT_DIFFUSION_FACTOR = 0.40


class ConversionResult(NamedTuple):
    """Résultat complet utilisable par les routes PNG et binaire."""

    preview: Image.Image
    palette_indices: bytes
    color_statistics: dict[int, int]


def is_protected_pixel(x: int, y: int) -> bool:
    """Indique si un pixel appartient à une zone forcée en noir et blanc."""

    weather_x1, weather_y1, weather_x2, weather_y2 = WEATHER_PROTECTED_BOX
    bottom_x1, bottom_y1, bottom_x2, bottom_y2 = BOTTOM_PROTECTED_BOX
    return (
        weather_x1 <= x <= weather_x2 and weather_y1 <= y <= weather_y2
    ) or (bottom_x1 <= x <= bottom_x2 and bottom_y1 <= y <= bottom_y2)


def _nearest_palette_index(red: float, green: float, blue: float) -> int:
    """Retourne l'index de la couleur Spectra 6 la plus proche en RGB."""

    return min(
        range(len(SPECTRA6_PALETTE)),
        key=lambda index: (
            (red - SPECTRA6_PALETTE[index][0]) ** 2
            + (green - SPECTRA6_PALETTE[index][1]) ** 2
            + (blue - SPECTRA6_PALETTE[index][2]) ** 2
        ),
    )


def _black_or_white_index(
    pixel: tuple[int, int, int], luminance_threshold: int
) -> int:
    """Convertit un pixel original en noir ou blanc selon sa luminance."""

    red, green, blue = pixel
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return WHITE_INDEX if luminance >= luminance_threshold else BLACK_INDEX


def _build_result(width: int, height: int, indices: bytearray) -> ConversionResult:
    """Construit l'aperçu RGB et les statistiques depuis les index calculés."""

    statistics = {index: 0 for index in range(len(SPECTRA6_PALETTE))}
    preview_pixels: list[tuple[int, int, int]] = []
    for index in indices:
        statistics[index] += 1
        preview_pixels.append(SPECTRA6_PALETTE[index])

    preview = Image.new("RGB", (width, height))
    preview.putdata(preview_pixels)
    return ConversionResult(preview, bytes(indices), statistics)


def convert_direct(image: Image.Image) -> ConversionResult:
    """Convertit chaque pixel vers la couleur Spectra 6 la plus proche."""

    source = image.convert("RGB")
    width, height = source.size
    indices = bytearray(
        _nearest_palette_index(red, green, blue)
        for red, green, blue in source.getdata()
    )
    return _build_result(width, height, indices)


def _convert_with_floyd_steinberg(
    image: Image.Image,
    *,
    diffusion_factor: float,
    protected_pixel: Callable[[int, int], bool] | None = None,
    luminance_threshold: int = DEFAULT_LUMINANCE_THRESHOLD,
) -> ConversionResult:
    """Applique Floyd-Steinberg, avec protection facultative de certaines zones."""

    if not 0.0 <= diffusion_factor <= 1.0:
        raise ValueError("Le facteur de diffusion doit être compris entre 0 et 1")
    if not 0 <= luminance_threshold <= 255:
        raise ValueError("Le seuil de luminance doit être compris entre 0 et 255")

    source = image.convert("RGB")
    width, height = source.size
    source_pixels = source.load()
    indices = bytearray(width * height)

    # Deux rangées d'erreurs suffisent : la rangée active et la suivante.
    current_red = [0.0] * (width + 2)
    current_green = [0.0] * (width + 2)
    current_blue = [0.0] * (width + 2)
    next_red = [0.0] * (width + 2)
    next_green = [0.0] * (width + 2)
    next_blue = [0.0] * (width + 2)

    def can_receive_error(target_x: int, target_y: int) -> bool:
        return (
            0 <= target_x < width
            and 0 <= target_y < height
            and (protected_pixel is None or not protected_pixel(target_x, target_y))
        )

    for y in range(height):
        for x in range(width):
            position = y * width + x
            original = source_pixels[x, y]

            # Une zone protégée emploie strictement le RGB original. Elle ne
            # lit aucune erreur accumulée et n'en produit aucune nouvelle.
            if protected_pixel is not None and protected_pixel(x, y):
                indices[position] = _black_or_white_index(
                    original, luminance_threshold
                )
                continue

            error_position = x + 1
            adjusted_red = min(255.0, max(0.0, original[0] + current_red[error_position]))
            adjusted_green = min(
                255.0, max(0.0, original[1] + current_green[error_position])
            )
            adjusted_blue = min(
                255.0, max(0.0, original[2] + current_blue[error_position])
            )

            palette_index = _nearest_palette_index(
                adjusted_red, adjusted_green, adjusted_blue
            )
            indices[position] = palette_index
            palette_red, palette_green, palette_blue = SPECTRA6_PALETTE[
                palette_index
            ]
            red_error = (adjusted_red - palette_red) * diffusion_factor
            green_error = (adjusted_green - palette_green) * diffusion_factor
            blue_error = (adjusted_blue - palette_blue) * diffusion_factor

            # Les poids Floyd-Steinberg sont appliqués seulement aux pixels
            # non protégés. Ainsi aucune erreur ne traverse leurs frontières.
            if can_receive_error(x + 1, y):
                current_red[error_position + 1] += red_error * 7 / 16
                current_green[error_position + 1] += green_error * 7 / 16
                current_blue[error_position + 1] += blue_error * 7 / 16
            if can_receive_error(x - 1, y + 1):
                next_red[error_position - 1] += red_error * 3 / 16
                next_green[error_position - 1] += green_error * 3 / 16
                next_blue[error_position - 1] += blue_error * 3 / 16
            if can_receive_error(x, y + 1):
                next_red[error_position] += red_error * 5 / 16
                next_green[error_position] += green_error * 5 / 16
                next_blue[error_position] += blue_error * 5 / 16
            if can_receive_error(x + 1, y + 1):
                next_red[error_position + 1] += red_error / 16
                next_green[error_position + 1] += green_error / 16
                next_blue[error_position + 1] += blue_error / 16

        current_red, next_red = next_red, [0.0] * (width + 2)
        current_green, next_green = next_green, [0.0] * (width + 2)
        current_blue, next_blue = next_blue, [0.0] * (width + 2)

    return _build_result(width, height, indices)


def convert_floyd_steinberg(
    image: Image.Image, diffusion_factor: float = DEFAULT_DIFFUSION_FACTOR
) -> ConversionResult:
    """Convertit toute l'image avec Floyd-Steinberg et la palette complète."""

    return _convert_with_floyd_steinberg(
        image,
        diffusion_factor=diffusion_factor,
    )


def _validate_hybrid_result(result: ConversionResult) -> None:
    """Vérifie les invariants du fichier destiné au firmware EE04."""

    if len(result.palette_indices) != BINARY_SIZE:
        raise ValueError(
            f"Le binaire doit contenir {BINARY_SIZE} octets exactement"
        )
    if any(index >= len(SPECTRA6_PALETTE) for index in result.palette_indices):
        raise ValueError("Le binaire contient un index de palette invalide")

    width, height = IMAGE_SIZE
    for y in range(height):
        row_start = y * width
        for x in range(width):
            if is_protected_pixel(x, y) and result.palette_indices[row_start + x] not in (
                BLACK_INDEX,
                WHITE_INDEX,
            ):
                raise ValueError("Une zone protégée contient une couleur interdite")


def convert_hybrid(
    image: Image.Image,
    *,
    luminance_threshold: int = DEFAULT_LUMINANCE_THRESHOLD,
    diffusion_factor: float = DEFAULT_DIFFUSION_FACTOR,
) -> ConversionResult:
    """Applique la conversion validée pour l'écran Spectra 6 du projet."""

    if image.size != IMAGE_SIZE:
        raise ValueError(
            f"L'image source doit mesurer {IMAGE_SIZE[0]} x {IMAGE_SIZE[1]} pixels"
        )

    result = _convert_with_floyd_steinberg(
        image,
        diffusion_factor=diffusion_factor,
        protected_pixel=is_protected_pixel,
        luminance_threshold=luminance_threshold,
    )
    _validate_hybrid_result(result)
    return result
