from io import StringIO
import pandas as pd
import requests
import streamlit as st
from core.config import MARKETS
SOURCES = {
 "Nasdaq-100": ("https://www.slickcharts.com/nasdaq100", "Symbol", 90),
 "Dow": ("https://www.slickcharts.com/dowjones", "Symbol", 30),
 "FTSE 100": ("https://research-centre.barclays.co.uk/shares/indices/ftse-100/", "EPIC", 95),
 "FTSE 250": ("https://research-centre.barclays.co.uk/shares/indices/ftse-250/", "EPIC", 230),
 "FTSE AIM All-Share": ("https://research-centre.barclays.co.uk/shares/indices/ftse-aim-all-share/", "EPIC", 200),
}
def normalize(frame, market):
    required={"symbol", "name", "group"}
    if not required.issubset(frame.columns):
        raise ValueError("CSV needs symbol,name,group columns; optional yahoo_symbol column.")
    frame=frame.copy()
    for col in required:
        if frame[col].isna().any():
            raise ValueError(f"Missing values in {col}")
        frame[col]=frame[col].astype(str).str.strip()
    if not set(MARKETS[market]["groups"]).issubset(set(frame.group)):
        raise ValueError("Every required index group must be present; partial universes are not accepted.")
    def ticker(row):
        supplied=str(row.get("yahoo_symbol", "")).strip()
        if supplied and supplied.lower()!="nan": return supplied
        s=row.symbol.strip().upper()
        if market=="US": return s.replace(".", "-")
        return s if s.endswith(".L") else s.rstrip(".")+".L"
    frame["ticker"]=frame.apply(ticker,axis=1)
    return frame.groupby("ticker",as_index=False).agg(
        symbol=("symbol","first"),name=("name","first"),
        group=("group",lambda x:" + ".join(sorted(set(x)))))
@st.cache_data(ttl=86400, show_spinner=False)
def load(market):
    rows=[]; report=[]
    for group in MARKETS[market]["groups"]:
        url,key,minimum=SOURCES[group]
        response=requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=45)
        response.raise_for_status()
        tables=pd.read_html(StringIO(response.text))
        selected=None
        for table in tables:
            table.columns=[str(c[-1] if isinstance(c,tuple) else c).strip() for c in table.columns]
            if key in table.columns:
                selected=table; break
        if selected is None: raise ValueError(f"{group}: expected ticker table missing. Upload a verified CSV instead.")
        selected=selected.dropna(subset=[key]).copy()
        selected=selected[selected[key].astype(str).str.match(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")]
        if selected[key].nunique()<minimum:
            raise ValueError(f"{group}: only {selected[key].nunique()} symbols found; may be paginated/incomplete. Upload verified CSV.")
        namecol=next((c for c in ["Company", "Investment", "Name"] if c in selected),key)
        rows.extend(dict(symbol=str(r[key]),name=str(r[namecol]),group=group) for _,r in selected.iterrows())
        report.append(dict(group=group,rows=len(selected),source=url,
                           retrieved_utc=pd.Timestamp.now(tz="UTC").isoformat()))
    return normalize(pd.DataFrame(rows),market),pd.DataFrame(report)
