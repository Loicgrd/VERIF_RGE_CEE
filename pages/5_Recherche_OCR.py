"""
Recherche OCR dans les PDF scannés — V1
- OCR local (Tesseract), sans IA externe
- PDF cherchable téléchargeable (Ctrl+F)
- Recherche exacte / floue avec page, contexte et aperçu surligné
- Score de confiance OCR par page et par résultat

Dépendances :
    pip install pytesseract pymupdf rapidfuzz pillow pandas
    + Tesseract installé sur la machine avec le pack de langue 'fra'
"""
import hashlib
import re
import unicodedata

import fitz  # PyMuPDF
import pandas as pd
import pytesseract
import streamlit as st
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

# Windows : décommenter et adapter le chemin si Tesseract n'est pas dans le PATH
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

DPI_OCR = 300
LANGUE = "fra"
SEUIL_TEXTE_NATIF = 50  # nb de caractères au-delà duquel une page est déjà textuelle (pas d'OCR)
SEUIL_PAGE_FIABLE = 70  # confiance moyenne (%) en dessous de laquelle une page est signalée


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


def ocr_pdf(pdf_bytes, barre=None):
    """Retourne (pdf_cherchable, mots, conf_pages).
    mots : dicts {page, x0, y0, x1, y1, texte, conf}, coordonnées en points (page affichée)."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    mots, conf_pages = [], []
    echelle = 72 / DPI_OCR

    for i, page in enumerate(doc):
        num = i + 1
        if len(page.get_text().strip()) >= SEUIL_TEXTE_NATIF:
            # Page déjà textuelle : pas d'OCR, confiance 100 %
            for x0, y0, x1, y1, t, *_ in page.get_text("words", sort=True):
                r = fitz.Rect(x0, y0, x1, y1) * page.rotation_matrix
                mots.append(dict(page=num, x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1, texte=t, conf=100.0))
            conf_pages.append((num, 100.0, "Texte natif"))
        else:
            pix = page.get_pixmap(dpi=DPI_OCR)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            data = pytesseract.image_to_data(img, lang=LANGUE, output_type=pytesseract.Output.DICT)
            confs = []
            for t, c, l, tp, w, h in zip(data["text"], data["conf"], data["left"],
                                         data["top"], data["width"], data["height"]):
                c = float(c)
                if not t.strip() or c < 0:
                    continue
                rect = fitz.Rect(l * echelle, tp * echelle, (l + w) * echelle, (tp + h) * echelle)
                mots.append(dict(page=num, x0=rect.x0, y0=rect.y0, x1=rect.x1, y1=rect.y1,
                                 texte=t, conf=c))
                confs.append(c)
                _inserer_texte_invisible(page, t, rect)
            conf_pages.append((num, sum(confs) / len(confs) if confs else 0.0, "OCR"))

        if barre:
            barre.progress(num / len(doc), text=f"OCR page {num}/{len(doc)}…")

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
    c2.metric("Pages OCRisées", sum(1 for *_, s in conf_pages if s == "OCR"))
    moy = sum(c for _, c, _ in conf_pages) / len(conf_pages) if conf_pages else 0
    c3.metric("Confiance OCR moyenne", f"{moy:.0f} %")

    faibles = [(p, c) for p, c, _ in conf_pages if c < SEUIL_PAGE_FIABLE]
    if faibles:
        st.warning("Pages peu lisibles — un « non trouvé » n'y est pas fiable : "
                   + ", ".join(f"p.{p} ({c:.0f} %)" for p, c in faibles))
    with st.expander("Confiance par page"):
        st.dataframe(pd.DataFrame(conf_pages, columns=["Page", "Confiance (%)", "Source"])
                     .round(0), hide_index=True)

    st.download_button("📥 Télécharger le PDF cherchable (Ctrl+F)", pdf_ocr,
                       file_name=fichier.name.rsplit(".", 1)[0] + "_ocr.pdf",
                       mime="application/pdf")

    # --- Recherche
    st.divider()
    c1, c2, c3 = st.columns([3, 1, 1])
    requete = c1.text_input("Rechercher", placeholder="ex. BAR-TH-171, n° SIRET, nom…")
    mode = c2.radio("Mode", ["Floue", "Exacte"], horizontal=True)
    seuil = c3.slider("Seuil flou (%)", 60, 100, 85, disabled=(mode == "Exacte"))
    if not requete:
        return

    res = rechercher(mots, requete, mode, seuil)
    if res.empty:
        st.info("Aucun résultat.")
        return

    st.caption(f"{len(res)} résultat(s) — cliquer sur une ligne pour voir la page")
    sel = st.dataframe(
        res, hide_index=True, width="stretch",
        column_order=["Page", "Trouvé", "Similarité (%)", "Confiance OCR (%)", "Contexte"],
        on_select="rerun", selection_mode="single-row", key=f"res_{cle}",
    )
    lignes = sel.selection.rows
    ligne = res.iloc[lignes[0]] if lignes and lignes[0] < len(res) else res.iloc[0]
    st.image(apercu(pdf_ocr, int(ligne["Page"]), ligne["_boites"]),
             caption=f"Page {ligne['Page']} — « {ligne['Trouvé']} »", width="stretch")


if __name__ == "__main__":
    afficher_recherche_ocr()
