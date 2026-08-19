"""
Génération d'un PDF unique à envoyer au bailleur :
  - Page 1 : récapitulatif comparatif des scénarios, scénario retenu en évidence.
  - Page 2 (+ suite si besoin) : fiche "Liste des travaux et entreprises", au même
    format que le gabarit Excel, mais en PDF avec de VRAIS champs de formulaire
    (AcroForm) directement remplissables (entreprise, SIRET, qualification,
    travaux réalisés, signatures...), pré-remplie avec les données de l'audit.

Aucune dépendance à un gabarit externe : tout est dessiné avec reportlab.
Utilise uniquement des tables ASCII (pas de caractères Unicode exotiques).
"""

from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 12 * mm

COL_HEADER = colors.HexColor("#1F4E78")
COL_HEADER_TXT = colors.white
COL_HILITE = colors.HexColor("#E2EFDA")
COL_HILITE_BORDER = colors.HexColor("#548235")
COL_ROW_ALT = colors.HexColor("#F2F2F2")
COL_BORDER = colors.HexColor("#BFBFBF")
COL_FIELD_BG = colors.HexColor("#FFF8E1")  # fond légèrement teinté = "à remplir"


_CHAR_REPLACEMENTS = {
    "\u2014": "-",   # em dash —
    "\u2013": "-",   # en dash –
    "\u2018": "'",   # ‘
    "\u2019": "'",   # ’
    "\u201c": '"',   # “
    "\u201d": '"',   # ”
    "\u2026": "...", # …
    "\u00a0": " ",   # espace insécable
    "\u2022": "-",   # puce •
}


def _clean(text: str | None) -> str:
    """Nettoie le texte pour l'écriture PDF (canvas et surtout champs AcroForm) :
    remplace les caractères typographiques non gérés par l'encodeur de reportlab
    pour les champs de formulaire, puis retombe sur Latin-1 en dernier recours
    pour éviter tout KeyError d'échappement PDF."""
    if not text:
        return ""
    s = str(text)
    for bad, good in _CHAR_REPLACEMENTS.items():
        s = s.replace(bad, good)
    # Filet de sécurité : tout caractère encore hors Latin-1 (accents exotiques,
    # symboles, emoji...) est remplacé plutôt que de faire planter la génération.
    return s.encode("latin-1", errors="replace").decode("latin-1")


def _wrap_text(c: canvas.Canvas, text: str, font: str, size: float, max_width: float) -> list[str]:
    """Découpe `text` en lignes tenant dans `max_width` pour la police/taille donnée."""
    words = _clean(text).split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if stringWidth(trial, font, size) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_wrapped(c: canvas.Canvas, text: str, x: float, top_y: float, max_width: float,
                   font: str = "Helvetica", size: float = 8, leading: float = 9.5,
                   max_lines: int = 6) -> None:
    c.setFont(font, size)
    lines = _wrap_text(c, text, font, size, max_width)[:max_lines]
    y = top_y
    for line in lines:
        c.drawString(x, y, line)
        y -= leading


# ---------------------------------------------------------------------------
# Page 1 : récapitulatif des scénarios
# ---------------------------------------------------------------------------

TRAVAUX_TYPES = [
    ("Murs", ["Murs"]),
    ("Plancher bas", ["Plancher", "Planchers bas"]),
    ("Toiture / Combles", ["Toiture / Combles"]),
    ("Menuiseries", ["Menuiseries"]),
    ("Ventilation", ["Ventilation"]),
    ("Chauffage", ["Chauffage"]),
    ("ECS", ["Eau chaude sanitaire"]),
]


def draw_summary_page(c: canvas.Canvas, batiment, scenarios, scenario_choisi_id: str) -> None:
    c.setFillColor(colors.HexColor("#1F1F1F"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(MARGIN, PAGE_H - MARGIN - 10, "Récapitulatif des scénarios de travaux — Rénovation globale")

    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#404040"))
    infos = (
        f"Bénéficiaire : {batiment.beneficiaire or '—'}    |    "
        f"Adresse : {batiment.adresse or '—'}    |    "
        f"Date : {date.today().strftime('%d/%m/%Y')}"
    )
    c.drawString(MARGIN, PAGE_H - MARGIN - 26, _clean(infos))

    # Bandeau scénario retenu
    chosen = next((s for s in scenarios if s.id == scenario_choisi_id), None)
    if chosen:
        band_y = PAGE_H - MARGIN - 44
        c.setFillColor(COL_HILITE_BORDER)
        c.roundRect(MARGIN, band_y - 14, 260, 20, 3, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(MARGIN + 8, band_y - 8, _clean(f"SCENARIO RETENU : {chosen.nom.replace(chr(10), ' ')}"))

    # Tableau comparatif
    headers = ["Scénario", "CEP avant", "CEP après", "CEF avant", "CEF après",
               "Étiq. avant", "Étiq. après", "Économie"] + [t[0] for t in TRAVAUX_TYPES]

    table_top = PAGE_H - MARGIN - 70
    table_left = MARGIN
    table_width = PAGE_W - 2 * MARGIN
    n_cols = len(headers)
    col_w = table_width / n_cols
    row_h = 16
    header_h = 28

    # En-tête
    c.setFillColor(COL_HEADER)
    c.rect(table_left, table_top - header_h, table_width, header_h, fill=1, stroke=0)
    c.setFillColor(COL_HEADER_TXT)
    c.setFont("Helvetica-Bold", 7.2)
    for i, h in enumerate(headers):
        x = table_left + i * col_w
        _draw_wrapped(c, h, x + 3, table_top - 10, col_w - 6, "Helvetica-Bold", 7.2, 8.5, 3)
        if i > 0:
            c.setStrokeColor(colors.white)
            c.line(x, table_top - header_h, x, table_top)

    # Lignes
    y = table_top - header_h
    for ridx, sc in enumerate(scenarios):
        derniere = sc.etapes[-1] if sc.etapes else None
        is_chosen = sc.id == scenario_choisi_id
        row_top = y
        row_bottom = y - row_h

        if is_chosen:
            c.setFillColor(COL_HILITE)
        elif ridx % 2 == 1:
            c.setFillColor(COL_ROW_ALT)
        else:
            c.setFillColor(colors.white)
        c.rect(table_left, row_bottom, table_width, row_h, fill=1, stroke=0)

        vals = [
            sc.nom.replace("\n", " "),
            f"{batiment.cep_initial:g}" if batiment.cep_initial else "—",
            f"{derniere.cep_apres:g}" if derniere and derniere.cep_apres else "—",
            f"{batiment.cef_initial:g}" if batiment.cef_initial else "—",
            f"{derniere.cef_apres:g}" if derniere and derniere.cef_apres else "—",
            batiment.etiquette_initiale or "—",
            (derniere.etiquette_apres if derniere else None) or "—",
            f"{derniere.economie_pct:g}%" if derniere and derniere.economie_pct is not None else "—",
        ]
        for label, postes in TRAVAUX_TYPES:
            present = any(
                any(t.poste in postes for t in e.travaux) for e in sc.etapes
            )
            vals.append("Oui" if present else "-")

        c.setFont("Helvetica-Bold" if is_chosen else "Helvetica", 7.5)
        c.setFillColor(colors.HexColor("#1F1F1F"))
        for i, v in enumerate(vals):
            x = table_left + i * col_w
            _draw_wrapped(c, str(v), x + 3, row_top - 10, col_w - 6, c._fontname, 7.5, 8.5, 2)

        c.setStrokeColor(COL_BORDER)
        c.setLineWidth(0.5)
        c.rect(table_left, row_bottom, table_width, row_h, fill=0, stroke=1)
        if is_chosen:
            c.setStrokeColor(COL_HILITE_BORDER)
            c.setLineWidth(1.4)
            c.rect(table_left, row_bottom, table_width, row_h, fill=0, stroke=1)

        y -= row_h

    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(colors.HexColor("#7F7F7F"))
    c.drawString(MARGIN, y - 16,
                 "Le détail des travaux préconisés et le tableau à compléter (entreprises, SIRET, "
                 "qualifications, travaux réalisés) figurent en page suivante.")


# ---------------------------------------------------------------------------
# Page 2+ : fiche "Liste des travaux et entreprises" — AcroForm remplissable
# ---------------------------------------------------------------------------

def _field(c: canvas.Canvas, name: str, x: float, y: float, w: float, h: float,
           value: str = "", font_size: int = 8, multiline: bool = False, tooltip: str = ""):
    form = c.acroForm
    form.textfield(
        name=name,
        tooltip=_clean(tooltip or name),
        x=x, y=y, width=w, height=h,
        value=_clean(value),
        fontName="Helvetica",
        fontSize=font_size,
        borderStyle="underlined",
        borderColor=colors.HexColor("#9E9E9E"),
        borderWidth=0.6,
        fillColor=COL_FIELD_BG,
        textColor=colors.HexColor("#1F1F1F"),
        forceBorder=True,
        fieldFlags="multiline" if multiline else "",
    )


def _section_header(c: canvas.Canvas, text: str, x: float, y: float, w: float):
    c.setFillColor(COL_HEADER)
    c.rect(x, y, w, 16, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 5, y + 4.5, text)


def draw_fiche_page(c: canvas.Canvas, batiment, scenario, all_travaux: list[dict],
                     field_prefix: str) -> None:
    """
    all_travaux : liste de dicts {"nature": ..., "carac": ..., "quantite": ...}
    (mêmes valeurs que celles écrites dans l'Excel — colonne "préconisés").
    field_prefix : préfixe pour l'unicité des noms de champs (id du scénario).
    """
    left = MARGIN
    top = PAGE_H - MARGIN
    width = PAGE_W - 2 * MARGIN

    c.setFillColor(colors.HexColor("#1F1F1F"))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(left, top - 10, "LISTE DES TRAVAUX PRECONISES ET REALISES")

    # Bloc identification
    c.setFont("Helvetica-Bold", 9)
    c.drawString(left, top - 30, "Bénéficiaire :")
    c.drawString(left + width / 2, top - 30, "Scénario choisi :")
    c.drawString(left, top - 46, "Opération :")
    c.drawString(left + width / 2, top - 46, "Date :")

    c.setFont("Helvetica", 9)
    c.drawString(left + 68, top - 30, _clean(batiment.beneficiaire or ""))
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(COL_HILITE_BORDER)
    c.drawString(left + width / 2 + 90, top - 30, _clean(scenario.nom.replace("\n", " ")))
    c.setFillColor(colors.HexColor("#1F1F1F"))
    c.setFont("Helvetica", 9)
    c.drawString(left + 68, top - 46, _clean(batiment.adresse or ""))
    c.drawString(left + width / 2 + 40, top - 46, date.today().strftime("%d/%m/%Y"))

    # --- Tableau des travaux (préconisés = texte figé issu de l'audit ;
    #     réalisés = champs remplissables, pré-remplis avec les mêmes valeurs
    #     par défaut, à ajuster après chantier) ---
    table_top = top - 62
    row_h = 34
    header_h = 14
    col_nat_w = width * 0.24
    col_carac_w = width * 0.20
    col_qte_w = width * 0.09
    half = col_nat_w + col_carac_w + col_qte_w  # largeur d'un demi-tableau (préco / réalisé)

    _section_header(c, "Travaux préconisés", left, table_top - header_h, half)
    _section_header(c, "Travaux réalisés", left + half, table_top - header_h, half)

    headers = ["Nature des travaux", "Caractéristiques techniques / Marque et référence", "Surface / Quantités"]
    col_widths = [col_nat_w, col_carac_w, col_qte_w]

    y = table_top - header_h
    max_rows = max(len(all_travaux), 6)
    for ridx in range(max_rows):
        row_top = y
        row_bottom = y - row_h
        t = all_travaux[ridx] if ridx < len(all_travaux) else {"nature": "", "carac": "", "quantite": ""}

        for side, x0 in ((0, left), (1, left + half)):
            x = x0
            for ci, cw in enumerate(col_widths):
                c.setStrokeColor(COL_BORDER)
                c.setLineWidth(0.4)
                c.rect(x, row_bottom, cw, row_h, fill=0, stroke=1)
                if side == 0:
                    # Préconisé : texte figé (donnée de l'audit, non modifiable)
                    val = [t["nature"], t["carac"], t["quantite"]][ci]
                    _draw_wrapped(c, val, x + 3, row_top - 10, cw - 6, "Helvetica", 7.5, 8.8, 4)
                else:
                    # Réalisé : champ de formulaire pré-rempli, modifiable
                    fname = f"{field_prefix}_realise_{ridx}_{ci}"
                    val = [t["nature"], t["carac"], t["quantite"]][ci]
                    _field(c, fname, x + 2, row_bottom + 2, cw - 4, row_h - 4,
                           value=val, font_size=7.5, multiline=True,
                           tooltip=f"{headers[ci]} — travaux réalisés")
                x += cw
        y -= row_h

    table_bottom = y

    # --- Tableau des entreprises (100% remplissable) ---
    ent_top = table_bottom - 22
    _section_header(c, "LISTE DES ENTREPRISES", left, ent_top - header_h, width)
    ent_headers = ["Nature des travaux", "Entreprise (titulaire ou sous-traitant)", "SIRET entreprise", "N° de qualification"]
    ent_col_w = [width * 0.22, width * 0.38, width * 0.20, width * 0.20]
    ey = ent_top - header_h
    ent_row_h = 20
    n_ent_rows = 6
    for ridx in range(n_ent_rows):
        row_top = ey
        row_bottom = ey - ent_row_h
        x = left
        # valeur par défaut de la 1re colonne = nature du travail correspondant si dispo
        default_nat = all_travaux[ridx]["nature"] if ridx < len(all_travaux) else ""
        for ci, cw in enumerate(ent_col_w):
            c.setStrokeColor(COL_BORDER)
            c.setLineWidth(0.4)
            c.rect(x, row_bottom, cw, ent_row_h, fill=0, stroke=1)
            fname = f"{field_prefix}_entreprise_{ridx}_{ci}"
            val = default_nat if ci == 0 else ""
            _field(c, fname, x + 2, row_bottom + 2, cw - 4, ent_row_h - 4,
                   value=val, font_size=7.5, tooltip=ent_headers[ci])
            x += cw
        ey -= ent_row_h

    ent_bottom = ey

    # --- Signatures ---
    sig_top = ent_bottom - 16
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(colors.HexColor("#1F1F1F"))
    c.drawString(left, sig_top, "Signature bénéficiaire :")
    c.drawString(left + width / 2, sig_top, "Signature maître d'œuvre :")

    _field(c, f"{field_prefix}_nom_signataire_1", left, sig_top - 34, width / 2 - 20, 22,
           tooltip="Nom, prénom et fonction du signataire (bénéficiaire)")
    _field(c, f"{field_prefix}_nom_signataire_2", left + width / 2, sig_top - 34, width / 2 - 10, 22,
           tooltip="Nom, prénom et fonction du signataire (maître d'œuvre)")
    c.setFont("Helvetica", 6.5)
    c.setFillColor(colors.HexColor("#7F7F7F"))
    c.drawString(left, sig_top - 40, "Nom, prénom et fonction du signataire")
    c.drawString(left + width / 2, sig_top - 40, "Nom, prénom et fonction du signataire")


# ---------------------------------------------------------------------------
# Assemblage
# ---------------------------------------------------------------------------

def generate_pdf(batiment, scenarios, scenario_choisi_id: str) -> bytes:
    """Construit le PDF complet : page récap + une fiche par... non, une seule
    fiche pour le scénario RETENU (celui envoyé au bailleur pour signature).
    Les autres scénarios restent visibles sur la page récap pour comparaison."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("Liste des travaux et entreprises")

    draw_summary_page(c, batiment, scenarios, scenario_choisi_id)
    c.showPage()

    chosen = next((s for s in scenarios if s.id == scenario_choisi_id), scenarios[0])
    all_travaux = []
    for e in chosen.etapes:
        suffix = f" - {e.libelle}" if len(chosen.etapes) > 1 else ""
        for t in e.travaux:
            all_travaux.append({
                "nature": _clean(f"{t.nature_affichee}{suffix}"),
                "carac": _clean(t.caracteristiques),
                "quantite": _clean(t.quantite),
            })

    draw_fiche_page(c, batiment, chosen, all_travaux, field_prefix=chosen.id)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
