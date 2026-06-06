import pandas as pd
import glob
import os
import streamlit as st

def fetch_local_backup(siret):
    siret = str(siret)
    results = []
    
    # On force la recherche depuis le dossier où Streamlit est lancé
    # On cherche dans le dossier "database"
    chemin_recherche = "database/RGE/rge_backup_part*.parquet"
    files = glob.glob(chemin_recherche)
    
    # --- ZONE DE DÉBOGAGE ---
    if not files:
        st.error(f"🚨 BUG LOCAL : Je ne trouve aucun fichier avec le chemin `{chemin_recherche}`")
        st.info(f"Dossier actuel de l'application : `{os.getcwd()}`")
        # On tente de voir si les fichiers ne sont pas restés à la racine par erreur
        fichiers_racine = glob.glob("rge_backup_part*.parquet")
        if fichiers_racine:
            st.warning(f"⚠️ Les fichiers parquet sont à la racine du projet, pas dans le dossier 'database' ! Déplace-les.")
    else:
        # st.success(f"✅ {len(files)} fichiers Parquet trouvés pour la recherche locale !") # Tu pourras décommenter ça pour te rassurer
        pass
    # ------------------------
    
    for file in files:
        try:
            # On ne lit QUE la colonne 'siret' pour économiser la RAM
            df = pd.read_parquet(file, columns=['siret'])
            
            # On cherche l'index des lignes qui correspondent
            match_indices = df[df['siret'].astype(str) == siret].index
            
            if not match_indices.empty:
                # Si trouvé, on relit le fichier COMPLET uniquement pour les lignes trouvées
                full_df = pd.read_parquet(file)
                results.extend(full_df.loc[match_indices].to_dict(orient='records'))
        except Exception as e:
            st.error(f"Erreur lors de la lecture du fichier {file} : {e}")
            continue
            
    return results