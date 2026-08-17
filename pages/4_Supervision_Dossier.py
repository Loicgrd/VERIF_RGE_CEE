import streamlit as st
import json
import re
from datetime import datetime
from urllib.parse import quote
import pytz

from core.utils_supervision import (
    REGLES, SEUILS, FICHES_RGE_OBLIGATOIRE, CHAMPS_CUMULABLES,
    seuil_r_en101, decoder_valeur, decoder_type_fenetre, champs_en104,
)

st.set_page_config(page_title="Supervision Dossier CEE", layout="wide")

PARIS_TZ = pytz.timezone("Europe/Paris")


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def fmt_ts(ts):
    if ts:
        return datetime.fromtimestamp(ts / 1000.0, PARIS_TZ).strftime("%d/%m/%Y")
    return None


def _decouper_adresse(adresse_complete):
    """Sépare le bloc de numéros de rue (ex: "16 et 18", "10, 12, 14") du reste de l'adresse
    (rue + CP + ville). Retourne (liste_numeros, reste_adresse). Si aucun numéro n'est trouvé en
    tête de chaîne, liste_numeros est vide et reste_adresse est l'adresse complète."""
    m = re.match(r"^((?:\d+\w*\s*(?:,|/|et)?\s*)+)(.*)$", adresse_complete)
    if not m:
        return [], adresse_complete
    bloc_numeros, reste = m.group(1), m.group(2).strip()
    numeros = re.findall(r"\d+\w*", bloc_numeros)
    return numeros, reste


def maps_url_pour(numero, reste_adresse):
    """Construit une URL Google Maps pour un numéro de rue donné + le reste de l'adresse."""
    adresse = f"{numero} {reste_adresse}".strip() if numero else reste_adresse
    return "https://www.google.com/maps/search/?api=1&query=" + quote(adresse)


def maps_url_adresse(adresse_complete):
    """URL Google Maps pointant sur le premier numéro de l'adresse (utilisé quand un seul lien
    suffit, ex: cas à un seul numéro). Pour les adresses à numéros multiples, préférer
    _decouper_adresse() + maps_url_pour() pour générer un lien par numéro."""
    numeros, reste = _decouper_adresse(adresse_complete)
    premier = numeros[0] if numeros else None
    return maps_url_pour(premier, reste)


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


STATUTS_OK = {"D_CONTROLE_OK", "CONTROLE_OK", "CONTROLE_OK_CONTACT"}


def just_warning(just, label, obligatoire=True):
    """Affiche un simple avertissement si le justificatif n'est pas dans un statut "vert",
    au lieu d'afficher systématiquement le badge de statut (trop de bruit visuel en
    vérification — D_CONTROLE_OK partout n'apporte rien)."""
    if just is None:
        if obligatoire:
            st.warning(f"⚠️ {label} : aucun document trouvé.")
        return
    statut = just.get("status", "")
    if statut not in STATUTS_OK:
        st.warning(f"⚠️ {label} : statut {statut}")


def checkbox_etape(dossier_id, uid_lot_ou_groupe, etape, label="✅ Étape vérifiée"):
    """Checkbox de validation pour une étape de vérification d'un lot. L'état est conservé
    dans st.session_state pour persister entre les interactions (cocher une case ailleurs
    ne doit pas réinitialiser celle-ci)."""
    key = f"verif_{dossier_id}_{uid_lot_ou_groupe}_{etape}"
    return st.checkbox(label, key=key)


def lot_uid(lot, fiche_ref, adresse_site):
    """Identifiant stable d'un lot pour les clés de session_state (basé sur l'id du lot
    si disponible, sinon sur fiche + adresse)."""
    return lot.get("id") or f"{fiche_ref}_{adresse_site}"


# ─────────────────────────────────────────────
# VÉRIFICATION DES SEUILS (REGLES, SEUILS, FICHES_RGE_OBLIGATOIRE importés de reglages_fiches.py)
# ─────────────────────────────────────────────

def verif_seuil(fiche_ref, cle, valeur):
    ref = fiche_ref.upper()

    # Cas particulier BAR-EN-101 : seuil R dépend de type_pose (combles perdus vs rampant)
    if "BAR-EN-101" in ref and cle == "resistance_thermique":
        # On a besoin de type_pose mais cette fonction ne reçoit que (fiche_ref, cle, valeur).
        # Le seuil EN-101 est donc vérifié séparément dans afficher_lot via seuil_r_en101().
        return None, None

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



# ─────────────────────────────────────────────
# AFFICHAGE D'UN LOT — PARCOURS DE VÉRIFICATION
# ─────────────────────────────────────────────

def afficher_lot(lot, lot_index, data, adresse_site=None):
    fd = lot.get("formData", {}) or {}
    fiche_ref = fd.get("reference", "")
    ref_upper = fiche_ref.upper()
    dossier_id = data.get("id", "")
    uid = lot_uid(lot, fiche_ref, adresse_site or "")

    adresse_fd = " ".join(filter(None, [
        fd.get("adresse_travaux", ""),
        fd.get("code_postal", ""),
        fd.get("ville", "")
    ])) or "Non renseignée"

    statut_lot = lot.get("statut", "")
    nc1 = lot.get("nonConformiteUn")
    nc2 = lot.get("nonConformiteDeux")

    etapes = ["engagement_realisation", "technique", "rge", "ah"]
    nb_ok = sum(
        st.session_state.get(f"verif_{dossier_id}_{uid}_{e}", False) for e in etapes
    )
    lot_complet = nb_ok == len(etapes)
    prefixe = "✅" if lot_complet else f"⬜ {nb_ok}/4"

    label_exp = f"{prefixe} — Lot {lot_index} — {adresse_site or adresse_fd}"
    with st.expander(label_exp, expanded=not lot_complet):

        cols = st.columns([1, 1, 2])
        cols[0].markdown(f"**Statut**\n\n{badge_statut(statut_lot)}")
        if nc1:
            cols[1].error(f"NC1 : {nc1}")
        if nc2:
            cols[2].error(f"NC2 : {nc2}")

        st.markdown("---")

        # ═══════════════════════════════════════════
        # ÉTAPE 1 — ENGAGEMENT & RÉALISATION (fusionnées)
        # ═══════════════════════════════════════════
        st.markdown("#### 1️⃣ Engagement & Réalisation")
        ok_etape1 = checkbox_etape(dossier_id, uid, "engagement_realisation")
        col1, col2 = st.columns(2)
        with col1:
            date_eng = fmt_ts(data.get("dateEngagementReelle"))
            row("Date d'engagement", date_eng, critique=True)
            date_real = fmt_ts(data.get("dateRealisationReelle"))
            row("Date de réalisation", date_real, critique=True)
        with col2:
            b = data.get("beneficiaire", {}) or {}
            row("Bailleur", b.get("raisonSociale"), critique=True)
            row("Adresse des travaux", adresse_fd, critique=True)

        just_engagement = get_just(lot, 1)  # "Preuve d'engagement"
        just_warning(just_engagement, "Preuve d'engagement")
        just_real = get_just(lot, 2)  # "Preuve de réalisation"
        just_warning(just_real, "Preuve de réalisation")

        st.caption("👉 Vérifier la cohérence du document avec l'engagement (adresse, fiche, bailleur) avant de poursuivre.")

        # ═══════════════════════════════════════════
        # ÉTAPE 2 — ÉLÉMENTS TECHNIQUES
        # ═══════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 2️⃣ Données techniques")

        key_tout = f"verif_{dossier_id}_{uid}_technique_tout"
        tout_valide = st.checkbox("✅ Tout valider d'un coup", key=key_tout)

        regles_fiche = None
        if "BAR-EN-104" in ref_upper:
            regles_fiche = champs_en104(data.get("dateEngagementReelle"))
        else:
            for k in REGLES:
                if k in ref_upper:
                    regles_fiche = REGLES[k]
                    break

        nb_champs_technique = len(regles_fiche) if regles_fiche else 0

        if regles_fiche:
            # BAR-EN-101 : seuil R dépend du type de pose (combles perdus / rampant)
            type_pose_val = fd.get("type_pose") if "BAR-EN-101" in ref_upper else None
            seuil_en101 = seuil_r_en101(type_pose_val) if "BAR-EN-101" in ref_upper else None

            for idx_champ, (cle, label, unite, critique) in enumerate(regles_fiche):
                valeur = fd.get(cle)
                if valeur is None and cle == "resistance_thermique":
                    valeur = fd.get("resistance_thermique_non_exported")

                ok_seuil, msg_seuil = verif_seuil(fiche_ref, cle, valeur)

                # Cas spécial EN-101 : seuil conditionnel au type de pose
                if "BAR-EN-101" in ref_upper and cle == "resistance_thermique" and seuil_en101 is not None:
                    try:
                        v_num = float(valeur)
                        if v_num < seuil_en101:
                            ok_seuil, msg_seuil = False, f"⚠️ {v_num} < seuil min ({seuil_en101}, selon type de pose)"
                        else:
                            ok_seuil, msg_seuil = True, None
                    except (TypeError, ValueError):
                        pass

                valeur_affichee = decoder_valeur(fiche_ref, cle, valeur)
                if "BAR-EN-104" in ref_upper and cle == "type_fenetre":
                    valeur_affichee = decoder_type_fenetre(valeur, data.get("dateEngagementReelle"))

                if alerte(valeur, critique=critique):
                    contenu = f"<span style='color:#c0392b;font-weight:600'>⚠️ Manquant / vide</span>"
                elif ok_seuil is False:
                    contenu = f"<span style='color:#e67e22;font-weight:600'>{valeur_affichee} {unite} — {msg_seuil}</span>"
                else:
                    contenu = f"<span style='font-weight:500'>{valeur_affichee}{' ' + unite if unite else ''}</span>"

                col_chk, col_row = st.columns([0.06, 0.94])
                with col_chk:
                    key_ligne = f"verif_{dossier_id}_{uid}_technique_{idx_champ}"
                    st.checkbox(
                        "valider", key=key_ligne, value=tout_valide,
                        label_visibility="collapsed",
                    )
                with col_row:
                    st.markdown(
                        f"<div style='display:flex;gap:12px;padding:4px 0;border-bottom:1px solid #f0f0f0'>"
                        f"<span style='min-width:260px;color:#888;font-size:.9rem'>{label}</span>"
                        f"{contenu}</div>",
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
                            st.markdown("**Émetteurs électriques :**")
                            df_eq = pd.DataFrame(rows)
                            st.dataframe(df_eq, use_container_width=True, hide_index=True)
                            try:
                                total_qte = pd.to_numeric(df_eq["Quantité"]).sum()
                                st.caption(f"Quantité totale : {total_qte:g}")
                            except (ValueError, TypeError):
                                pass
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

        # Étape technique considérée validée si "tout valider" est coché, ou si toutes les
        # lignes individuelles le sont (fiches sans REGLES dédiées : on retombe sur "tout valider").
        if nb_champs_technique > 0:
            technique_ok = all(
                st.session_state.get(f"verif_{dossier_id}_{uid}_technique_{i}", False)
                for i in range(nb_champs_technique)
            )
        else:
            technique_ok = tout_valide
        st.session_state[f"verif_{dossier_id}_{uid}_technique"] = technique_ok

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
        ok_etape3 = checkbox_etape(dossier_id, uid, "rge")

        rge_requis = any(k in ref_upper for k in FICHES_RGE_OBLIGATOIRE)
        rge_qualif = lot.get("professionnelTitulaireSigneQualite") or {}
        sous_traitant_rge = lot.get("professionnelSousTraitant") or {}

        # Le RGE qualifié peut être renseigné soit dans professionnelTitulaireSigneQualite,
        # soit assuré par le sous-traitant (professionnelSousTraitant) selon les fiches.
        if rge_qualif.get("siret"):
            rge = rge_qualif
            source_rge = "Professionnel titulaire du signe de qualité"
        elif sous_traitant_rge.get("siret"):
            rge = sous_traitant_rge
            source_rge = "Sous-traitant"
        else:
            rge = {}
            source_rge = None

        if rge_requis:
            col1, col2 = st.columns(2)
            with col1:
                row("Raison sociale RGE", rge.get("raisonSociale"), critique=True)
            with col2:
                row("SIRET RGE", rge.get("siret"), critique=True)
            if source_rge:
                st.caption(f"Source : {source_rge}")
            just_qualif = get_just(lot, 6)  # "Qualification ou certification"
            just_warning(just_qualif, "Justificatif de qualification RGE")
        else:
            st.caption("Cette fiche ne nécessite pas obligatoirement de RGE — à confirmer selon les conditions de la fiche.")

        # Signataire de la partie C (peut différer du professionnel principal)
        signataire_c = lot.get("professionnelTitulaire") or prof
        if signataire_c.get("siret") and signataire_c.get("siret") != prof.get("siret"):
            row("Signataire partie C (différent du professionnel principal)", signataire_c.get("raisonSociale"), critique=True)

        IDS_DEJA_TRAITES = {1, 2, 3, 6, 124}  # 124 = "Autres Justificatifs..." : rare, non bloquant, pas de warning
        autres_justs = [j for j in (lot.get("justificatifs") or [])
                         if (j.get("typeJustificatif") or {}).get("id") not in IDS_DEJA_TRAITES]
        for j in autres_justs:
            tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
            facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
            just_warning(j, tj, obligatoire=not facultatif)

        # ═══════════════════════════════════════════
        # ÉTAPE 4 — ATTESTATION SUR L'HONNEUR
        # ═══════════════════════════════════════════
        st.markdown("---")
        st.markdown("#### 4️⃣ Attestation sur l'Honneur")
        ok_etape4 = checkbox_etape(dossier_id, uid, "ah")

        just_ah = get_just(lot, 3)  # "Attestation sur l'Honneur"
        just_warning(just_ah, "Attestation sur l'Honneur")
        if just_ah:
            date_ah = fmt_ts(just_ah.get("date"))
            row("Date de signature AH", date_ah, critique=True)

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

        with st.expander("📎 Détail de tous les justificatifs (statuts complets)", expanded=False):
            justs_tous = lot.get("justificatifs") or []
            if justs_tous:
                for j in justs_tous:
                    tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
                    facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
                    mention = " *(facultatif)*" if facultatif else ""
                    date_j = fmt_ts(j.get("date"))
                    date_str = f" — {date_j}" if date_j else ""
                    st.markdown(f"- {badge_statut(j.get('status'))} **{tj}**{mention}{date_str}")
            else:
                st.caption("Aucun justificatif dans ce lot.")


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


def champs_fiche(ref_upper, date_engagement_ts=None):
    """Retourne la liste (clé, label) des champs techniques définis pour cette fiche.
    Cas spécial BAR-EN-104 : les clés dépendent de la date d'engagement (changement de version
    du logiciel Odicee), voir champs_en104()."""
    if "BAR-EN-104" in ref_upper:
        return [(cle, label) for cle, label, unite, critique in champs_en104(date_engagement_ts)]
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
    # Mode tableau uniforme dès qu'on a un SIRET professionnel valide et un seul SIRET
    # (que ce soit 1 site ou plusieurs) — l'affichage reste cohérent quel que soit le nombre de sites.
    meme_facture = len(sirets) == 1 and None not in sirets

    if not meme_facture:
        # Repli : professionnels différents sur les sites d'une même fiche -> détail par lot
        if len(lots_sites) > 1:
            st.markdown(f"### 📄 {fiche_ref} — {len(lots_sites)} site(s), professionnels différents")
        else:
            st.markdown(f"### 📄 {fiche_ref}")
        for i, (lot, adresse_site) in enumerate(lots_sites, start=1):
            afficher_lot(lot, i, data, adresse_site=adresse_site)
        return

    # ── Cas "même facture" : tableau compact ──
    import pandas as pd

    champs = champs_fiche(ref_upper, data.get("dateEngagementReelle"))

    lot0 = lots_seuls[0]
    fd0 = lot0.get("formData", {}) or {}
    prof0 = lot0.get("professionnel") or {}
    date_eng = fmt_ts(data.get("dateEngagementReelle"))
    date_real = fmt_ts(data.get("dateRealisationReelle"))

    dossier_id = data.get("id", "")
    groupe_uid = f"GRP_{fiche_ref}_{prof0.get('siret', '')}"
    etapes = ["engagement_realisation", "technique", "rge", "ah"]
    nb_ok_grp = sum(
        st.session_state.get(f"verif_{dossier_id}_{groupe_uid}_{e}", False) for e in etapes
    )
    prefixe_grp = "✅" if nb_ok_grp == 4 else f"⬜ {nb_ok_grp}/4"

    nb_sites_txt = f"{len(lots_sites)} site(s)"
    st.markdown(f"### {prefixe_grp} 📄 {fiche_ref} — {nb_sites_txt}")
    col1, col2, col3 = st.columns(3)
    col1.markdown(f"**Date engagement**\n\n{date_eng or '⚠️ Manquante'}")
    col2.markdown(f"**Date réalisation**\n\n{date_real or '⚠️ Manquante'}")
    col3.markdown(f"**SIRET professionnel**\n\n{prof0.get('siret', '⚠️ Manquant')} ({prof0.get('raisonSociale', '—')})")
    checkbox_etape(dossier_id, groupe_uid, "engagement_realisation", "✅ Engagement & réalisation vérifiés")

    rows = []
    for lot, adresse_site in lots_sites:
        fd = lot.get("formData", {}) or {}
        maps_url = maps_url_adresse(adresse_site)
        r = {"Site": maps_url}
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
    total_row = {"Site": ""}
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

    # Libellés affichés pour la colonne Site : l'adresse en clair, le lien pointe vers Google Maps.
    # On utilise un Styler plutôt que la regex de LinkColumn, plus fiable avec des adresses
    # contenant espaces/accents (la regex de LinkColumn a des soucis de décodage sur ces caractères).
    adresses_par_ligne = [adresse_site for _, adresse_site in lots_sites] + ["TOTAL"]
    url_to_adresse = {row_val: adresse for row_val, adresse in zip(df_total["Site"], adresses_par_ligne)}

    styled = df_total.style.format({"Site": lambda u: url_to_adresse.get(u, "")})

    st.dataframe(
        styled,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Site": st.column_config.LinkColumn(
                "Site",
                help="Cliquer pour ouvrir l'adresse dans Google Maps",
            )
        },
    )
    st.caption("👉 Comparer le(s) total(aux) ci-dessus avec le volume facturé. Cliquez sur une adresse pour l'ouvrir dans Google Maps.")

    # Pour les sites avec plusieurs numéros de rue (ex: "16 et 18 Rue X"), le lien du tableau ne
    # pointe que sur le premier numéro. On ajoute ici un lien par numéro individuel, plus un lien
    # "rue" pointant sur le dernier numéro, pour vérifier chaque adresse précisément.
    sites_multi_numeros = [
        (adresse_site, *_decouper_adresse(adresse_site))
        for _, adresse_site in lots_sites
    ]
    sites_multi_numeros = [(a, nums, reste) for a, nums, reste in sites_multi_numeros if len(nums) > 1]

    if sites_multi_numeros:
        with st.expander("📍 Adresses à numéros multiples — liens détaillés", expanded=False):
            for adresse_site, numeros, reste in sites_multi_numeros:
                st.markdown(f"**{adresse_site}**")
                liens_numeros = " · ".join(
                    f"[📍 {n}]({maps_url_pour(n, reste)})" for n in numeros
                )
                lien_rue = maps_url_pour(numeros[-1], reste)
                st.markdown(f"{liens_numeros}  —  [🛣️ {reste}]({lien_rue})")

    checkbox_etape(dossier_id, groupe_uid, "technique", "✅ Données techniques vérifiées (tous sites)")



    # Alerte visible si un site du groupe a une non-conformité (la colonne Statut a été retirée du tableau)
    sites_nc = [adresse_site for lot, adresse_site in lots_sites
                if lot.get("nonConformiteUn") or lot.get("nonConformiteDeux")]
    if sites_nc:
        st.error(f"🔴 Non-conformité signalée sur : {', '.join(sites_nc)} — voir détail ci-dessous.")

    # ── Vérifications communes (une seule fois pour le groupe) ──
    with st.expander("🪪 RGE & professionnel (commun à tous les sites)", expanded=True):
        checkbox_etape(dossier_id, groupe_uid, "rge")
        prof_global = lot0.get("professionnel") or {}
        rge_qualif_global = lot0.get("professionnelTitulaireSigneQualite") or {}
        sous_traitant_global = lot0.get("professionnelSousTraitant") or {}

        # Même logique de repli que pour le mode lot par lot : si professionnelTitulaireSigneQualite
        # est vide, le sous-traitant peut être celui qui porte la qualification.
        if rge_qualif_global.get("siret"):
            rge_global = rge_qualif_global
            source_rge_global = "Professionnel titulaire du signe de qualité"
        elif sous_traitant_global.get("siret"):
            rge_global = sous_traitant_global
            source_rge_global = "Sous-traitant"
        else:
            rge_global = {}
            source_rge_global = None

        col1, col2 = st.columns(2)
        with col1:
            row("Raison sociale professionnel", prof_global.get("raisonSociale"), critique=True)
            row("SIRET professionnel", prof_global.get("siret"), critique=True)
            if sous_traitant_global.get("siret"):
                row("Sous-traitant", sous_traitant_global.get("raisonSociale"))
                row("SIRET sous-traitant", sous_traitant_global.get("siret"))
        with col2:
            rge_requis = any(k in ref_upper for k in FICHES_RGE_OBLIGATOIRE)
            if rge_requis:
                row("Raison sociale RGE", rge_global.get("raisonSociale"), critique=True)
                row("SIRET RGE", rge_global.get("siret"), critique=True)
                if source_rge_global:
                    st.caption(f"Source : {source_rge_global}")
            else:
                st.caption("RGE non obligatoire pour cette fiche — à confirmer.")

        signataire_c_global = lot0.get("professionnelTitulaire") or prof_global
        if signataire_c_global.get("siret") and signataire_c_global.get("siret") != prof_global.get("siret"):
            row("Signataire partie C (différent du professionnel principal)", signataire_c_global.get("raisonSociale"), critique=True)

    with st.expander("📎 Justificatifs (communs à tous les sites)", expanded=True):
        checkbox_etape(dossier_id, groupe_uid, "ah", "✅ Attestation sur l'Honneur vérifiée")
        justs = lot0.get("justificatifs") or []
        IDS_CONTEXTE = {1, 2, 124}  # engagement/réalisation déjà couverts ; 124 = rare, pas de warning
        for j in justs:
            if (j.get("typeJustificatif") or {}).get("id") in IDS_CONTEXTE:
                continue
            tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
            facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
            just_warning(j, tj, obligatoire=not facultatif)
        just_ah = get_just(lot0, 3)
        if just_ah:
            row("Date de signature AH", fmt_ts(just_ah.get("date")), critique=True)
        st.caption(
            "👉 Vérifier que le professionnel signataire de la partie C correspond bien au "
            "professionnel déclaré (info non disponible dans le JSON)."
        )

    with st.expander("📎 Détail de tous les justificatifs (statuts complets)", expanded=False):
        if justs:
            for j in justs:
                tj = (j.get("typeJustificatif") or {}).get("libelle", "—")
                facultatif = (j.get("typeJustificatif") or {}).get("facultatif", False)
                mention = " *(facultatif)*" if facultatif else ""
                date_j = fmt_ts(j.get("date"))
                date_str = f" — {date_j}" if date_j else ""
                st.markdown(f"- {badge_statut(j.get('status'))} **{tj}**{mention}{date_str}")
        else:
            st.caption("Aucun justificatif.")

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

        # ── Calcul des UID de vérification pour la barre de progression globale ──
        # (même logique de regroupement "même facture" que afficher_groupe_fiche, dupliquée ici
        # pour pouvoir compter la progression avant l'affichage détaillé)
        verif_uids = []
        for fiche_ref, lots_sites in lots_par_fiche.items():
            lots_seuls = [ls[0] for ls in lots_sites]
            sirets = {cle_groupe_facture(l) for l in lots_seuls}
            meme_facture = len(sirets) == 1 and None not in sirets
            if meme_facture:
                prof0 = lots_seuls[0].get("professionnel") or {}
                verif_uids.append(f"GRP_{fiche_ref}_{prof0.get('siret', '')}")
            else:
                for lot, adresse_site in lots_sites:
                    verif_uids.append(lot_uid(lot, fiche_ref, adresse_site))

        etapes_progress = ["engagement_realisation", "technique", "rge", "ah"]
        total_etapes = len(verif_uids) * len(etapes_progress)
        etapes_cochees = sum(
            1 for u in verif_uids for e in etapes_progress
            if st.session_state.get(f"verif_{dossier_id}_{u}_{e}", False)
        )
        nb_lots_complets = sum(
            1 for u in verif_uids
            if all(st.session_state.get(f"verif_{dossier_id}_{u}_{e}", False) for e in etapes_progress)
        )

        st.markdown(f"#### Progression : {nb_lots_complets}/{len(verif_uids)} lot(s)/groupe(s) entièrement vérifié(s)")
        st.progress(etapes_cochees / total_etapes if total_etapes else 0)
        st.markdown("---")

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
