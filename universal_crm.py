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
    st.error("⚠️ Librairie manquante : 'extra-streamlit-components'. Ajoutez-la à requirements.txt")
    st.stop()

# Import Drag & Drop
try:
    from streamlit_sortables import sort_items
except ImportError:
    st.error("⚠️ Librairie manquante : 'streamlit-sortables'. Ajoutez-la à requirements.txt")
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
        st.error(f"Erreur technique connexion Supabase : {e}")
        st.stop()

supabase = init_connection()

# --- GESTION DES COOKIES ---
cookie_manager = stx.CookieManager()

# --- GESTION ÉTAT SESSION ---
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
            if res.user and res.session:
                st.session_state.user = res.user
                profile_data = supabase.table("profiles").select("*").eq("id", res.user.id).execute().data
                if profile_data:
                    st.session_state.profile = profile_data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
        except: cookie_manager.delete("sb_refresh_token")

# --- FONCTIONS UTILITAIRES ---

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        user = res.user
        profile_data = supabase.table("profiles").select("*").eq("id", user.id).execute().data
        if profile_data:
            st.session_state.user = user
            st.session_state.profile = profile_data[0]
            if res.session:
                cookie_manager.set("sb_refresh_token", res.session.refresh_token, expires_at=datetime.now() + timedelta(days=30))
            st.success("Connexion réussie !")
            time.sleep(0.5)
            st.rerun()
        else:
            st.error("Profil non trouvé.")
            supabase.auth.sign_out()
    except Exception as e: st.error(f"Erreur de connexion : {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.profile = None
    cookie_manager.delete("sb_refresh_token")
    time.sleep(0.5)
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
# 🔐 PAGE DE LOGIN
# ==========================================
if not st.session_state.user:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Mot de passe", type="password")
            if st.form_submit_button("Se connecter", use_container_width=True):
                login(email, password)
    st.stop()

# ==========================================
# 🚀 APPLICATION PRINCIPALE
# ==========================================
if st.session_state.profile is None: logout()

MY_PROFILE = st.session_state.profile
MY_ROLE = MY_PROFILE.get('role', 'user')
MY_COMPANY_ID = MY_PROFILE.get('company_id')

with st.sidebar:
    st.markdown(f"### 👋 {MY_PROFILE.get('full_name', 'Utilisateur')}")
    st.info(f"Rôle : {MY_ROLE.upper()}") # Affichage du rôle hiérarchique
    st.divider()
    if st.button("Se déconnecter", use_container_width=True, type="primary"):
        logout()

st.title("Universal CRM SaaS 🚀")

# ------------------------------------------------------------------
# 👑 SUPER ADMIN (CREATION ADMIN 1)
# ------------------------------------------------------------------
if MY_ROLE == "super_admin":
    st.success("👑 Mode Super Admin")
    sa_tabs = st.tabs(["🏢 Gestion Entreprises", "👀 Accéder au CRM"])
    with sa_tabs[0]:
        with st.form("create_comp"):
            c_name = st.text_input("Nom Entreprise")
            a_email = st.text_input("Email Gérant (Admin 1)")
            a_pass = st.text_input("Pass temporaire", type="password")
            if st.form_submit_button("Créer Entreprise & Admin 1"):
                try:
                    res_c = supabase.table("companies").insert({"name": c_name}).execute()
                    n_id = res_c.data[0]['id']
                    res_a = supabase.auth.sign_up({"email": a_email, "password": a_pass})
                    supabase.table("profiles").insert({
                        "id": res_a.user.id, "email": a_email, "company_id": n_id, 
                        "role": "admin1", "full_name": f"Gérant {c_name}"
                    }).execute()
                    st.success("✅ Entreprise et Admin 1 créés !")
                    st.rerun()
                except Exception as e: st.error(f"Erreur : {e}")
    with sa_tabs[1]:
        all_comps = supabase.table("companies").select("*").execute().data
        comp_map = {c['name']: c['id'] for c in all_comps}
        target_name = st.selectbox("Voir en tant que :", list(comp_map.keys()))
        if target_name: MY_COMPANY_ID = comp_map[target_name]

# ------------------------------------------------------------------
# 🏢 CRM LOGIC (HIERARCHIE ADMIN 1 / ADMIN 2)
# ------------------------------------------------------------------

# Définition dynamique des onglets selon le rôle
tabs_list = ["1. 📝 Nouveau Dossier", "2. 📂 Gestion des Dossiers"]

# Seuls Super Admin et Admin 1 peuvent configurer le CRM
if MY_ROLE in ["admin1", "super_admin"]:
    tabs_list.append("3. ⚙️ Configuration")

# Super Admin, Admin 1 et Admin 2 peuvent gérer les utilisateurs
if MY_ROLE in ["admin1", "admin2", "super_admin"]:
    tabs_list.append("4. 👥 Utilisateurs")

tabs = st.tabs(tabs_list)

# ONGLET 1 : NOUVEAU
with tabs[0]:
    st.header("Créer un nouveau dossier")
    # ... (Le reste de votre code de création reste identique)
    st.info("Formulaire de création actif.")

# ONGLET 2 : GESTION
with tabs[1]:
    st.header("Gestion des dossiers")
    # ... (Le reste de votre code de gestion reste identique)
    st.info("Liste des dossiers de l'entreprise.")

# ONGLET 3 : CONFIGURATION (Réservé Admin 1 et Super Admin)
if len(tabs) > 2 and "3. ⚙️ Configuration" in tabs_list:
    current_tab_index = tabs_list.index("3. ⚙️ Configuration")
    with tabs[current_tab_index]:
        st.header("⚙️ Configuration (Droits Gérant)")
        # ... (Le reste de votre code de configuration reste identique)
        st.write("Gestion des activités et des modèles.")

# ONGLET 4 : UTILISATEURS (Hiérarchie de création et suppression)
if "4. 👥 Utilisateurs" in tabs_list:
    current_tab_index = tabs_list.index("4. 👥 Utilisateurs")
    with tabs[current_tab_index]:
        st.header("👥 Gestion de l'équipe")
        
        # Définition des rôles créables selon qui est connecté
        if MY_ROLE in ["admin1", "super_admin"]:
            possible_roles = ["admin2", "user"]
            st.caption("Vous pouvez créer des Adjoints (Admin 2) et des Utilisateurs.")
        else:
            possible_roles = ["user"]
            st.caption("Vous pouvez uniquement créer des Utilisateurs.")

        with st.form("add_user_hierarchical"):
            nu_email = st.text_input("Email")
            nu_pass = st.text_input("Mot de passe", type="password")
            nu_role = st.selectbox("Rôle à attribuer", possible_roles)
            if st.form_submit_button("Ajouter à l'équipe"):
                try:
                    res = supabase.auth.sign_up({"email": nu_email, "password": nu_pass})
                    if res.user:
                        supabase.table("profiles").insert({
                            "id": res.user.id, "email": nu_email, "company_id": MY_COMPANY_ID,
                            "role": nu_role, "full_name": nu_email.split('@')[0]
                        }).execute()
                        st.success(f"Compte {nu_role} créé !")
                        st.rerun()
                except Exception as e: st.error(f"Erreur : {e}")
        
        st.divider()
        st.subheader("Membres de l'entreprise")
        users_data = supabase.table("profiles").select("*").eq("company_id", MY_COMPANY_ID).execute().data
        
        if users_data:
            for u in users_data:
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.write(f"**{u['full_name']}**\n{u['email']}")
                c2.info(u['role'].upper())
                
                # Logique de suppression hiérarchique
                can_delete = False
                if MY_ROLE in ["admin1", "super_admin"] and u['role'] in ["admin2", "user"]:
                    can_delete = True # Admin 1 supprime tout le monde sous lui
                elif MY_ROLE == "admin2" and u['role'] == "user":
                    can_delete = True # Admin 2 supprime seulement les users
                
                # On ne peut pas se supprimer soi-même
                if u['id'] == st.session_state.user.id:
                    can_delete = False
                    c3.write("🏁 (Moi)")

                if can_delete:
                    if c3.button("🗑️", key=f"del_{u['id']}", help="Supprimer ce membre"):
                        try:
                            supabase.table("profiles").delete().eq("id", u['id']).execute()
                            st.success("Membre supprimé.")
                            time.sleep(1)
                            st.rerun()
                        except: st.error("Erreur suppression.")
