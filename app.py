import streamlit as st
import pandas as pd
from datetime import datetime
import requests
import io
import zipfile
import urllib.parse
import plotly.express as px

# --- CONFIGURATION INITIALE ---
st.set_page_config(page_title="Vérification des RGE", layout="wide")

# --- STYLE CSS AVANCÉ (COMPACITÉ TOTALE) ---
st.markdown("""
    <style>
    [data-testid="column"] {
        display: flex;
        flex-direction: column;
        justify-content: flex-start;
        min-width: 0px;
    }
    .certif-info {
        font-size: 12px !important;
        line-height: 1.1 !important;
    }
    div.stDownloadButton > button, div.stButton > button {
        height: 26px !important;
        width: 100% !important;
        font-size: 11px !important;
        padding: 0px !important;
        min-height: 26px !important;
    }
    .add-btn button {
        background-color: #f0f2f6 !important;
        border: 1px dashed #999 !important;
        color: #333 !important;
    }
    .stElementContainer { margin-bottom: 1px !important; }
    .stVerticalBlock { gap: 0rem !important; }
    .streamlit-expanderContent { padding: 0.5rem !important; }
    </style>
""", unsafe_allow_html=True)

# --- CONFIGURATION DES FICHES CEE ---
MAP_CEE = {
    "Fenêtres, volets, portes extérieures 2020": ["EN104", "EN108", "EN110"],
    "Isolation du toit 2020": ["EN101", "EN105", "EN106"],
    "Isolation des murs et planchers bas 2020": ["EN102", "EN103", "EN107"],
    "Isolation par l'intérieur des murs ou rampants de toitures ou plafonds": ["EN101", "EN102"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul 2020": ["TH106", "TH107"],
    "Equipements électriques hors ENR : chauffage, eau chaude, éclairage 2020": ["EQ110", "EQ115"],
    "Pompe à chaleur : chauffage": ["TH171", "TH172", "TH129", "TH159"],
    "Isolation des combles perdus": ["EN101"],
    "Chauffe-Eau Thermodynamique": ["TH148", "TH169"],
    "Fenêtres, volets, portes donnant sur l'extérieur": ["EN104", "EN108"],
    "Chaudière condensation ou micro-cogénération gaz ou fioul": ["TH106", "TH107"],
    "Poêle ou insert bois": ["TH112"],
    "Isolation des murs par l'extérieur": ["EN102"],
    "Isolation des planchers bas": ["EN103"],
    "Isolation des toitures terrasses ou des toitures par l'extérieur": ["EN105"],
    "Fenêtres de toit": ["EN104"],
    "Radiateurs électriques, dont régulation.": ["TH158", "TH173"],
    "Chaudière bois": ["TH113"],
    "Panneaux solaires photovoltaïques": ["PV"],
    "Ventilation mécanique": ["TH127", "TH125", "TH155"],
    "Ventilation 2020": ["TH127", "TH125", "TH155"],
    "Audit énergétique Maison individuelle": ["TH164", "TH174"],
    "Architecte": ["TH164", "TH174"],
    "Chauffage et/ou eau chaude solaire": ["TH101", "TH143", "TH124"],
    "Pompe à chaleur et/ou Chauffe-eau thermodynamique 2020": ["TH171", "TH148", "TH159"],
    "Chauffage et/ou eau chaude au bois 2020": ["TH113", "TH112"],
    "Audit énergétique Logement collectif": ["TH145"],
    "Projet complet de rénovation": ["TH164", "TH145", "TH174"],
    "Chauffage et/ou eau chaude solaire 2020": ["TH101", "TH143"],
    "Forage géothermique": ["TH178"],
}

def extract_qualif_code(id_complet):
    if not id_complet or id_complet == "N/A": return "N/A"
    id_str = str(id_complet).strip()
    pos_tiret = id_str.find("-")
    longueur_fin = len(id_str) if pos_tiret == -1 else pos_tiret
    return id_str[1:longueur_fin] if id_str.startswith("Q") else id_str[:longueur_fin]

def clean_url(url):
    return urllib.parse.quote(url, safe=':/?&=') if url else ""

def get_cee_options(domaine):
    dom_clean = str(domaine).lower().strip()
    for key, codes in MAP_CEE.items():
        if key.lower() in dom_clean: return codes
    return ["RGE"]

def fetch_ademe_data(siret):
    url = f"https://data.ademe.fr/data-fair/api/v1/datasets/historique-rge/lines?q=siret.exact:'{siret}'&size=1000"
    try:
        r = requests.get(url, timeout=15)
        return r.json().get('results', []) if r.status_code == 200 else []
    except: return []

# --- INTERFACE ---
st.title("🛡️ Vérification des RGE")

c_date, _ = st.columns([1, 2])
with c_date:
    date_eng = st.date_input("Date d'engagement :", datetime.now(), format="DD/MM/YYYY")

if 'siret_rows' not in st.session_state:
    st.session_state.siret_rows = pd.DataFrame([{"SIRET": ""}], dtype=str)

df_saisie = st.data_editor(st.session_state.siret_rows, num_rows="dynamic", use_container_width=True,
                           column_config={"SIRET": st.column_config.TextColumn("SIRET", max_chars=14)})

if st.button("🔍 Analyser les SIRET", type="primary"):
    sirets = [str(s).strip() for s in df_saisie["SIRET"] if s and str(s).strip()]
    if sirets:
        all_results = []
        with st.spinner("Analyse ADEME..."):
            for s in sirets:
                api_lines = fetch_ademe_data(s)
                if api_lines:
                    nom_ent = api_lines[0].get('nom_entreprise') or api_lines[0].get('raison_sociale') or "Inconnu"
                    domaines_raw = {}
                    for line in api_lines:
                        dom = str(line.get('domaine', 'Inconnu')).strip()
                        debut_str, fin_str = line.get('date_debut_validite') or line.get('lien_date_debut'), line.get('date_fin_validite') or line.get('lien_date_fin')
                        if debut_str and fin_str:
                            try:
                                d_debut, d_fin = datetime.strptime(debut_str[:10], '%Y-%m-%d').date(), datetime.strptime(fin_str[:10], '%Y-%m-%d').date()
                                if dom not in domaines_raw: domaines_raw[dom] = []
                                domaines_raw[dom].append({"n_certif": extract_qualif_code(line.get('_id', "N/A")), "debut": d_debut, "fin": d_fin, "url": clean_url(line.get('url_qualification') or line.get('lien_certificat'))})
                            except: continue
                    domaines_finaux = {dom: {**(next((p for p in periodes if p['debut'] <= date_eng <= p['fin']), None) or max(periodes, key=lambda x: x['fin'])), "status_rge": bool(next((p for p in periodes if p['debut'] <= date_eng <= p['fin']), None)), "historique": periodes} for dom, periodes in domaines_raw.items()}
                    all_results.append({"SIRET": s, "Entreprise": nom_ent, "Domaines": domaines_finaux})
        st.session_state.audit_results = all_results

if 'audit_results' in st.session_state:
    files_to_zip, excel_data = [], []

    for res in st.session_state.audit_results:
        with st.expander(f"🏢 {res['Entreprise']} ({res['SIRET']})", expanded=True):
            graph_data = []
            for d, info in res['Domaines'].items():
                c_code = "#28a745" if info['status_rge'] else "#dc3545"
                for h in info['historique']:
                    graph_data.append({"Domaine": f"<span style='color:{c_code}'>{d}</span>", "Début": h['debut'], "Fin": h['fin'], "Statut": "Valide" if h['debut'] <= date_eng <= h['fin'] else "Expiré"})

            liste_doms, nb_key = list(res['Domaines'].keys()), f"nb_{res['SIRET']}"
            if nb_key not in st.session_state: st.session_state[nb_key] = 1

            for i in range(st.session_state[nb_key]):
                c1, c2, c3, c4, c5, c6, c7 = st.columns([1.8, 0.8, 1.2, 0.8, 1.2, 0.6, 0.3])
                with c1: dom_sel = st.selectbox(f"D{i}", options=liste_doms, key=f"s_{res['SIRET']}_{i}", label_visibility="collapsed")
                info = res['Domaines'][dom_sel]
                with c2: 
                    if info['status_rge']: st.success("✅ Valide")
                    else: st.error("❌ Expiré")
                with c3: st.markdown(f"<div class='certif-info'><b>N° :</b> {info['n_certif']}<br><i>Fin : {info['fin'].strftime('%d/%m/%Y')}</i></div>", unsafe_allow_html=True)
                with c4: choix_bar = st.selectbox("F", options=get_cee_options(dom_sel), key=f"b_{res['SIRET']}_{dom_sel}_{i}", label_visibility="collapsed")
                with c5:
                    if info['url']:
                        st.markdown(f"[👁️ Voir PDF]({info['url']})", unsafe_allow_html=True)
                        try:
                            content = requests.get(info['url'], timeout=5).content
                            ent_clean = res['Entreprise'].replace(" ", "_").replace("/", "-")
                            
                            # Nom pour le téléchargement individuel
                            nom_indiv = f"{dom_sel}-{ent_clean}.pdf"
                            
                            # Nom spécifique pour le ZIP (avec STATUT)
                            statut_txt = "VALIDE" if info['status_rge'] else "EXPIRE"
                            nom_zip = f"{dom_sel}-{ent_clean}-{statut_txt}.pdf"
                            
                            st.download_button("📥 Télécharger certificat", content, nom_indiv, "application/pdf", key=f"dl_{res['SIRET']}_{i}")
                            files_to_zip.append({"content": content, "nom": nom_zip})
                        except: st.caption("⚠️")
                with c6: show_g = st.checkbox("📊 Graph", key=f"check_{res['SIRET']}_{i}")
                with c7:
                    if i == st.session_state[nb_key] - 1:
                        st.markdown('<div class="add-btn">', unsafe_allow_html=True)
                        if st.button("➕", key=f"add_{res['SIRET']}"):
                            st.session_state[nb_key] += 1
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                    elif st.session_state[nb_key] > 1:
                        if st.button("🗑️", key=f"del_{res['SIRET']}_{i}"):
                            st.session_state[nb_key] -= 1
                            st.rerun()

                if show_g and graph_data:
                    df_g = pd.DataFrame(graph_data)
                    df_g["Début"], df_g["Fin"] = pd.to_datetime(df_g["Début"]), pd.to_datetime(df_g["Fin"])
                    fig = px.timeline(df_g, x_start="Début", x_end="Fin", y="Domaine", color="Statut", color_discrete_map={"Valide": "#28a745", "Expiré": "#dee2e6"})
                    fig.add_vline(x=pd.to_datetime(date_eng).timestamp() * 1000, line_dash="dash", line_color="blue")
                    fig.update_layout(barcornerradius=10, height=max(180, (len(df_g["Domaine"].unique()) * 30) + 80), margin=dict(l=0, r=0, t=30, b=60),
                                      yaxis={'title': None, 'tickfont': {'size': 10}}, xaxis={'visible': True, 'tickfont': {'size': 9}},
                                      legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="center", x=0.5))
                    st.plotly_chart(fig, use_container_width=True, key=f"fig_global_{res['SIRET']}_{i}")

                excel_data.append({"SIRET": res['SIRET'], "Entreprise": res['Entreprise'], "Domaine": dom_sel, "Fiche": choix_bar, "Certificat": info['n_certif'], "RGE": "Valide" if info['status_rge'] else "Expiré"})

    if excel_data:
        st.divider()
        cz, ce = st.columns(2)
        with cz:
            if st.button("📦 ZIP des certificats", use_container_width=True) and files_to_zip:
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED) as zf:
                    for f in files_to_zip: zf.writestr(f['nom'], f['content'])
                st.download_button("⬇️ Télécharger ZIP", buf.getvalue(), "Certificats.zip", use_container_width=True)
        with ce:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                pd.DataFrame(excel_data).to_excel(writer, index=False)
            st.download_button("📊 Télécharger Excel", output.getvalue(), "Synthese.xlsx", use_container_width=True)