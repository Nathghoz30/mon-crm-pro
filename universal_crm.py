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
        st.error(f"Erreur connexion : {e}")
        st.stop()

supabase = init_connection()

# --- GESTION ÉTAT SESSION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'profile' not in st.session_state: st.session_state.profile = None
if 'form_reset_id' not in st.session_state: st.session_state.form_reset_id = 0

# --- FONCTION LOGIN (FIX DOUBLE CLIC V45) ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            # Récupération FORCÉE immédiate du profil
            p_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
            if p_res.data:
                st.session_state.user = res.user
                st.session_state.profile = p_res.data[0]
                st.success("✅ Connecté !")
                time.sleep(0.5)
                st.rerun()
    except:
        st.error("❌ Identifiants incorrects.")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    st.rerun()

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

# ==========================================
# 🔐 ÉCRAN DE CONNEXION
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
# 🚀 APPLICATION PRINCIPALE
# ==========================================
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.info(f"Rôle : {MY_ROLE.upper()}")
    if st.button("Se déconnecter", use_container_width=True): logout()

# --- FIX SUPER ADMIN (Image 28fffb.jpg) ---
if MY_ROLE == "super_admin":
    all_comps = supabase.table("companies").select("*").execute().data
    target = st.selectbox("🏢 Entreprise à gérer :", ["Choisir..."] + [c['name'] for c in all_comps])
    if target != "Choisir...":
        MY_COMPANY_ID = next(c['id'] for c in all_comps if c['name'] == target)
    else:
        st.warning("👈 Sélectionnez une entreprise pour voir les dossiers.")
        st.stop()

# --- ONGLETS ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin1", "super_admin"]: tabs_list.append("3. ⚙️ Configuration")
if MY_ROLE in ["admin1", "admin2", "super_admin"]: tabs_list.append("4. 👥 Utilisateurs")
tabs = st.tabs(tabs_list)

# ONGLET 1 : CRÉATION (RESTAURÉ)
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if acts:
        act_sel = st.selectbox("Activité", [a['name'] for a in acts])
        act_id = next(a['id'] for a in acts if a['name'] == act_sel)
        cols = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if cols:
            mod = next(c for c in cols if c['name'] == st.selectbox("Modèle", [c['name'] for c in cols]))
            st.divider()
            data, f_map = {}, {}
            for i, f in enumerate(mod['fields']):
                k = f"f_{mod['id']}_{i}_{f['name']}_{st.session_state.form_reset_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Fichier/Image": f_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=k)
                else: data[f['name']] = st.text_input(f['name'], key=k)

            if st.button("💾 ENREGISTRER", type="primary"):
                for fn, fl in f_map.items():
                    urls = [upload_file(fi, f"{MY_COMPANY_ID}/{mod['id']}/{int(time.time())}_{fi.name}") for fi in fl]
                    data[fn] = [u for u in urls if u]
                supabase.table("records").insert({"collection_id": mod['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.session_state.form_reset_id += 1
                st.rerun()

# ONGLET 2 : GESTION RESTAURÉE (Fix image 290b03.png)
with tabs[1]:
    st.header("Gestion des Dossiers")
    # On récupère les colonnes de l'entreprise
    m_acts = supabase.table("activities").select("id").eq("company_id", MY_COMPANY_ID).execute().data
    if m_acts:
        a_cols = supabase.table("collections").select("*").in_("activity_id", [a['id'] for a in m_acts]).execute().data
        if a_cols:
            recs = supabase.table("records").select("*, collections(name, fields)").in_("collection_id", [c['id'] for c in a_cols]).order('created_at', desc=True).execute().data
            if recs:
                s_map = {f"👤 {r['data'].get('nom', 'Dossier')} | 📄 {r['collections']['name']} | 📅 {r['created_at'][:10]}": r for r in recs}
                sel_label = st.selectbox("Choisir dossier", list(s_map.keys()))
                if sel_label:
                    r = s_map[sel_label]
                    # --- FORMULAIRE DE MODIF ---
                    with st.form(f"edit_{r['id']}"):
                        up_d = r['data'].copy()
                        for f in r['collections']['fields']:
                            if f['type'] in ["Fichier/Image", "Section/Titre"]: continue
                            up_d[f['name']] = st.text_input(f['name'], value=r['data'].get(f['name'], ""))
                        if st.form_submit_button("💾 Sauvegarder"):
                            supabase.table("records").update({"data": up_d}).eq("id", r['id']).execute()
                            st.rerun()
                    
                    if st.button("💀 Supprimer Dossier", type="primary"):
                        supabase.table("records").delete().eq("id", r['id']).execute()
                        st.rerun()
            else: st.info("Aucun dossier enregistré.")
        else: st.info("Créez d'abord un modèle dans l'onglet Configuration.")

# ONGLET 4 : UTILISATEURS (FIX SUPPRESSION DÉFINITIF)
if "4. 👥 Utilisateurs" in tabs_list:
    with tabs[tabs_list.index("4. 👥 Utilisateurs")]:
        st.header("👥 Équipe")
        u_list = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if u_list:
            st.write("**Membres actuels :**")
            st.dataframe(pd.DataFrame(u_list)[["email", "role"]], use_container_width=True)
            for u in u_list:
                if u['id'] != st.session_state.user.id:
                    if st.button(f"🗑️ Supprimer {u['email']}", key=f"d_{u['id']}"):
                        supabase.table("profiles").delete().eq("id", u['id']).execute()
                        st.success("Utilisateur retiré.")
                        time.sleep(0.5)
                        st.rerun() # INDISPENSABLE
