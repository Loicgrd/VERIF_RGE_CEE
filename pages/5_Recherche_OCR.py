"""
Recherche OCR dans les PDF scannés — V3
- OCR local (Tesseract), sans IA externe
- PDF cherchable téléchargeable (Ctrl+F)
- Recherche exacte / floue avec page, contexte et aperçu surligné
- Score de confiance OCR par page et par résultat
- Volet technique : fiches BAR détectées (code et/ou termes) + checklist des éléments attendus
- Volet administratif : synthèse présent / absent par catégorie
- Export Excel (motifs et référentiel fiches dans core/motifs_cee.py)

Dépendances :
    requirements.txt : pytesseract pymupdf rapidfuzz pillow pandas openpyxl
    packages.txt     : tesseract-ocr tesseract-ocr-fra
"""
import hashlib
import io
import os
import re
import unicodedata
from bisect import bisect_right
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait

# Tesseract lance par défaut plusieurs threads internes (OpenMP) qui se concurrencent :
# 1 thread par processus est ~3× plus rapide, et on parallélise plutôt les pages.
# (doit être défini avant le premier appel à tesseract ; hérité par les sous-processus)
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

from core.motifs_cee import (ADMINISTRATIF, ELEMENTS, FICHES, PREUVES, a_surligner, element_partout, motifs_administratifs,
                             motifs_elements, motifs_fiches, normaliser_code)

# Windows : décommenter et adapter le chemin si Tesseract n'est pas dans le PATH
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

DPI_OCR = 300
LANGUE = "fra"
SEUIL_TEXTE_NATIF = 50  # nb de caractères au-delà duquel une page est déjà textuelle (pas d'OCR)
SEUIL_PAGE_FIABLE = 70  # confiance moyenne (%) en dessous de laquelle une page est signalée
# Segmentation Tesseract : mode auto (3) par défaut ; il saute les colonnes de chiffres des
# tableaux à traits verticaux (DPGF, devis). Ces pages sont détectées et lues en mode 6
# (« bloc uniforme »), qui garde les lignes du tableau. Le mode 6 dégrade les pages de texte.
PSM_TEXTE, PSM_TABLEAU = 3, 6
SEUIL_TRAITS_TABLEAU = 3  # nb de traits verticaux longs pour considérer qu'une page est un tableau
NB_WORKERS = max(1, min(os.cpu_count() or 1, 8))  # pages OCRisées en parallèle (1 par cœur)


# ---------------------------------------------------------------- OCR

def _inserer_texte_invisible(page, texte, rect):
    """Ajoute le mot en texte invisible à son emplacement pour rendre le PDF cherchable."""
    largeur_1pt = fitz.get_text_length(texte, fontname="helv", fontsize=1)
    if largeur_1pt <= 0:
        return
    taille = max(1, min(rect.width / largeur_1pt, rect.height))
    point = fitz.Point(rect.x0, rect.y1) * page.derotation_matrix
    page.insert_text(point, texte, fontsize=taille, fontname="helv",
                     render_mode=3, rotate=page.rotation)


def _ocr_image(img, psm):
    """Exécuté dans un thread : pytesseract lance un processus tesseract (le GIL est libéré)."""
    return pytesseract.image_to_data(img, lang=LANGUE, config=f"--psm {psm}",
                                     output_type=pytesseract.Output.DICT)


def _est_tableau(img, frac=0.25):
    """True si la page contient ≥ SEUIL_TRAITS_TABLEAU traits verticaux couvrant > 25 % de la hauteur
    (tableau quadrillé). Calcul sur une image réduite : quelques millisecondes."""
    a = np.asarray(img.reduce(3)) < 128
    h = a.shape[0]
    n, prec = 0, False
    for c in np.where(a.mean(axis=0) > frac)[0]:
        bords = np.diff(np.concatenate(([0], a[:, c].astype(np.int8), [0])))
        debut, fin = np.where(bords == 1)[0], np.where(bords == -1)[0]
        ok = len(debut) and (fin - debut).max() > frac * h
        n += bool(ok and not prec)
        prec = ok
    return n >= SEUIL_TRAITS_TABLEAU


def ocr_pdf(pdf_bytes, barre=None):
    """Retourne (pdf_cherchable, mots, conf_pages).
    mots : dicts {page, x0, y0, x1, y1, texte, conf}, coordonnées en points (page affichée).

    Parallélisme : les pages scannées sont rendues une à une dans le thread principal
    (PyMuPDF n'est pas thread-safe) puis OCRisées en parallèle (NB_WORKERS processus tesseract).
    Au plus 2 × NB_WORKERS images sont en mémoire à la fois."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    nb_pages = len(doc)
    echelle = 72 / DPI_OCR
    mots_par_page, conf_par_page, resultats_ocr, source = {}, {}, {}, {}

    def avancer():
        if barre:
            fait = len(conf_par_page) + len(resultats_ocr)
            barre.progress(fait / nb_pages, text=f"OCR {fait}/{nb_pages} pages ({NB_WORKERS} en parallèle)…")

    with ThreadPoolExecutor(max_workers=NB_WORKERS) as pool:
        en_cours = {}
        for i, page in enumerate(doc):
            num = i + 1
            if len(page.get_text().strip()) >= SEUIL_TEXTE_NATIF:
                # Page déjà textuelle : pas d'OCR, confiance 100 %
                mots_par_page[num] = []
                for x0, y0, x1, y1, t, *_ in page.get_text("words", sort=True):
                    r = fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix
                    mots_par_page[num].append(dict(page=num, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1,
                                                   texte=t, conf=100.0))
                conf_par_page[num] = (num, 100.0, "Texte natif")
                avancer()
                continue

            # Niveaux de gris : même qualité OCR, image 3× plus légère
            pix = page.get_pixmap(dpi=DPI_OCR, colorspace=fitz.csGRAY)
            img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
            tableau = _est_tableau(img)
            source[num] = "OCR (tableau)" if tableau else "OCR"
            en_cours[pool.submit(_ocr_image, img, PSM_TABLEAU if tableau else PSM_TEXTE)] = num

            if len(en_cours) >= 2 * NB_WORKERS:  # limite la mémoire
                finis, _ = wait(en_cours, return_when=FIRST_COMPLETED)
                for f in finis:
                    resultats_ocr[en_cours.pop(f)] = f.result()
                avancer()

        for f in as_completed(en_cours):
            resultats_ocr[en_cours[f]] = f.result()
            avancer()

    # Couche texte invisible + mots (thread principal, ordre des pages)
    for num, data in resultats_ocr.items():
        page = doc[num - 1]
        mots_par_page[num], confs = [], []
        for t, c, l, tp, w, h in zip(data["text"], data["conf"], data["left"],
                                     data["top"], data["width"], data["height"]):
            c = float(c)
            if not t.strip() or c < 0:
                continue
            rect = fitz.Rect(l * echelle, tp * echelle, (l + w) * echelle, (tp + h) * echelle)
            mots_par_page[num].append(dict(page=num, x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                                           texte=t, conf=c))
            confs.append(c)
            _inserer_texte_invisible(page, t, rect)
        conf_par_page[num] = (num, sum(confs) / len(confs) if confs else 0.0, source[num])

    mots = [m for num in sorted(mots_par_page) for m in mots_par_page[num]]
    conf_pages = [conf_par_page[num] for num in sorted(conf_par_page)]
    return doc.tobytes(garbage=3, deflate=True), mots, conf_pages


# ---------------------------------------------------------------- Recherche

def _normaliser(txt):
    """Minuscules, sans accents, sans espaces ni séparateurs (BAR-TH-171 == bar th 171)."""
    txt = unicodedata.normalize("NFKD", txt.lower())
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"[\s\-_.,;:/'’]", "", txt)


def rechercher(mots, requete, mode, seuil):
    q = _normaliser(requete)
    if not q:
        return pd.DataFrame()
    seuil_effectif = 100 if mode == "Exacte" else seuil

    par_page = {}
    for m in mots:
        par_page.setdefault(m["page"], []).append(m)

    resultats = []
    for page, liste in par_page.items():
        norms = [_normaliser(m["texte"]) for m in liste]
        candidats = []
        # Fenêtres de mots consécutifs jusqu'à la longueur de la requête
        # (l'OCR coupe ou fusionne les mots : on raisonne en caractères, pas en nb de mots)
        long_max = len(q) * 1.3 + 2
        for i in range(len(liste)):
            cand = ""
            for n in range(1, len(liste) - i + 1):
                cand += norms[i + n - 1]
                if cand:
                    score = (100.0 if q in cand else 0.0) if mode == "Exacte" else fuzz.ratio(q, cand)
                    if score >= seuil_effectif:
                        candidats.append((score, -n, i, n))
                if len(cand) > long_max:
                    break

        # Meilleurs candidats sans chevauchement
        pris = set()
        for score, _, i, n in sorted(candidats, reverse=True):
            idx = set(range(i, i + n))
            if idx & pris:
                continue
            pris |= idx
            sel = liste[i:i + n]
            resultats.append({
                "Page": page,
                "Trouvé": " ".join(m["texte"] for m in sel),
                "Similarité (%)": round(score),
                "Confiance OCR (%)": round(sum(m["conf"] for m in sel) / len(sel)),
                "Contexte": " ".join(m["texte"] for m in liste[max(0, i - 8):i + n + 8]),
                "_boites": [(m["x0"], m["y0"], m["x1"], m["y1"]) for m in sel],
            })

    if not resultats:
        return pd.DataFrame()
    return (pd.DataFrame(resultats)
            .sort_values(["Page", "Similarité (%)"], ascending=[True, False])
            .reset_index(drop=True))


def apercu(pdf_bytes, num_page, boites, zoom=2):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pix = doc[num_page - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    calque = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(calque)
    for x0, y0, x1, y1 in boites:
        d.rectangle([x0 * zoom - 3, y0 * zoom - 3, x1 * zoom + 3, y1 * zoom + 3],
                    fill=(255, 230, 0, 90), outline=(230, 120, 0, 255), width=3)
    return Image.alpha_composite(img, calque)


# ---------------------------------------------------------------- Repérage automatique

SEUIL_TERMES = 2  # nb d'occurrences de termes pour détecter une fiche sans son code


def indexer_pages(mots):
    """page → (mots, position de début de chaque mot, texte de la page)."""
    par_page = {}
    for m in mots:
        par_page.setdefault(m["page"], []).append(m)
    index = {}
    for page, liste in par_page.items():
        # Mots séparés par « \n » quand on change de ligne (sinon espace) : les motifs
        # « même ligne » (marque / référence…) ne débordent pas sur la ligne suivante.
        debuts, pos, morceaux = [], 0, []
        for i, m in enumerate(liste):
            if i:
                prec = liste[i - 1]
                hauteur = max(prec["y1"] - prec["y0"], 1)
                nouvelle_ligne = m["y0"] > prec["y1"] - 0.3 * hauteur or m["x0"] < prec["x0"]
                morceaux.append("\n" if nouvelle_ligne else " ")
                pos += 1
            debuts.append(pos)
            morceaux.append(m["texte"])
            pos += len(m["texte"])
        index[page] = (liste, debuts, "".join(morceaux))
    return index


def appliquer(index, motifs):
    """motifs : [(groupe, nom, regex[, filtre de ligne])] → une ligne par occurrence,
    ramenée aux mots OCR couverts. Le filtre éventuel doit figurer sur la même ligne."""
    resultats = []
    for page, (liste, debuts, texte) in index.items():
        for groupe, nom, rx, *filtre in motifs:
            filtre = filtre[0] if filtre else None
            for match in rx.finditer(texte):
                if filtre is not None:
                    debut_l = texte.rfind("\n", 0, match.start()) + 1
                    fin_l = texte.find("\n", match.end())
                    if not filtre.search(texte[debut_l:fin_l if fin_l >= 0 else None]):
                        continue
                i0 = bisect_right(debuts, match.start()) - 1
                i1 = bisect_right(debuts, match.end() - 1)
                sel = liste[i0:i1]
                if not sel:
                    continue
                resultats.append({
                    "Groupe": groupe, "Élément": nom, "Valeur": " ".join(match.group(0).split()), "Page": page,
                    "Confiance OCR (%)": round(sum(m["conf"] for m in sel) / len(sel)),
                    "Contexte": " ".join(m["texte"] for m in liste[max(0, i0 - 8):i1 + 8]),
                    "_boites": [(m["x0"], m["y0"], m["x1"], m["y1"]) for m in sel],
                })
    colonnes = ["Groupe", "Élément", "Valeur", "Page", "Confiance OCR (%)", "Contexte", "_boites"]
    return pd.DataFrame(resultats, columns=colonnes)


def _pages(df):
    return ", ".join(map(str, sorted(df["Page"].unique())))


def _valeurs(df, n=5):
    return " | ".join(df["Valeur"].drop_duplicates().head(n))


def _statut_absent(pages_faibles):
    return (f"⚠️ Non trouvé (OCR faible p. {', '.join(map(str, pages_faibles))})"
            if pages_faibles else "❌ Absent")


# --- Volet administratif

def synthese_admin(res, pages_faibles):
    lignes = []
    cat_pieces = "Pièces engagement / réalisation"
    for preuve, pieces in PREUVES.items():
        occ = res[(res["Groupe"] == cat_pieces) & res["Élément"].isin(pieces)]
        lignes.append({"Catégorie": cat_pieces, "Élément": f"➜ {preuve}",
                       "Statut": "✅ Présent" if len(occ) else _statut_absent(pages_faibles),
                       "Occurrences": len(occ), "Pages": _pages(occ),
                       "Valeurs": ", ".join(occ["Élément"].drop_duplicates()), "Note": "Au moins une pièce"})
    for cat, liste in ADMINISTRATIF.items():
        for motif in liste:
            occ = res[(res["Groupe"] == cat) & (res["Élément"] == motif["nom"])]
            statut = ("✅ Présent" if len(occ)
                      else _statut_absent(pages_faibles) if motif.get("presence") else "—")
            lignes.append({"Catégorie": cat, "Élément": motif["nom"], "Statut": statut,
                           "Occurrences": len(occ), "Pages": _pages(occ), "Valeurs": _valeurs(occ),
                           "Note": motif.get("note", "")})
    return pd.DataFrame(lignes)


# --- Volet technique

def detecter_fiches(occ_fiches):
    """Fiches présentes d'après le code explicite et/ou les termes techniques associés."""
    occ = occ_fiches.copy()
    est_code = occ["Élément"] == "Code"
    occ.loc[est_code, "Groupe"] = occ.loc[est_code, "Valeur"].map(normaliser_code)

    lignes = []
    for code in sorted(set(occ["Groupe"])):
        codes = occ[(occ["Groupe"] == code) & (occ["Élément"] == "Code")]
        termes = occ[(occ["Groupe"] == code) & (occ["Élément"] == "Terme")]
        if len(codes) and len(termes):
            detection = "✅ Code + termes"
        elif len(codes):
            detection = "🔵 Code seul"
        elif len(termes) >= SEUIL_TERMES:
            detection = "🟡 Termes seuls (à confirmer)"
        else:
            detection = "⚪ Indice faible"
        pages = sorted(set(codes["Page"]) | set(termes["Page"]))
        lignes.append({
            "Fiche": code,
            "Libellé": FICHES.get(code, {}).get("libelle", "Pas de référentiel"),
            "Détection": detection,
            "Code (pages)": _pages(codes),
            "Termes trouvés": f"{len(termes)} : " + ", ".join(
                termes["Valeur"].str.lower().drop_duplicates().head(6)) if len(termes) else "",
            "Pages fiche": ", ".join(map(str, pages)),
            "_pages": pages,
        })
    colonnes = ["Fiche", "Libellé", "Détection", "Code (pages)", "Termes trouvés", "Pages fiche", "_pages"]
    return pd.DataFrame(lignes, columns=colonnes), occ


def checklist_fiche(code, res_tech, pages_fiche, restreindre, pages_faibles):
    """Checklist des éléments attendus pour la fiche + occurrences retenues."""
    attendus = list(FICHES[code]["elements"])
    if FICHES[code]["rge"]:
        attendus.append(f"Domaine RGE {code}")

    lignes, occurrences = [], []
    for el in attendus:
        nom = "Domaine RGE (libellé exact)" if el.startswith("Domaine RGE") else el
        if el not in ELEMENTS and not el.startswith("Domaine RGE"):
            lignes.append({"Élément": nom, "Statut": "👁️ À vérifier", "Occurrences": 0,
                           "Pages": "", "Valeurs": "", "Note": "Non repérable par motif"})
            continue
        occ = res_tech[res_tech["Élément"] == el]
        hors_pages = element_partout(el) or not restreindre
        if not hors_pages:
            occ = occ[occ["Page"].isin(pages_fiche)]
        note = ELEMENTS.get(el, {}).get("note", "")
        if element_partout(el):
            note = ("Cherché dans tout le document. " + note).strip()
        absent = ELEMENTS.get(el, {}).get("absent") or _statut_absent(pages_faibles)
        lignes.append({"Élément": nom, "Statut": "✅ Trouvé" if len(occ) else absent,
                       "Occurrences": len(occ), "Pages": _pages(occ), "Valeurs": _valeurs(occ),
                       "Note": note})
        occurrences.append(occ.assign(Groupe=code, Élément=nom))
    occ_df = pd.concat(occurrences) if occurrences else res_tech.iloc[0:0]
    return pd.DataFrame(lignes), occ_df


# --- Export et affichage

def export_excel(feuilles):
    """feuilles : {nom d'onglet: DataFrame}"""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for nom, df in feuilles.items():
            df.drop(columns=["_boites", "_pages"], errors="ignore").to_excel(xw, sheet_name=nom[:31], index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                largeur = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, largeur + 2), 60)
            ws.freeze_panes = "A2"
    buf.seek(0)
    return buf.getvalue()


COULEURS = {  # RGB 0-1 (surlignage PDF) + hex (légende)
    "SIRET": ((0.45, 0.70, 1.00), "#73B3FF"),
    "Technique": ((0.45, 0.90, 0.40), "#73E666"),
    "Marque / référence": ((1.00, 0.70, 0.30), "#FFB34D"),
}


def pdf_surligne(pdf_ocr, volets):
    """Ajoute une annotation de surlignage par occurrence.
    volets : {nom du volet: DataFrame d'occurrences (Groupe, Élément, Valeur, Page, _boites)}.
    Le libellé de l'élément apparaît en info-bulle au survol dans le lecteur PDF."""
    doc = fitz.open(stream=pdf_ocr, filetype="pdf")
    for volet, occ in volets.items():
        couleur = COULEURS[volet][0]
        # Une même zone repérée par plusieurs motifs → un seul surlignage, libellés fusionnés
        zones = {}
        for o in occ.to_dict("records"):
            if not a_surligner(o["Groupe"], o["Élément"]):
                continue
            cle = (o["Page"], tuple(o["_boites"]))
            zones.setdefault(cle, []).append(f"{o['Groupe']} › {o['Élément']}")
        for (num, boites), libelles in zones.items():
            page = doc[num - 1]
            rects = [fitz.Rect(b) * page.derotation_matrix for b in boites]
            annot = page.add_highlight_annot(rects)
            annot.set_colors(stroke=couleur)
            annot.set_info(title=volet, content="\n".join(dict.fromkeys(libelles)))
            annot.update(opacity=0.5)
    return doc.tobytes(garbage=3, deflate=True)


def legende(volets):
    return " ".join(
        f"<span style='background:{COULEURS[v][1]};padding:2px 8px;border-radius:4px;"
        f"color:#000'>{v}</span>" for v in volets)


def tableau_avec_apercu(df, pdf_ocr, colonnes, cle, libelle):
    """Tableau cliquable + aperçu de la page avec la zone surlignée."""
    sel = st.dataframe(df, hide_index=True, width="stretch", column_order=colonnes,
                       on_select="rerun", selection_mode="single-row", key=cle)
    lignes = sel.selection.rows
    ligne = df.iloc[lignes[0]] if lignes and lignes[0] < len(df) else df.iloc[0]
    st.image(apercu(pdf_ocr, int(ligne["Page"]), ligne["_boites"]),
             caption=f"Page {ligne['Page']} — « {ligne[libelle]} »", width="stretch")


def voir_occurrences(occ, pdf_ocr, cle):
    """Choix d'un élément trouvé → ses occurrences avec aperçu."""
    if occ.empty:
        return
    choix = (occ["Groupe"] + " › " + occ["Élément"]).drop_duplicates().tolist()
    sel = st.selectbox("Voir les occurrences de…", choix, index=None,
                       placeholder="Choisir un élément trouvé", key=f"voir_{cle}")
    if sel:
        groupe, element = sel.split(" › ", 1)
        vue = occ[(occ["Groupe"] == groupe) & (occ["Élément"] == element)] \
            .sort_values("Page").reset_index(drop=True)
        tableau_avec_apercu(vue, pdf_ocr, ["Page", "Valeur", "Confiance OCR (%)", "Contexte"],
                            f"occ_{cle}_{sel}", "Valeur")


def _titre(nom, synth, statut_ok):
    n_ok = synth["Statut"].str.startswith(statut_ok).sum()
    n_ko = synth["Statut"].str.startswith(("❌", "⚠️")).sum()
    n_vu = synth["Statut"].str.startswith("👁️").sum()
    suffixe = (f" · ❌ {n_ko} manquant(s)" if n_ko else "") + (f" · 👁️ {n_vu} à vérifier" if n_vu else "")
    return f"**{nom}** — {n_ok}/{len(synth)} trouvés{suffixe}"


# ---------------------------------------------------------------- Interface

def afficher_recherche_ocr():
    st.header("🔎 Recherche dans un PDF scanné")
    fichier = st.file_uploader("PDF à analyser", type="pdf", key="ocr_upload")
    if not fichier:
        return

    pdf_bytes = fichier.getvalue()
    cle = hashlib.md5(pdf_bytes).hexdigest()
    cache = st.session_state.setdefault("ocr_cache", {})
    if cle not in cache:
        barre = st.progress(0.0, text="OCR en cours…")
        try:
            cache[cle] = ocr_pdf(pdf_bytes, barre)
        except pytesseract.TesseractNotFoundError:
            barre.empty()
            st.error("Tesseract introuvable : vérifier l'installation ou `tesseract_cmd`.")
            return
        barre.empty()
    pdf_ocr, mots, conf_pages = cache[cle]

    # --- Fiabilité OCR
    c1, c2, c3 = st.columns(3)
    c1.metric("Pages", len(conf_pages))
    c2.metric("Pages OCRisées", sum(1 for *_, s in conf_pages if s.startswith("OCR")))
    moy = sum(c for _, c, _ in conf_pages) / len(conf_pages) if conf_pages else 0
    c3.metric("Confiance OCR moyenne", f"{moy:.0f} %")

    faibles = [(p, c) for p, c, _ in conf_pages if c < SEUIL_PAGE_FIABLE]
    if faibles:
        st.warning("Pages peu lisibles — un « non trouvé » n'y est pas fiable : "
                   + ", ".join(f"p.{p} ({c:.0f} %)" for p, c in faibles))
    with st.expander("Confiance par page"):
        st.dataframe(pd.DataFrame(conf_pages, columns=["Page", "Confiance (%)", "Source"])
                     .round(0), hide_index=True)

    index = indexer_pages(mots)
    pages_faibles = [p for p, _ in faibles]
    res_admin = appliquer(index, motifs_administratifs())
    res_tech = appliquer(index, motifs_elements())
    detection, occ_fiches = detecter_fiches(appliquer(index, motifs_fiches()))
    synth_admin = synthese_admin(res_admin, pages_faibles)

    # --- PDF surligné (sortie principale)
    st.divider()
    st.subheader("🖍️ PDF surligné")
    volets = st.pills("Éléments à surligner", list(COULEURS), selection_mode="multi",
                      default=list(COULEURS), key="ocr_volets") or []
    if volets:
        st.markdown(legende(volets) + "&nbsp; — survoler un surlignage dans le lecteur PDF "
                    "pour voir l'élément repéré.", unsafe_allow_html=True)
    est_marque = res_tech["Élément"] == "Marque / référence"
    sources = {
        "SIRET": res_admin[res_admin["Élément"] == "SIRET"],
        "Technique": pd.concat([res_tech[~est_marque], occ_fiches[occ_fiches["Élément"] == "Terme"]
                                .assign(Élément="Terme technique")]),
        "Marque / référence": res_tech[est_marque],
    }
    cle_surl = (cle, tuple(volets))
    if st.session_state.get("ocr_surligne_cle") != cle_surl:
        with st.spinner("Surlignage…"):
            st.session_state["ocr_surligne"] = pdf_surligne(pdf_ocr, {v: sources[v] for v in volets})
        st.session_state["ocr_surligne_cle"] = cle_surl

    base = fichier.name.rsplit(".", 1)[0]
    c1, c2 = st.columns(2)
    c1.download_button("📥 PDF surligné + cherchable", st.session_state["ocr_surligne"],
                       file_name=base + "_surligne.pdf", mime="application/pdf", type="primary",
                       disabled=not volets, width="stretch")
    c2.download_button("📄 PDF cherchable seul (Ctrl+F)", pdf_ocr,
                       file_name=base + "_ocr.pdf", mime="application/pdf", width="stretch")

    fiches_vues = detection[~detection["Détection"].str.startswith("⚪")]
    if len(fiches_vues):
        st.caption("Fiches détectées : " + " · ".join(
            f"**{f}** ({d[2:]})" for f, d in zip(fiches_vues["Fiche"], fiches_vues["Détection"])))

    volet = st.expander("📊 Données détaillées — checklist par fiche, administratif, recherche, export Excel")
    onglet_tech, onglet_admin, onglet_libre = volet.tabs(
        ["🔧 Checklist par fiche", "📋 Administratif", "🔎 Recherche libre"])

    # --- Technique par fiche
    with onglet_tech:
        st.subheader("Fiches détectées")
        if detection.empty:
            st.info("Aucun code fiche ni terme technique repéré.")
        else:
            st.dataframe(detection, hide_index=True, width="stretch",
                         column_order=["Fiche", "Libellé", "Détection", "Code (pages)",
                                       "Termes trouvés", "Pages fiche"])

        detectees = detection[~detection["Détection"].str.startswith("⚪")]["Fiche"].tolist()
        options = list(dict.fromkeys(list(FICHES) + detection["Fiche"].tolist()))
        c1, c2 = st.columns([3, 1])
        fiches = c1.multiselect("Fiches à contrôler", options, default=detectees, key=f"fiches_{cle}")
        restreindre = c2.toggle("Limiter aux pages de la fiche", value=True,
                                help="Ne retient que les valeurs trouvées sur les pages où le code "
                                     "ou les termes de la fiche apparaissent. Le domaine RGE, l'ACERMI "
                                     "et le tableau de répartition sont toujours cherchés partout.")

        checklists, occ_tech = [], []
        for code in fiches:
            if code not in FICHES:
                st.info(f"**{code}** — pas de référentiel dans `core/motifs_cee.py` (ajouter la fiche dans FICHES).")
                continue
            ligne = detection[detection["Fiche"] == code]
            pages_fiche = ligne["_pages"].iloc[0] if len(ligne) else []
            synth, occ = checklist_fiche(code, res_tech, pages_fiche, restreindre, pages_faibles)
            checklists.append(synth.assign(Fiche=code))
            occ_tech.append(occ)
            with st.container(border=True):
                st.markdown(_titre(f"{code} · {FICHES[code]['libelle']}", synth, "✅"))
                if not pages_fiche:
                    st.caption("Fiche non détectée dans le document : recherche sur toutes les pages.")
                elif restreindre:
                    st.caption(f"Pages de la fiche : {', '.join(map(str, pages_fiche))}")
                st.dataframe(synth, hide_index=True, width="stretch")

        occ_tech = pd.concat(occ_tech) if occ_tech else res_tech.iloc[0:0]
        voir_occurrences(occ_tech, pdf_ocr, f"tech_{cle}")

    # --- Administratif
    with onglet_admin:
        cats = st.pills("Catégorie", list(ADMINISTRATIF), selection_mode="multi",
                        default=list(ADMINISTRATIF), key=f"cats_{cle}") or []
        for cat in cats:
            synth = synth_admin[synth_admin["Catégorie"] == cat].drop(columns="Catégorie")
            with st.container(border=True):
                st.markdown(_titre(cat, synth, "✅"))
                st.dataframe(synth, hide_index=True, width="stretch")
        voir_occurrences(res_admin, pdf_ocr, f"admin_{cle}")

    volet.download_button(
        "📊 Exporter en Excel (fiches, technique, administratif, détail)",
        export_excel({
            "Fiches détectées": detection,
            "Technique": (pd.concat(checklists)[["Fiche"] + [c for c in checklists[0] if c != "Fiche"]]
                          if checklists else pd.DataFrame()),
            "Administratif": synth_admin,
            "Détail": pd.concat([occ_tech, res_admin]).sort_values("Page"),
        }),
        file_name=fichier.name.rsplit(".", 1)[0] + "_reperage.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # --- Recherche libre
    with onglet_libre:
        c1, c2, c3 = st.columns([3, 1, 1])
        requete = c1.text_input("Rechercher", placeholder="ex. BAR-TH-171, n° SIRET, nom…")
        mode = c2.radio("Mode", ["Floue", "Exacte"], horizontal=True)
        seuil = c3.slider("Seuil flou (%)", 60, 100, 85, disabled=(mode == "Exacte"))
        if requete:
            res = rechercher(mots, requete, mode, seuil)
            if res.empty:
                st.info("Aucun résultat.")
            else:
                st.caption(f"{len(res)} résultat(s) — cliquer sur une ligne pour voir la page")
                tableau_avec_apercu(
                    res, pdf_ocr,
                    ["Page", "Trouvé", "Similarité (%)", "Confiance OCR (%)", "Contexte"],
                    f"res_{cle}", "Trouvé")


if __name__ == "__main__":
    afficher_recherche_ocr()
