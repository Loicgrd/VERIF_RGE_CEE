import streamlit as st
import json
import re
from datetime import datetime
import pytz

st.set_page_config(page_title="Supervision Dossier CEE", layout="wide")

PARIS_TZ = pytz.timezone("Europe/Paris")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt_ts(ts):
    if ts:
        return datetime.fromtimestamp(ts / 1000.0, PARIS_TZ).strftime("%d/%m/%Y")
    return None


def alerte(valeur, critique=False):
    if valeur is None or valeur == "" or valeur == "Non renseigné":
        return True
    if isinstance(valeur, (int, float)) and valeur == 0 and critique:
        return True
    return False


def badge_statut(statut):
    couleurs = {
        "CONTROLE_OK": "🟢", "CONTROLE_KO": "🔴",
        "CONTROLE_OK_CONTACT": "🟢", "CONTROLE_KO_CONTACT": "🔴",
        "EN_ATTENTE": "🟡", "EN_COURS": "🟡",
        "NON_RECU": "🔴", "D_CONTROLE_OK": "🟢", "D_CONTROLE_KO": "🔴",
        "LOT_OK": "🟢", "LOT_DEPOSE": "🔵", "LOT_KO": "🔴",
        "STADE_6": "🟢", "STADE_5": "🟡", "STADE_3V": "🟡",
        "STADE_3": "🟠", "STADE_3F": "🟡",
    }
    return couleurs.get(statut, "⚪") + f" {statut}"


def row(label, valeur, critique=False, unite=""):
    val_str = str(valeur) + (f" {unite}" if unite and valeur not in (None, "") else "")
    if alerte(valeur, critique=critique):
        st.markdown(
            f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
            f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
            f"<span style='color:#c0392b;font-weight:600'>⚠️ Manquant / vide</span></div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
            f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
            f"<span style='font-weight:500'>{val_str}</span></div>",
            unsafe_allow_html=True,
        )


def get_just(lot, type_id):
    """Récupère le justificatif d'un type donné (par id typeJustificatif)."""
    for j in lot.get("justificatifs", []) or []:
        if (j.get("typeJustificatif") or {}).get("id") == type_id:
            return j
    return None


# ─────────────────────────────────────────────
# RÈGLES TECHNIQUES PAR FICHE (étape 2 - éléments techniques)
# ─────────────────────────────────────────────

REGLES = {
    "BAR-EN-101": [
        ("surface_isolant", "Surface isolée (m²)", "m²", True),
        ("resistance_thermique", "Résistance thermique R (m².K/W)", "m².K/W", True),
        ("type_pose", "Type de pose", "", True),
        ("marque_isolant", "Marque isolant", "", True),
        ("reference_isolant", "Référence isolant", "", False),
        ("epaisseur_isolant", "Épaisseur (mm)", "mm", False),
    ],
    "BAR-EN-102": [
        ("surface_isolant", "Surface isolée (m²)", "m²", True),
        ("resistance_thermique", "Résistance thermique R (m².K/W)", "m².K/W", True),
        ("marque_isolant", "Marque isolant", "", True),
        ("reference_isolant", "Référence isolant", "", False),
        ("epaisseur_isolant", "Épaisseur (mm)", "mm", False),
    ],
    "BAR-EN-103": [
        ("surface", "Surface (m²)", "m²", True),
        ("resistance_thermique", "Résistance thermique R (m².K/W)", "m².K/W", True),
        ("marque_isolant", "Marque isolant", "", True),
        ("reference_isolant", "Référence isolant", "", False),
        ("epaisseur_isolant", "Épaisseur (mm)", "mm", False),
    ],
    "BAR-EN-104": [
        ("type_fenetre", "Type de fenêtre", "", True),
        ("Quantité", "Quantité", "", True),
        ("Uw (W/m².K)", "Uw (W/m².K)", "W/m².K", True),
        ("Sw", "Facteur solaire Sw", "", False),
        ("marque", "Marque", "", True),
        ("reference_produit", "Référence produit", "", False),
        ("surface_fenetres", "Surface totale fenêtres (m²)", "m²", True),
    ],
    "BAR-EN-105": [
        ("surface", "Surface isolée (m²)", "m²", True),
        ("resistance_thermique_non_exported", "Résistance thermique R (m².K/W)", "m².K/W", True),
        ("marque_isolant", "Marque isolant", "", True),
        ("reference_isolant", "Référence isolant", "", False),
        ("epaisseur_isolant", "Épaisseur (mm)", "mm", False),
    ],
    "BAR-TH-106": [
        ("type_logement", "Type installation", "", True),
        ("marque_chaudiere", "Marque chaudière", "", True),
        ("reference_chaudiere", "Référence chaudière", "", False),
        ("etas", "ETAS (%)", "%", True),
        ("classe_regulateur", "Classe régulateur", "", True),
    ],
    "BAR-TH-127": [
        ("type_installation", "Type installation", "", True),
        ("type_caisson", "Type caisson", "", True),
        ("type_ventilation", "Type ventilation", "", True),
        ("marque_caisson", "Marque caisson", "", True),
        ("reference_caisson", "Référence caisson", "", True),
        ("marque_bouches_extraction", "Marque bouches extraction", "", True),
        ("reference_bouches_extraction", "Référence bouches extraction", "", True),
        ("marque_bouches_entree_air", "Marque bouches entrée air", "", False),
        ("reference_bouches_entree_air", "Référence bouches entrée air", "", False),
        ("reference_technique", "Référence technique (ATec/DTA)", "", True),
        ("date_validite", "Date validité ATec/DTA", "", True),
        ("classe_energetique", "Classe énergétique", "", False),
        ("nb_appartement", "Nombre d'appartements", "", True),
        ("surface_habitable", "Surface habitable (m²)", "m²", False),
    ],
    "BAR-TH-158": [
        ("nb_equipements", "Nombre d'émetteurs total", "", True),
    ],
}

SEUILS = {
    "BAR-EN-101": {"resistance_thermique": (7, None)},
    "BAR-EN-102": {"resistance_thermique": (3.7, None)},
    "BAR-EN-103": {"resistance_thermique": (3.7, None)},
    "BAR-EN-104": {"Uw (W/m².K)": (None, 1.3), "Sw": (None, 0.36)},
    "BAR-EN-105": {"resistance_thermique_non_exported": (3.7, None)},
    "BAR-TH-106": {"etas": (87, None)},
}


def verif_seuil(fiche_ref, cle, valeur):
    ref = fiche_ref.upper()
    for k, seuils in SEUILS.items():
        if k in ref and cle in seuils:
            seuil_min, seuil_max = seuils[cle]
            try:
                v = float(valeur)
                if seuil_min is not None and v < seuil_min:
                    return False, f"⚠️ {v} < seuil min ({seuil_min})"
                if seuil_max is not None and v > seuil_max:
                    return False, f"⚠️ {v} > seuil max ({seuil_max})"
                return True, None
            except (TypeError, ValueError):
                return None, None
    return None, None


# Fiches nécessitant obligatoirement un RGE (à ajuster selon ta connaissance métier)
FICHES_RGE_OBLIGATOIRE = {
    "BAR-EN-101", "BAR-EN-102", "BAR-EN-103", "BAR-EN-104", "BAR-EN-105",
    "BAR-TH-106", "BAR-TH-127", "BAR-TH-158", "BAR-TH-179",
}


# ─────────────────────────────────────────────
# AFFICHAGE D'UN LOT — PARCOURS DE VÉRIFICATION
# ─────────────────────────────────────────────

def afficher_lot(lot, lot_index, data, adresse_site=None):
    fd = lot.get("formData", {}) or {}
    fiche_ref = fd.get("reference", "")
    ref_upper = fiche_ref.upper()

    adresse_fd = " ".join(filter(None, [
        fd.get("adresse_travaux", ""),
        fd.get("code_postal", ""),
        fd.get("ville", "")
    ])) or "Non renseignée"

    statut_lot = lot.get("statut", "")
    nc1 = lot.get("nonConformiteUn")
    nc2 = lot.get("nonConformiteDeux")

    label_exp = f"Lot {lot_index} — {adresse_site or adresse_fd}"
    with st.expander(label_exp, expanded=True):

        cols = st.columns([1, 1, 2])
        cols[0].markdown(f"**Statut**\n\n{badge_statut(statut_lot)}")
        if nc1:
            cols[1].error(f"NC1 : {nc1}")
        if nc2:
            cols[2].error(f"NC2 : {nc2}")

        st.markdown("---")

        # ═══════════════════════════════════════════
        # ÉTAPE 1 — ENGAGEMENT
        # ═══════════════════════════════════════════
        st.markdown("#### 1️⃣ Engagement")
        col1, col2 = st.columns(2)
        with col1:
            date_eng = fmt_ts(data.get("dateEngagementReelle"))
            row("Date d'engagement", date_eng, critique=True)
            row("Adresse des travaux", adresse_fd, critique=True)
        with col2:
            b = data.get("beneficiaire", {}) or {}
            row("Bailleur", b.get("raisonSociale"), critique=True)
            row("Fiche / Lot d'engagement", fiche_ref, critique=True)

        just_engagement = get_just(lot, 1)  # "Preuve d'engagement"
        if just_engagement:
            st.markdown(
                f"📎 Preuve d'engagement : {badge_statut(just_engagement.get('status'))}"
                + (f" — {fmt_ts(just_engagement.get('date'))}" if just_engagement.get('date') else "")
            )

        # ═══════════════════════════════════════════
        # ÉTAPE 2 — PREUVE DE RÉALISATION
        # ═══════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 2️⃣ Preuve de réalisation")

        just_real = get_just(lot, 2)  # "Preuve de réalisation"
        if just_real:
            st.markdown(f"📎 Statut document : {badge_statut(just_real.get('status'))}")
        else:
            st.warning("⚠️ Aucune preuve de réalisation trouvée dans les justificatifs.")

        date_real = fmt_ts(data.get("dateRealisationReelle"))
        row("Date de réalisation", date_real, critique=True)

        st.caption("👉 Vérifier la cohérence du document avec l'engagement (adresse, fiche, bailleur) avant de poursuivre.")

        # -- Éléments techniques --
        st.markdown("**🔧 Données techniques**")
        regles_fiche = None
        for k in REGLES:
            if k in ref_upper:
                regles_fiche = REGLES[k]
                break

        if regles_fiche:
            for cle, label, unite, critique in regles_fiche:
                valeur = fd.get(cle)
                if valeur is None and cle == "resistance_thermique":
                    valeur = fd.get("resistance_thermique_non_exported")

                ok_seuil, msg_seuil = verif_seuil(fiche_ref, cle, valeur)

                if alerte(valeur, critique=critique):
                    st.markdown(
                        f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
                        f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
                        f"<span style='color:#c0392b;font-weight:600'>⚠️ Manquant / vide</span></div>",
                        unsafe_allow_html=True,
                    )
                elif ok_seuil is False:
                    st.markdown(
                        f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
                        f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
                        f"<span style='color:#e67e22;font-weight:600'>{valeur} {unite} — {msg_seuil}</span></div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
                        f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
                        f"<span style='font-weight:500'>{valeur}{' ' + unite if unite else ''}</span></div>",
                        unsafe_allow_html=True,
                    )

            if "BAR-TH-158" in ref_upper:
                eq_raw = fd.get("Equipements")
                if eq_raw:
                    try:
                        if isinstance(eq_raw, dict):
                            eq_list = json.loads(eq_raw["values"]) if isinstance(eq_raw.get("values"), str) else eq_raw.get("values", [])
                        elif isinstance(eq_raw, str):
                            eq_list = json.loads(eq_raw)
                        else:
                            eq_list = eq_raw
                        import pandas as pd
                        rows = []
                        for item in eq_list:
                            rows.append({
                                "Marque": item[0] if len(item) > 0 else "",
                                "Référence": item[1] if len(item) > 1 else "",
                                "N° certif": item[2] if len(item) > 2 else "",
                                "Quantité": item[3] if len(item) > 3 else "",
                                "Puissance (W)": item[4] if len(item) > 4 else "",
                            })
                        if rows:
                            st.markdown("**Équipements :**")
                            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    except Exception:
                        pass

            if "BAR-TH-106" in ref_upper:
                puissance_key = next((k for k in fd if k.lower() == "puissance"), None)
                type_log = fd.get("type_logement")
                if type_log == 2 and puissance_key:
                    eq_raw = fd.get(puissance_key)
                    try:
                        if isinstance(eq_raw, dict):
                            eq_list = json.loads(eq_raw["values"]) if isinstance(eq_raw.get("values"), str) else eq_raw.get("values", [])
                        elif isinstance(eq_raw, str):
                            eq_list = json.loads(eq_raw)
                        else:
                            eq_list = eq_raw
                        import pandas as pd
                        rows = []
                        for item in eq_list:
                            rows.append({
                                "M et R Chaudière": item[0] if len(item) > 0 else "",
                                "Quantité": item[1] if len(item) > 1 else "",
                                "Puissance (kW)": item[2] if len(item) > 2 else "",
                                "ETAS (%)": item[3] if len(item) > 3 else "",
                                "M et R Régulateur": item[4] if len(item) > 4 else "",
                                "Classe régu": item[5] if len(item) > 5 else "",
                            })
                        if rows:
                            st.markdown("**Chaudières :**")
                            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    except Exception:
                        pass
        else:
            EXCLUDE = {
                "sme", "titre", "ville", "version", "Altitude", "reference",
                "code_postal", "departement", "zoneClimatique", "adresse_travaux",
                "nom_site_travaux", "zoneGeographique", "adresse_travaux_ah",
                "complement_adresse", "count_html_block_A", "secteurApplication",
                "nombreLogements", "nombreLogementsConventionnes",
                "volume", "volumeClassique", "volumePrecarite",
                "coefficient_zone_a", "energieChauffage",
            }
            for cle, valeur in fd.items():
                if cle not in EXCLUDE and valeur is not None:
                    row(cle, valeur)

        # -- SIRET professionnel + sous-traitant --
        st.markdown("**🪪 Professionnel ayant réalisé les travaux**")
        prof = lot.get("professionnel") or {}
        sous_traitant = lot.get("professionnelSousTraitant")
        col1, col2 = st.columns(2)
        with col1:
            row("Raison sociale", prof.get("raisonSociale"), critique=True)
            row("SIRET", prof.get("siret"), critique=True)
        with col2:
            if sous_traitant:
                row("Sous-traitant", sous_traitant.get("raisonSociale"))
                row("SIRET sous-traitant", sous_traitant.get("siret"))
            else:
                st.caption("Aucun sous-traitant déclaré.")

        # ═══════════════════════════════════════════
        # ÉTAPE 3 — RGE + DOCUMENTS COMPLÉMENTAIRES
        # ═══════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 3️⃣ RGE & documents complémentaires")

        rge_requis = any(k in ref_upper for k in FICHES_RGE_OBLIGATOIRE)
        rge = lot.get("professionnelTitulaireSigneQualite") or {}

        if rge_requis:
            col1, col2 = st.columns(2)
            with col1:
                row("Raison sociale RGE", rge.get("raisonSociale"), critique=True)
            with col2:
                row("SIRET RGE", rge.get("siret"), critique=True)
            just_qualif = get_just(lot, 6)  # "Qualification ou certification"
            if just_qualif:
                st.markdown(f"📎 Justificatif qualification : {badge_statut(just_qualif.get('status'))}")
        else:
            st.caption("Cette fiche ne nécessite pas obligatoirement de RGE — à confirmer selon les conditions de la fiche.")

        IDS_DEJA_TRAITES = {1, 2, 3, 6}
        autres_justs = [j for j in (lot.get("justificatifs") or [])
                         if (j.get("typeJustificatif") or {}).get("id") not in IDS_DEJA_TRAITES]
        if autres_justs:
            st.markdown("**📎 Documents complémentaires**")
            for j in autres_justs:
                tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
                facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
                mention = " *(facultatif)*" if facultatif else ""
                date_j = fmt_ts(j.get("date"))
                date_str = f" — {date_j}" if date_j else ""
                st.markdown(f"- {badge_statut(j.get('status'))} **{tj}**{mention}{date_str}")

        # ═══════════════════════════════════════════
        # ÉTAPE 4 — ATTESTATION SUR L'HONNEUR
        # ═══════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 4️⃣ Attestation sur l'Honneur")

        just_ah = get_just(lot, 3)  # "Attestation sur l'Honneur"
        if just_ah:
            st.markdown(f"📎 Statut document : {badge_statut(just_ah.get('status'))}")
            date_ah = fmt_ts(just_ah.get("date"))
            row("Date de signature AH", date_ah, critique=True)
        else:
            st.warning("⚠️ Aucune Attestation sur l'Honneur trouvée dans les justificatifs.")

        col1, col2 = st.columns(2)
        with col1:
            row("Nombre de logements", fd.get("nombreLogements") or fd.get("nb_appartement"), critique=True)
        with col2:
            row("Logements conventionnés", fd.get("nombreLogementsConventionnes"))

        st.caption(
            "👉 Vérifier que le professionnel signataire de la partie C correspond bien au "
            "professionnel déclaré ci-dessus (information non disponible dans le JSON — "
            "à confirmer sur le document)."
        )

        # ═══════════════════════════════════════════
        # INFOS SECONDAIRES (repliées)
        # ═══════════════════════════════════════════
        st.markdown("---")
        with st.expander("ℹ️ Informations complémentaires (volumes, zones, contexte)", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                row("Volume classique (kWhc)", fd.get("volumeClassique"))
                row("Volume précarité (kWhc)", fd.get("volumePrecarite"))
                row("Zone climatique", fd.get("zoneClimatique"))
            with col2:
                row("Zone géographique", fd.get("zoneGeographique"))
                row("Énergie chauffage", fd.get("energieChauffage"))
                row("Département", fd.get("departement"))


# ─────────────────────────────────────────────
# BLOC LOT DE CONTRÔLE
# ─────────────────────────────────────────────

def bloc_lot_controle(data):
    dlc = data.get("dossierLotsControle", []) or []
    if not dlc:
        return

    st.markdown("## 🔍 Lot(s) de contrôle")
    for item in dlc:
        lc = item.get("lotControle", {}) or {}
        statut_item = item.get("statut", "")
        conclusion = lc.get("conclusion", "")
        org = (lc.get("organismeControle") or {}).get("raisonSociale", "—")
        fiche_lc = lc.get("referenceFiche", "—")

        with st.expander(f"{fiche_lc} — Lot {lc.get('nom', '—')} | Organisme : {org}", expanded=False):
            col1, col2, col3 = st.columns(3)
            col1.markdown(f"**Statut dossier dans lot**\n\n{badge_statut(statut_item)}")
            col2.markdown(f"**Conclusion lot**\n\n{badge_statut(conclusion)}")
            col3.markdown(f"**Statut lot**\n\n{badge_statut(lc.get('statut', ''))}")
            nc = item.get("nonConformites")
            if nc:
                st.warning(f"🔴 Non-conformité : {nc}")


# ─────────────────────────────────────────────
# CHAMPS NUMÉRIQUES À TOTALISER PAR FICHE (pour cohérence multi-sites)
# ─────────────────────────────────────────────

CHAMPS_TOTAL = {
    "BAR-EN-101": [("surface_isolant", "Surface isolée totale", "m²")],
    "BAR-EN-102": [("surface_isolant", "Surface isolée totale", "m²")],
    "BAR-EN-103": [("surface", "Surface totale", "m²")],
    "BAR-EN-104": [("surface_fenetres", "Surface fenêtres totale", "m²"), ("Quantité", "Quantité totale", "")],
    "BAR-EN-105": [("surface", "Surface isolée totale", "m²")],
    "BAR-TH-106": [("nb_equipements", "Nb équipements total", "")],
    "BAR-TH-127": [("nb_appartement", "Nb appartements total", "")],
    "BAR-TH-158": [("nb_equipements", "Nb émetteurs total", "")],
}


def cle_groupe_facture(lot):
    """Clé identifiant un groupe 'même facture' : SIRET pro identique (les dates d'engagement/
    réalisation sont au niveau dossier donc déjà communes à tous les lots)."""
    prof = lot.get("professionnel") or {}
    return prof.get("siret")


def champs_fiche(ref_upper):
    """Retourne la liste (clé, label) des champs techniques définis pour cette fiche dans REGLES."""
    for k, regles in REGLES.items():
        if k in ref_upper:
            return [(cle, label) for cle, label, unite, critique in regles]
    return None


# Champs pour lesquels un total a un sens (surfaces, quantités, nb d'équipements...).
# Tout ce qui n'est pas listé ici (marque, référence, R, Uw, ETAS...) n'est jamais totalisé,
# même si la valeur est numérique, car sommer une résistance thermique ou un ETAS n'a pas de sens.
CHAMPS_CUMULABLES = {
    "surface", "surface_isolant", "surface_fenetres", "Quantité",
    "nb_equipements", "nb_appartement", "nombreLogements", "Nb logements",
}


def afficher_groupe_fiche(fiche_ref, lots_sites, data):
    """Affiche un groupe de lots pour une même fiche BAR. Si tous les lots partagent le même
    SIRET professionnel (= probablement la même facture), affiche un tableau compact avec une
    ligne par site + total (pour les colonnes numériques), et les vérifications communes une
    seule fois. Sinon, retombe sur l'affichage détaillé lot par lot."""
    ref_upper = fiche_ref.upper()
    lots_seuls = [ls[0] for ls in lots_sites]

    sirets = {cle_groupe_facture(l) for l in lots_seuls}
    meme_facture = len(lots_sites) > 1 and len(sirets) == 1 and None not in sirets

    if not meme_facture:
        # Comportement précédent : un expander complet par site
        if len(lots_sites) > 1:
            st.markdown(f"### 📄 {fiche_ref} — {len(lots_sites)} site(s), professionnels différents")
        else:
            st.markdown(f"### 📄 {fiche_ref}")
        for i, (lot, adresse_site) in enumerate(lots_sites, start=1):
            afficher_lot(lot, i, data, adresse_site=adresse_site)
        return

    # ── Cas "même facture" : tableau compact ──
    import pandas as pd

    champs = champs_fiche(ref_upper)

    lot0 = lots_seuls[0]
    fd0 = lot0.get("formData", {}) or {}
    prof0 = lot0.get("professionnel") or {}
    date_eng = fmt_ts(data.get("dateEngagementReelle"))
    date_real = fmt_ts(data.get("dateRealisationReelle"))

    st.markdown(f"### 📄 {fiche_ref} — {len(lots_sites)} sites, même facture")
    col1, col2, col3 = st.columns(3)
    col1.markdown(f"**Date engagement**\n\n{date_eng or '⚠️ Manquante'}")
    col2.markdown(f"**Date réalisation**\n\n{date_real or '⚠️ Manquante'}")
    col3.markdown(f"**SIRET professionnel**\n\n{prof0.get('siret', '⚠️ Manquant')} ({prof0.get('raisonSociale', '—')})")

    rows = []
    for lot, adresse_site in lots_sites:
        fd = lot.get("formData", {}) or {}
        r = {"Site": adresse_site}
        if champs:
            for cle, label in champs:
                v = fd.get(cle)
                if v is None and cle == "resistance_thermique":
                    v = fd.get("resistance_thermique_non_exported")
                r[label] = v
        r["Nb logements"] = fd.get("nombreLogements") or fd.get("nb_appartement")
        rows.append(r)

    df = pd.DataFrame(rows)

    # Construit la correspondance label -> clé d'origine pour savoir quelles colonnes totaliser
    label_to_cle = {label: cle for cle, label in (champs or [])}
    label_to_cle["Nb logements"] = "nombreLogements"

    # Ligne total : uniquement pour les colonnes dont le champ d'origine est cumulable
    # (surface, quantité, nb logements...). Les caractéristiques techniques (marque, référence,
    # résistance thermique, ETAS...) ne sont jamais sommées, même si numériques.
    total_row = {"Site": "**TOTAL**"}
    for col in df.columns:
        if col == "Site":
            continue
        cle_origine = label_to_cle.get(col, col)
        if cle_origine in CHAMPS_CUMULABLES or col in CHAMPS_CUMULABLES:
            try:
                total_row[col] = pd.to_numeric(df[col]).sum()
            except (ValueError, TypeError):
                total_row[col] = ""
        else:
            total_row[col] = ""
    df_total = pd.concat([df, pd.DataFrame([total_row])], ignore_index=True)

    st.dataframe(df_total, use_container_width=True, hide_index=True)
    st.caption("👉 Comparer le(s) total(aux) ci-dessus avec le volume facturé.")

    # Alerte visible si un site du groupe a une non-conformité (la colonne Statut a été retirée du tableau)
    sites_nc = [adresse_site for lot, adresse_site in lots_sites
                if lot.get("nonConformiteUn") or lot.get("nonConformiteDeux")]
    if sites_nc:
        st.error(f"🔴 Non-conformité signalée sur : {', '.join(sites_nc)} — voir détail ci-dessous.")

    # ── Vérifications communes (une seule fois pour le groupe) ──
    with st.expander("🪪 RGE & professionnel (commun à tous les sites)", expanded=True):
        prof_global = lot0.get("professionnel") or {}
        rge_global = lot0.get("professionnelTitulaireSigneQualite") or {}
        sous_traitant = lot0.get("professionnelSousTraitant")

        col1, col2 = st.columns(2)
        with col1:
            row("Raison sociale professionnel", prof_global.get("raisonSociale"), critique=True)
            row("SIRET professionnel", prof_global.get("siret"), critique=True)
            if sous_traitant:
                row("Sous-traitant", sous_traitant.get("raisonSociale"))
        with col2:
            rge_requis = any(k in ref_upper for k in FICHES_RGE_OBLIGATOIRE)
            if rge_requis:
                row("Raison sociale RGE", rge_global.get("raisonSociale"), critique=True)
                row("SIRET RGE", rge_global.get("siret"), critique=True)
            else:
                st.caption("RGE non obligatoire pour cette fiche — à confirmer.")

    with st.expander("📎 Justificatifs (communs à tous les sites)", expanded=True):
        justs = lot0.get("justificatifs") or []
        for j in justs:
            tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
            facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
            mention = " *(facultatif)*" if facultatif else ""
            date_j = fmt_ts(j.get("date"))
            date_str = f" — {date_j}" if date_j else ""
            st.markdown(f"- {badge_statut(j.get('status'))} **{tj}**{mention}{date_str}")
        just_ah = get_just(lot0, 3)
        if just_ah:
            row("Date de signature AH", fmt_ts(just_ah.get("date")), critique=True)
        st.caption(
            "👉 Vérifier que le professionnel signataire de la partie C correspond bien au "
            "professionnel déclaré (info non disponible dans le JSON)."
        )

    with st.expander("ℹ️ Détails techniques par site", expanded=False):
        for lot, adresse_site in lots_sites:
            st.markdown(f"**{adresse_site}**")
            fd = lot.get("formData", {}) or {}
            nc1, nc2 = lot.get("nonConformiteUn"), lot.get("nonConformiteDeux")
            if nc1:
                st.error(f"NC1 : {nc1}")
            if nc2:
                st.error(f"NC2 : {nc2}")
            if champs:
                for cle, label in champs:
                    row(label, fd.get(cle))
            st.markdown("---")



st.title("🔎 Supervision — Aide à la vérification CEE")
st.caption("Importez le JSON Odicee d'un dossier pour guider la vérification réglementaire du 2e regard.")

st.sidebar.header("🔗 Raccourci Odicee")
num_dossier = st.sidebar.text_input("Numéro de dossier (ex: T123272)")
if num_dossier:
    num_clean = re.sub(r"\D", "", num_dossier)
    if num_clean:
        lien = f"https://odicee.edf.fr/api/dossiers/{num_clean}"
        st.sidebar.markdown(f"**[➡️ JSON dossier {num_clean}]({lien})**")
        st.sidebar.caption("Ctrl+S sur la page pour sauvegarder, puis importez ici.")

uploaded = st.file_uploader("Choisissez un fichier JSON Odicee", type="json")

if uploaded:
    try:
        data = json.load(uploaded)
        dossier_id = data.get("id", "")
        nom_dossier = data.get("nom", "")
        st.success(f"✅ Dossier **{dossier_id}** — {nom_dossier}")

        sites = data.get("sites", []) or []

        # Regrouper tous les lots BAR de tous les sites, par référence de fiche
        lots_par_fiche = {}
        for site in sites:
            num_site = site.get("numero", "")
            voie = site.get("nomVoie", "")
            cp = site.get("codePostal", "")
            ville = site.get("ville", "")
            adresse_site = " ".join(filter(None, [str(num_site), voie, cp, ville])) or "Site sans adresse"

            for lot in site.get("lotsTravaux", []) or []:
                fd = lot.get("formData", {}) or {}
                ref = str(fd.get("reference", "")).upper()
                if "BAR" not in ref:
                    continue
                lots_par_fiche.setdefault(fd.get("reference", ""), []).append((lot, adresse_site))

        lot_global_index = 1
        for fiche_ref, lots_sites in lots_par_fiche.items():
            with st.container(border=True):
                afficher_groupe_fiche(fiche_ref, lots_sites, data)

        st.markdown("---")
        bloc_lot_controle(data)

    except Exception as e:
        st.error(f"Erreur lors de la lecture du fichier : {e}")
        import traceback
        st.code(traceback.format_exc())