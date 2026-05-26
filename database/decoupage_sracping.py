import pandas as pd

df = pd.read_parquet("19052026rge_backup.parquet")
nb_parts = 6
taille_partie = len(df) // nb_parts

for i in range(nb_parts):
    start = i * taille_partie
    end = (i + 1) * taille_partie if i < nb_parts - 1 else len(df)
    df.iloc[start:end].to_parquet(f"rge_backup_part{i+1}.parquet", compression='brotli', index=False)