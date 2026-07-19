#!/usr/bin/env python3
"""Convertit le .bin 6 couleurs Spectra 6 en tableau C++ PROGMEM."""

import argparse
from pathlib import Path


IMAGE_PATH_DEFAULT = Path("generated/dashboard_hybrid40_bwui.bin")
HEADER_PATH_DEFAULT = Path("include/dashboard_image.h")
LARGEUR = 800
HAUTEUR = 480
TAILLE_ATTENDUE = LARGEUR * HAUTEUR

ENTETE_CPP = """#pragma once

#include <Arduino.h>

// Image dashboard Spectra 6 (palette: 0..5)
// - largeur : 800
// - hauteur : 480
// - taille  : 384000 octets
"""


def nom_tableau() -> str:
    """Nom du tableau généré."""
    return "DASHBOARD_IMAGE_DATA"


def lire_fichier_binaire(chemin: Path) -> bytes:
    """Lit le fichier binaire et effectue les contrôles demandés."""
    if not chemin.exists():
        raise FileNotFoundError(f"Fichier introuvable : {chemin}")

    donnees = chemin.read_bytes()
    if len(donnees) != TAILLE_ATTENDUE:
        raise ValueError(
            f"Taille invalide : {len(donnees)} octets. "
            f"Attendu : {TAILLE_ATTENDUE} octets."
        )
    max_index = max(donnees) if donnees else -1
    min_index = min(donnees) if donnees else 256
    if min_index < 0 or max_index > 5:
        raise ValueError(
            f"Indices invalides détectés : min={min_index}, max={max_index} "
            "(attendu 0..5)."
        )
    return donnees


def formater_liste(donnees: bytes, par_ligne: int = 24) -> str:
    """Retourne le contenu du tableau C++ lisible, en plusieurs valeurs par ligne."""
    lignes = []
    for i in range(0, len(donnees), par_ligne):
        chunk = ", ".join(str(v) for v in donnees[i : i + par_ligne])
        if i + par_ligne < len(donnees):
            ligne = f"    {chunk},"
        else:
            ligne = f"    {chunk}"
        lignes.append(ligne)
    return "\n".join(lignes)


def ecrire_header(chemin: Path, donnees: bytes):
    """Génère include/dashboard_image.h en PROGMEM."""
    texte = []
    texte.append(ENTETE_CPP.strip())
    texte.append(f"#define DASHBOARD_IMAGE_WIDTH {LARGEUR}")
    texte.append(f"#define DASHBOARD_IMAGE_HEIGHT {HAUTEUR}")
    texte.append(f"#define DASHBOARD_IMAGE_SIZE {TAILLE_ATTENDUE}")
    texte.append("")
    texte.append(f"const uint8_t {nom_tableau()}[DASHBOARD_IMAGE_SIZE] PROGMEM = {{")
    texte.append(formater_liste(donnees))
    texte.append("};")
    texte.append("")

    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(texte), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(
        description="Génère un header PROGMEM depuis un .bin 6 couleurs Spectra 6."
    )
    parser.add_argument(
        "--input",
        default=str(IMAGE_PATH_DEFAULT),
        help="Fichier binaire source (défaut: generated/dashboard_hybrid40_bwui.bin)",
    )
    parser.add_argument(
        "--output",
        default=str(HEADER_PATH_DEFAULT),
        help="Header C++ de sortie (défaut: include/dashboard_image.h)",
    )

    args = parser.parse_args()
    source = Path(args.input)
    sortie = Path(args.output)

    donnees = lire_fichier_binaire(source)
    ecrire_header(sortie, donnees)

    print("Conversion binaire -> header réussie.")
    print(f"Source         : {source}")
    print(f"Taille source  : {source.stat().st_size} octets")
    print(f"Sortie        : {sortie}")
    print(f"Nombre d'octets: {len(donnees)}")
    print("Validation    : OK (indices entre 0 et 5, taille 384000)")


if __name__ == "__main__":
    main()
