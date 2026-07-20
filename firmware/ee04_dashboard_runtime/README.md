# Phase 1.5B.1 — Téléchargement dashboard binaire sans affichage

## Objectif

Cette phase implémente un firmware stable qui :
- télécharge `dashboard.bin` depuis `DASHBOARD_URL` (défini dans `include/wifi_secrets.h`),
- valide strictement le contenu binaire,
- enregistre l'image dans LittleFS,
- remplace de façon atomique le fichier précédent uniquement après validation complète,
- sans encore rafraîchir l'écran e-paper.

## Paramètres de format

- Résolution cible : **800 x 480**
- Format : **1 octet par pixel**
- Taille attendue : **384000 octets**
- Chaque octet doit être compris entre **0 et 5**

## Comportement du remplacement

- Le téléchargement s'effectue dans `/dashboard.tmp`.
- Le fichier temporaire est validé (taille et plages de valeurs) avant remplacement.
- En cas d'erreur de validation ou de réseau, `/dashboard.tmp` est supprimé et l'ancien `/dashboard.bin` est conservé.
- En cas de succès, `/dashboard.tmp` remplace `/dashboard.bin` de manière atomique.

## Build / Upload / Monitor

Depuis `firmware/ee04_dashboard_runtime` :
- `pio run`
- `pio run -t upload`
- `pio device monitor -b 115200`

## Rythme d'exécution

- 1er téléchargement : ~5 secondes après démarrage
- Téléchargements suivants : toutes les 5 minutes
- Rapport d'état : toutes les 10 secondes
- Aucune attente bloquante de 300000 ms (planification via `millis()`)

## Détails observables sur la liaison série

Au démarrage :
- nom du projet
- phase
- raison du redémarrage
- MAC
- état et espace LittleFS

Pour chaque cycle :
- code HTTP
- MIME (`application/octet-stream` attendu)
- octets reçus
- taille du fichier final
- délai de téléchargement
- RSSI
- nombre d'octets invalides
- `SUCCES` ou `ECHEC`

## Test manuel de 20 cycles

1. Démarrer le moniteur série en 115200.
2. Vérifier qu'un premier cycle se lance autour de `+5s`.
3. Laisser fonctionner 20 cycles (~100 minutes, cadence 5 min).
4. Contrôler les logs :
   - chaque cycle doit afficher un résultat `SUCCES` ou `ECHEC`,
   - en succès, vérifier l'affichage du résultat et de la taille 384000,
   - en échec réseau, vérifier que l'ancien `/dashboard.bin` reste présent.

## Limites actuelles de la phase

- Pas d'initialisation écran / affichage e-paper.
- Pas de PNG, ni Home Assistant.
- Pas de deep sleep.
- Pas de bouton.
- Pas d'autoload (build/upload/monitor non lancés automatiquement).
