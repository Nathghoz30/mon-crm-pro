# --- AJUSTEMENT SÉCURITÉ V30 ---

# 1. Pont JavaScript pour le Hash (#)
components.html(
    """
    <script>
    var hash = window.location.hash;
    if (hash && (hash.includes('type=recovery') || hash.includes('access_token'))) {
        var newUrl = window.location.origin + window.location.pathname + hash.replace('#', '?');
        window.location.href = newUrl;
    }
    </script>
    """, height=0
)

# 2. Détection Recovery
is_recovery_mode = st.query_params.get("type") == "recovery"

# 3. Reconnexion automatique améliorée
if not st.session_state.user and not is_recovery_mode:
    refresh_token = cookie_manager.get("sb_refresh_token")
    if refresh_token:
        try:
            res = supabase.auth.refresh_session(refresh_token)
            if res.user and res.session:
                # On s'assure de récupérer le profil AVANT d'autoriser l'accès
                p_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
                if p_res.data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_res.data[0]
                    cookie_manager.set("sb_refresh_token", res.session.refresh_token)
        except:
            cookie_manager.delete("sb_refresh_token")

# 4. Écran de connexion (avec gestion d'erreur propre)
if not st.session_state.user and not is_recovery_mode:
    st.markdown("<h1 style='text-align: center;'>🔐 Connexion CRM</h1>", unsafe_allow_html=True)
    with st.container():
        email = st.text_input("Email")
        password = st.text_input("Mot de passe", type="password")
        if st.button("Se connecter", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                p_res = supabase.table("profiles").select("*").eq("id", res.user.id).execute()
                if p_res.data:
                    st.session_state.user = res.user
                    st.session_state.profile = p_res.data[0]
                    st.rerun()
                else:
                    st.error("Profil introuvable. Contactez le Super Admin.")
            except:
                st.error("Identifiants incorrects ou mail non confirmé.")
    st.stop()
