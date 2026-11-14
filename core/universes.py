from io import StringIO
import re
import pandas as pd
import requests
import streamlit as st
from core.config import MARKETS

SOURCES = {
 "Nasdaq-100": [("https://en.wikipedia.org/wiki/Nasdaq-100",100,105), ("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies",100,105)],
 "Dow": [("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average",30,30), ("https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies",30,30)],
 "FTSE 100": [("https://en.wikipedia.org/wiki/FTSE_100_Index",100,105)],
 "FTSE 250": [("https://en.wikipedia.org/wiki/FTSE_250_Index",245,260)],
 "FTSE AIM All-Share": [], # Repository snapshot only; no web scraping
}

def clean(value):
    return re.sub(r"\[[^\]]*\]", "", str(value)).strip()

def normalize(frame, market):
    frame=frame.copy()
    if not {"symbol","name","group"}.issubset(frame.columns):
        raise ValueError("CSV requires symbol,name,group; optional yahoo_symbol")
    for col in ["symbol","name","group"]:
        if frame[col].isna().any(): raise ValueError(f"Missing values in {col}")
        frame[col]=frame[col].astype(str).str.strip()
        if frame[col].eq("").any(): raise ValueError(f"Blank values in {col}")
    if not set(MARKETS[market]["groups"]).issubset(set(frame.group)):
        raise ValueError("All required index groups must be present; partial universe rejected")
    def ticker(row):
        override=str(row.get("yahoo_symbol", "")).strip()
        if override and override.lower()!="nan": return override
        s=row.symbol.upper()
        if market=="US": return s.replace(".","-")
        return s if s.endswith(".L") else s.rstrip(".")+".L"
    frame["ticker"]=frame.apply(ticker,axis=1)
    return frame.groupby("ticker",as_index=False).agg(symbol=("symbol","first"),name=("name","first"),group=("group",lambda x:" + ".join(sorted(set(x)))))

def parse_table(html, group, minimum, maximum):
    reasons=[]
    for table in pd.read_html(StringIO(html)):
        table.columns=[clean(c[-1] if isinstance(c,tuple) else c) for c in table.columns]
        if group=="FTSE AIM All-Share":
            if "Share" not in table.columns: continue
            values=table["Share"].dropna().map(clean)
            # Extract the LAST parenthesised token; names may contain other parentheses.
            symbols=values.str.extract(r"\(([A-Za-z0-9][A-Za-z0-9.\-]*)\)\s*$",expand=False)
            names=values.str.replace(r"\s*\([A-Za-z0-9][A-Za-z0-9.\-]*\)\s*$","",regex=True)
            rows=pd.DataFrame({"symbol":symbols,"name":names}).dropna()
        else:
            sym=next((c for c in ["Ticker","Symbol","EPIC"] if c in table.columns),None)
            name=next((c for c in ["Company","Name","Investment"] if c in table.columns),None)
            if not sym or not name: continue
            rows=table[[sym,name]].dropna().copy(); rows.columns=["symbol","name"]
            for col in rows: rows[col]=rows[col].map(clean)
        rows=rows[rows.symbol.str.match(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")].drop_duplicates("symbol")
        if not minimum<=len(rows)<=maximum:
            reasons.append(f"{len(rows)} tickers; expected {minimum}–{maximum}"); continue
        rows["group"]=group
        return rows
    raise ValueError("No validated constituent table: "+"; ".join(reasons))



def load_aim_snapshot():
    from pathlib import Path
    import json
    import hashlib
    root = Path(__file__).resolve().parent.parent
    csv_path = root / "data" / "ftse_aim_all_share.csv"
    meta_path = root / "data" / "ftse_aim_all_share_metadata.json"
    if not csv_path.is_file() or not meta_path.is_file():
        raise ValueError("AIM snapshot missing. Add data/ftse_aim_all_share.csv and data/ftse_aim_all_share_metadata.json at repository root. No live AIM scrape is attempted.")
    raw = csv_path.read_bytes()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if hashlib.sha256(raw).hexdigest() != meta.get("csv_sha256"):
        raise ValueError("AIM CSV integrity check failed; CSV differs from its metadata. Regenerate metadata when intentionally updating the snapshot.")
    rows = pd.read_csv(StringIO(raw.decode("utf-8")), dtype=str, keep_default_na=False)
    required = {"symbol", "name", "group", "yahoo_symbol"}
    if not required.issubset(rows.columns):
        raise ValueError("AIM snapshot columns missing")
    if rows.empty or any(rows[c].str.strip().eq("").any() for c in required):
        raise ValueError("Empty AIM snapshot or blank constituent fields")
    if set(rows.group) != {"FTSE AIM All-Share"}:
        raise ValueError("AIM snapshot has unexpected group values")
    if rows.symbol.duplicated().any() or rows.yahoo_symbol.duplicated().any():
        raise ValueError("AIM snapshot contains duplicate symbols")
    if len(rows) != meta.get("rows"):
        raise ValueError("AIM snapshot count differs from metadata")
    report = dict(group="FTSE AIM All-Share", rows=len(rows),
        source="Repository CSV — originally user-saved London South East page",
        snapshot_extracted_date=meta.get("snapshot_extracted_date"),
        membership_as_of=meta.get("membership_as_of"),
        retrieved_utc=pd.Timestamp.now(tz="UTC").isoformat(),
        validation="File integrity and count checked; current membership and Yahoo aliases not independently verified")
    return rows, report

@st.cache_data(ttl=86400,show_spinner=False)
def load(market):
    frames=[]; report=[]
    for group in MARKETS[market]["groups"]:
        if group == "FTSE AIM All-Share":
            rows, snapshot_report = load_aim_snapshot()
            frames.append(rows)
            report.append(snapshot_report)
            continue
        errors=[]; rows=None
        for url,minimum,maximum in SOURCES[group]:
            try:
                response=requests.get(url,headers={"User-Agent":"GlobalHistoricalStudy/1.2 (public constituent research)"},timeout=45)
                response.raise_for_status()
                rows=parse_table(response.text,group,minimum,maximum)
                report.append(dict(group=group,rows=len(rows),source=url,retrieved_utc=pd.Timestamp.now(tz="UTC").isoformat(),validation="Table/count sanity checks only; membership and completeness not independently verified"))
                break
            except Exception as error: errors.append(f"{url}: {type(error).__name__}: {error}")
        if rows is None:
            raise ValueError(f"{group}: all sources failed. Upload a verified full-universe CSV. Details: "+" | ".join(errors))
        frames.append(rows)
    return normalize(pd.concat(frames,ignore_index=True),market),pd.DataFrame(report)
