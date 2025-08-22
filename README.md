# mcc-plotter — Comparateur MCC (PDD & Profils)

**Application Tkinter + Matplotlib** pour comparer des acquisitions dosimétriques au format **MCC** : **PDD** (Percent Depth Dose) et **profils** (inplane / crossplane). Le programme lit les métadonnées, déduit automatiquement plusieurs paramètres (énergie, SSD/DSP, taille de champ, FOV au point, orientation détecteur, pas/mode de scan…), les affiche dans un tableau interactif et trace les courbes avec styles et légendes configurables. Les préférences sont persistées globalement et par fichier (`~/.mcc_plotter_prefs.json`). Export **PNG** disponible.

> Auteur : **Sarah MARTIN-ALONSO** • Licence : MIT

---

## ✨ Fonctionnalités clés

- 1 ligne par fichier MCC, colonnes auto-remplies via les métadonnées et/ou vos overrides manuels.
- Détection du **détecteur** (référence PTW depuis `DETECTOR_TYPE`), de l’**énergie** (suffixe *FFF* si applicable), de la **SSD (DSP)** en cm, de l’**orientation** détecteur (Radial/Axial), de l’**angle de bras** (gantry) et du **débit de dose**.
- Calcul de la **mâchoire X×Y @ 100 cm** et du **FOV** au(x) point(s) de mesure.
- Choix du **paramètre variable** (couleur & légende) + **marqueur secondaire**.
- **Normalisation** optionnelle des courbes à 1.
- **Export PNG** de la figure.
- Correctifs importants côté profils : segmentation **par profondeur trouvée dans le MCC** et, si le paramètre variable est le **FOV**, mappage couleur/légende à partir du **FOV à la profondeur concernée** (`fov@depth`).

## 🔧 Installation

Prérequis : **Python 3.8+** (Tkinter est inclus dans la bibliothèque standard de Python).

```bash
pip install -r requirements.txt
```

## ▶️ Utilisation

Lancer l’application graphique :

```bash
python3 plt_MCC.py
```

- Ajoutez un ou plusieurs fichiers **.mcc**.
- Sélectionnez **PDD** ou **Profil** (et Inplane/Crossplane pour les profils).
- Choisissez le **paramètre variable** (couleurs & légende) et, si besoin, un **paramètre secondaire** (marqueurs).
- Ajustez ΔX / échelle Y / offset Y par fichier, modifiez les colonnes si nécessaire.
- Cliquez sur **Tracer**, puis éventuellement **Exporter PNG…**.

**Préférences** : elles sont sauvegardées automatiquement dans `~/.mcc_plotter_prefs.json` (global + par fichier).

## 📁 Structure du dépôt

```text
mcc-plotter/
├─ plt_MCC.py          # Application principale (Tkinter + Matplotlib)
├─ requirements.txt    # Dépendances Python
├─ LICENSE             # Licence (MIT par défaut)
├─ .gitignore          # Fichiers à ignorer
└─ README.md           # Vous êtes ici
```

## 💡 Astuces

- **PDD** : l’axe X correspond à la profondeur (cm) ; **Profil** : position latérale (cm).
- Activez la **normalisation** pour comparer facilement des courbes hétérogènes.
- Le **titre** et les **légendes** s’adaptent au paramètre variable.

## 🛣️ Feuille de route (idées)

- Export CSV/JSON des tableaux de paramètres.
- Palette couleur éditable et thèmes.
- Empilement multi-figures et mise en page automatique pour publication.

## ⚖️ Licence

Sous licence **MIT**.
---

_Dernière mise à jour : 2025-08-22_
