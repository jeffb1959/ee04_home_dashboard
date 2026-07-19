#!/usr/bin/env python3
"""Conversion de dashboard.png vers la palette Spectra 6 (6 couleurs)."""

import argparse
import sys
import time
from pathlib import Path

from PIL import Image


PALETTE = [
    (0, 0, 0),      # 0 : noir
    (255, 255, 255),# 1 : blanc
    (255, 0, 0),    # 2 : rouge
    (255, 255, 0),  # 3 : jaune
    (0, 255, 0),    # 4 : vert
    (0, 0, 255),    # 5 : bleu
]
NOMS_COULEURS = ["noir", "blanc", "rouge", "jaune", "vert", "bleu"]

LARGEUR = 800
HAUTEUR = 480
TAILLE_BINAIRE = LARGEUR * HAUTEUR

# Coefficients Floyd-Steinberg
FS_WEIGHTS = [
    (1, 0, 7 / 16),
    (-1, 1, 3 / 16),
    (0, 1, 5 / 16),
    (1, 1, 1 / 16),
]

# Zones protégées
ZONE_A_Y_MIN = 360
ZONE_A_Y_MAX = 479
ZONE_B_X_MIN = 500
ZONE_B_X_MAX = 779
ZONE_B_Y_MIN = 40
ZONE_B_Y_MAX = 319

# Matrices Bayer classiques (0..N^2-1)
BAYERS = {
    4: [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    8: [
        [0, 48, 12, 60, 3, 51, 15, 63],
        [32, 16, 44, 28, 35, 19, 47, 31],
        [8, 56, 4, 52, 11, 59, 7, 55],
        [40, 24, 36, 20, 43, 27, 39, 23],
        [2, 50, 14, 62, 1, 49, 13, 61],
        [34, 18, 46, 30, 33, 17, 45, 29],
        [10, 58, 6, 54, 9, 57, 5, 53],
        [42, 26, 38, 22, 41, 25, 37, 21],
    ],
}
BAYER_INTENSITE = 16

# Seuils de conversion noir/blanc dans zones UI
LUMINANCE_NOIR_BLANC = 150
LUMINANCE_BANDE = 155


def clamp_rgb(value: float) -> float:
    """Limite une valeur RGB entre 0 et 255."""
    if value < 0:
        return 0.0
    if value > 255:
        return 255.0
    return float(value)


def plus_proche_palette(r: float, g: float, b: float) -> int:
    """Retourne l'index palette le plus proche en distance RGB euclidienne."""
    meilleur_idx = 0
    meilleure_distance = None
    for idx, (pr, pg, pb) in enumerate(PALETTE):
        distance = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if meilleure_distance is None or distance < meilleure_distance:
            meilleure_distance = distance
            meilleur_idx = idx
    return meilleur_idx


def charger_pixels_rgb_float(image: Image.Image) -> list[float]:
    """Charge les pixels en liste [R,G,B,...] de type float, sans dépendance Numpy."""
    return [float(v) for v in image.tobytes()]


def construire_image_from_indices(indices: list[int]) -> tuple[Image.Image, list[int]]:
    """Construit une image RGB depuis les indices et compte les pixels par couleur."""
    compte = [0] * len(PALETTE)
    rgb_data = bytearray()
    for idx in indices:
        if idx < 0 or idx > 5:
            raise ValueError(f"Index de palette invalide: {idx}")
        compte[idx] += 1
        rgb_data.extend(PALETTE[idx])
    image = Image.frombytes("RGB", (LARGEUR, HAUTEUR), bytes(rgb_data))
    return image, compte


def verifier_image_source(img: Image.Image, source: Path):
    """Vérifie source existante, lisible et de taille attendue."""
    if not source.exists():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    if img.width != LARGEUR or img.height != HAUTEUR:
        raise ValueError(
            f"Taille invalide {img.width}x{img.height} (attendu {LARGEUR}x{HAUTEUR})."
        )


def verifier_bin(indices: list[int], path: Path):
    """Valide un tableau d'indices avant la sortie binaire."""
    if len(indices) != TAILLE_BINAIRE:
        raise ValueError(
            f"Taille indice invalide : {len(indices)} (attendu {TAILLE_BINAIRE})."
        )
    if any(idx < 0 or idx > 5 for idx in indices):
        raise ValueError("Un indice hors plage 0..5 a été généré.")
    path.write_bytes(bytearray(indices))
    if path.stat().st_size != TAILLE_BINAIRE:
        raise ValueError(
            f"Taille .bin incorrecte pour {path} : {path.stat().st_size} octets."
        )


def verifier_image_sortie(img: Image.Image):
    """Valide mode, dimensions et palette des images générées."""
    if img.size != (LARGEUR, HAUTEUR):
        raise ValueError(f"Image de sortie taille invalide: {img.size}.")
    if img.mode != "RGB":
        raise ValueError(f"Mode de sortie invalide: {img.mode}, attendu RGB.")
    autorisees = {c for c in PALETTE}
    raw = img.tobytes()
    for i in range(0, len(raw), 3):
        if (raw[i], raw[i + 1], raw[i + 2]) not in autorisees:
            raise ValueError("La palette de sortie contient une couleur non autorisée.")


def _type_zone_protegee(x: int, y: int):
    """Retourne le type de zone: 'meteo', 'bande' ou None."""
    if ZONE_A_Y_MIN <= y <= ZONE_A_Y_MAX:
        return "bande"
    if (
        ZONE_B_X_MIN <= x <= ZONE_B_X_MAX
        and ZONE_B_Y_MIN <= y <= ZONE_B_Y_MAX
    ):
        return "meteo"
    return None


def _est_zone_protegee(x: int, y: int) -> bool:
    """Retourne vrai si le pixel est dans une zone sans tramage."""
    return _type_zone_protegee(x, y) is not None


def _luminance_noir_blanc(r: float, g: float, b: float) -> int:
    """Conversion N/B par seuil de luminance."""
    valeur = 0.299 * r + 0.587 * g + 0.114 * b
    return 1 if valeur >= LUMINANCE_NOIR_BLANC else 0


def _est_pixel_jaune_cles(r: float, g: float, b: float) -> bool:
    """Détecte un jaune clair suffisant pour la carte météo."""
    return (
        r >= 220
        and g >= 210
        and b <= 150
        and (r - b) >= 70
        and (g - b) >= 70
        and abs(r - g) <= 45
        and (r + g + b) / 3 >= 230
    )


def _convertir_meteo(r: float, g: float, b: float) -> int:
    """
    Carte météo:
    - noir/blanc par défaut
    - jaune autorisé seulement si le pixel est très clair et jaune.
    """
    if _est_pixel_jaune_cles(r, g, b):
        return 3
    return _luminance_noir_blanc(r, g, b)


def _convertir_bande(r: float, g: float, b: float) -> int:
    """Bande inférieure en noir/blanc strict."""
    valeur = 0.299 * r + 0.587 * g + 0.114 * b
    return 1 if valeur >= LUMINANCE_BANDE else 0


def convertir_direct(image: Image.Image):
    """Conversion directe: couleur de palette la plus proche pour chaque pixel."""
    raw = charger_pixels_rgb_float(image)
    indices = [0] * TAILLE_BINAIRE
    for i in range(TAILLE_BINAIRE):
        base = i * 3
        idx = plus_proche_palette(raw[base], raw[base + 1], raw[base + 2])
        indices[i] = idx
    sortie, compte = construire_image_from_indices(indices)
    verifier_image_sortie(sortie)
    return sortie, indices, compte


def convertir_floyd_steinberg(image: Image.Image, facteur: float):
    """Floyd-Steinberg avec facteur de diffusion."""
    raw = charger_pixels_rgb_float(image)
    indices = [0] * TAILLE_BINAIRE
    for y in range(HAUTEUR):
        for x in range(LARGEUR):
            i = y * LARGEUR + x
            base = i * 3
            idx = plus_proche_palette(raw[base], raw[base + 1], raw[base + 2])
            indices[i] = idx

            pr, pg, pb = PALETTE[idx]
            err_r = raw[base] - pr
            err_g = raw[base + 1] - pg
            err_b = raw[base + 2] - pb

            for dx, dy, coeff in FS_WEIGHTS:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= LARGEUR or ny < 0 or ny >= HAUTEUR:
                    continue
                n = (ny * LARGEUR + nx) * 3
                raw[n] = clamp_rgb(raw[n] + err_r * coeff * facteur)
                raw[n + 1] = clamp_rgb(raw[n + 1] + err_g * coeff * facteur)
                raw[n + 2] = clamp_rgb(raw[n + 2] + err_b * coeff * facteur)

    sortie, compte = construire_image_from_indices(indices)
    verifier_image_sortie(sortie)
    return sortie, indices, compte


def convertir_bayer(image: Image.Image, taille_matrice: int):
    """Ordered dithering Bayer NxN puis quantification vers la palette 6 couleurs."""
    raw = charger_pixels_rgb_float(image)
    matrice = BAYERS[taille_matrice]
    denom = taille_matrice * taille_matrice
    indices = [0] * TAILLE_BINAIRE
    for y in range(HAUTEUR):
        for x in range(LARGEUR):
            i = y * LARGEUR + x
            base = i * 3
            seuil = matrice[y % taille_matrice][x % taille_matrice]
            offset = (seuil / denom - 0.5) * BAYER_INTENSITE

            r = clamp_rgb(raw[base] + offset)
            g = clamp_rgb(raw[base + 1] + offset)
            b = clamp_rgb(raw[base + 2] + offset)

            idx = plus_proche_palette(r, g, b)
            indices[i] = idx
    sortie, compte = construire_image_from_indices(indices)
    verifier_image_sortie(sortie)
    return sortie, indices, compte


def convertir_hybride(image: Image.Image, facteur: float):
    """
    Mode hybride :
    - fond illustré : Floyd-Steinberg à facteur variable (palette 6)
    - météo : noir/blanc, jaune seulement pour éléments très clairs
    - bande inférieure : noir/blanc uniquement
    - pas de propagation d'erreur vers ou depuis une zone protégée.
    """
    source = charger_pixels_rgb_float(image)
    raw = source.copy()
    indices = [0] * TAILLE_BINAIRE

    for y in range(HAUTEUR):
        for x in range(LARGEUR):
            i = y * LARGEUR + x
            base = i * 3
            zone = _type_zone_protegee(x, y)

            if zone == "meteo":
                indices[i] = _convertir_meteo(source[base], source[base + 1], source[base + 2])
                continue

            if zone == "bande":
                indices[i] = _convertir_bande(source[base], source[base + 1], source[base + 2])
                continue

            idx = plus_proche_palette(raw[base], raw[base + 1], raw[base + 2])
            indices[i] = idx
            pr, pg, pb = PALETTE[idx]
            err_r = raw[base] - pr
            err_g = raw[base + 1] - pg
            err_b = raw[base + 2] - pb

            for dx, dy, coeff in FS_WEIGHTS:
                nx = x + dx
                ny = y + dy
                if nx < 0 or nx >= LARGEUR or ny < 0 or ny >= HAUTEUR:
                    continue
                if _est_zone_protegee(nx, ny):
                    continue
                n = (ny * LARGEUR + nx) * 3
                raw[n] = clamp_rgb(raw[n] + err_r * coeff * facteur)
                raw[n + 1] = clamp_rgb(raw[n + 1] + err_g * coeff * facteur)
                raw[n + 2] = clamp_rgb(raw[n + 2] + err_b * coeff * facteur)

    sortie, compte = construire_image_from_indices(indices)
    verifier_image_sortie(sortie)
    return sortie, indices, compte


def sauvegarder_variant(nom: str, image: Image.Image, indices: list[int], output_dir: Path):
    """Sauvegarde PNG + BIN pour un variant."""
    png = output_dir / f"{nom}.png"
    bin_path = output_dir / f"{nom}.bin"
    image.save(png)
    verifier_image_sortie(image)
    verifier_bin(indices, bin_path)
    return png, bin_path


def print_compte(label: str, compte: list[int]):
    print(label)
    for i, nom in enumerate(NOMS_COULEURS):
        print(f" - {nom} : {compte[i]} px")


def main():
    parser = argparse.ArgumentParser(
        description="Compare plusieurs methodes de conversion vers la palette Spectra 6."
    )
    parser.add_argument(
        "--input",
        default="assets/dashboard.png",
        help="Image d'entree (defaut: assets/dashboard.png)",
    )
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        print(f"Erreur: fichier source introuvable : {source}")
        return 1

    try:
        image = Image.open(source)
        image.load()
    except Exception as exception:
        print(f"Erreur: impossible d'ouvrir l'image : {exception}")
        return 1

    if image.mode != "RGB":
        image = image.convert("RGB")

    try:
        verifier_image_source(image, source)
    except Exception as exception:
        print(f"Erreur de validation: {exception}")
        return 1

    generated = Path("generated")
    generated.mkdir(exist_ok=True)

    variants = [
        ("dashboard_direct", lambda: convertir_direct(image)),
        ("dashboard_fs80", lambda: convertir_floyd_steinberg(image, 0.8)),
        ("dashboard_fs60", lambda: convertir_floyd_steinberg(image, 0.6)),
        ("dashboard_fs40", lambda: convertir_floyd_steinberg(image, 0.4)),
        ("dashboard_bayer4", lambda: convertir_bayer(image, 4)),
        ("dashboard_bayer8", lambda: convertir_bayer(image, 8)),
        ("dashboard_hybrid40", lambda: convertir_hybride(image, 0.4)),
        ("dashboard_hybrid50", lambda: convertir_hybride(image, 0.5)),
    ]

    debut_total = time.perf_counter()
    temps_variants = []
    resultats = []

    for nom, fonction in variants:
        t0 = time.perf_counter()
        img, indices, compte = fonction()
        t_ms = (time.perf_counter() - t0) * 1000
        png_path, bin_path = sauvegarder_variant(nom, img, indices, generated)
        temps_variants.append((nom, t_ms))
        resultats.append({
            "nom": nom,
            "png": png_path,
            "bin": bin_path,
            "bin_size": bin_path.stat().st_size,
            "compte": compte,
        })

    temps_total = (time.perf_counter() - debut_total) * 1000

    print("=== Rapport conversion Spectra 6 ===")
    print(f"Image source : {source}")
    print(f"Dimensions : {image.width}x{image.height}")
    print("Temps par variante (ms) :")
    for nom, t_ms in temps_variants:
        print(f" - {nom} : {t_ms:.2f} ms")
    print(f"Temps total : {temps_total:.2f} ms")
    print("Fichiers generes :")
    for item in resultats:
        print(f" - PNG : {item['png']}")
        print(f" - BIN : {item['bin']}")
    print("Tailles des .bin :")
    for item in resultats:
        print(f" - {item['bin']} : {item['bin_size']} octets")
    for item in resultats:
        print_compte(f"Pixels par couleur ({item['nom']}) :", item["compte"])

    return 0


if __name__ == "__main__":
    sys.exit(main())
