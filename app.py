import streamlit as st
st.set_page_config(page_title="Global Historical Filter Study", layout="wide")
from core.ui import render
page = st.sidebar.radio("Market", ["US", "UK", "Expanded US — All Nasdaq + Dow"])
if page in ("US", "UK"):
    render(page)
else:
    from core.expanded_us_ui import render_expanded
    render_expanded()
