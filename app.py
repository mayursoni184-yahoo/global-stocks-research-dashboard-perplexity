import streamlit as st
from core.ui import render
st.set_page_config(page_title="Global Historical Filter Study", layout="wide")
market = st.sidebar.radio("Market", ["US", "UK"])
render(market)
