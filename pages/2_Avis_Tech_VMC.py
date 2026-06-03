import streamlit as st
from supabase import create_client
import datetime
import re
import pandas as pd
import json
import tempfile
import os
from google import genai
from google.genai import types

st.set_page_config(page_title="Contrôle CEE - VMC", page_icon="🌬️", layout="wide")

# --- 1. CONNEXIONS API (Supabase & Gemini) ---
@st.cache_resource
def init_supabase():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

@st.cache_resource
def init_gemini():
    return genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

supabase = init_supabase()
client_gemini = init_gemini()

# --- LE PROMPT (Cerveau de l'IA pour le pré-remplissage) ---
PROMPT_VMC = """
Tu es un Ingénieur Expert en conformité documentaire pour les Certificats d'Économies d'Énergie (CEE).
Analyse cet Avis Technique (ATec) du CSTB.

Extrais les informations au format JSON strict avec la structure exacte suivante :
{
  "est_vmc": true,
  "numero_atec": "Ex: 14.5/17-2273",
  "indice_revision": "Ex: 'V2', 'Modificatif 1' ou 'V1' si non précisé",
  "titulaire": "Le(s) constructeur(s) officiel(s) (ex: ANJOS, ALDES / AERECO)",
  "distributeur": "La marque commerciale (ex: ATLANTIC). Si aucune marque distincte, remets le titulaire.",
  "debut_validite": "YYYY-MM-DD",
  "fin_validite": "YYYY-MM-DD",
  "modeles": [
    {
      "nom_modele": "Le nom de base de la gamme (ex: EASYVEC)",
      "type_logement": "'Individuel', 'Collectif' ou 'Mixte'",
      "basse_pression": true ou false,
      "debits_disponibles": ["400"]
    }
  ]
}

RÈGLES D'EXTRACTION ABSOLUES :
1. FILTRE HORS PÉRIMÈTRE : Si le document ne traite pas de VMC, mets "est_vmc": false.
2. TITULAIRE ET DISTRIBUTEUR : "titulaire" (Titulaire(s), sans termes juridiques), "distributeur" (Marque commerciale ou recopie titulaire).
3. IDENTIFICATION DES CAISSONS ET REGROUPEMENT (TRÈS IMPORTANT) :
   - Isole le nom de base de la gamme (ex: "MATRYS", "EASYVEC").
   - REGROUPEMENT : Si plusieurs puissances, crée UN SEUL objet et liste les puissances dans `debits_disponibles`.
   - INTERDICTION ABSOLUE DES ACCESSOIRES : Tu ne dois extraire QUE les moteurs (Groupes d'extraction / Caissons de ventilation). Il est STRICTEMENT INTERDIT d'extraire les accessoires périphériques. Rejette systématiquement : les bouches d'extraction, les entrées d'air, les chapeaux de toiture (ex: Grauli, Defa), les conduits, les variateurs de tension, les boîtiers de commande ou les logiciels.4. EXCLUSION DES RÉFÉRENCES CROISÉES : Ignore les modèles renvoyant à un autre Avis.
5. TYPE DE LOGEMENT : "maisons individuelles" = "Individuel", "logements collectifs" = "Collectif", les deux = "Mixte".
6. BASSE PRESSION (RÈGLE GLOBALE ET STRICTE) : 
   - Règle du tout ou rien : Si l'Avis Technique décrit globalement un système "Basse Pression" ou "BP", tu dois mettre "basse_pression": true pour l'INTÉGRALITÉ des modèles de ta liste, sans aucune exception.
   - Si le système n'est pas "Basse Pression", mets `false` pour TOUS les modèles.
   - ATTENTION AUX PIÈGES : Ne confonds SURTOUT PAS "Basse Pression" avec "Basse consommation" (basse conso / micro-watt), ni avec "Pression constante" ou "Pression standard". Si tu vois ces termes, cela NE VEUT PAS DIRE basse pression (mets false).
7. DÉBITS : Uniquement si inclus dans le nom commercial du caisson.
8. FORMAT : Renvoie UNIQUEMENT un JSON valide.
"""

# --- 2. GESTION DE LA MÉMOIRE (Session State) ---
# Sert à conserver les données de l'IA entre deux rafraîchissements de page
if 'prefill_data' not in st.session_state:
    st.session_state['prefill_data'] = {}

# --- 3. RÉCUPÉRATION DES DONNÉES ---
@st.cache_data(ttl=600)
def fetch_all_atec():
    reponse = supabase.table("referentiel_vmc").select("*").execute()
    return reponse.data

donnees_atec = fetch_all_atec()

if not donnees_atec:
    st.warning("Aucune donnée trouvée dans la base.")
    st.stop()

# --- 4. FONCTIONS UTILITAIRES POUR LES DÉBITS ---
def format_debits_to_str(debits_list):
    if not isinstance(debits_list, list): return ""
    return ", ".join(str(d) for d in debits_list)

def parse_debits_from_str(debits_str):
    if not debits_str: return []
    return [d.strip() for d in str(debits_str).split(",") if d.strip()]

config_colonnes = {
    "nom_modele": st.column_config.TextColumn("📦 Nom du caisson", required=True),
    "type_logement": st.column_config.SelectboxColumn("🏠 Logement", options=["Collectif", "Individuel", "Mixte"]),
    "basse_pression": st.column_config.CheckboxColumn("⬇️ Basse Pression"),
    "debits_disponibles": st.column_config.TextColumn("💨 Débits (ex: 400, 700)")
}

# --- CRÉATION DES ONGLETS ---
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

        with col1:
            filtre_marque = st.selectbox("🏭 Marque / Distributeur", ["Toutes"] + marques_disponibles)

        with col2:
            filtre_texte = st.text_input("📦 Modèle ou N° d'Avis", "")

        with col3:
            filtre_date = st.date_input("📅 Date d'engagement", value=None, format="DD/MM/YYYY")
        
        submit_search = st.form_submit_button("🚀 Rechercher", use_container_width=True)

    st.divider()

    # --- NOUVEAU : ON N'AFFICHE RIEN TANT QU'ON N'A PAS CLIQUÉ ---
    if not submit_search:
        st.info("👈 Veuillez définir vos critères et cliquer sur **Rechercher** pour afficher les résultats.")
        st.stop() # Arrête le script ici : tout ce qui est en dessous ne sera pas lu

    def get_base_atec(numero):
        return str(numero or '').split('_')[0].split(' ')[0]

    resultats_filtres = []

    for doc in donnees_atec:
        if filtre_marque != "Toutes" and doc.get('distributeur') != filtre_marque: continue

        match_texte = False
        texte_lower = filtre_texte.lower()
        
        if not texte_lower: match_texte = True
        else:
            atec_val = str(doc.get('numero_atec') or '').lower()
            dist_val = str(doc.get('distributeur') or '').lower()
            if texte_lower in atec_val or texte_lower in dist_val: match_texte = True
            else:
                modeles = doc.get('modeles') or []
                for mod in modeles:
                    if texte_lower in str(mod.get('nom_modele') or '').lower():
                        match_texte = True
                        break
        
        if not match_texte: continue

        try: deb = datetime.datetime.strptime(doc['debut_validite'], "%Y-%m-%d").date() if doc.get('debut_validite') else None
        except: deb = None
        try: fin = datetime.datetime.strptime(doc['fin_validite'], "%Y-%m-%d").date() if doc.get('fin_validite') else None
        except: fin = None

        if filtre_date:
            if deb and fin and not (deb <= filtre_date <= fin): continue
            elif deb and filtre_date < deb: continue
            elif fin and filtre_date > fin: continue

        doc['_deb_parsed'] = deb
        resultats_filtres.append(doc)

    atec_groupes = {}
    for doc in resultats_filtres:
        base_num = get_base_atec(doc.get('numero_atec', ''))
        if base_num not in atec_groupes:
            atec_groupes[base_num] = doc
        else:
            doc_actuel = atec_groupes[base_num]
            if doc.get('_deb_parsed') and doc_actuel.get('_deb_parsed') and doc.get('_deb_parsed') > doc_actuel.get('_deb_parsed'):
                atec_groupes[base_num] = doc

    resultats_finaux = list(atec_groupes.values())

    if len(resultats_finaux) == 0:
        st.info("Aucun Avis Technique ne correspond à ces critères.")
    else:
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

            is_expanded = len(resultats_finaux) < 5

            with st.expander(f"🏭 {doc.get('distributeur', doc.get('titulaire', 'Inconnu'))}  |  📄 {full_atec}", expanded=is_expanded):
                
                mode_edition = st.toggle("✏️ Éditer cet Avis", key=f"toggle_{doc['id']}")
                
                if not mode_edition:
                    col_ref, col_dates, col_lien = st.columns([2, 2, 1])
                    with col_ref: st.code(full_atec, language=None)
                    with col_dates:
                        deb_str = doc['_deb_parsed'].strftime("%d/%m/%Y") if doc.get('_deb_parsed') else "Inconnue"
                        try: fin_str = datetime.datetime.strptime(doc.get('fin_validite', ''), "%Y-%m-%d").date().strftime("%d/%m/%Y")
                        except: fin_str = "Inconnue"
                        st.markdown(f"**Validité :** {deb_str} ➡️ {fin_str}")
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
                                modeles_groupes[nom_base] = {'nom_modele': nom_base, 'type_logement': m.get('type_logement', 'N/A'), 'basse_pression': m.get('basse_pression', False), 'debits': set()}
                            if m.get('basse_pression'): modeles_groupes[nom_base]['basse_pression'] = True
                            if debit_extrait: modeles_groupes[nom_base]['debits'].add(debit_extrait)
                            if m.get('debits_disponibles'): modeles_groupes[nom_base]['debits'].update(m.get('debits_disponibles'))

                        lignes_modeles = []
                        for m in modeles_groupes.values():
                            bp = " | BP: ✅" if m['basse_pression'] else ""
                            type_log = f" ({m['type_logement']})"
                            def tri_numerique(val):
                                nombres = re.findall(r'\d+', val)
                                return int(nombres[0]) if nombres else 0
                            liste_debits = sorted(list(m['debits']), key=tri_numerique)
                            debits_str = f" ({', '.join(liste_debits)})" if liste_debits else ""
                            lignes_modeles.append(f"- **{m['nom_modele']}**{debits_str} {type_log}{bp}")
                        
                        st.markdown("\n".join(lignes_modeles))
                
                else:
                    st.info("Vous modifiez actuellement cet Avis Technique.")
                    with st.form(f"form_edit_{doc['id']}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            mod_num = st.text_input("Numéro d'Avis", value=doc.get('numero_atec', ''))
                            mod_rev = st.text_input("Indice de révision", value=doc.get('indice_revision', ''))
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
                            lignes_df.append({"nom_modele": m.get('nom_modele', ''), "type_logement": m.get('type_logement', 'Collectif'), "basse_pression": bool(m.get('basse_pression', False)), "debits_disponibles": format_debits_to_str(m.get('debits_disponibles', []))})
                        
                        if not lignes_df: lignes_df.append({"nom_modele": "", "type_logement": "Collectif", "basse_pression": False, "debits_disponibles": ""})
                            
                        df_edit = pd.DataFrame(lignes_df)
                        edited_df_mod = st.data_editor(df_edit, num_rows="dynamic", column_config=config_colonnes, hide_index=True, use_container_width=True, key=f"grid_{doc['id']}")

                        if st.form_submit_button("💾 Sauvegarder les modifications", type="primary"):
                            modeles_json_mod = []
                            for _, row in edited_df_mod.iterrows():
                                if row['nom_modele'].strip():
                                    modeles_json_mod.append({"nom_modele": row['nom_modele'], "type_logement": row['type_logement'], "basse_pression": bool(row['basse_pression']), "debits_disponibles": parse_debits_from_str(row['debits_disponibles'])})
                            
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
    
    # --- MODULE D'ASSISTANCE PAR IA ---
    st.markdown("### 🤖 Pré-remplissage Magique par l'IA")
    st.info("Importez le PDF de l'Avis Technique. Gemini va le lire et pré-remplir tous les champs ci-dessous pour vous !")
    
    fichier_pdf = st.file_uploader("Glissez le PDF ici", type=["pdf"])
    
    if fichier_pdf:
        if st.button("✨ Analyser et Pré-remplir", type="primary", use_container_width=True):
            with st.spinner("Analyse du document en cours (environ 10 secondes)..."):
                try:
                    # Création d'un fichier temporaire pour que Gemini puisse le lire
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                        tmp_file.write(fichier_pdf.getvalue())
                        tmp_path = tmp_file.name

                    fichier_upload = client_gemini.files.upload(file=tmp_path)
                    
                    reponse_ia = client_gemini.models.generate_content(
                        model='gemini-3.1-flash-lite',
                        contents=[fichier_upload, PROMPT_VMC],
                        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
                    )
                    
                    client_gemini.files.delete(name=fichier_upload.name)
                    os.remove(tmp_path)
                    
                    # Nettoyage du JSON
                    raw_text = reponse_ia.text.replace("```json", "").replace("```", "").strip()
                    if "{" in raw_text and "}" in raw_text:
                        raw_text = raw_text[raw_text.find("{"):raw_text.rfind("}") + 1]
                    
                    donnees_extraites = json.loads(raw_text)
                    
                    if donnees_extraites.get("est_vmc") is False:
                        st.error("⚠️ L'IA a détecté que ce document ne concerne pas une VMC.")
                    else:
                        st.success("Analyse réussie ! Les champs ont été pré-remplis.")
                        # On sauvegarde dans la mémoire de Streamlit
                        st.session_state['prefill_data'] = donnees_extraites
                        # On relance la page pour appliquer le pré-remplissage
                        st.rerun()

                except Exception as e:
                    st.error(f"Erreur lors de l'analyse : {e}")

    st.divider()

    # --- FORMULAIRE D'AJOUT (Connecté à la mémoire de l'IA) ---
    prefill = st.session_state.get('prefill_data', {})
    
    with st.form("form_add_atec"):
        col1, col2 = st.columns(2)
        with col1:
            in_num = st.text_input("Numéro de l'Avis (ex: 14.5/17-2273)", value=prefill.get("numero_atec", ""))
            in_rev = st.text_input("Indice de révision (ex: V1, Modificatif 1)", value=prefill.get("indice_revision", "V1"))
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
        
        # Pré-remplissage du tableau de modèles
        lignes_df_new = []
        if prefill.get("modeles"):
            for m in prefill["modeles"]:
                lignes_df_new.append({
                    "nom_modele": m.get('nom_modele', ''),
                    "type_logement": m.get('type_logement', 'Collectif'),
                    "basse_pression": bool(m.get('basse_pression', False)),
                    "debits_disponibles": format_debits_to_str(m.get('debits_disponibles', []))
                })
        
        if not lignes_df_new:
            lignes_df_new.append({"nom_modele": "", "type_logement": "Collectif", "basse_pression": False, "debits_disponibles": ""})
            
        df_new = pd.DataFrame(lignes_df_new)
        edited_df_new = st.data_editor(df_new, num_rows="dynamic", column_config=config_colonnes, hide_index=True, use_container_width=True)

        if st.form_submit_button("✅ Enregistrer le nouvel Avis", type="primary"):
            if not in_num or not in_tit:
                st.error("⚠️ Le Numéro d'Avis et le Titulaire sont obligatoires.")
            else:
                try:
                    modeles_json_new = []
                    for _, row in edited_df_new.iterrows():
                        if row['nom_modele'].strip():
                            modeles_json_new.append({
                                "nom_modele": row['nom_modele'],
                                "type_logement": row['type_logement'],
                                "basse_pression": bool(row['basse_pression']),
                                "debits_disponibles": parse_debits_from_str(row['debits_disponibles'])
                            })
                    
                    nouveau_doc = {
                        "numero_atec": in_num, "indice_revision": in_rev,
                        "titulaire": in_tit, "distributeur": in_dist if in_dist else in_tit,
                        "debut_validite": in_deb.strftime("%Y-%m-%d") if in_deb else None,
                        "fin_validite": in_fin.strftime("%Y-%m-%d") if in_fin else None,
                        "url_batipedia": in_url, "modeles": modeles_json_new
                    }
                    
                    supabase.table("referentiel_vmc").insert(nouveau_doc).execute()
                    st.success(f"L'Avis {in_num} a été ajouté avec succès !")
                    
                    # On vide le cache, on réinitialise la mémoire IA et on rafraîchit
                    fetch_all_atec.clear()
                    st.session_state['prefill_data'] = {}
                    st.rerun()

                except Exception as e:
                    erreur_str = str(e)
                    # On intercepte le code d'erreur spécifique aux doublons de PostgreSQL (23505)
                    if "23505" in erreur_str or "duplicate key" in erreur_str:
                        st.error(f"⚠️ L'Avis Technique **{in_num}** (Révision **{in_rev}**) existe déjà dans la base de données. Si vous souhaitez le mettre à jour, utilisez l'interrupteur 'Éditer cet Avis' dans le premier onglet.")
                    else:
                        st.error(f"❌ Erreur inattendue lors de l'insertion : {e}")