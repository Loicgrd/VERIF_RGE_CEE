# database.py
import duckdb
import streamlit as st

def fetch_local_backup(siret):
    """
    Recherche un SIRET instantanément dans les fichiers découpés 
    sans charger la RAM de Streamlit Cloud.
    """
    conn = duckdb.connect()
    # L'étoile '*' permet à DuckDB de scanner part1 et part2 en même temps
    query = f"SELECT * FROM 'rge_backup_part*.parquet' WHERE siret = '{siret}'"
    
    try:
        df_res = conn.execute(query).df()
        # On convertit en liste de dictionnaires pour garder le format de l'ADEME
        return df_res.to_dict(orient='records')
    except Exception as e:
        st.error(f"Erreur lors de la lecture de la base locale : {e}")
        return []