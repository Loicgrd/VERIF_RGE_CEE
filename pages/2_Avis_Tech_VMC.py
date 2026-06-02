import streamlit as st
from supabase import create_client
import datetime

st.set_page_config(page_title="Contrôle CEE - VMC", page_icon="🌬️", layout="wide")

# --- 1. CONNEXION À SUPABASE ---
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

# --- 2. RÉCUPÉRATION DES DONNÉES ---
@st.cache_data(ttl=600)
def fetch_all_atec():
    reponse = supabase.table("referentiel_vmc").select("*").execute()
    return reponse.data

donnees_atec = fetch_all_atec()

if not donnees_atec:
    st.warning("Aucune donnée trouvée dans la base.")
    st.stop()

# --- 3. INTERFACE UTILISATEUR ET FORMULAIRE DE RECHERCHE ---
st.title("🌬️ Référentiel Avis Techniques VMC")

marques_disponibles = sorted(list(set([doc.get('distributeur', 'Inconnu') for doc in donnees_atec if doc.get('distributeur')])))

# Utilisation d'un formulaire pour bloquer le rafraîchissement automatique
with st.form("formulaire_recherche"):
    st.markdown("### 🔍 Critères de recherche")
    col1, col2, col3 = st.columns(3)

    with col1:
        filtre_marque = st.selectbox("🏭 Marque / distributeur", ["Toutes"] + marques_disponibles)

    with col2:
        filtre_texte = st.text_input("📦 Modèle ou N° d'Avis", "")

    with col3:
        filtre_date = st.date_input("📅 Date d'engagement", value=None, format="DD/MM/YYYY")
    
    # Le bouton qui déclenche la recherche
    submit_search = st.form_submit_button("🚀 Rechercher", use_container_width=True)

st.divider()

# --- 4. LOGIQUE DE FILTRAGE (S'exécute avec les valeurs du formulaire) ---
def get_base_atec(numero):
    return numero.split('_')[0].split(' ')[0]

resultats_filtres = []

for doc in donnees_atec:
    if filtre_marque != "Toutes" and doc.get('distributeur') != filtre_marque:
        continue

    match_texte = False
    texte_lower = filtre_texte.lower()
    if not texte_lower:
        match_texte = True
    else:
        if texte_lower in doc.get('numero_atec', '').lower() or texte_lower in doc.get('distributeur', '').lower():
            match_texte = True
        else:
            for mod in doc.get('modeles', []):
                if texte_lower in mod.get('nom_modele', '').lower():
                    match_texte = True
                    break
    
    if not match_texte:
        continue

    try:
        deb = datetime.datetime.strptime(doc['debut_validite'], "%Y-%m-%d").date() if doc.get('debut_validite') else None
        fin = datetime.datetime.strptime(doc['fin_validite'], "%Y-%m-%d").date() if doc.get('fin_validite') else None
    except:
        deb, fin = None, None

    if filtre_date:
        if deb and fin:
            if not (deb <= filtre_date <= fin):
                continue
        elif deb:
            if filtre_date < deb:
                continue
        elif fin:
            if filtre_date > fin:
                continue

    doc['_deb_parsed'] = deb
    resultats_filtres.append(doc)

# Dédoublonnage pour garder la meilleure version
atec_groupes = {}
for doc in resultats_filtres:
    base_num = get_base_atec(doc.get('numero_atec', ''))
    if base_num not in atec_groupes:
        atec_groupes[base_num] = doc
    else:
        doc_actuel = atec_groupes[base_num]
        deb_nouveau = doc.get('_deb_parsed')
        deb_actuel = doc_actuel.get('_deb_parsed')
        if deb_nouveau and deb_actuel and deb_nouveau > deb_actuel:
            atec_groupes[base_num] = doc

resultats_finaux = list(atec_groupes.values())

# --- 5. AFFICHAGE COMPACT DES RÉSULTATS ---
if len(resultats_finaux) == 0:
    st.info("Aucun Avis Technique ne correspond à ces critères.")
else:
    st.caption(f"**{len(resultats_finaux)} résultat(s) trouvé(s)**")
    
    for doc in resultats_finaux:
        # Création du format exact demandé (ex: 14.5/17-2273_V8)
        revision = doc.get('indice_revision', 'V1')
        full_atec = f"{doc['numero_atec']}_{revision}"

        

        if filtre_texte and filtre_texte.lower() not in doc.get('numero_atec', '').lower() and filtre_texte.lower() not in doc.get('distributeur', '').lower():
            modeles_a_afficher = [m for m in doc.get('modeles', []) if filtre_texte.lower() in m.get('nom_modele', '').lower()]
        else:
            modeles_a_afficher = doc.get('modeles', [])

        # On n'ouvre l'expander par défaut que s'il y a peu de résultats (pour la compacité)
        is_expanded = len(resultats_finaux) < 5

        # En-tête de l'expander plus propre
        with st.expander(f"🏭 {doc['distributeur']}  |  📄 {full_atec}", expanded=is_expanded):
            
            # Ligne principale ultra-compacte
            col_ref, col_dates, col_lien = st.columns([2, 2, 1])
            
            with col_ref:
                # Ceci va créer une zone grise avec un bouton "Copier" automatique !
                st.code(full_atec, language=None)
                
            with col_dates:
                deb_str = doc['_deb_parsed'].strftime("%d/%m/%Y") if doc.get('_deb_parsed') else "Inconnue"
                try:
                    fin_parsed = datetime.datetime.strptime(doc['fin_validite'], "%Y-%m-%d").date()
                    fin_str = fin_parsed.strftime("%d/%m/%Y")
                except:
                    fin_str = "Inconnue"
                st.markdown(f"**Validité :** {deb_str} ➡️ {fin_str}")
                
            with col_lien:
                if doc.get('url_batipedia'):
                    st.link_button("📥 Ouvrir PDF", doc['url_batipedia'], use_container_width=True)
            
            # Liste des modèles en format "inline" très condensé
            if modeles_a_afficher:
                st.markdown("**Modèles éligibles :**")
                # On regroupe tout dans une seule string par modèle pour gagner en hauteur
                lignes_modeles = []
                for m in modeles_a_afficher:
                    bp = " | BP: ✅" if m.get('basse_pression') else ""
                    debits = f" | Débits: {', '.join(m['debits_disponibles'])}" if m.get('debits_disponibles') else ""
                    type_log = f" ({m.get('type_logement', 'N/A')})"
                    lignes_modeles.append(f"- **{m.get('nom_modele', 'Inconnu')}**{type_log}{bp}{debits}")
                
                st.markdown("\n".join(lignes_modeles))