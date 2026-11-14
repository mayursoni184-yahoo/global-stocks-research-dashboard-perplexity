from io import StringIO
import hashlib
import re
import pandas as pd
import requests
import streamlit as st
from core.universes import SOURCES, parse_table
URL="https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"

def parse_directory(text):
    lines=text.lstrip("\ufeff").splitlines()
    footer=[x for x in lines if x.startswith("File Creation Time")]
    lines=[x for x in lines if x.strip() and not x.startswith("File Creation Time")]
    raw=pd.read_csv(StringIO("\n".join(lines)),sep="|",dtype=str,keep_default_na=False)
    required={"Symbol","Security Name","Test Issue","ETF","NextShares"}
    if not required.issubset(raw.columns): raise ValueError("Not a Nasdaq-listed directory: missing required columns")
    if len(raw)<1000: raise ValueError(f"Directory has only {len(raw)} rows; refusing potentially incomplete input")
    name=raw["Security Name"]
    # Eligibility is explicit and auditable; naming rules are not a security master.
    reason=pd.Series("",index=raw.index)
    reason.loc[raw["Test Issue"].ne("N")]="Test issue or unknown test flag"
    reason.loc[reason.eq("") & raw.ETF.ne("N")]="ETF or unknown ETF flag"
    reason.loc[reason.eq("") & raw.NextShares.ne("N")]="NextShares or unknown flag"
    excluded=name.str.contains(r"warrants?|rights?|units?|preferred|preference|depositary shares.*(?:1/|fraction|interest in)",case=False,regex=True)
    reason.loc[reason.eq("") & excluded]="Excluded security type by name"
    ordinary=name.str.contains(r"common stock|common shares|ordinary shares|ordinary stock|american depositary|american depository|\bADRs?\b|\bADSs?\b|beneficial interest",case=False,regex=True)
    reason.loc[reason.eq("") & ~ordinary]="Unclassified security — requires manual review"
    raw["eligibility_reason"]=reason.where(reason.ne(""),"Candidate company share/ADR/beneficial interest")
    raw["included"]=reason.eq("")
    good=raw.loc[raw.included]
    frame=pd.DataFrame({"symbol":good.Symbol,"name":good["Security Name"],"group":"All Nasdaq"})
    frame["ticker"]=frame.symbol.str.replace(".","-",regex=False)
    if frame.ticker.duplicated().any(): raise ValueError("Duplicate normalized Nasdaq symbols")
    return frame,raw,(footer[0] if footer else "Source creation timestamp not supplied")

@st.cache_data(ttl=86400,show_spinner=False)
def get_directory():
    r=requests.get(URL,timeout=60,headers={"User-Agent":"GlobalHistoricalStudy/2.0"})
    r.raise_for_status(); return r.text

@st.cache_data(ttl=86400,show_spinner=False)
def get_dow():
    errors=[]
    for url,minimum,maximum in SOURCES["Dow"]:
        try:
            r=requests.get(url,timeout=45,headers={"User-Agent":"GlobalHistoricalStudy/2.0"})
            r.raise_for_status()
            rows=parse_table(r.text,"Dow",minimum,maximum)
            rows["ticker"]=rows.symbol.str.replace(".","-",regex=False)
            return rows,url
        except Exception as e: errors.append(f"{url}: {e}")
    raise ValueError("Dow source failed: "+" | ".join(errors))

def combine(nasdaq,dow):
    if dow.ticker.nunique()!=30: raise ValueError("Exactly 30 distinct Dow tickers are required")
    return pd.concat([nasdaq,dow],ignore_index=True).groupby("ticker",as_index=False).agg(
        symbol=("symbol","first"),name=("name","first"),group=("group",lambda x:" + ".join(sorted(set(x)))))

def universe_hash(u):
    return hashlib.sha256(u.sort_values("ticker").to_csv(index=False).encode()).hexdigest()
