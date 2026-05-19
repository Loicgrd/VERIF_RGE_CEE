import pandas as pd
import glob
import streamlit as st

def fetch_local_backup(siret):
    siret = str(siret)
    results = []
    files = glob.glob("backup_ademe/rge_backup_part*.parquet")
    
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
        except Exception:
            continue
            
    return results