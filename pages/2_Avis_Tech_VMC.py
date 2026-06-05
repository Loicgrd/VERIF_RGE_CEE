import streamlit as st
import sys
import os

dossier_actuel = os.path.dirname(os.path.abspath(__file__))
dossier_racine = os.path.abspath(os.path.join(dossier_actuel, ".."))
if dossier_racine not in sys.path:
    sys.path.append(dossier_racine)

from core.utils_vmc import PROMPT_VMC, format_debits_to_str, parse_debits_from_str, filter_and_group_atec
from supabase import create_client
import datetime
import re
import pandas as pd
import json
import tempfile
from google import genai
from google.genai import types

st.set_page_config(page_title="Contrôle CEE - VMC", page_icon="🌬️", layout="wide")

# --- CONNEXIONS API ---
@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

@st.cache_resource
def init_gemini():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

supabase = init_supabase()
client_gemini = init_gemini()

if 'prefill_data' not in st.session_state:
    st.session_state['prefill_data'] = {}

@st.cache_data(ttl=600)
def fetch_all_atec():
    reponse = supabase.table("referentiel_vmc").select("*").execute()
    return reponse.data

donnees_atec = fetch_all_atec()

if not donnees_atec:
    st.warning("Aucune donnée trouvée dans la base.")
    st.stop()

# --- FORMATAGE DU NUMERO ---
def parse_numero_complet(texte_complet):
    """Sépare '14.5/17-2273_v6' en ('14.5/17-2273', 'V6') pour la base de données."""
    if not texte_complet:
        return "", "V1"
    if "_" in texte_complet:
        parties = texte_complet.rsplit("_", 1)
        return parties[0].strip(), parties[1].strip().upper()
    return texte_complet.strip(), "V1"


config_colonnes = {
    "nom_modele": st.column_config.TextColumn("📦 Modèle", required=True),
    "type_logement": st.column_config.SelectboxColumn("🏠 Logement", options=["Collectif", "Individuel", "Mixte"]),
    "basse_pression": st.column_config.CheckboxColumn("⬇️ Basse Pression"),
    "double_flux": st.column_config.CheckboxColumn("🔄 Double Flux"),
    "debits_disponibles": st.column_config.TextColumn("💨 Débits"),
    "puissance_hygro_a": st.column_config.TextColumn("⚡ WThC (Hygro A)"),
    "puissance_hygro_b": st.column_config.TextColumn("⚡ WThC (Hygro B)")
}

tab_consult, tab_ajout = st.tabs(["🔍 Consultation & Modification", "➕ Ajouter un Avis"])

# =====================================================================
# ONGLET 1 : CONSULTATION ET MODIFICATION IN-PLACE
# =====================================================================
with tab_consult:
    st.title("🌬️ Référentiel Avis Techniques VMC")

    marques_disponibles = sorted(list(set([doc.get('distributeur', 'Inconnu') for doc in donnees_atec if doc.get('distributeur')])))

    with st.form("formulaire_recherche"):
        st.markdown("### 🔍 Critères de recherche")
        col1, col2, col3 = st.columns(3)
        with col1: filtre_marque = st.selectbox("🏭 Marque / Distributeur", ["Toutes"] + marques_disponibles)
        with col2: filtre_texte = st.text_input("📦 Modèle ou N° d'Avis", "")
        with col3: filtre_date = st.date_input("📅 Date d'engagement", value=None, format="DD/MM/YYYY")
        
        submit_search = st.form_submit_button("🚀 Rechercher", use_container_width=True)

    st.divider()

    if not submit_search and not st.session_state.get('recherche_active', False):
        st.info("👈 Veuillez définir vos critères et cliquer sur **Rechercher** pour afficher les résultats.")
    else:
        st.session_state['recherche_active'] = True
        
        # --- LOGIQUE D'EXTRACTION ET DE GROUPEMENT ROBUSTE ---
        # 1. Trouver les familles (numéros de base) d'avis correspondant aux filtres texte/marque
        bases_retenues = set()
        for doc in donnees_atec:
            num_atec = str(doc.get('numero_atec', ''))
            base_num = num_atec.split('_')[0].strip()
            distributeur = str(doc.get('distributeur', '')).lower()
            titulaire = str(doc.get('titulaire', '')).lower()
            
            match_marque = True
            if filtre_marque != "Toutes":
                match_marque = (filtre_marque.lower() in distributeur) or (filtre_marque.lower() in titulaire)
            
            match_texte = True
            if filtre_texte:
                txt = filtre_texte.lower()
                match_model = any(txt in str(m.get('nom_modele', '')).lower() for m in doc.get('modeles', []) if isinstance(m, dict))
                match_texte = (txt in num_atec.lower()) or (txt in distributeur) or match_model
            
            if match_marque and match_texte:
                bases_retenues.add(base_num)
        
        # 2. Re-sélectionner TOUTES les versions pour ces familles (évite la perte d'historique)
        resultats_filtres = []
        for doc in donnees_atec:
            base_num = str(doc.get('numero_atec', '')).split('_')[0].strip()
            if base_num in bases_retenues:
                if filtre_date:
                    try:
                        deb = datetime.datetime.strptime(doc.get('debut_validite', ''), "%Y-%m-%d").date() if doc.get('debut_validite') else None
                        fin = datetime.datetime.strptime(doc.get('fin_validite', ''), "%Y-%m-%d").date() if doc.get('fin_validite') else None
                        if deb and fin and not (deb <= filtre_date <= fin): continue
                        elif deb and filtre_date < deb: continue
                        elif fin and filtre_date > fin: continue
                    except:
                        pass
                resultats_filtres.append(doc)

        if len(resultats_filtres) == 0:
            st.info("Aucun Avis Technique ne correspond à ces critères.")
        else:
            # 3. Tri ordonné : par numéro de base, puis par indice de révision décroissant
            def get_sort_key(d):
                base = str(d.get('numero_atec', '')).split('_')[0].strip()
                rev_str = str(d.get('indice_revision', 'V1')).upper().replace('V', '').replace('MODIFICATIF', '').strip()
                try: 
                    rev_num = int(rev_str)
                except ValueError: 
                    rev_num = 0
                
                # CORRECTION : On ne trie plus par distributeur en premier !
                # Ainsi, les variations d'orthographe (V.T.I vs VTI) ne séparent plus la famille.
                return (base, -rev_num)

            resultats_finaux = sorted(resultats_filtres, key=get_sort_key)

            # 4. Identification dynamique de la version la plus haute à l'écran
            bases_vues = set()
            for d in resultats_finaux:
                base = str(d.get('numero_atec', '')).split('_')[0].strip()
                if base not in bases_vues:
                    d['_est_version_recente'] = True
                    bases_vues.add(base)
                else:
                    d['_est_version_recente'] = False

            st.caption(f"**{len(resultats_finaux)} résultat(s) trouvé(s)**")
            
            for doc in resultats_finaux:
                revision = doc.get('indice_revision') or 'V1'
                full_atec = f"{doc.get('numero_atec', 'Inconnu')}_{revision}"

                modeles_bruts = doc.get('modeles') or []
                if isinstance(modeles_bruts, list):
                    if filtre_texte and filtre_texte.lower() not in str(doc.get('numero_atec', '')).lower() and filtre_texte.lower() not in str(doc.get('distributeur', '')).lower():
                        modeles_a_afficher = [m for m in modeles_bruts if filtre_texte.lower() in str(m.get('nom_modele', '')).lower()]
                    else: modeles_a_afficher = modeles_bruts
                else: modeles_a_afficher = []

                deb_str = doc.get('debut_validite', 'Inconnue')
                try: deb_str = datetime.datetime.strptime(deb_str, "%Y-%m-%d").date().strftime("%d/%m/%Y")
                except: pass
                try: fin_str = datetime.datetime.strptime(doc.get('fin_validite', ''), "%Y-%m-%d").date().strftime("%d/%m/%Y")
                except: fin_str = "Inconnue"

                # REIFICATION ICI : La version récente reste ouverte, l'historique se ferme de manière isolée
                is_expanded = doc.get('_est_version_recente', False)
                badge = "🟢 Version Récente" if doc.get('_est_version_recente') else "🕰️ Historique"
                
                titre_bandeau = f"🏭 {doc.get('distributeur', doc.get('titulaire', 'Inconnu'))}  |  📄 {full_atec}  |  📅 {deb_str} ➡️ {fin_str}  |  {badge}"

                with st.expander(titre_bandeau, expanded=is_expanded):
                    mode_edition = st.toggle("✏️ Éditer cet Avis", key=f"toggle_{doc['id']}")
                    
                    if not mode_edition:
                        col_ref, col_lien = st.columns([3, 1])
                        with col_ref: st.code(full_atec, language=None)
                        with col_lien:
                            if doc.get('url_batipedia'): st.link_button("📥 Ouvrir PDF", doc['url_batipedia'], use_container_width=True)
                        
                        if modeles_a_afficher:
                            st.markdown("**Modèles éligibles :**")
                            modeles_groupes = {}
                            for m in modeles_a_afficher:
                                nom_brut = m.get('nom_modele', 'Inconnu').strip()
                                match = re.search(r"^(.*?)\s+(\d+(?:\s*[a-zA-Z]+)?)$", nom_brut)
                                if match: nom_base, debit_extrait = match.group(1).strip(), match.group(2).strip()
                                else: nom_base, debit_extrait = nom_brut, None

                                if nom_base not in modeles_groupes:
                                    modeles_groupes[nom_base] = {
                                        'nom_modele': nom_base, 'type_logement': m.get('type_logement', 'N/A'), 
                                        'basse_pression': False, 'double_flux': False, 'debits': set(),
                                        'pw_a': set(), 'pw_b': set()
                                    }
                                
                                if m.get('basse_pression'): modeles_groupes[nom_base]['basse_pression'] = True
                                if m.get('double_flux'): modeles_groupes[nom_base]['double_flux'] = True
                                if debit_extrait: modeles_groupes[nom_base]['debits'].add(debit_extrait)
                                if m.get('debits_disponibles'): modeles_groupes[nom_base]['debits'].update(m.get('debits_disponibles'))
                                if m.get('puissance_hygro_a'): modeles_groupes[nom_base]['pw_a'].add(str(m['puissance_hygro_a']))
                                if m.get('puissance_hygro_b'): modeles_groupes[nom_base]['pw_b'].add(str(m['puissance_hygro_b']))

                            lignes_modeles = []
                            for m in modeles_groupes.values():
                                bp = " | BP: ✅" if m['basse_pression'] else ""
                                df = " | DF: 🔄" if m['double_flux'] else ""
                                type_log = f" ({m['type_logement']})"
                                def tri_numerique(val):
                                    nombres = re.findall(r'\d+', val)
                                    return int(nombres[0]) if nombres else 0
                                liste_debits = sorted(list(m['debits']), key=tri_numerique)
                                debits_str = f" ({', '.join(liste_debits)})" if liste_debits else ""
                                pw_a_str = f" | W-Th-C (A): {', '.join(m['pw_a'])}" if m['pw_a'] else ""
                                pw_b_str = f" | W-Th-C (B): {', '.join(m['pw_b'])}" if m['pw_b'] else ""
                                lignes_modeles.append(f"- **{m['nom_modele']}**{debits_str} {type_log}{bp}{df}{pw_a_str}{pw_b_str}")
                            
                            st.markdown("\n".join(lignes_modeles))
                    
                    else:
                        st.info("Vous modifiez actuellement cet Avis Technique.")
                        with st.form(f"form_edit_{doc['id']}"):
                            c1, c2 = st.columns(2)
                            with c1:
                                mod_full_num = st.text_input("Numéro d'Avis complet (ex: 14.5/17-2273_V2)", value=full_atec)
                                mod_tit = st.text_input("Titulaire", value=doc.get('titulaire', ''))
                            with c2:
                                mod_dist = st.text_input("Distributeur", value=doc.get('distributeur', ''))
                                try: val_deb = datetime.datetime.strptime(doc.get('debut_validite', ''), "%Y-%m-%d").date()
                                except: val_deb = None
                                try: val_fin = datetime.datetime.strptime(doc.get('fin_validite', ''), "%Y-%m-%d").date()
                                except: val_fin = None
                                mod_deb = st.date_input("Début de validité", value=val_deb, format="DD/MM/YYYY")
                                mod_fin = st.date_input("Fin de validité", value=val_fin, format="DD/MM/YYYY")
                                
                            mod_url = st.text_input("Lien URL Batipedia", value=doc.get('url_batipedia', ''))
                            
                            st.markdown("**Modèles associés**")
                            lignes_df = []
                            for m in doc.get('modeles', []):
                                log_db = m.get('type_logement', 'Collectif')
                                if log_db not in ["Collectif", "Individuel", "Mixte"]: log_db = "Collectif"
                                lignes_df.append({
                                    "nom_modele": m.get('nom_modele', ''), "type_logement": log_db, 
                                    "basse_pression": bool(m.get('basse_pression', False)), "double_flux": bool(m.get('double_flux', False)),
                                    "debits_disponibles": format_debits_to_str(m.get('debits_disponibles', [])),
                                    "puissance_hygro_a": str(m.get('puissance_hygro_a', '') or ''), "puissance_hygro_b": str(m.get('puissance_hygro_b', '') or '')
                                })
                            
                            if not lignes_df: lignes_df.append({"nom_modele": "", "type_logement": "Collectif", "basse_pression": False, "double_flux": False, "debits_disponibles": "", "puissance_hygro_a": "", "puissance_hygro_b": ""})
                                
                            df_edit = pd.DataFrame(lignes_df)
                            edited_df_mod = st.data_editor(df_edit, num_rows="dynamic", column_config=config_colonnes, hide_index=True, use_container_width=True, key=f"grid_{doc['id']}")

                            if st.form_submit_button("💾 Sauvegarder les modifications", type="primary"):
                                mod_num, mod_rev = parse_numero_complet(mod_full_num)
                                
                                modeles_json_mod = []
                                for _, row in edited_df_mod.iterrows():
                                    if row['nom_modele'].strip():
                                        modeles_json_mod.append({
                                            "nom_modele": row['nom_modele'], "type_logement": row['type_logement'], 
                                            "basse_pression": bool(row['basse_pression']), "double_flux": bool(row['double_flux']),
                                            "debits_disponibles": parse_debits_from_str(row['debits_disponibles']),
                                            "puissance_hygro_a": str(row['puissance_hygro_a']).strip() if row['puissance_hygro_a'] else None,
                                            "puissance_hygro_b": str(row['puissance_hygro_b']).strip() if row['puissance_hygro_b'] else None
                                        })
                                
                                doc_update = {
                                    "numero_atec": mod_num, "indice_revision": mod_rev, "titulaire": mod_tit, "distributeur": mod_dist,
                                    "debut_validite": mod_deb.strftime("%Y-%m-%d") if mod_deb else None, "fin_validite": mod_fin.strftime("%Y-%m-%d") if mod_fin else None,
                                    "url_batipedia": mod_url, "modeles": modeles_json_mod
                                }
                                
                                supabase.table("referentiel_vmc").update(doc_update).eq("id", doc['id']).execute()
                                st.success("Modifications sauvegardées avec succès !")
                                fetch_all_atec.clear()
                                st.rerun()

# =====================================================================
# ONGLET 2 : AJOUTER UN NOUVEL AVIS MANUELLEMENT (AVEC IA)
# =====================================================================
with tab_ajout:
    st.header("➕ Ajouter un nouvel Avis Technique")
    st.info("Importez le PDF de l'Avis Technique. Gemini va le lire et pré-remplir tous les champs ci-dessous pour vous !")
    
    fichier_pdf = st.file_uploader("Glissez le PDF ici", type=["pdf"])
    
    if fichier_pdf:
        if st.button("✨ Analyser et Pré-remplir", type="primary", use_container_width=True):
            with st.spinner("Analyse du document en cours (environ 10 secondes)..."):
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(fichier_pdf.getvalue())
                        tmp_path = tmp_file.name

                    fichier_upload = client_gemini.files.upload(file=tmp_path)
                    
                    try:
                        # TENTATIVE 1 : On essaie avec Gemini 1.5 Flash (Le plus performant, mais limité)
                        reponse_ia = client_gemini.models.generate_content(
                            model='gemini-3.5-flash', 
                            contents=[fichier_upload, PROMPT_VMC], # Ou prompt_hybride si tu as gardé Python
                            config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                        )
                        
                    except Exception as e:
                        # Si l'erreur contient "429" (Too Many Requests) ou "quota"
                        if "429" in str(e) or "quota" in str(e).lower():
                            # On avertit l'utilisateur sans bloquer l'application
                            st.warning("⚠️ Quota journalier du modèle principal atteint. Basculement automatique sur la version Lite...")
                            
                            # TENTATIVE 2 : On bascule sur Flash Lite (Flash-8b)
                            reponse_ia = client_gemini.models.generate_content(
                                model='gemini-3.1-flash-lite', 
                                contents=[fichier_upload, PROMPT_VMC],
                                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                            )
                        else:
                            # Si c'est une autre erreur (ex: fichier corrompu, problème réseau), on l'affiche normalement
                            raise e
                    
                    client_gemini.files.delete(name=fichier_upload.name)
                    os.remove(tmp_path)
                    
                    raw_text = reponse_ia.text.replace("```json", "").replace("```", "").strip()
                    if "{" in raw_text and "}" in raw_text:
                        raw_text = raw_text[raw_text.find("{"):raw_text.rfind("}") + 1]
                    
                    donnees_extraites = json.loads(raw_text)
                    
                    donnees_extraites = json.loads(raw_text)
                    
                    # --- NOUVEAU : FILTRE POST-IA (NETTOYAGE DES FAUX MODÈLES) ---
                    if "modeles" in donnees_extraites:
                        vrais_modeles = []
                        # Liste des mots qui prouvent que ce n'est pas un nom commercial
                        mots_interdits = [
                            "débits", "décroissants", "config", "bouches", "pmin", 
                            "multipiquage", "courbe", "caractéristique",
                            "b100", "b200", "fan_", "-fan", "t.flow", "thermodynamique"
                        ]
                        
                        for m in donnees_extraites["modeles"]:
                            nom = str(m.get("nom_modele", "")).lower()
                            
                            # On garde le modèle SI : 
                            # 1. Le nom fait moins de 45 caractères (un nom commercial est court)
                            # 2. Il ne contient aucun mot interdit
                            if len(nom) < 45 and not any(mot in nom for mot in mots_interdits):
                                vrais_modeles.append(m)
                                
                        # On remplace la liste brute par la liste nettoyée
                        donnees_extraites["modeles"] = vrais_modeles
                    # -------------------------------------------------------------
                    
                    if donnees_extraites.get("est_vmc") is False:
                        st.error("⚠️ L'IA a détecté que ce document ne concerne pas une VMC.")
                    else:
                        st.success("Analyse réussie ! Les champs ont été pré-remplis.")
                        st.session_state['prefill_data'] = donnees_extraites
                        st.rerun()

                except Exception as e:
                    st.error(f"Erreur lors de l'analyse : {e}")

    st.divider()

    prefill = st.session_state.get('prefill_data', {})
    prefill_num = prefill.get("numero_atec", "")
    if prefill_num and prefill.get("indice_revision") and "_" not in prefill_num:
        prefill_num = f"{prefill_num}_{prefill['indice_revision']}"
    
    with st.form("form_add_atec"):
        col1, col2 = st.columns(2)
        with col1:
            in_full_num = st.text_input("Numéro d'Avis complet (ex: 14.5/17-2273_V2)", value=prefill_num)
            in_tit = st.text_input("Titulaire (ex: ALDES)", value=prefill.get("titulaire", ""))
        with col2:
            in_dist = st.text_input("Distributeur (Marque commerciale)", value=prefill.get("distributeur", ""))
            try: def_deb = datetime.datetime.strptime(prefill.get('debut_validite', ''), "%Y-%m-%d").date()
            except: def_deb = None
            try: def_fin = datetime.datetime.strptime(prefill.get('fin_validite', ''), "%Y-%m-%d").date()
            except: def_fin = None
            
            in_deb = st.date_input("Début de validité", value=def_deb, format="DD/MM/YYYY")
            in_fin = st.date_input("Fin de validité", value=def_fin, format="DD/MM/YYYY")
        
        in_url = st.text_input("Lien URL Batipedia (Optionnel)")
        
        st.markdown("**Caissons / Modèles**")
        
        lignes_df_new = []
        if prefill.get("modeles"):
            for m in prefill["modeles"]:
                log_db = m.get('type_logement', 'Collectif')
                if log_db not in ["Collectif", "Individuel", "Mixte"]: log_db = "Collectif"
                lignes_df_new.append({
                    "nom_modele": m.get('nom_modele', ''), "type_logement": log_db,
                    "basse_pression": bool(m.get('basse_pression', False)), "double_flux": bool(m.get('double_flux', False)),
                    "debits_disponibles": format_debits_to_str(m.get('debits_disponibles', [])),
                    "puissance_hygro_a": str(m.get('puissance_hygro_a', '') or ''), "puissance_hygro_b": str(m.get('puissance_hygro_b', '') or '')
                })
        
        if not lignes_df_new:
            lignes_df_new.append({"nom_modele": "", "type_logement": "Collectif", "basse_pression": False, "double_flux": False, "debits_disponibles": "", "puissance_hygro_a": "", "puissance_hygro_b": ""})
            
        df_new = pd.DataFrame(lignes_df_new)
        edited_df_new = st.data_editor(df_new, num_rows="dynamic", column_config=config_colonnes, hide_index=True, use_container_width=True)

        if st.form_submit_button("✅ Enregistrer le nouvel Avis", type="primary"):
            if not in_full_num or not in_tit:
                st.error("⚠️ Le Numéro d'Avis et le Titulaire sont obligatoires.")
            else:
                try:
                    in_num, in_rev = parse_numero_complet(in_full_num)
                    
                    modeles_json_new = []
                    for _, row in edited_df_new.iterrows():
                        if row['nom_modele'].strip():
                            modeles_json_new.append({
                                "nom_modele": row['nom_modele'], "type_logement": row['type_logement'],
                                "basse_pression": bool(row['basse_pression']), "double_flux": bool(row['double_flux']),
                                "debits_disponibles": parse_debits_from_str(row['debits_disponibles']),
                                "puissance_hygro_a": str(row['puissance_hygro_a']).strip() if row['puissance_hygro_a'] else None,
                                "puissance_hygro_b": str(row['puissance_hygro_b']).strip() if row['puissance_hygro_b'] else None
                            })
                    
                    nouveau_doc = {
                        "numero_atec": in_num, "indice_revision": in_rev,
                        "titulaire": in_tit, "distributeur": in_dist if in_dist else in_tit,
                        "debut_validite": in_deb.strftime("%Y-%m-%d") if in_deb else None,
                        "fin_validite": in_fin.strftime("%Y-%m-%d") if in_fin else None,
                        "url_batipedia": in_url, "modeles": modeles_json_new
                    }
                    
                    supabase.table("referentiel_vmc").insert(nouveau_doc).execute()
                    st.success(f"L'Avis {in_num}_{in_rev} a été ajouté avec succès !")
                    
                    fetch_all_atec.clear()
                    st.session_state['prefill_data'] = {}
                    st.rerun()

                except Exception as e:
                    if "23505" in str(e) or "duplicate key" in str(e):
                        st.error(f"⚠️ L'Avis Technique **{in_num}** (Révision **{in_rev}**) existe déjà dans la base.")
                    else:
                        st.error(f"❌ Erreur inattendue : {e}")