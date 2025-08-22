#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
plt_mcc.py

Auteur(s) : Sarah MARTIN-ALONSO (modifié)
Date de création : 2025-08-13

Résumé
------
Application graphique (Tkinter + Matplotlib) pour comparer des acquisitions
dosimétriques au format MCC : PDD (Percent Depth Dose) et Profils (inplane /
crossplane). Le programme lit les métadonnées, déduit des paramètres (énergie,
SSD, champs, FOV, orientation détecteur…), les affiche dans un tableau
interactif et trace les courbes avec styles et légendes configurables
(couleurs / marqueurs mappés sur un paramètre variable). Les préférences sont
persistées globalement et par fichier (~/.mcc_plotter_prefs.json). Export PNG
disponible.

Points clefs
------------
- 1 ligne par fichier, les colonnes d’info se remplissent via métadonnées MCC
  et/ou overrides manuels.
- DETECTOR_TYPE → référence PTW (extraction type "Txxxxx" → "PTW xxxxx").
- SSD lu en mm dans MCC, converti en cm pour l’UI.
- Énergie suffixée "FFF" si applicable (détectée via différents indicateurs).
- Profondeurs dédupliquées (union inplane + crossplane), affichées en cm.
- Mode de scan "Fixe / Variable (mm)" ou "Continu (mm/s)" inféré automatiquement.
- Orientation détecteur : DETECTOR_ORIENTATION HORIZONTAL→Radial, VERTICAL→Axial.
- Colonne unique "Mâchoire X*Y @ 100 cm" (mise à l’échelle au plan 100 cm).
- Colonne FOV listant "@z cm : X*Y" pour toutes les profondeurs détectées.

IMPORTANT (correctifs exigés)
-----------------------------
- Lors du tracé des PROFILS, on segmente toujours par profondeur trouvée dans
  les données MCC (inplane/crossplane), même si la cellule "depth" de la ligne
  n’est pas renseignée depuis le JSON.
- Si le paramètre variable = FOV, chaque profil utilise le FOV **à sa propre
  profondeur** pour la couleur et la légende (espace de noms séparé "fov@depth").

Usage
-----
    python3 plt_mcc.py

Dépendances
-----------
- Python 3.8+
- matplotlib
- tkinter (standard library)

Licence
-------
Ce script est fourni tel quel, sans garantie. À adapter selon votre contexte QA.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib
import matplotlib.pyplot as plt
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

# ======================== Dataviz ============================================

matplotlib.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 12,
    "axes.titlesize": 20,
    "axes.labelsize": 18,
    "legend.fontsize": 16,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "axes.edgecolor": "#222222",
    "text.color": "#111111",
    "axes.labelcolor": "#111111",
    "xtick.color": "#111111",
    "ytick.color": "#111111",
    "grid.color": "#cccccc",
    "grid.linewidth": 0.7,
    "axes.grid": True,
})

# ======================== Constantes =========================================

APP_TITLE = "Comparateur MCC – PDD / Profil"
WINDOW_GEOMETRY = "1180x700"
WINDOW_MIN_WIDTH = 980
WINDOW_MIN_HEIGHT = 560

PREFS_PATH = Path.home() / ".mcc_plotter_prefs.json"

# Clés de préférences
PREF_KEY_FILES = "files"      # par-fichier (clé = chemin absolu du fichier)
PREF_KEY_GLOBAL = "global"
PREF_KEY_MEASURE_TYPE = "measure_type"
PREF_KEY_NORMALIZE = "normalize"
PREF_KEY_PROFILE_INPLANE = "profile_inplane"
PREF_KEY_PROFILE_CROSSPLANE = "profile_crossplane"
PREF_KEY_CUSTOM_TITLE = "custom_title"
PREF_KEY_COLOR_VAR = "color_variable"
PREF_KEY_MARKER_VAR = "marker_variable"
PREF_KEY_COLOR_MAPS = "color_maps"
PREF_KEY_MARKER_MAPS = "marker_maps"

# Modes / types
MEASURE_PDD = "pdd"
MEASURE_PROFILE = "profil"

# Valeurs par défaut
DEFAULT_MEASURE_TYPE = MEASURE_PDD
DEFAULT_NORMALIZE = True
DEFAULT_PROFILE_INPLANE = True
DEFAULT_PROFILE_CROSSPLANE = True
DEFAULT_CUSTOM_TITLE = ""
DEFAULT_COLOR_VAR = "detector"
DEFAULT_MARKER_VAR = ""

# Tracé
DEFAULT_LINESTYLE = "-"
FORCED_INPLANE_LINESTYLE = "-"
FORCED_CROSSPLANE_LINESTYLE = "--"
OKABE_ITO = (
    "#0072B2", "#E69F00", "#009E73", "#D55E00",
    "#CC79A7", "#56B4E9", "#F0E442", "#000000",
)
MARKER_POOL = ("o", "s", "^", "v", "d", "p", "h", "x", "*", "+", "<", ">", ".")
PLOT_SIZE = (10, 6)
EXPORT_DPI = 300
LINEWIDTH = 2.0
MARKERSIZE = 5

# UI
SYMBOL_INCLUDE = "✔"
SYMBOL_EXCLUDE = "✖"
FILE_DIALOG_TITLE = "Sélectionne des fichiers .mcc"
FILE_TYPES_MCC = (("Fichiers MCC", "*.mcc"),)
EXPORT_DEFAULT_NAME = "mcc_plot.png"
EXPORT_DIALOG_TITLE = "Enregistrer la figure"

# Paramètres affichés (orientation = orientation du détecteur)
PARAMS: List[Tuple[str, str]] = [
    ("detector", "Détecteur"),
    ("energy", "Énergie [MV]"),
    ("ssd", "DSP [cm]"),
    ("depth", "Profondeur [cm]"),
    ("dose_rate", "Débit de dose"),
    ("step", "Pas / Mode"),
    ("integration", "Intégr. [s]"),
    ("gantry", "Angle bras [°]"),
    ("jaw_xy", "Mâchoire X*Y @ 100 cm"),
    ("fov", "FOV @ point [cm]"),
    ("Orientation", "Orientation détecteur"),
]

DEFAULT_SAD_CM = 100.0

# ======================== Utilitaires ========================================


def normalize(values: Iterable[float]) -> List[float]:
    """
    Normaliser une séquence de valeurs sur [0, 1] en divisant par le maximum.

    :param values: Itérable de valeurs numériques.
    :type values: Iterable[float]
    :return: Liste normalisée (vide si `values` est vide).
    :rtype: List[float]
    """
    vals = list(values)
    if not vals:
        return []
    maximum = max(vals)
    if maximum == 0:
        return vals
    return [v / maximum for v in vals]


def _as_float(txt: Optional[str]) -> Optional[float]:
    """
    Convertir une chaîne vers float en prenant en charge la virgule décimale.

    :param txt: Chaîne à convertir (peut être None).
    :type txt: Optional[str]
    :return: Nombre flottant, ou None si conversion invalide.
    :rtype: Optional[float]
    """
    if txt is None:
        return None
    try:
        return float(str(txt).strip().replace(",", "."))
    except ValueError:
        return None


def _parse_depth_csv_cm(txt: str) -> List[float]:
    """
    Parser une chaîne CSV de profondeurs (en cm). Les duplicats (à 2 décimales)
    sont retirés en conservant le premier ordre d'apparition.

    :param txt: Chaîne CSV, séparateurs ',' ou ';'.
    :type txt: str
    :return: Liste des profondeurs uniques en cm.
    :rtype: List[float]
    """
    raw: List[float] = []
    for part in str(txt).replace(";", ",").split(","):
        val = _as_float(part)
        if val is not None:
            raw.append(val)
    seen = set()
    out: List[float] = []
    for depth in raw:
        key = round(depth, 2)
        if key not in seen:
            seen.add(key)
            out.append(depth)
    return out


def _parse_csv_floats(txt: str) -> List[float]:
    """
    Parser une chaîne CSV quelconque en liste de flottants.

    :param txt: Chaîne CSV, séparateurs ',' ou ';'.
    :type txt: str
    :return: Liste de floats (les tokens non-numériques sont ignorés).
    :rtype: List[float]
    """
    out: List[float] = []
    for part in str(txt).replace(";", ",").split(","):
        val = _as_float(part)
        if val is not None:
            out.append(val)
    return out


# ======================== Parsing MCC ========================================

KV_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.+?)\s*$")


def _scan_keyvals(lines: List[str]) -> Dict[str, str]:
    """
    Extraire des paires clé/valeur à partir des lignes entêtes d'un MCC.

    :param lines: Lignes du fichier MCC.
    :type lines: List[str]
    :return: Dictionnaire des métadonnées (clé en MAJUSCULES).
    :rtype: Dict[str, str]
    """
    kv: Dict[str, str] = {}
    for raw in lines:
        if "BEGIN_DATA" in raw or "END_DATA" in raw:
            continue
        match = KV_RE.match(raw)
        if match:
            kv[match.group(1).upper()] = match.group(2).strip()
    return kv


def parse_mcc_profiles_all(filepath: Path | str) -> Dict[str, List[Dict[str, object]]]:
    """
    Parser toutes les courbes profil d'un fichier MCC.

    Structure de retour :
        {
          "inplane": [
              {"depth_mm": float|None, "xs": List[float], "ys": List[float]},
              ...
          ],
          "crossplane": [
              ...
          ]
        }

    :param filepath: Chemin de fichier .mcc.
    :type filepath: Path | str
    :return: Dictionnaire par orientation (absent si aucune courbe de ce type).
    :rtype: Dict[str, List[Dict[str, object]]]
    """
    path = Path(filepath)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:  # pragma: no cover - robustesse I/O
        print(f"Erreur d'ouverture {path}: {exc}")
        return {}

    current_kind: Optional[str] = None
    current_depth: Optional[float] = None
    in_data = False
    xs: List[float] = []
    ys: List[float] = []
    result: Dict[str, List[Dict[str, object]]] = {"inplane": [], "crossplane": []}

    def commit() -> None:
        """
        Commit interne : pousse la courbe accumulée dans `result`.

        :return: None
        :rtype: None
        """
        nonlocal xs, ys, current_kind, current_depth
        if current_kind in ("inplane", "crossplane") and xs and ys:
            result[current_kind].append({
                "depth_mm": float(current_depth) if current_depth is not None else None,
                "xs": xs, "ys": ys
            })
        xs, ys = [], []

    for raw in lines:
        line = raw.strip()

        if line.startswith("SCAN_CURVETYPE="):
            if in_data:
                commit()
                in_data = False
            val = line.split("=", 1)[1].strip().upper()
            if "INPLANE_PROFILE" in val:
                current_kind = "inplane"
            elif "CROSSPLANE_PROFILE" in val:
                current_kind = "crossplane"
            else:
                current_kind = None

        elif line.startswith("SCAN_DEPTH="):
            try:
                current_depth = float(line.split("=", 1)[1].strip())
            except ValueError:
                current_depth = None

        elif "BEGIN_DATA" in line:
            in_data = True
            xs, ys = [], []

        elif "END_DATA" in line:
            if in_data:
                commit()
            in_data = False

        elif in_data and current_kind:
            parts = line.split()
            if len(parts) >= 2:
                try:
                    xs.append(float(parts[0]))
                    ys.append(float(parts[1]))
                except ValueError:
                    # Ignore lignes malformées dans les données
                    pass

    if in_data:
        commit()

    if not result["inplane"]:
        result.pop("inplane", None)
    if not result["crossplane"]:
        result.pop("crossplane", None)
    return result


def parse_mcc_pdd(filepath: Path | str) -> Tuple[Optional[List[float]], Optional[List[float]]]:
    """
    Parser une acquisition PDD depuis un fichier MCC.

    :param filepath: Chemin du fichier MCC.
    :type filepath: Path | str
    :return: Tuple (xs, ys) ou (None, None) si échec / non trouvé.
    :rtype: Tuple[Optional[List[float]], Optional[List[float]]]
    """
    path = Path(filepath)
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception as exc:  # pragma: no cover
        print(f"Erreur d'ouverture {path}: {exc}")
        return None, None
    try:
        i0 = next(i for i, l in enumerate(lines) if "BEGIN_DATA" in l)
        i1 = next(i for i, l in enumerate(lines) if "END_DATA" in l)
    except StopIteration:
        return None, None
    xs: List[float] = []
    ys: List[float] = []
    for line in lines[i0 + 1:i1]:
        parts = line.split()
        if len(parts) >= 2:
            try:
                xs.append(float(parts[0]))
                ys.append(float(parts[1]))
            except ValueError:
                pass
    return (xs or None), (ys or None)


# ======================== Mapping métadonnées ================================


def _pick(meta: Dict[str, str], *keys: str) -> Optional[str]:
    """
    Retourner la première valeur non vide trouvée parmi `keys` dans `meta`.

    :param meta: Métadonnées (clés en MAJUSCULES).
    :type meta: Dict[str, str]
    :param keys: Liste de clés testées dans l'ordre.
    :type keys: str
    :return: Valeur correspondante ou None.
    :rtype: Optional[str]
    """
    for key in keys:
        if key in meta and str(meta[key]).strip():
            return meta[key]
    return None


def _energy_from(meta: Dict[str, str]) -> Optional[str]:
    """
    Déduire l'énergie (MV) et suffixer FFF si applicable.

    Détecte FFF via :
      - présence de 'FFF' dans ENERGY
      - présence de 'FFF' dans l'ensemble des métadonnées
      - 'FLATTENING' et 'OFF/FREE' présents

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: Chaîne énergie (ex. '6 MV', '10 MV FFF') ou None si inconnue.
    :rtype: Optional[str]
    """
    energy = _pick(meta, "ENERGY", "SCAN_ENERGY", "BEAM_ENERGY", "XRAY_ENERGY")
    if not energy:
        return None
    e = str(energy).strip()
    up_all = " ".join([f"{k}={v}" for k, v in meta.items()]).upper()
    want_fff = ("FFF" in e.upper()) or ("FFF" in up_all) or (
        "FLATTENING" in up_all and ("OFF" in up_all or "FREE" in up_all)
    )
    if "FFF" not in e.upper() and want_fff:
        e = f"{e} FFF"
    return e


def _detector_from(meta: Dict[str, str]) -> Optional[str]:
    """
    Déduire la référence PTW depuis DETECTOR_TYPE (extrait 'Txxxxx').

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: Chaîne 'PTW xxxxx' ou None si non détectable.
    :rtype: Optional[str]
    """
    raw = _pick(meta, "DETECTOR_TYPE", "DETECTOR", "SENSOR_TYPE")
    if not raw:
        return None
    match = re.search(r"\bT([A-Za-z0-9\-]+)\b", str(raw))
    if not match:
        return None
    ref = match.group(1)
    return f"PTW {ref}"


def _ssd_cm_from_mm(meta: Dict[str, str]) -> Optional[float]:
    """
    Extraire la SSD en cm (converti depuis mm si besoin).

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: SSD en cm ou None.
    :rtype: Optional[float]
    """
    value = _pick(meta, "SSD", "SCAN_SSD", "SOURCE_SURFACE_DISTANCE", "DSP")
    val = _as_float(value)
    if val is None:
        return None
    return val / 10.0  # mm -> cm


def _sid_from(meta: Dict[str, str]) -> Optional[float]:
    """
    SID/SAD en cm si présent dans les métadonnées.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: Distance en cm ou None.
    :rtype: Optional[float]
    """
    value = _pick(meta, "SID", "SOURCE_IMAGE_DISTANCE", "SAD")
    return _as_float(value)


def _gantry_from(meta: Dict[str, str]) -> Optional[float]:
    """
    Angle de bras (gantry) en degrés si présent.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: Angle en degrés ou None.
    :rtype: Optional[float]
    """
    value = _pick(meta, "GANTRY", "GANTRY_ANGLE", "SCAN_GANTRY", "BEAM_ANGLE")
    return _as_float(value)


def _dose_rate_from(meta: Dict[str, str]) -> Optional[str]:
    """
    Débit de dose (texte tel que fourni).

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: Chaîne de débit de dose ou None.
    :rtype: Optional[str]
    """
    return _pick(meta, "DOSE_RATE", "MU_PER_MIN", "DOSE_RATE_MU_MIN")


def _orientation_from(meta: Dict[str, str]) -> Optional[str]:
    """
    Orientation détecteur à partir de DETECTOR_ORIENTATION.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: 'Radial', 'Axial' ou None.
    :rtype: Optional[str]
    """
    orient = (_pick(meta, "DETECTOR_ORIENTATION") or "").strip().upper()
    if orient.startswith("HOR"):
        return "Radial"
    if orient.startswith("VER"):
        return "Axial"
    return None


def _jaws_from(meta: Dict[str, str],
               depth_mm_for_guess: Optional[float]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Déduire la taille de champ aux mâchoires (X,Y en cm) et le plan de référence.

    Sources possibles :
      - JAW_X/JAW_Y/FIELD_X/FIELD_Y/COLL_X/COLL_Y (déjà en cm)
      - FIELD_INPLANE/FIELD_CROSSPLANE (en mm) + FIELD_DEFINED (plan)
    Le plan de référence (`d_ref_cm`) peut être l’isocentre (100 cm), SSD ou SSD+profondeur.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :param depth_mm_for_guess: Profondeur (mm) pour estimer le plan si ambigu.
    :type depth_mm_for_guess: Optional[float]
    :return: (jawx_cm, jawy_cm, d_ref_cm)
    :rtype: Tuple[Optional[float], Optional[float], Optional[float]]
    """
    jawx = _as_float(_pick(meta, "JAW_X", "FIELD_X", "COLL_X"))
    jawy = _as_float(_pick(meta, "JAW_Y", "FIELD_Y", "COLL_Y"))

    if jawx is None or jawy is None:
        rf_x_mm = _as_float(_pick(meta, "FIELD_INPLANE", "FIELD_INPLANE"))
        rf_y_mm = _as_float(_pick(meta, "FIELD_CROSSPLANE", "FIELD_CROSSPLANE"))
        if rf_x_mm is not None and rf_y_mm is not None:
            jawx = rf_x_mm / 10.0
            jawy = rf_y_mm / 10.0

    ssd_cm = _ssd_cm_from_mm(meta)
    refdef = (_pick(meta, "FIELD_DEFINED", "FIELD_REFERENCE", "FIELD_AT") or "").strip().upper()
    d_ref: Optional[float] = None

    ref_depth_cm = _as_float(_pick(meta, "FIELD_DEPTH"))
    if ref_depth_cm is not None:
        ref_depth_cm /= 10.0

    if "ISO" in refdef or "ISOCENTER" in refdef or "SAD" in refdef:
        d_ref = DEFAULT_SAD_CM
    elif "SSD" in refdef and ssd_cm is not None:
        d_ref = ssd_cm
    elif "DEPTH" in refdef and ssd_cm is not None and ref_depth_cm is not None:
        d_ref = ssd_cm + ref_depth_cm

    if d_ref is None:
        depth_cm_guess = None if depth_mm_for_guess is None else (depth_mm_for_guess / 10.0)
        if ssd_cm is not None and depth_cm_guess is not None:
            d_ref = ssd_cm + depth_cm_guess
        elif ssd_cm is not None:
            d_ref = ssd_cm
        else:
            d_ref = None

    return jawx, jawy, d_ref


def _scale_jaw_to_100(jaw_raw_cm: Optional[float], d_ref_cm: Optional[float]) -> Optional[float]:
    """
    Mettre à l'échelle une ouverture de mâchoire (cm) vers le plan 100 cm.

    :param jaw_raw_cm: Taille de mâchoire mesurée au plan de référence.
    :type jaw_raw_cm: Optional[float]
    :param d_ref_cm: Distance du plan de référence (cm).
    :type d_ref_cm: Optional[float]
    :return: Taille correspondante à 100 cm, ou valeur d'origine si indéterminable.
    :rtype: Optional[float]
    """
    if jaw_raw_cm is None or d_ref_cm is None or d_ref_cm == 0:
        return jaw_raw_cm
    return jaw_raw_cm * (DEFAULT_SAD_CM / d_ref_cm)


# ---- FOV helpers -------------------------------------------------------------


def _unique_depths_cm_from_mm(depths_mm: List[float]) -> List[float]:
    """
    Convertir et dédupliquer des profondeurs en mm → cm (arrondi 0.01).

    :param depths_mm: Profondeurs en mm.
    :type depths_mm: List[float]
    :return: Profondeurs uniques en cm triées.
    :rtype: List[float]
    """
    return sorted({round(mm / 10.0, 2) for mm in depths_mm if mm is not None})


def _fov_at_depth_pair(meta: Dict[str, str], depth_cm: float) -> Optional[Tuple[float, float]]:
    """
    Calculer le FOV (X,Y) au point en profondeur `depth_cm`.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :param depth_cm: Profondeur en cm.
    :type depth_cm: float
    :return: Tuple (fx, fy) en cm, ou None si indéterminable.
    :rtype: Optional[Tuple[float, float]]
    """
    ssd_cm = _ssd_cm_from_mm(meta)
    if ssd_cm is None:
        return None
    jawx, jawy, d_ref = _jaws_from(meta, depth_mm_for_guess=depth_cm * 10.0)
    jawx100 = _scale_jaw_to_100(jawx, d_ref)
    jawy100 = _scale_jaw_to_100(jawy, d_ref)
    if jawx100 is None or jawy100 is None:
        return None
    fx = jawx100 * (ssd_cm + depth_cm) / DEFAULT_SAD_CM
    fy = jawy100 * (ssd_cm + depth_cm) / DEFAULT_SAD_CM
    return fx, fy


def _fov_at_depth_str(meta: Dict[str, str], depth_cm: float) -> Optional[str]:
    """
    Formatter le FOV (X*Y) à une profondeur donnée.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :param depth_cm: Profondeur cm.
    :type depth_cm: float
    :return: Texte 'X*Y' (deux décimales) ou None.
    :rtype: Optional[str]
    """
    pair = _fov_at_depth_pair(meta, depth_cm)
    if not pair:
        return None
    fx, fy = pair
    return f"{fx:.2f}*{fy:.2f}"


def _fov_string_from(meta: Dict[str, str], depths_mm: List[float]) -> Optional[str]:
    """
    Concaténer les FOV pour une liste de profondeurs (union in+cross).

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :param depths_mm: Profondeurs en mm (avec doublons possibles).
    :type depths_mm: List[float]
    :return: Chaîne du type '@z cm : X*Y ; ...' ou None.
    :rtype: Optional[str]
    """
    depths_cm = _unique_depths_cm_from_mm(depths_mm)
    if not depths_cm:
        return None
    parts = []
    for z in depths_cm:
        fov = _fov_at_depth_str(meta, z)
        if fov:
            parts.append(f"@{z:.1f} cm : {fov}")
    return " ; ".join(parts) if parts else None


# ---- Pas / Mode (auto) ------------------------------------------------------


def _infer_mode(meta: Dict[str, str]) -> Optional[str]:
    """
    Inférer le mode de mesure depuis MEAS_PRESET.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :return: 'continuous', 'step' ou None si inconnu.
    :rtype: Optional[str]
    """
    preset = (meta.get("MEAS_PRESET") or "").strip().upper()
    if "MEAS_CONTINUOUS" in preset:
        return "continuous"
    if "REFERENCE_DOSEMETER" in preset:
        return "step"
    return None


def _step_from_positions_csv(csv_txt: Optional[str]) -> Optional[Tuple[float, float, bool]]:
    """
    Déduire le pas minimal / maximal et si le pas est fixe ou variable.

    :param csv_txt: Chaîne CSV des positions (mm).
    :type csv_txt: Optional[str]
    :return: (pas_min, pas_max, is_fixed) ou None.
    :rtype: Optional[Tuple[float, float, bool]]
    """
    if not csv_txt:
        return None
    xs = _parse_csv_floats(csv_txt)
    if len(xs) < 2:
        return None
    diffs = []
    for a, b in zip(xs[:-1], xs[1:]):
        d = abs(b - a)
        if d > 1e-6:
            diffs.append(d)
    if not diffs:
        return None
    dmin = min(diffs)
    dmax = max(diffs)
    is_fixed = abs(dmax - dmin) <= 1e-3
    return dmin, dmax, is_fixed


def _step_mode_string(meta: Dict[str, str], measure_kind: str) -> Optional[str]:
    """
    Construire une description textuelle du mode/pas de mesure.

    :param meta: Métadonnées MCC.
    :type meta: Dict[str, str]
    :param measure_kind: 'pdd' ou 'profil'.
    :type measure_kind: str
    :return: 'Continu (x mm/s)', 'Fixe (x mm)', 'Variable (a–b mm)' ou None.
    :rtype: Optional[str]
    """
    mode = _infer_mode(meta)
    if mode == "continuous":
        speed = None
        if measure_kind == MEASURE_PDD:
            speed = _as_float(meta.get("SCAN_SPEED_PDD"))
        elif measure_kind == MEASURE_PROFILE:
            speed = _as_float(meta.get("SCAN_SPEED_PROFILE"))
        if speed is None:
            speed = _as_float(meta.get("SCAN_SPEED_PDD")) or _as_float(meta.get("SCAN_SPEED_PROFILE"))
        if speed is not None:
            return f"Continu ({speed:g} mm/s)"
        return "Continu (vitesse inconnue)"

    if mode == "step":
        res = _step_from_positions_csv(meta.get("REF_SCAN_POSITIONS"))
        if res is None:
            return "Pas inconnu"
        dmin, dmax, is_fixed = res
        if is_fixed:
            return f"Fixe ({dmax:.2f} mm)"
        return f"Variable ({dmin:.2f}–{dmax:.2f} mm)"

    return None


def map_meta_to_params(meta: Dict[str, str], depths_mm: List[float], measure_kind: str) -> Dict[str, str]:
    """
    Mapper métadonnées + profondeurs détectées vers colonnes UI.

    Remplit : depth, ssd, energy, detector, gantry, integration, dose_rate, step,
    Orientation, jaw_xy, fov.

    :param meta: Métadonnées MCC (clés en MAJUSCULES).
    :type meta: Dict[str, str]
    :param depths_mm: Profondeurs trouvées (in+cross) en mm.
    :type depths_mm: List[float]
    :param measure_kind: Type de mesure ('pdd' ou 'profil').
    :type measure_kind: str
    :return: Dictionnaire clé/valeur pour affichage.
    :rtype: Dict[str, str]
    """
    out: Dict[str, str] = {}

    # Profondeurs → union unique (cm)
    if depths_mm:
        uniq_cm = sorted({round(mm / 10.0, 2) for mm in depths_mm if mm is not None})
        out["depth"] = ", ".join(f"{v:.1f}" for v in uniq_cm)

    ssd_cm = _ssd_cm_from_mm(meta)
    if ssd_cm is not None:
        out["ssd"] = f"{ssd_cm:g}"

    energy = _energy_from(meta)
    if energy:
        out["energy"] = energy

    det = _detector_from(meta)
    if det:
        out["detector"] = det

    gan = _gantry_from(meta)
    if gan is not None:
        out["gantry"] = f"{gan:g}"

    integ = _as_float(_pick(meta, "INTEGRATION", "DWELL", "DWELL_TIME", "MEAS_TIME", "SAMPLE_TIME"))
    if integ is not None:
        out["integration"] = f"{integ:g}"

    dr = _dose_rate_from(meta)
    if dr:
        out["dose_rate"] = str(dr)

    step_mode = _step_mode_string(meta, measure_kind)
    if step_mode:
        out["step"] = step_mode

    ori = _orientation_from(meta)
    if ori:
        out["Orientation"] = ori

    # JAW @100 → colonne fusionnée X*Y
    depth_mm_first = depths_mm[0] if depths_mm else None
    jawx, jawy, d_ref = _jaws_from(meta, depth_mm_first)
    jawx100 = _scale_jaw_to_100(jawx, d_ref)
    jawy100 = _scale_jaw_to_100(jawy, d_ref)
    if jawx100 is not None and jawy100 is not None:
        out["jaw_xy"] = f"{jawx100:.2f}*{jawy100:.2f}"

    # FOV : concat @z cm : X*Y pour toutes les profondeurs (in + cross)
    fov_txt = _fov_string_from(meta, depths_mm)
    if fov_txt:
        out["fov"] = fov_txt

    return out


# ======================== Préférences ========================================


def _default_prefs() -> Dict[str, dict]:
    """
    Créer la structure par défaut des préférences.

    :return: Dictionnaire de préférences initiales.
    :rtype: Dict[str, dict]
    """
    return {
        PREF_KEY_FILES: {},
        PREF_KEY_GLOBAL: {
            PREF_KEY_MEASURE_TYPE: DEFAULT_MEASURE_TYPE,
            PREF_KEY_NORMALIZE: DEFAULT_NORMALIZE,
            PREF_KEY_PROFILE_INPLANE: DEFAULT_PROFILE_INPLANE,
            PREF_KEY_PROFILE_CROSSPLANE: DEFAULT_PROFILE_CROSSPLANE,
            PREF_KEY_CUSTOM_TITLE: DEFAULT_CUSTOM_TITLE,
            PREF_KEY_COLOR_VAR: DEFAULT_COLOR_VAR,
            PREF_KEY_MARKER_VAR: DEFAULT_MARKER_VAR,
            PREF_KEY_COLOR_MAPS: {},
            PREF_KEY_MARKER_MAPS: {},
        },
    }


def load_prefs() -> Dict[str, dict]:
    """
    Charger les préférences depuis PREFS_PATH.

    Fallback robuste : en cas d'erreur de lecture/parse, retourne la valeur par défaut.

    :return: Dictionnaire des préférences.
    :rtype: Dict[str, dict]
    """
    if PREFS_PATH.exists():
        try:
            with PREFS_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return _default_prefs()
            data.setdefault(PREF_KEY_FILES, {})
            data.setdefault(PREF_KEY_GLOBAL, {})
            g = data[PREF_KEY_GLOBAL]
            g.setdefault(PREF_KEY_MEASURE_TYPE, DEFAULT_MEASURE_TYPE)
            g.setdefault(PREF_KEY_NORMALIZE, DEFAULT_NORMALIZE)
            g.setdefault(PREF_KEY_PROFILE_INPLANE, DEFAULT_PROFILE_INPLANE)
            g.setdefault(PREF_KEY_PROFILE_CROSSPLANE, DEFAULT_PROFILE_CROSSPLANE)
            g.setdefault(PREF_KEY_CUSTOM_TITLE, DEFAULT_CUSTOM_TITLE)
            g.setdefault(PREF_KEY_COLOR_VAR, DEFAULT_COLOR_VAR)
            g.setdefault(PREF_KEY_MARKER_VAR, DEFAULT_MARKER_VAR)
            g.setdefault(PREF_KEY_COLOR_MAPS, {})
            g.setdefault(PREF_KEY_MARKER_MAPS, {})
            return data
        except Exception:  # pragma: no cover - robustesse lecture prefs
            return _default_prefs()
    return _default_prefs()


def save_prefs(prefs: Dict[str, dict]) -> None:
    """
    Sauvegarder les préférences vers PREFS_PATH (JSON).

    :param prefs: Dictionnaire de préférences à sauvegarder.
    :type prefs: Dict[str, dict]
    :return: None
    :rtype: None
    """
    try:
        with PREFS_PATH.open("w", encoding="utf-8") as f:
            json.dump(prefs, f, ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover - robustesse I/O
        print(f"Impossible d'écrire {PREFS_PATH}: {exc}")


# ======================== GUI =================================================


class MCCPlotterGUI(tk.Tk):
    """
    Fenêtre principale de l'application de comparaison MCC.

    Gère :
      - l'état des préférences (globales & par fichier),
      - le chargement des fichiers MCC,
      - l'affichage tabulaire des paramètres,
      - le tracé PDD/profils,
      - l'export PNG.

    Les mappings couleur/marqueur sont mémorisés par paramètre (et pour FOV,
    par profondeur via l'espace de noms 'fov@depth').
    """

    def __init__(self) -> None:
        """
        Initialiser la fenêtre, l'UI et charger les préférences.

        :return: None
        :rtype: None
        """
        super().__init__()
        self.title(APP_TITLE)
        self.geometry(WINDOW_GEOMETRY)
        self.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self.prefs: Dict[str, dict] = load_prefs()
        self.rows: List[Dict[str, object]] = []  # 1 entrée = 1 fichier

        # --- Haut : options ---
        top = ttk.Frame(self)
        top.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)

        ttk.Label(top, text="Type de mesure :").pack(side=tk.LEFT)
        self.measure_type = tk.StringVar(value=str(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_MEASURE_TYPE)))
        ttk.Radiobutton(top, text="PDD", value=MEASURE_PDD, variable=self.measure_type).pack(
            side=tk.LEFT, padx=(6, 12)
        )
        ttk.Radiobutton(top, text="Profil", value=MEASURE_PROFILE, variable=self.measure_type).pack(
            side=tk.LEFT, padx=(0, 16)
        )

        self.normalize_var = tk.BooleanVar(value=bool(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_NORMALIZE)))
        ttk.Checkbutton(top, text="Normaliser à 1", variable=self.normalize_var).pack(side=tk.LEFT, padx=(0, 16))

        self.profile_inplane_var = tk.BooleanVar(
            value=bool(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_PROFILE_INPLANE))
        )
        self.profile_crossplane_var = tk.BooleanVar(
            value=bool(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_PROFILE_CROSSPLANE))
        )
        self.chk_inplane = ttk.Checkbutton(top, text="Inplane", variable=self.profile_inplane_var)
        self.chk_cross = ttk.Checkbutton(top, text="Crossplane", variable=self.profile_crossplane_var)
        self.chk_inplane.pack(side=tk.LEFT, padx=(0, 8))
        self.chk_cross.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(top, text="Titre :").pack(side=tk.LEFT)
        self.custom_title_var = tk.StringVar(value=str(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_CUSTOM_TITLE)))
        ttk.Entry(top, textvariable=self.custom_title_var, width=28).pack(side=tk.LEFT, padx=(6, 12))

        ttk.Label(top, text="Paramètre variable (couleur & légende) :").pack(side=tk.LEFT, padx=(0, 6))
        self.color_var_name = tk.StringVar(
            value=str(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_COLOR_VAR, DEFAULT_COLOR_VAR))
        )
        ttk.Combobox(
            top,
            textvariable=self.color_var_name,
            values=[k for k, _ in PARAMS],
            width=16,
            state="readonly",
        ).pack(side=tk.LEFT)

        ttk.Label(top, text="Secondaire → marqueur :").pack(side=tk.LEFT, padx=(12, 6))
        self.marker_var_name = tk.StringVar(
            value=str(self.prefs[PREF_KEY_GLOBAL].get(PREF_KEY_MARKER_VAR, DEFAULT_MARKER_VAR))
        )
        self.marker_combo = ttk.Combobox(
            top,
            textvariable=self.marker_var_name,
            values=[""] + [k for k, _ in PARAMS if k != self.color_var_name.get()],
            width=16,
            state="readonly",
        )
        self.marker_combo.pack(side=tk.LEFT)

        def _on_var_change(*_args) -> None:
            """
            Callback de modifications d'options haut de page : actualise préférences,
            met à jour l'UI et recharge les profondeurs profil si besoin.

            :return: None
            :rtype: None
            """
            g = self.prefs[PREF_KEY_GLOBAL]
            g[PREF_KEY_MEASURE_TYPE] = self.measure_type.get()
            g[PREF_KEY_NORMALIZE] = bool(self.normalize_var.get())
            g[PREF_KEY_PROFILE_INPLANE] = bool(self.profile_inplane_var.get())
            g[PREF_KEY_PROFILE_CROSSPLANE] = bool(self.profile_crossplane_var.get())
            g[PREF_KEY_CUSTOM_TITLE] = self.custom_title_var.get()
            g[PREF_KEY_COLOR_VAR] = self.color_var_name.get()
            sec = self.marker_var_name.get()
            g[PREF_KEY_MARKER_VAR] = sec if sec and sec != g[PREF_KEY_COLOR_VAR] else ""
            save_prefs(self.prefs)
            self._update_profile_controls()
            self.marker_combo.configure(values=[""] + [k for k, _ in PARAMS if k != self.color_var_name.get()])

            if self.measure_type.get() == MEASURE_PROFILE:
                self._ensure_profile_depths_loaded()

        self.measure_type.trace_add("write", _on_var_change)
        self.normalize_var.trace_add("write", _on_var_change)
        self.profile_inplane_var.trace_add("write", _on_var_change)
        self.profile_crossplane_var.trace_add("write", _on_var_change)
        self.custom_title_var.trace_add("write", _on_var_change)
        self.color_var_name.trace_add("write", _on_var_change)
        self.marker_var_name.trace_add("write", _on_var_change)

        self._update_profile_controls()

        # --- Table ---
        mid = ttk.Frame(self)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))
        columns = ("include", "x_shift", "y_scale", "y_offset") + tuple(k for k, _ in PARAMS) + ("file",)
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", selectmode="extended")

        self.tree.heading("include", text="Inclure")
        self.tree.heading("x_shift", text="ΔX")
        self.tree.heading("y_scale", text="Échelle Y")
        self.tree.heading("y_offset", text="Offset Y")
        for key, label in PARAMS:
            self.tree.heading(key, text=label)
        self.tree.heading("file", text="Fichier")

        self.tree.column("include", width=60, anchor=tk.CENTER)
        for col in ("x_shift", "y_scale", "y_offset"):
            self.tree.column(col, width=80, anchor=tk.E)
        for key, _lbl in PARAMS:
            self.tree.column(key, width=180 if key in ("jaw_xy", "fov") else 130)
        self.tree.column("file", width=360)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Édition ---
        edit = ttk.LabelFrame(self, text="Édition acquisition")
        edit.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 8))

        self.x_shift_var = tk.StringVar(value="0")
        self.y_scale_var = tk.StringVar(value="1")
        self.y_offset_var = tk.StringVar(value="0")
        self.include_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(edit, text="Inclure", variable=self.include_var).grid(row=0, column=0, padx=6, pady=6)
        ttk.Label(edit, text="ΔX :").grid(row=0, column=1, sticky=tk.E, padx=(8, 4))
        ttk.Entry(edit, textvariable=self.x_shift_var, width=10).grid(row=0, column=2, sticky=tk.W)
        ttk.Label(edit, text="Échelle Y :").grid(row=0, column=3, sticky=tk.E, padx=(8, 4))
        ttk.Entry(edit, textvariable=self.y_scale_var, width=10).grid(row=0, column=4, sticky=tk.W)
        ttk.Label(edit, text="Offset Y :").grid(row=0, column=5, sticky=tk.E, padx=(8, 4))
        ttk.Entry(edit, textvariable=self.y_offset_var, width=10).grid(row=0, column=6, sticky=tk.W)

        self.param_vars: Dict[str, tk.StringVar] = {}
        row = 1
        col = 1
        for key, label in PARAMS:
            self.param_vars[key] = tk.StringVar()
            ttk.Label(edit, text=label + ":").grid(row=row, column=col, sticky=tk.E, padx=(8, 4), pady=2)
            ttk.Entry(edit, textvariable=self.param_vars[key], width=24).grid(row=row, column=col + 1, sticky=tk.W, pady=2)
            col += 2
            if col > 5:
                col = 1
                row += 1

        ttk.Button(edit, text="Appliquer à l'élément", command=self.apply_edit).grid(row=0, column=7, padx=8, sticky=tk.E)
        for i in range(8):
            edit.grid_columnconfigure(i, weight=1)

        # --- Bas actions ---
        bottom = ttk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)
        ttk.Button(bottom, text="Ajouter des fichiers .mcc", command=self.add_files).pack(side=tk.LEFT)
        ttk.Button(bottom, text="Supprimer la sélection", command=self.remove_selected).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Vider la liste", command=self.clear_all).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Tout cocher", command=self.select_all).pack(side=tk.LEFT, padx=(12, 4))
        ttk.Button(bottom, text="Tout décocher", command=self.deselect_all).pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="Inverser", command=self.invert_all).pack(side=tk.LEFT, padx=(4, 12))
        ttk.Button(bottom, text="Tracer", command=self.plot).pack(side=tk.RIGHT)
        ttk.Button(bottom, text="Exporter PNG…", command=self.export_png).pack(side=tk.RIGHT, padx=6)

        # Événements
        self.tree.bind("<<TreeviewSelect>>", self.on_select_row)
        self.tree.bind("<Double-1>", self.toggle_selected)
        self.tree.bind("<space>", self.toggle_selected)
        self.ctx_menu = tk.Menu(self, tearoff=0)
        self.ctx_menu.add_command(label="Inclure", command=lambda: self._set_include_for_indices(self._selected_indices(), True))
        self.ctx_menu.add_command(label="Exclure", command=lambda: self._set_include_for_indices(self._selected_indices(), False))
        self.ctx_menu.add_separator()
        self.ctx_menu.add_command(label="Inverser", command=self.toggle_selected)
        self.tree.bind("<Button-3>", self._on_right_click)

    # --------- Utilitaires GUI ---------

    def _update_profile_controls(self) -> None:
        """
        Activer/désactiver les cases Inplane/Crossplane selon le type de mesure.

        :return: None
        :rtype: None
        """
        state = tk.NORMAL if self.measure_type.get() == MEASURE_PROFILE else tk.DISABLED
        self.chk_inplane.configure(state=state)
        self.chk_cross.configure(state=state)

    def _param_label(self, key: str) -> str:
        """
        Récupérer le libellé utilisateur d'un paramètre.

        :param key: Clé interne (ex. 'energy').
        :type key: str
        :return: Libellé (ex. 'Énergie [MV]').
        :rtype: str
        """
        for k, lbl in PARAMS:
            if k == key:
                return lbl
        return key

    def _normalize_key(self, text: str) -> str:
        """
        Normaliser une valeur de paramètre pour servir de clé de mapping.

        :param text: Valeur brute.
        :type text: str
        :return: Clé normalisée (trim + lower).
        :rtype: str
        """
        return str(text).strip().lower()

    def _next_from_pool(self, used_set: set, pool: Iterable[str]) -> str:
        """
        Choisir le prochain élément disponible d'un pool (avec wrap).

        :param used_set: Ensemble des valeurs déjà utilisées.
        :type used_set: set
        :param pool: Itérable de candidats.
        :type pool: Iterable[str]
        :return: Élément choisi.
        :rtype: str
        """
        for val in pool:
            if val not in used_set:
                used_set.add(val)
                return val
        pool_list = list(pool)
        return pool_list[(len(used_set)) % max(1, len(pool_list))]

    def _get_color_for(self, param_name: str, value: str) -> str:
        """
        Récupérer (ou allouer) une couleur pour la paire (paramètre, valeur).

        :param param_name: Nom du paramètre (espace de noms).
        :type param_name: str
        :param value: Valeur textuelle (clé normalisée).
        :type value: str
        :return: Code couleur hexadécimal.
        :rtype: str
        """
        g = self.prefs[PREF_KEY_GLOBAL]
        maps: Dict[str, Dict[str, str]] = g.get(PREF_KEY_COLOR_MAPS, {})
        key = param_name or "default"
        maps.setdefault(key, {})
        norm_val = self._normalize_key(value)
        param_map = maps[key]
        if norm_val not in param_map:
            used = set(param_map.values())
            param_map[norm_val] = self._next_from_pool(used, OKABE_ITO)
            g[PREF_KEY_COLOR_MAPS] = maps
            save_prefs(self.prefs)
        return param_map[norm_val]

    def _get_marker_for(self, param_name: str, value: str) -> str:
        """
        Récupérer (ou allouer) un marqueur pour la paire (paramètre, valeur).

        :param param_name: Nom du paramètre (peut être vide).
        :type param_name: str
        :param value: Valeur textuelle (clé normalisée).
        :type value: str
        :return: Symbole de marqueur Matplotlib.
        :rtype: str
        """
        if not param_name:
            return "o"
        g = self.prefs[PREF_KEY_GLOBAL]
        maps: Dict[str, Dict[str, str]] = g.get(PREF_KEY_MARKER_MAPS, {})
        maps.setdefault(param_name, {})
        norm_val = self._normalize_key(value)
        param_map = maps[param_name]
        if norm_val not in param_map:
            used = set(param_map.values())
            param_map[norm_val] = self._next_from_pool(used, MARKER_POOL)
            g[PREF_KEY_MARKER_MAPS] = maps
            save_prefs(self.prefs)
        return param_map[norm_val]

    # --------- Persistance per-file (clé = chemin absolu) ---------

    def _file_key(self, item: Dict[str, object]) -> str:
        """
        Obtenir une clé unique pour un fichier (chemin absolu résolu).

        :param item: Dictionnaire de ligne (contient 'path').
        :type item: Dict[str, object]
        :return: Clé de fichier.
        :rtype: str
        """
        return str(Path(str(item.get("path", ""))).resolve())

    def _load_file_block(self, file_key: str) -> Optional[dict]:
        """
        Charger le bloc de préférences spécifique à un fichier.

        :param file_key: Clé absolue de fichier.
        :type file_key: str
        :return: Dictionnaire des settings par fichier, ou None si absent.
        :rtype: Optional[dict]
        """
        return self.prefs.get(PREF_KEY_FILES, {}).get(file_key)

    def _save_file_block(self, file_key: str, content: Dict[str, object]) -> None:
        """
        Sauvegarder le bloc de préférences pour un fichier.

        :param file_key: Clé absolue de fichier.
        :type file_key: str
        :param content: Valeurs à persister (x_shift, y_scale, etc.).
        :type content: Dict[str, object]
        :return: None
        :rtype: None
        """
        block = {
            "x_shift": content["x_shift"],
            "y_scale": content["y_scale"],
            "y_offset": content["y_offset"],
            "include": bool(content["include"]),
            "linestyle": content.get("linestyle", DEFAULT_LINESTYLE),
        }
        for key, _ in PARAMS:
            block[key] = content.get(key, "")
        self.prefs.setdefault(PREF_KEY_FILES, {})[file_key] = block

    # --------- Table ---------

    def add_files(self) -> None:
        """
        Ouvrir un dialogue de sélection et ajouter des fichiers MCC à la liste.

        Lecture :
          1) Charge préférences JSON par fichier (si existantes),
          2) Parse MCC pour métadonnées / profils / PDD,
          3) Auto-remplit colonnes UI si champs vides,
          4) Insère dans le Treeview.

        :return: None
        :rtype: None
        """
        paths = filedialog.askopenfilenames(title=FILE_DIALOG_TITLE, filetypes=list(FILE_TYPES_MCC))
        if not paths:
            return

        for pth in paths:
            abspath = str(Path(pth).resolve())
            item: Dict[str, object] = {
                "path": abspath,
                "x_shift": 0.0,
                "y_scale": 1.0,
                "y_offset": 0.0,
                "include": True,
                "linestyle": DEFAULT_LINESTYLE,
                "iid": None,
                "_profiles": None,
                "_pdd": None,
                "_meta": {},
            }
            for key, _ in PARAMS:
                item[key] = ""

            # 1) Charger le JSON (prioritaire pour les champs textes)
            saved = self._load_file_block(abspath)
            if isinstance(saved, dict):
                item["x_shift"] = float(saved.get("x_shift", item["x_shift"]))
                item["y_scale"] = float(saved.get("y_scale", item["y_scale"]))
                item["y_offset"] = float(saved.get("y_offset", item["y_offset"]))
                item["include"] = bool(saved.get("include", item["include"]))
                item["linestyle"] = saved.get("linestyle", item["linestyle"])
                for key, _ in PARAMS:
                    if key in saved and str(saved[key]).strip():
                        item[key] = saved[key]

            # 2) Lire Meta + Profils + PDD (indépendant du JSON)
            try:
                lines = Path(abspath).read_text(encoding="utf-8", errors="ignore").splitlines()
                meta = _scan_keyvals(lines)
            except Exception:
                meta = {}

            profiles = parse_mcc_profiles_all(abspath)
            item["_profiles"] = profiles
            item["_meta"] = meta

            xs_pdd, ys_pdd = parse_mcc_pdd(abspath)
            if xs_pdd is not None and ys_pdd is not None:
                item["_pdd"] = (xs_pdd, ys_pdd)

            # 3) Profondeurs détectées (union In+Cross)
            depths_mm_all: List[float] = []
            for lst in profiles.values():
                for d in lst:
                    if d.get("depth_mm") is not None:
                        depths_mm_all.append(float(d["depth_mm"]))

            # 4) Auto-remplissage des champs vides (priorité JSON)
            auto = map_meta_to_params(meta, depths_mm_all, self.measure_type.get())
            for key, _ in PARAMS:
                if (not str(item.get(key, "")).strip()) and (key in auto):
                    item[key] = auto[key]

            # 5) Affichage
            include_txt = SYMBOL_INCLUDE if item["include"] else SYMBOL_EXCLUDE
            display_name = Path(abspath).name
            values = [include_txt, item["x_shift"], item["y_scale"], item["y_offset"]]
            values += [item[key] for key, _ in PARAMS] + [display_name]
            iid = self.tree.insert("", tk.END, values=tuple(values))
            item["iid"] = iid
            self.rows.append(item)

    def get_selected_index(self) -> Optional[int]:
        """
        Retourner l'index de la ligne sélectionnée dans le Treeview.

        :return: Index ou None si pas de sélection.
        :rtype: Optional[int]
        """
        sel = self.tree.selection()
        if not sel:
            return None
        iid = sel[0]
        for i, row in enumerate(self.rows):
            if row.get("iid") == iid:
                return i
        return None

    def _selected_indices(self) -> List[int]:
        """
        Renvoyer les indices de toutes les lignes sélectionnées.

        :return: Liste d'indices.
        :rtype: List[int]
        """
        ids = self.tree.selection()
        out: List[int] = []
        for iid in ids:
            for i, row in enumerate(self.rows):
                if row.get("iid") == iid:
                    out.append(i)
                    break
        return out

    def on_select_row(self, _event: Optional[tk.Event] = None) -> None:
        """
        Remplir le panneau d'édition avec les valeurs de la ligne sélectionnée.

        :param _event: Événement Tkinter (non utilisé).
        :type _event: Optional[tk.Event]
        :return: None
        :rtype: None
        """
        idx = self.get_selected_index()
        if idx is None or idx >= len(self.rows):
            return
        row = self.rows[idx]
        self.x_shift_var.set(str(row["x_shift"]))
        self.y_scale_var.set(str(row["y_scale"]))
        self.y_offset_var.set(str(row["y_offset"]))
        self.include_var.set(bool(row["include"]))
        for key, _ in PARAMS:
            self.param_vars[key].set(str(row.get(key, "")))

    def _refresh_row(self, idx: int) -> None:
        """
        Rafraîchir l'affichage d'une ligne après modification.

        :param idx: Index de la ligne.
        :type idx: int
        :return: None
        :rtype: None
        """
        row = self.rows[idx]
        include_txt = SYMBOL_INCLUDE if row["include"] else SYMBOL_EXCLUDE
        display_name = Path(str(row["path"])).name
        values = [include_txt, row["x_shift"], row["y_scale"], row["y_offset"]]
        values += [row[key] for key, _ in PARAMS] + [display_name]
        if row.get("iid"):
            self.tree.item(row["iid"], values=tuple(values))

    def apply_edit(self) -> None:
        """
        Appliquer le panneau d'édition à la ligne sélectionnée et persister.

        Valide les champs numériques (ΔX, Échelle Y, Offset Y). Si 'depth' est
        modifiée manuellement, recalcule la chaîne FOV agrégée pour l'UI.

        :raises ValueError: Si ΔX, Échelle Y ou Offset Y non numériques.
        :return: None
        :rtype: None
        """
        idx = self.get_selected_index()
        if idx is None:
            messagebox.showinfo("Édition", "Sélectionne d'abord un fichier.")
            return
        try:
            x_shift = float(self.x_shift_var.get())
            y_scale = float(self.y_scale_var.get())
            y_offset = float(self.y_offset_var.get())
        except ValueError:
            messagebox.showerror("Valeurs invalides", "ΔX, Échelle Y et Offset Y doivent être numériques.")
            return

        row = self.rows[idx]
        row["x_shift"] = x_shift
        row["y_scale"] = y_scale
        row["y_offset"] = y_offset
        row["include"] = bool(self.include_var.get())
        for key, _ in PARAMS:
            row[key] = self.param_vars[key].get().strip()

        # Si 'depth' a été modifié manuellement, recalcul FOV agrégé pour l’UI
        try:
            depth_csv = row.get("depth", "")
            manual_depths_mm: List[float] = []
            for part in str(depth_csv).replace(";", ",").split(","):
                val = _as_float(part)
                if val is not None:
                    manual_depths_mm.append(val * 10.0)  # cm -> mm
            if manual_depths_mm:
                fov_txt = _fov_string_from(row.get("_meta") or {}, manual_depths_mm)
                if fov_txt:
                    row["fov"] = fov_txt
        except Exception:
            pass

        self._refresh_row(idx)
        file_key = self._file_key(row)
        self._save_file_block(file_key, row)
        save_prefs(self.prefs)

    def remove_selected(self) -> None:
        """
        Supprimer toutes les lignes actuellement sélectionnées.

        :return: None
        :rtype: None
        """
        idxs = self._selected_indices()
        if not idxs:
            return
        for idx in sorted(idxs, reverse=True):
            row = self.rows[idx]
            if row.get("iid"):
                try:
                    self.tree.delete(row["iid"])
                except Exception:
                    pass
            del self.rows[idx]

    def clear_all(self) -> None:
        """
        Vider complètement la liste et le Treeview.

        :return: None
        :rtype: None
        """
        self.rows.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)

    def _set_include_for_indices(self, indices: Iterable[int], value: bool) -> None:
        """
        Cocher/décocher 'Inclure' pour un ensemble d'indices.

        :param indices: Indices de lignes.
        :type indices: Iterable[int]
        :param value: True pour inclure, False pour exclure.
        :type value: bool
        :return: None
        :rtype: None
        """
        for idx in indices:
            row = self.rows[idx]
            row["include"] = value
            self._refresh_row(idx)
            file_key = self._file_key(row)
            self._save_file_block(file_key, row)
        save_prefs(self.prefs)

    def toggle_selected(self, *_args) -> None:
        """
        Inverser l'état 'Inclure' des lignes sélectionnées.

        :param _args: Arguments d'événement (ignorés).
        :type _args: Any
        :return: None
        :rtype: None
        """
        idxs = self._selected_indices()
        if not idxs:
            return
        new_val = not bool(self.rows[idxs[0]]["include"])
        self._set_include_for_indices(idxs, new_val)

    def select_all(self, *_args) -> None:
        """
        Cocher 'Inclure' sur toutes les lignes.

        :param _args: Non utilisé.
        :type _args: Any
        :return: None
        :rtype: None
        """
        self._set_include_for_indices(range(len(self.rows)), True)

    def deselect_all(self, *_args) -> None:
        """
        Décocher 'Inclure' sur toutes les lignes.

        :param _args: Non utilisé.
        :type _args: Any
        :return: None
        :rtype: None
        """
        self._set_include_for_indices(range(len(self.rows)), False)

    def invert_all(self, *_args) -> None:
        """
        Inverser l'état 'Inclure' sur toutes les lignes.

        :param _args: Non utilisé.
        :type _args: Any
        :return: None
        :rtype: None
        """
        for idx in range(len(self.rows)):
            self.rows[idx]["include"] = not bool(self.rows[idx]["include"])
            self._refresh_row(idx)
            file_key = self._file_key(self.rows[idx])
            self._save_file_block(file_key, self.rows[idx])
        save_prefs(self.prefs)

    def _on_right_click(self, event: tk.Event) -> None:
        """
        Ouvrir le menu contextuel sur clic droit.

        :param event: Événement souris Tkinter.
        :type event: tk.Event
        :return: None
        :rtype: None
        """
        iid = self.tree.identify_row(event.y)
        if iid and iid not in self.tree.selection():
            self.tree.selection_set(iid)
        try:
            self.ctx_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.ctx_menu.grab_release()

    # --- Remplissage auto des profondeurs après bascule vers "Profil"

    def _ensure_profile_depths_loaded(self) -> None:
        """
        S'assurer que la colonne 'depth' est renseignée à partir des profils
        quand le mode 'Profil' est activé (si vide), et recalculer FOV agrégé.

        :return: None
        :rtype: None
        """
        changed = False
        for i, row in enumerate(self.rows):
            need_profiles = not bool(row.get("_profiles"))
            need_depth_cell = not str(row.get("depth", "")).strip()

            if need_profiles:
                try:
                    profiles = parse_mcc_profiles_all(str(row["path"]))
                except Exception:
                    profiles = {}
                row["_profiles"] = profiles

            profiles = row.get("_profiles") or {}
            if profiles and need_depth_cell:
                depths_mm_all: List[float] = []
                for lst in profiles.values():
                    for d in lst:
                        dm = d.get("depth_mm")
                        if dm is not None:
                            depths_mm_all.append(float(dm))
                if depths_mm_all:
                    uniq_cm = sorted({round(mm / 10.0, 2) for mm in depths_mm_all})
                    row["depth"] = ", ".join(f"{v:.1f}" for v in uniq_cm)

                    meta = row.get("_meta") or {}
                    fov_txt = _fov_string_from(meta, depths_mm_all)
                    if fov_txt:
                        row["fov"] = fov_txt

                    self._refresh_row(i)
                    self._save_file_block(self._file_key(row), row)
                    changed = True

        if changed:
            save_prefs(self.prefs)

    # --------- Légende / styles / tracé ---------

    def _compose_title(self) -> str:
        """
        Composer le titre de figure à partir des options UI.

        :return: Titre complet.
        :rtype: str
        """
        custom = self.custom_title_var.get().strip()
        if self.measure_type.get() == MEASURE_PROFILE:
            want_in = bool(self.profile_inplane_var.get())
            want_cross = bool(self.profile_crossplane_var.get())
            if want_in and want_cross:
                prefix = "Profil"
            elif want_in:
                prefix = "Profil inplane"
            elif want_cross:
                prefix = "Profil crossplane"
            else:
                prefix = "Profil"
        else:
            prefix = "PDD"
        color_param = self.color_var_name.get().strip()
        info = f" – Var: {self._param_label(color_param)}" if color_param else ""
        return f"{prefix}{info}" + (f" – {custom}" if custom else "")

    def _apply_plot_labels(self) -> None:
        """
        Appliquer les labels d'axes et le titre, serrer la mise en page.

        :return: None
        :rtype: None
        """
        if self.measure_type.get() == MEASURE_PROFILE:
            plt.xlabel("Position latérale (cm)")
        else:
            plt.xlabel("Profondeur (cm)")
        ylabel = "Dose normalisée" if self.normalize_var.get() else "Charge [nC]"
        plt.ylabel(ylabel)
        plt.title(self._compose_title())
        plt.tight_layout()

    def _transform_xy(self, xs: List[float], ys: List[float], row: Dict[str, object]) -> Tuple[List[float], List[float]]:
        """
        Appliquer ΔX, échelle Y, offset Y, et normalisation éventuelle.

        :param xs: Abscisses brutes.
        :type xs: List[float]
        :param ys: Ordonnées brutes.
        :type ys: List[float]
        :param row: Dictionnaire de la ligne (contient x_shift/y_scale/y_offset).
        :type row: Dict[str, object]
        :return: (xs_transformés, ys_transformés)
        :rtype: Tuple[List[float], List[float]]
        """
        x_shift = float(row["x_shift"])
        y_scale = float(row["y_scale"])
        y_offset = float(row["y_offset"])
        xs_t = [x + x_shift for x in xs]
        ys_t = [(y + y_offset) * y_scale for y in ys]
        if self.normalize_var.get():
            ys_t = normalize(ys_t)
        return xs_t, ys_t

    def _legend_for(self,
                    row: Dict[str, object],
                    base_label_value: str,
                    depth_cm: Optional[float],
                    suffix: str = "") -> str:
        """
        Construire un libellé de légende à partir de la valeur de base + profondeur.

        :param row: Ligne de données.
        :type row: Dict[str, object]
        :param base_label_value: Valeur de base (souvent le paramètre variable).
        :type base_label_value: str
        :param depth_cm: Profondeur (cm) si applicable.
        :type depth_cm: Optional[float]
        :param suffix: Suffixe ('Inplane' / 'Crossplane') si orientations distinctes.
        :type suffix: str
        :return: Libellé prêt pour la légende.
        :rtype: str
        """
        label = base_label_value if base_label_value else "(valeur manquante)"
        if self.color_var_name.get().strip() != "depth" and depth_cm is not None and self.color_var_name.get().strip() != "fov":
            label = f"{label} – {depth_cm:g} cm"
        if suffix:
            label = f"{label} – {suffix}"
        return label

    def _fov_value_at_depth(self, row: Dict[str, object], depth_cm: float) -> str:
        """
        Obtenir le FOV (X*Y) pour une ligne/fichier à la profondeur spécifiée.

        Essaye d'abord un calcul direct via métadonnées, sinon tente d'extraire
        depuis la chaîne agrégée 'fov' de la ligne.

        :param row: Ligne de données (contient '_meta', 'fov').
        :type row: Dict[str, object]
        :param depth_cm: Profondeur cm.
        :type depth_cm: float
        :return: 'X*Y' ou '(FOV inconnu)'.
        :rtype: str
        """
        meta = row.get("_meta") or {}
        text = _fov_at_depth_str(meta, depth_cm)
        if text:
            return text

        agg = str(row.get("fov", ""))
        try:
            match = re.search(rf"@{depth_cm:.1f}\s*cm\s*:\s*([0-9.,]+)\*([0-9.,]+)", agg)
            if match:
                x_val = match.group(1).replace(",", ".")
                y_val = match.group(2).replace(",", ".")
                return f"{float(x_val):.2f}*{float(y_val):.2f}"
        except Exception:
            pass

        return "(FOV inconnu)"

    def _all_depths_from_profiles(self, row: Dict[str, object]) -> List[float]:
        """
        Lister toutes les profondeurs (cm) présentes dans les profils du fichier.

        :param row: Ligne contenant '_profiles'.
        :type row: Dict[str, object]
        :return: Profondeurs uniques (cm) triées.
        :rtype: List[float]
        """
        profiles = row.get("_profiles") or {}
        depths: List[float] = []
        for lst in profiles.values():
            for d in lst:
                dm = d.get("depth_mm")
                if dm is not None:
                    depths.append(round(float(dm) / 10.0, 3))
        return sorted({round(v, 2) for v in depths})

    def _plot_profiles_for_row(self, row: Dict[str, object]) -> None:
        """
        Tracer les profils d'une ligne (inplane/crossplane), regroupés par profondeur.

        Implémente les correctifs :
          - On segmente toujours par profondeur trouvée dans le MCC.
          - Si paramètre variable = FOV, on colore/légende selon FOV @ profondeur
            (espace de noms 'fov@depth').

        :param row: Ligne/fichier à tracer (contient '_profiles' et métadonnées).
        :type row: Dict[str, object]
        :return: None
        :rtype: None
        """
        profiles = row.get("_profiles") or {}
        want_in = bool(self.profile_inplane_var.get())
        want_cross = bool(self.profile_crossplane_var.get())

        inplane_list = profiles.get("inplane", [])
        cross_list = profiles.get("crossplane", [])

        # Déterminer les profondeurs à tracer : filtre UI si rempli, sinon tout
        depth_csv = str(row.get("depth", "")).strip()
        if depth_csv:
            target_cm_list = _parse_depth_csv_cm(depth_csv)
        else:
            target_cm_list = self._all_depths_from_profiles(row)

        def match_depths(seq: List[Dict[str, object]], target_cm: float) -> List[Tuple[List[float], List[float]]]:
            """
            Filtrer les courbes dont la profondeur ≈ target_cm.

            :param seq: Liste d'objets courbe {'depth_mm','xs','ys'}.
            :type seq: List[Dict[str, object]]
            :param target_cm: Profondeur visée (cm).
            :type target_cm: float
            :return: Liste de paires (xs, ys).
            :rtype: List[Tuple[List[float], List[float]]]
            """
            out: List[Tuple[List[float], List[float]]] = []
            for e in seq:
                dmm = e.get("depth_mm")
                if dmm is None:
                    continue
                dcm = dmm / 10.0
                if abs(dcm - target_cm) <= 0.05:
                    out.append((e["xs"], e["ys"]))
            return out

        both_orients = bool(inplane_list) and bool(cross_list) and want_in and want_cross
        pvar = self.color_var_name.get().strip()
        psec = self.marker_var_name.get().strip()

        for depth_cm in target_cm_list:
            depth_cm_str = f"{depth_cm:g}"

            # --- Sélection des clés couleur/marker au niveau de la profondeur ---
            if pvar == "depth":
                color_key = depth_cm_str
                color_ns = "depth"
            elif pvar == "fov":
                color_key = self._fov_value_at_depth(row, depth_cm)
                color_ns = "fov@depth"  # espace de noms séparé
            else:
                color_key = str(row.get(pvar, "")) if pvar else ""
                color_ns = pvar or "default"

            if psec == "depth":
                marker_key = depth_cm_str
                marker_ns = "depth"
            elif psec == "fov":
                marker_key = self._fov_value_at_depth(row, depth_cm)
                marker_ns = "fov@depth"
            else:
                marker_key = str(row.get(psec, "")) if psec else ""
                marker_ns = psec

            color = self._get_color_for(color_ns, color_key)
            marker = self._get_marker_for(marker_ns, marker_key) if psec else "o"

            # ---- Légendes ----
            if pvar == "depth":
                base = depth_cm_str
            elif pvar == "fov":
                base = f"{color_key} @ {depth_cm:g} cm"
            else:
                base = str(row.get(pvar, "")) if pvar else "(valeur manquante)"

            label_in = self._legend_for(row, base, depth_cm, "Inplane" if both_orients else "")
            label_cross = self._legend_for(row, base, depth_cm, "Crossplane" if both_orients else "")

            # ---- Tracés ----
            if want_in and inplane_list:
                for xs_raw, ys_raw in match_depths(inplane_list, depth_cm):
                    xs, ys = self._transform_xy(xs_raw, ys_raw, row)
                    linestyle = FORCED_INPLANE_LINESTYLE if both_orients else str(row.get("linestyle", DEFAULT_LINESTYLE))
                    plt.plot(
                        xs, ys,
                        linestyle=linestyle,
                        marker=marker,
                        markersize=MARKERSIZE,
                        linewidth=LINEWIDTH,
                        color=color,
                        label=label_in,
                    )

            if want_cross and cross_list:
                for xs_raw, ys_raw in match_depths(cross_list, depth_cm):
                    xs, ys = self._transform_xy(xs_raw, ys_raw, row)
                    linestyle = FORCED_CROSSPLANE_LINESTYLE if both_orients else str(row.get("linestyle", DEFAULT_LINESTYLE))
                    plt.plot(
                        xs, ys,
                        linestyle=linestyle,
                        marker=marker,
                        markersize=MARKERSIZE,
                        linewidth=LINEWIDTH,
                        color=color,
                        label=label_cross,
                    )

    def _plot_common(self, included_rows: List[Dict[str, object]]) -> None:
        """
        Tracer PDD ou Profils pour un ensemble de lignes incluses.

        :param included_rows: Lignes marquées 'include=True'.
        :type included_rows: List[Dict[str, object]]
        :return: None
        :rtype: None
        """
        if self.measure_type.get() == MEASURE_PROFILE:
            for row in included_rows:
                if not row.get("_profiles"):
                    continue
                self._plot_profiles_for_row(row)
        else:
            for row in included_rows:
                xs_raw, ys_raw = (row.get("_pdd") or (None, None))
                if xs_raw is None:
                    continue
                xs, ys = self._transform_xy(xs_raw, ys_raw, row)
                pvar = self.color_var_name.get().strip()
                psec = self.marker_var_name.get().strip()

                if pvar == "depth":
                    label = str(row.get("depth", ""))
                elif pvar == "fov":
                    label = str(row.get("fov", ""))
                else:
                    label = str(row.get(pvar, "")) if pvar else "(valeur manquante)"

                color_ns = "fov@depth" if pvar == "fov" else (pvar or "default")
                color = self._get_color_for(color_ns, label)

                marker_ns = "fov@depth" if psec == "fov" else psec
                marker_val = str(row.get(psec, "")) if psec else ""
                marker = self._get_marker_for(marker_ns, marker_val) if psec else "o"

                plt.plot(
                    xs, ys,
                    linestyle=str(row.get("linestyle", DEFAULT_LINESTYLE)),
                    marker=marker,
                    markersize=MARKERSIZE,
                    linewidth=LINEWIDTH,
                    color=color,
                    label=label,
                )

        self._apply_plot_labels()
        legend = plt.legend(title=self._param_label(self.color_var_name.get()), frameon=True)
        if legend and legend.get_frame():
            legend.get_frame().set_edgecolor("#aaaaaa")
            legend.get_frame().set_linewidth(0.8)

    # --------- Actions ---------

    def plot(self) -> None:
        """
        Afficher la figure dans une fenêtre Matplotlib interactive.

        :return: None
        :rtype: None
        """
        included = [row for row in self.rows if row["include"]]
        if not included:
            messagebox.showwarning("Rien à tracer", 'Ajoute des fichiers et/ou coche "Inclure".')
            return
        plt.figure(figsize=PLOT_SIZE)
        self._plot_common(included)
        plt.show()

    def export_png(self) -> None:
        """
        Exporter la figure courante au format PNG (résolution EXPORT_DPI).

        :return: None
        :rtype: None
        """
        included = [row for row in self.rows if row["include"]]
        if not included:
            messagebox.showwarning("Export", 'Rien à exporter. Ajoute des fichiers et/ou coche "Inclure".')
            return
        save_path = filedialog.asksaveasfilename(
            title=EXPORT_DIALOG_TITLE,
            defaultextension=".png",
            filetypes=[("Image PNG", ".png")],
            initialfile=EXPORT_DEFAULT_NAME,
        )
        if not save_path:
            return
        fig = plt.figure(figsize=PLOT_SIZE)
        try:
            self._plot_common(included)
            fig.savefig(save_path, dpi=EXPORT_DPI)
            messagebox.showinfo("Export", f"Figure enregistrée :\n{save_path}")
        except Exception as exc:
            messagebox.showerror("Export", f"Échec de l'enregistrement : {exc}")
        finally:
            plt.close(fig)


# ======================== Entrée =============================================


def main() -> None:
    """
    Point d'entrée principal : instancie et lance l'interface.

    :return: None
    :rtype: None
    """
    app = MCCPlotterGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
