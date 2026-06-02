#Appli permettant de vérifier si la VMC a un avis technique valide
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Contrôle CEE - VMC", page_icon="🌬️", layout="wide")

# --- 1. CONNEXION À SUPABASE ---
@st.cache_resource
def init_connection():
    # Streamlit gère tout seul la lecture du secrets.toml !
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

# --- 2. RÉCUPÉRATION DES DONNÉES ---
@st.cache_data(ttl=600) # Mise en cache de 10 min
def fetch_all_atec():
    reponse = supabase.table("referentiel_vmc").select("*").execute()
    return reponse.data

donnees_atec = fetch_all_atec()

# --- 3. INTERFACE UTILISATEUR ---
st.title("🌬️ Référentiel Avis Techniques VMC")

if not donnees_atec:
    st.warning("Aucune donnée trouvée dans la base.")
    st.stop()

# Moteur de recherche
recherche = st.text_input("🔍 Rechercher un modèle ou un fabricant (ex: Copernic, Aldes...)", "")
st.divider()

# --- 4. LOGIQUE D'AFFICHAGE ---
resultats_trouves = 0

for doc in donnees_atec:
    match_global = recherche.lower() in doc['numero_atec'].lower() or recherche.lower() in doc['fabricant'].lower()
    
    # Filtre les modèles
    modeles_filtres = [
        m for m in doc['modeles'] 
        if match_global or recherche.lower() in m['nom_modele'].lower()
    ]
            
    if modeles_filtres:
        resultats_trouves += 1
        
        # Affichage du bloc extensible
        with st.expander(f"📄 {doc['numero_atec']} (Rév. {doc['indice_revision']}) - {doc['fabricant']}", expanded=(recherche != "")):
            
            # --- En-tête : Dates et Bouton PDF ---
            col_dates, col_lien = st.columns([3, 1])
            with col_dates:
                st.caption(f"📅 Validité : du **{doc['debut_validite']}** au **{doc['fin_validite']}**")
            with col_lien:
                if doc.get('url_batipedia'):
                    # Le fameux bouton qui ouvrira le PDF directement !
                    st.link_button("📥 Ouvrir le PDF", doc['url_batipedia'])
                else:
                    st.caption("*(Lien PDF non disponible)*")
            
            st.divider()
            
            # --- Détail des modèles ---
            colonnes = st.columns(3)
            for i, modele in enumerate(modeles_filtres):
                col = colonnes[i % 3]
                with col:
                    st.markdown(f"**{modele['nom_modele']}**")
                    st.write(f"- Type : {modele.get('type_logement', 'N/A')}")
                    
                    if modele.get('basse_pression') is not None:
                        bp_texte = "✅ Oui" if modele['basse_pression'] else "❌ Non"
                        st.write(f"- Basse Pression : {bp_texte}")
                        
                    if modele.get('debits_disponibles'):
                        debits = ", ".join(modele['debits_disponibles'])
                        st.write(f"- Débits : {debits} m³/h")
                        
                    st.write("---")

if resultats_trouves == 0:
    st.info("Aucun modèle ne correspond à votre recherche.")