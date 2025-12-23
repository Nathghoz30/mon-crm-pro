import streamlit as st
import pandas as pd
import requests
import json
from datetime import datetime, timedelta
import io
import time
import re
from supabase import create_client, Client
from pypdf import PdfWriter, PdfReader
from PIL import Image

# Import Gestion des Cookies
try:
    import extra_streamlit_components as stx
except ImportError:
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'.")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'.")
    st.stop()

# --- CONFIGURATION ---
st.set_page_config(page_title="Universal CRM SaaS", page_icon="🚀", layout="wide")

# --- INITIALISATION SUPABASE ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except Exception as e:
        st.error(f"Erreur technique connexion : {e}")
        st.stop()

supabase = init_connection()
cookie_manager = stx.CookieManager()

# --- ÉTAT SESSION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'profile' not in st.session_state: st.session_state.profile = None
if 'form_reset_id' not in st.session_state: st.session_state.form_reset_id = 0
if 'upload_reset_id' not in st.session_state: st.session_state.upload_reset_id = 0

# --- RECONNEXION AUTO ---
if not st.session_state.user:
    time.sleep(0.1)
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user:
                p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if p_data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
        except: cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS UTILITAIRES ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        p_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
        if p_data:
            st.session_state.user = res.user
            st.session_state.profile = p_data[0]
            if res.session:
                cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
            st.rerun()
    except: st.error("Identifiants incorrects.")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    st.rerun()

def get_siret_info(siret):
    try:
        url = f"https://recherche-entreprises.api.gouv.fr/search?q={siret.replace(' ', '')}"
        res = requests.get(url)
        if res.status_code == 200:
            ent = res.json()['results'][0]
            siege = ent.get('siege', {})
            return {"NOM": ent.get('nom_complet'), "ADRESSE": siege.get('adresse'), "VILLE": siege.get('libelle_commune'), "CP": siege.get('code_postal'), "TVA": ent.get('numero_tva_intracommunautaire')}
    except: return None

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

def merge_files_to_pdf(file_urls):
    merger = PdfWriter()
    for url in file_urls:
        try:
            res = requests.get(url)
            if res.status_code == 200:
                f_data = io.BytesIO(res.content)
                if url.lower().endswith('.pdf'):
                    reader = PdfReader(f_data)
                    for page in reader.pages: merger.add_page(page)
                elif url.lower().endswith(('.png', '.jpg', '.jpeg')):
                    img = Image.open(f_data)
                    if img.mode == 'RGBA': img = img.convert('RGB')
                    img_pdf = io.BytesIO()
                    img.save(img_pdf, format='PDF')
                    img_pdf.seek(0)
                    merger.add_page(PdfReader(img_pdf).pages[0])
        except: continue
    output = io.BytesIO()
    merger.write(output)
    return output.getvalue()

# ==========================================
# 🔐 LOGIN
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            em = st.text_input("Email")
            pw = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(em, pw)
    st.stop()

# ==========================================
# 🚀 APP
# ==========================================
if st.session_state.profile is None: logout()

MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.info(f"Rôle : {MY_ROLE.upper()}")
    if st.button("Se déconnecter", use_container_width=True, type="primary"): logout()

# --- SUPER ADMIN (Gestion globale) ---
if MY_ROLE == "super_admin":
    st.success("👑 Mode Super Admin")
    sa_tabs = st.tabs(["🏢 Entreprises", "👀 Accéder au CRM"])
    with sa_tabs[0]:
        with st.form("create_c"):
            cn = st.text_input("Nom Entreprise")
            ae = st.text_input("Email Gérant (Admin 1)")
            ap = st.text_input("Pass temporaire", type="password")
            if st.form_submit_button("Créer"):
                try:
                    res_c = supabase.table("companies").insert({"name": cn}).execute()
                    n_id = res_c.data[0]['id']
                    res_a = supabase.auth.sign_up({"email": ae, "password": ap})
                    supabase.table("profiles").insert({"id": res_a.user.id, "email": ae, "company_id": n_id, "role": "admin1", "full_name": f"Gérant {cn}"}).execute()
                    st.success("✅ Créé !")
                    st.rerun()
                except Exception as e: st.error(f"Erreur : {e}")
    with sa_tabs[1]:
        all_c = supabase.table("companies").select("*").execute().data
        comp_map = {c['name']: c['id'] for c in all_c}
        target = st.selectbox("Voir Entreprise", list(comp_map.keys()))
        if target: MY_COMPANY_ID = comp_map[target]

if MY_ROLE == "super_admin" and not MY_COMPANY_ID:
    st.warning("👈 Sélectionnez une entreprise.")
    st.stop()

# --- ONGLETS ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin1", "super_admin"]: tabs_list.append("3. ⚙️ Configuration")
if MY_ROLE in ["admin1", "admin2", "super_admin"]: tabs_list.append("4. 👥 Utilisateurs")

tabs = st.tabs(tabs_list)

# ONGLET 1 : NOUVEAU DOSSIER
with tabs[0]:
    st.header("Créer un nouveau dossier")
    activities = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if not activities: st.info("⚠️ Aucune activité configurée.")
    else:
        act_choice = st.selectbox("Activité", [a['name'] for a in activities])
        act_id = next(a['id'] for a in activities if a['name'] == act_choice)
        collections = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if collections:
            col_choice = st.selectbox("Modèle", [c['name'] for c in collections])
            sel_col = next(c for c in collections if c['name'] == col_choice)
            fields = sel_col['fields']
            FORM_ID = st.session_state.form_reset_id
            
            # SIRET
            if any(f['type'] == "SIRET" for f in fields):
                with st.expander("⚡ Remplissage SIRET", expanded=True):
                    c_s, c_b = st.columns([3, 1])
                    siret_in = c_s.text_input("SIRET", key=f"siret_{FORM_ID}")
                    if c_b.button("Remplir"):
                        infos = get_siret_info(siret_in)
                        if infos:
                            for i, f in enumerate(fields):
                                k = f"f_{sel_col['id']}_{i}_{f['name']}_{FORM_ID}"
                                n = f['name'].lower()
                                if f['type'] == 'SIRET': st.session_state[k] = siret_in
                                elif "nom" in n or "raison" in n: st.session_state[k] = infos['NOM']
                                elif "adresse" in n: st.session_state[k] = infos['ADRESSE']
                                elif "ville" in n: st.session_state[k] = infos['VILLE']
                                elif "cp" in n: st.session_state[k] = infos['CP']

            st.divider()
            data = {}
            files_map = {}
            for i, f in enumerate(fields):
                key = f"f_{sel_col['id']}_{i}_{f['name']}_{FORM_ID}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Fichier/Image": files_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=key)
                else: 
                    data[f['name']] = st.text_input(f['name'], key=key)

            if st.button("💾 ENREGISTRER", type="primary", use_container_width=True):
                with st.spinner("Enregistrement..."):
                    for fname, flist in files_map.items():
                        urls = []
                        if flist:
                            for fi in flist:
                                path = f"{MY_COMPANY_ID}/{sel_col['id']}/{int(time.time())}_{fi.name}"
                                u = upload_file(fi, path)
                                if u: urls.append(u)
                        data[fname] = urls
                    supabase.table("records").insert({"collection_id": sel_col['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                    st.success("✅ Dossier créé !")
                    st.session_state.form_reset_id += 1
                    time.sleep(1)
                    st.rerun()

# ONGLET 2 : GESTION RESTAURÉE (DESIGN COMPLET)
with tabs[1]:
    st.header("📂 Gestion des Dossiers")
    my_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if my_acts:
        act_ids = [a['id'] for a in my_acts]
        my_cols = supabase.table("collections").select("*").in_("activity_id", act_ids).execute().data
        if my_cols:
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", [c['id'] for c in my_cols]).order('created_at', desc=True).execute().data
            if recs:
                search_map = {}
                for r in recs:
                    d = r['data']
                    cl = next((v for k,v in d.items() if "nom" in k.lower()), "Client")
                    label = f"👤 {cl} | 📄 {r['collections']['name']} | 📅 {r['created_at'][:10]}"
                    search_map[label] = r
                sel_label = st.selectbox("Choisir un dossier", list(search_map.keys()))
                if sel_label:
                    r = search_map[sel_label]
                    f_def = r['collections']['fields']
                    curr_d = r['data']
                    
                    # --- DESIGN MODIFICATION ---
                    st.subheader("📝 Modifier les informations")
                    with st.form(f"edit_{r['id']}"):
                        up_d = curr_d.copy()
                        for f in f_def:
                            if f['type'] == "Fichier/Image" or f['type'] == "Section/Titre": continue
                            up_d[f['name']] = st.text_input(f['name'], value=curr_d.get(f['name'], ""))
                        if st.form_submit_button("💾 Sauvegarder"):
                            supabase.table("records").update({"data": up_d}).eq("id", r['id']).execute()
                            st.success("Mis à jour !")
                            st.rerun()
                    
                    # --- DESIGN FICHIERS ---
                    st.divider()
                    st.subheader("📂 Fichiers du dossier")
                    all_urls = []
                    for f in [x for x in f_def if x['type'] == "Fichier/Image"]:
                        fname = f['name']
                        urls = curr_d.get(fname, [])
                        all_urls.extend(urls)
                        with st.expander(f"📁 {fname} ({len(urls)})"):
                            for i, u in enumerate(urls):
                                c_v, c_d = st.columns([4, 1])
                                c_v.markdown(f"📄 [Lien fichier {i+1}]({u})")
                                if c_d.button("❌", key=f"del_{r['id']}_{fname}_{i}"):
                                    urls.remove(u)
                                    curr_d[fname] = urls
                                    supabase.table("records").update({"data": curr_d}).eq("id", r['id']).execute()
                                    st.rerun()
                            up_f = st.file_uploader("Ajouter", accept_multiple_files=True, key=f"add_{r['id']}_{fname}")
                            if up_f and st.button("Envoyer", key=f"btn_{r['id']}_{fname}"):
                                for nf in up_f:
                                    p = f"{MY_COMPANY_ID}/{r['collection_id']}/{int(time.time())}_{nf.name}"
                                    pub = upload_file(nf, p)
                                    if pub: urls.append(pub)
                                curr_d[fname] = urls
                                supabase.table("records").update({"data": curr_d}).eq("id", r['id']).execute()
                                st.rerun()

                    # --- PDF & SUPPRESSION ---
                    st.divider()
                    if all_urls and st.button("📄 GÉNÉRER PDF COMPLET"):
                        pdf = merge_files_to_pdf(all_urls)
                        st.download_button("📥 Télécharger", pdf, f"Dossier_{r['id']}.pdf", "application/pdf")
                    
                    if st.button("💀 Supprimer le dossier", type="primary"):
                        supabase.table("records").delete().eq("id", r['id']).execute()
                        st.rerun()

# ONGLET 3 : CONFIGURATION RESTAURÉE
if "3. ⚙️ Configuration" in tabs_list:
    idx = tabs_list.index("3. ⚙️ Configuration")
    with tabs[idx]:
        st.header("⚙️ Configuration (Droits Gérant)")
        # 1. Activités
        st.subheader("1. Activités")
        with st.form("new_act"):
            na = st.text_input("Nom activité")
            if st.form_submit_button("Ajouter"):
                supabase.table("activities").insert({"name": na, "company_id": MY_COMPANY_ID}).execute()
                st.rerun()
        
        # 2. Modèles (Design Complet)
        st.divider()
        st.subheader("2. Modèles de dossiers")
        acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if acts:
            s_act = st.selectbox("Activité", [a['name'] for a in acts], key="conf_sel")
            s_act_id = next(a['id'] for a in acts if a['name'] == s_act)
            
            with st.expander("➕ Nouveau Modèle"):
                nm = st.text_input("Nom modèle")
                if "temp" not in st.session_state: st.session_state.temp = []
                c1, c2, c3 = st.columns([3, 2, 1])
                fn = c1.text_input("Nom champ")
                ft = c2.selectbox("Type", ["Texte Court", "SIRET", "Fichier/Image", "Section/Titre"])
                if c3.button("Ajouter"):
                    st.session_state.temp.append({"name": fn, "type": ft})
                    st.rerun()
                if st.session_state.temp:
                    st.write(st.session_state.temp)
                    if st.button("💾 Sauvegarder Modèle"):
                        supabase.table("collections").insert({"name": nm, "activity_id": s_act_id, "fields": st.session_state.temp}).execute()
                        st.session_state.temp = []
                        st.rerun()

# ONGLET 4 : UTILISATEURS RESTAURÉ (LISTE ET TABLEAU)
if "4. 👥 Utilisateurs" in tabs_list:
    idx = tabs_list.index("4. 👥 Utilisateurs")
    with tabs[idx]:
        st.header("👥 Gestion de l'équipe")
        # Création
        with st.form("add_u"):
            ue, up, ur = st.text_input("Email"), st.text_input("Pass", type="password"), st.selectbox("Rôle", ["admin2", "user"] if MY_ROLE == "admin1" else ["user"])
            if st.form_submit_button("Ajouter"):
                try:
                    res = supabase.auth.sign_up({"email": ue, "password": up})
                    supabase.table("profiles").insert({"id": res.user.id, "email": ue, "company_id": MY_COMPANY_ID, "role": ur, "full_name": ue.split('@')[0]}).execute()
                    st.success("Ajouté !")
                    st.rerun()
                except Exception as e: st.error(f"Erreur : {e}")
        
        # Affichage Liste / Tableau
        st.divider()
        st.subheader("Membres de l'entreprise")
        users = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if users:
            df_users = pd.DataFrame(users)[["email", "role", "full_name"]]
            st.dataframe(df_users, use_container_width=True)
            for u in users:
                if u['id'] != st.session_state.user.id:
                    if st.button(f"🗑️ Supprimer {u['email']}", key=f"d_u_{u['id']}"):
                        supabase.table("profiles").delete().eq("id", u['id']).execute()
                        st.rerun()
