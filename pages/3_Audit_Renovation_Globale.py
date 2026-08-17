"""
Page Streamlit — Analyse automatique d'un Audit Énergétique réglementaire
(rénovation globale CEE) + export de la fiche "Liste des travaux et entreprises".

Extraction 100% par règles (regex), SANS appel IA / sans consommation de tokens.

Fonctionnement :
1. L'utilisateur dépose le PDF de l'audit énergétique.
2. `audit_parser.py` reconstruit le texte par position (x/y) puis applique des
   regex pour extraire bâtiment + scénarios (CEP/CEF avant/après, %, coût, travaux).
3. Rapport complet affiché, avec une table éditable par étape pour corriger les
   champs que le regex n'aurait pas bien identifiés (cas Climawin sur le CEP/CEF
   « après travaux », étiquette-lettre parfois dessinée en vectoriel, etc.).
4. Bouton par scénario -> génère le fichier "Liste des travaux et entreprises.xlsx".

Pré-requis :
- Le fichier gabarit Excel doit être placé dans ./templates/
  Liste_des_travaux_et_entreprises_Modèle.xlsx
"""

import copy
import io
from datetime import date
from pathlib import Path

import streamlit as st

from core.audit_parser import Travail, parse_audit_pdf

TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent
    / "database" / "templates" / "Liste_des_travaux_et_entreprises_Modèle.xlsx"
)

st.set_page_config(page_title="Audit énergétique — Rénovation globale", layout="wide")
st.title("🏢 Analyse automatique d'audit énergétique — Rénovation globale")
st.caption(
    "Extraction 100% par règles (regex), aucun appel IA. Dépose un audit énergétique "
    "réglementaire (PDF) : l'outil détecte les scénarios de travaux, leurs CEP/CEF "
    "avant/après, les postes de travaux, et permet de générer la fiche Excel "
    "« Liste des travaux et entreprises » pour le scénario choisi."
)

with st.expander("ℹ️ Fiabilité de l'extraction"):
    st.markdown(
        "- Fonctionne sur les formats testés (LICIEL Diagnostics, Climawin) qui suivent "
        "la structure imposée par l'arrêté du 4 mai 2022 (mêmes intitulés de sections).\n"
        "- L'étiquette-lettre (A→G) est parfois un dessin vectoriel non lisible en texte : "
        "elle est récupérée quand une phrase du type *« atteindre la lettre A »* existe, "
        "sinon laissée vide.\n"
        "- Le CEP/CEF « après travaux » peut être imprécis sur certains tableaux multi-lignes "
        "(notamment le format Climawin).\n"
        "- **Toutes les valeurs sont éditables ci-dessous avant génération de l'Excel** — "
        "aucun appel IA n'est fait, la correction se fait à la main si besoin."
    )

# ---------------------------------------------------------------------------
# Upload + extraction
# ---------------------------------------------------------------------------

uploaded = st.file_uploader("Audit énergétique (PDF)", type=["pdf"])

if uploaded is None:
    st.info("Dépose un fichier PDF d'audit énergétique pour lancer l'analyse.")
    st.stop()

if not TEMPLATE_PATH.exists():
    st.warning(
        f"⚠️ Gabarit Excel introuvable : `{TEMPLATE_PATH}`. Place le fichier "
        "« Liste_des_travaux_et_entreprises_Modèle.xlsx » dans `templates/` pour "
        "activer la génération Excel (le rapport reste consultable)."
    )

pdf_bytes = uploaded.read()

with st.spinner("Analyse de l'audit (règles, sans IA)..."):
    batiment, scenarios = parse_audit_pdf(io.BytesIO(pdf_bytes))

if not scenarios:
    st.error(
        "Aucun scénario n'a pu être détecté avec les règles actuelles — la mise en page "
        "de ce document diffère probablement de celles déjà testées (LICIEL / Climawin). "
        "Il faudra ajuster les regex de `audit_parser.py` pour ce format."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Édition du bâtiment
# ---------------------------------------------------------------------------

st.header("📋 Bâtiment")
c1, c2 = st.columns(2)
with c1:
    batiment.adresse = st.text_input("Adresse", batiment.adresse or "")
    batiment.beneficiaire = st.text_input("Bénéficiaire / Propriétaire", batiment.beneficiaire or "")
    batiment.surface_m2 = st.number_input("Surface de référence (m²)", value=float(batiment.surface_m2 or 0), step=1.0)
with c2:
    batiment.cep_initial = st.number_input("CEP initial (kWhEP/m²/an)", value=float(batiment.cep_initial or 0), step=1.0)
    batiment.cef_initial = st.number_input("CEF initial (kWhEF/m²/an)", value=float(batiment.cef_initial or 0), step=1.0)
    batiment.etiquette_initiale = st.text_input("Étiquette initiale (A-G)", batiment.etiquette_initiale or "")

st.divider()

# ---------------------------------------------------------------------------
# Tableau comparatif
# ---------------------------------------------------------------------------

st.header("📊 Comparatif des scénarios")

summary_rows = []
for sc in scenarios:
    for e in sc.etapes:
        summary_rows.append(
            {
                "Scénario": sc.nom.replace("\n", " "),
                "Étape": e.libelle,
                "CEP avant": batiment.cep_initial,
                "CEP après": e.cep_apres,
                "CEF avant": batiment.cef_initial,
                "CEF après": e.cef_apres,
                "Étiquette avant": batiment.etiquette_initiale,
                "Étiquette après": e.etiquette_apres,
                "Économie": f"{e.economie_pct}%" if e.economie_pct is not None else "—",
                "Coût travaux TTC": e.cout_travaux_ttc,
            }
        )
st.dataframe(summary_rows, use_container_width=True, hide_index=True)

st.divider()

# ---------------------------------------------------------------------------
# Détail par scénario, édition, export
# ---------------------------------------------------------------------------

st.header("🔍 Détail, correction et export Excel")

tabs = st.tabs([sc.nom.replace("\n", " ") for sc in scenarios])

for tab, sc in zip(tabs, scenarios):
    with tab:
        for ei, e in enumerate(sc.etapes):
            with st.container(border=True):
                st.markdown(f"**{e.libelle}**")
                m1, m2, m3, m4, m5 = st.columns(5)
                e.cep_apres = m1.number_input(
                    "CEP après", value=float(e.cep_apres or 0), step=1.0, key=f"cep_{sc.id}_{ei}"
                )
                e.cef_apres = m2.number_input(
                    "CEF après", value=float(e.cef_apres or 0), step=1.0, key=f"cef_{sc.id}_{ei}"
                )
                e.etiquette_apres = m3.text_input(
                    "Étiquette après", e.etiquette_apres or "", key=f"lbl_{sc.id}_{ei}"
                )
                e.economie_pct = m4.number_input(
                    "Économie %", value=float(e.economie_pct or 0), step=1.0, key=f"eco_{sc.id}_{ei}"
                )
                e.cout_travaux_ttc = m5.number_input(
                    "Coût TTC (€)", value=float(e.cout_travaux_ttc or 0), step=100.0, key=f"cout_{sc.id}_{ei}"
                )

                st.markdown("_Travaux détectés (modifiable) :_")
                edited = st.data_editor(
                    [
                        {"Poste": t.poste, "Description": t.description, "Coût TTC (€)": t.cout_ttc}
                        for t in e.travaux
                    ],
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key=f"travaux_{sc.id}_{ei}",
                )
                e.travaux = [
                    Travail(
                        poste=row.get("Poste") or "",
                        description=row.get("Description") or "",
                        cout_ttc=row.get("Coût TTC (€)"),
                    )
                    for row in edited
                    if (row.get("Poste") or row.get("Description"))
                ]

        st.markdown("")
        if st.button(f"📥 Générer l'Excel pour « {sc.nom.strip()} »", key=f"gen_{sc.id}"):
            if not TEMPLATE_PATH.exists():
                st.error("Le gabarit Excel est introuvable, impossible de générer le fichier.")
            else:
                import openpyxl

                def _copy_row_style(ws, src_row, dst_row, min_col, max_col):
                    for col in range(min_col, max_col + 1):
                        s = ws.cell(row=src_row, column=col)
                        d = ws.cell(row=dst_row, column=col)
                        d.font = copy.copy(s.font)
                        d.border = copy.copy(s.border)
                        d.fill = copy.copy(s.fill)
                        d.number_format = s.number_format
                        d.alignment = copy.copy(s.alignment)

                wb = openpyxl.load_workbook(TEMPLATE_PATH)
                ws = wb.active

                ws["B4"] = batiment.beneficiaire or ""
                ws["E4"] = sc.nom.replace("\n", " ")
                ws["B5"] = batiment.adresse or ""
                ws["E5"] = date.today().strftime("%d/%m/%Y")

                all_travaux = []
                for e in sc.etapes:
                    prefix = f"{e.libelle} — " if len(sc.etapes) > 1 else ""
                    for t in e.travaux:
                        all_travaux.append(
                            {
                                "nature": f"{prefix}{t.poste}".strip(" —"),
                                "carac": t.description,
                                "quantite": "",
                            }
                        )

                start_row, avail = 9, 6
                if len(all_travaux) > avail:
                    extra = len(all_travaux) - avail
                    ws.insert_rows(start_row + avail, amount=extra)
                    for i in range(extra):
                        _copy_row_style(ws, start_row, start_row + avail + i, 2, 7)

                for i, t in enumerate(all_travaux):
                    r = start_row + i
                    ws.cell(row=r, column=2, value=t["nature"])
                    ws.cell(row=r, column=3, value=t["carac"])
                    ws.cell(row=r, column=4, value=t["quantite"])
                    # Colonnes "Travaux réalisés" / tableau "Entreprises" laissés vides :
                    # non renseignés dans un audit énergétique.

                buf = io.BytesIO()
                wb.save(buf)
                buf.seek(0)

                st.success("Fichier généré.")
                st.download_button(
                    "⬇️ Télécharger le fichier Excel",
                    data=buf.getvalue(),
                    file_name=f"Liste_travaux_{sc.id}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key=f"dl_{sc.id}",
                )
