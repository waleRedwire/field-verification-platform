"""
Login + forced password change.
"""
import streamlit as st
from db import authenticate_user, change_password, ensure_admin_user, get_user_by_id


def bootstrap_admin_from_secrets():
    try:
        a = st.secrets["admin"]
        ensure_admin_user(
            username=str(a["username"]),
            email=str(a["email"]),
            name=str(a.get("name", "Administrator")),
            password=str(a["password"]),
        )
    except Exception:
        ensure_admin_user(
            username="admin",
            email="admin@local",
            name="Administrator",
            password="Admin@12345",
        )


def require_login():
    bootstrap_admin_from_secrets()

    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.user is None:
        st.markdown(
            """
            <div style="max-width:420px;margin:4rem auto 1.5rem auto;text-align:center;">
              <div style="font-size:0.75rem;letter-spacing:0.12em;text-transform:uppercase;
                          color:#64748b;font-weight:600;margin-bottom:0.5rem;">Secure access</div>
              <h1 style="margin:0;font-size:1.75rem;color:#0f172a;font-weight:700;">
                Field Verification Platform
              </h1>
              <p style="color:#64748b;margin-top:0.5rem;font-size:0.95rem;">
                Sign in with your username and password
              </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        left, center, right = st.columns([1, 1.2, 1])
        with center:
            with st.form("login_form"):
                username = st.text_input("Username")
                password = st.text_input("Password", type="password")
                submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)
            if submitted:
                user = authenticate_user(username, password)
                if not user:
                    st.error("Invalid username or password.")
                    st.stop()
                st.session_state.user = user
                st.rerun()
        st.stop()

    user = st.session_state.user
    fresh = get_user_by_id(user["id"])
    if not fresh or not fresh.get("is_active"):
        st.session_state.user = None
        st.warning("Account inactive or not found. Please log in again.")
        st.stop()
    st.session_state.user = fresh
    user = fresh

    if user.get("must_change_password"):
        st.markdown(
            """
            <div style="max-width:420px;margin:3rem auto 1rem auto;text-align:center;">
              <h2 style="margin:0;color:#0f172a;">Create a new password</h2>
              <p style="color:#64748b;">Required on first login before you can use the app.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        left, center, right = st.columns([1, 1.2, 1])
        with center:
            with st.form("change_pw_form"):
                p1 = st.text_input("New password", type="password")
                p2 = st.text_input("Confirm new password", type="password")
                ok = st.form_submit_button("Save password", type="primary", use_container_width=True)
            if ok:
                if p1 != p2:
                    st.error("Passwords do not match.")
                elif len(p1) < 8:
                    st.error("Use at least 8 characters.")
                else:
                    result = change_password(user["id"], p1)
                    if result["ok"]:
                        st.success("Password updated.")
                        st.session_state.user = get_user_by_id(user["id"])
                        st.rerun()
                    else:
                        st.error(result["error"])
        st.stop()

    return user


def logout_button():
    if st.sidebar.button("Sign out", use_container_width=True):
        st.session_state.user = None
        st.session_state.current_project_id = None
        st.rerun()