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

# --- CONFIGURATION PAGE ---
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
cookie_manager = stx.CookieManager()

# --- ÉTAT SESSION ---
if 'user' not in st.session_state: st.session_state.user = None
if 'profile' not in st.session_state: st.session_state.profile = None
if 'form_reset_id' not in st.session_state: st.session_state.form_reset_id = 0

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

# --- FONCTIONS ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            p_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
            if p_res.data:
                st.session_state.user = res.user
                st.session_state.profile = p_res.data[0]
                if res.session:
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token)
                st.rerun()
    except: st.error("Identifiants incorrects.")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    st.rerun()

def upload_file(file, path):
    try:
        file_bytes = file.getvalue()
        supabase.storage.from_("fichiers").upload(path, file_bytes, {"content-type": file.type, "upsert": "true"})
        return supabase.storage.from_("fichiers").get_public_url(path)
    except: return None

# ==========================================
# 🔐 LOGIN
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_f"):
            em = st.text_input("Email")
            pw = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(em, pw)
    st.stop()

# ==========================================
# 🚀 APPLICATION
# ==========================================
MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name')}")
    st.info(f"Rôle : {MY_ROLE.upper()}")
    if st.button("Se déconnecter", type="primary", use_container_width=True): logout()

# --- SUPER ADMIN (Sélection Entreprise) ---
if MY_ROLE == "super_admin":
    st.warning("👑 Mode Super Admin")
    all_c = supabase.table("companies").select("*").execute().data
    comp_names = ["Choisir une entreprise..."] + [c['name'] for c in all_c]
    target_name = st.selectbox("Accéder aux données de :", comp_names)
    if target_name != "Choisir une entreprise...":
        MY_COMPANY_ID = next(c['id'] for c in all_c if c['name'] == target_name)
    else:
        MY_COMPANY_ID = None

# --- VÉRIFICATION API (Fix Erreur 28fffb.jpg) ---
if not MY_COMPANY_ID and MY_ROLE == "super_admin":
    st.info("👈 Veuillez sélectionner une entreprise dans la barre latérale ou ci-dessus.")
    st.stop()

# --- ONGLETS ---
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]
if MY_ROLE in ["admin1", "super_admin"]: tabs_list.append("3. ⚙️ Configuration")
if MY_ROLE in ["admin1", "admin2", "super_admin"]: tabs_list.append("4. 👥 Utilisateurs")
tabs = st.tabs(tabs_list)

# ONGLET 1 : NOUVEAU DOSSIER
with tabs[0]:
    st.header("Créer un dossier")
    acts = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
    if not acts: st.info("Configurez une activité.")
    else:
        act_id = next(a['id'] for a in acts if a['name'] == st.selectbox("Activité", [a['name'] for a in acts]))
        cols = supabase.table("collections").select("*").eq("activity_id", act_id).execute().data
        if cols:
            mod = next(c for c in cols if c['name'] == st.selectbox("Modèle", [c['name'] for c in cols]))
            f_id = st.session_state.form_reset_id
            st.divider()
            data, f_map, main_addr = {}, {}, ""
            for i, f in enumerate(mod['fields']):
                k = f"f_{mod['id']}_{i}_{f['name']}_{f_id}"
                if f['type'] == "Section/Titre": st.markdown(f"**{f['name']}**")
                elif f['type'] == "Fichier/Image": f_map[f['name']] = st.file_uploader(f['name'], accept_multiple_files=True, key=k)
                elif f['type'] == "Texte Long": data[f['name']] = st.text_area(f['name'], key=k)
                elif f['type'] == "Adresse Travaux":
                    copy = st.checkbox(f"Copier adresse siège : {main_addr}", key=f"chk_{k}") if main_addr else False
                    data[f['name']] = st.text_input(f['name'], value=main_addr if copy else "", key=k)
                else:
                    data[f['name']] = st.text_input(f['name'], key=k)
                    if f['type'] == "Adresse": main_addr = data[f['name']]

            if st.button("💾 ENREGISTRER LE DOSSIER", type="primary", use_container_width=True):
                for fn, fl in f_map.items():
                    urls = [upload_file(fi, f"{MY_COMPANY_ID}/{mod['id']}/{int(time.time())}_{fi.name}") for fi in fl]
                    data[fn] = [u for u in urls if u]
                supabase.table("records").insert({"collection_id": mod['id'], "data": data, "created_by": st.session_state.user.id}).execute()
                st.session_state.form_reset_id += 1
                st.rerun()

# ONGLET 3 : CONFIGURATION (FIX AFFICHAGE + TOUS TYPES)
if "3. ⚙️ Configuration" in tabs_list:
    idx_conf = tabs_list.index("3. ⚙️ Configuration")
    with tabs[idx_conf]:
        st.header("⚙️ Configuration (Gérant)")
        # 1. Activités
        with st.form("a_act"):
            na = st.text_input("Nouvelle activité")
            if st.form_submit_button("Ajouter"):
                supabase.table("activities").insert({"name": na, "company_id": MY_COMPANY_ID}).execute()
                st.rerun()
        
        # 2. Modèles
        st.divider()
        acts_data = supabase.table("activities").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if acts_data:
            s_act_id = next(a['id'] for a in acts_data if a['name'] == st.selectbox("Activité :", [a['name'] for a in acts_data]))
            type_list = ["Texte Court", "Texte Long", "SIRET", "Adresse", "Adresse Travaux", "Fichier/Image", "Section/Titre"]
            
            with st.expander("➕ Créer un nouveau modèle"):
                with st.form("new_mod_f"):
                    nm = st.text_input("Nom du modèle")
                    if "tmp" not in st.session_state: st.session_state.tmp = []
                    c1, c2, c3 = st.columns([3, 2, 1])
                    fn = c1.text_input("Nom champ", key="new_f_n")
                    ft = c2.selectbox("Type", type_list, key="new_f_t")
                    if st.form_submit_button("Ajouter à la liste"):
                        st.session_state.tmp.append({"name": fn, "type": ft})
                        st.rerun()
                    if st.session_state.tmp and st.button("💾 SAUVEGARDER MODÈLE"):
                        supabase.table("collections").insert({"name": nm, "activity_id": s_act_id, "fields": st.session_state.tmp}).execute()
                        st.session_state.tmp = []
                        st.rerun()

            for m in supabase.table("collections").select("*").eq("activity_id", s_act_id).execute().data:
                with st.expander(f"📝 Gérer {m['name']}"):
                    st.markdown("#### ➕ Ajouter un champ")
                    # DESIGN CORRIGÉ : Pas de colonnes imbriquées complexes ici
                    new_fn = st.text_input("Nom du futur champ", key=f"afn_{m['id']}")
                    new_ft = st.selectbox("Type du futur champ", type_list, key=f"aft_{m['id']}")
                    if st.button("Confirmer l'ajout au modèle", key=f"abtn_{m['id']}"):
                        if new_fn:
                            u_fields = m['fields'] + [{"name": new_fn, "type": new_ft}]
                            supabase.table("collections").update({"fields": u_fields}).eq("id", m['id']).execute()
                            st.rerun()
                    
                    st.divider()
                    st.markdown("#### 🔃 Ordre & 🗑️ Suppression")
                    f_labels = [f"{f['name']} [{f['type']}]" for f in m['fields']]
                    sorted_labels = sort_items(f_labels, direction='vertical', key=f"sort_{m['id']}")
                    
                    if st.button("💾 Valider l'ordre", key=f"sv_{m['id']}"):
                        new_l = [next(f for f in m['fields'] if f"{f['name']} [{f['type']}]" == l) for l in sorted_labels]
                        supabase.table("collections").update({"fields": new_l}).eq("id", m['id']).execute()
                        st.rerun()
                    
                    to_rm = st.multiselect("Champs à supprimer :", [f['name'] for f in m['fields']], key=f"ms_{m['id']}")
                    if to_rm and st.button(f"Supprimer champs sélectionnés", key=f"cf_{m['id']}"):
                        supabase.table("collections").update({"fields": [f for f in m['fields'] if f['name'] not in to_rm]}).eq("id", m['id']).execute()
                        st.rerun()

# ONGLET 4 : UTILISATEURS (FIX SUPPRESSION DÉFINITIF)
if "4. 👥 Utilisateurs" in tabs_list:
    idx_u = tabs_list.index("4. 👥 Utilisateurs")
    with tabs[idx_u]:
        st.header("👥 Équipe")
        with st.form("u_add"):
            ue, up = st.text_input("Email"), st.text_input("Pass", type="password")
            ur = st.selectbox("Rôle", ["admin2", "user"] if MY_ROLE == "admin1" else ["user"])
            if st.form_submit_button("Ajouter"):
                res = supabase.auth.sign_up({"email": ue, "password": up})
                supabase.table("profiles").insert({"id": res.user.id, "email": ue, "company_id": MY_COMPANY_ID, "role": ur, "full_name": ue.split('@')[0]}).execute()
                st.rerun()
        
        st.divider()
        u_list = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        if u_list:
            # Affichage tableau informatif
            st.write("**Liste des membres :**")
            st.table(pd.DataFrame(u_list)[["email", "role", "full_name"]])
            
            for user in u_list:
                if user['id'] != st.session_state.user.id:
                    if (MY_ROLE == "admin1") or (MY_ROLE == "admin2" and user['role'] == "user") or (MY_ROLE == "super_admin"):
                        # FIX SUPPRESSION : On utilise st.button seul (pas dans une colonne) pour être sûr du clic
                        if st.button(f"🗑️ Supprimer définitivement : {user['email']}", key=f"d_{user['id']}"):
                            # 1. Suppression DB
                            supabase.table("profiles").delete().eq("id", user['id']).execute()
                            st.success(f"Utilisateur {user['email']} supprimé.")
                            time.sleep(1)
                            st.rerun() # INDISPENSABLE
