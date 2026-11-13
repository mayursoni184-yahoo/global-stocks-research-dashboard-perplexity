from io import StringIO
import re
import pandas as pd
import requests
import streamlit as st
from core.config import MARKETS

# Public HTML sources can fail; each source is independently validated.
SOURCES = {
 "Nasdaq-100": [
  ("https://en.wikipedia.org/wiki/Nasdaq-100", ["Ticker", "Symbol"], ["Company", "Name"], 100, 105),
  ("https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies", ["Ticker", "Symbol"], ["Company", "Name"], 100, 105)],
 "Dow": [
  ("https://en.wikipedia.org/wiki/Dow_Jones_Industrial_Average", ["Symbol", "Ticker"], ["Company", "Name"], 30, 30),
  ("https://en.wikipedia.org/wiki/List_of_Dow_Jones_Industrial_Average_companies", ["Symbol", "Ticker"], ["Company", "Name"], 30, 30)],
 "FTSE 100": [("https://research-centre.barclays.co.uk/shares/indices/ftse-100/", ["EPIC"], ["Investment", "Company", "Name"], 95, 110)],
 "FTSE 250": [("https://research-centre.barclays.co.uk/shares/indices/ftse-250/", ["EPIC"], ["Investment", "Company", "Name"], 230, 270)],
 "FTSE AIM All-Share": [("https://research-centre.barclays.co.uk/shares/indices/ftse-aim-all-share/", ["EPIC"], ["Investment", "Company", "Name"], 200, 1500)],
}

def clean(value):
    return re.sub(r"\[[^\]]*\]", "", str(value)).strip()

def normalize(frame, market):
    required={"symbol", "name", "group"}
    if not required.issubset(frame.columns):
        raise ValueError("CSV needs symbol,name,group columns; optional yahoo_symbol column.")
    frame=frame.copy()
    for col in required:
        if frame[col].isna().any(): raise ValueError(f"Missing values in {col}")
        frame[col]=frame[col].astype(str).str.strip()
        if frame[col].eq("").any(): raise ValueError(f"Blank values in {col}")
    if not set(MARKETS[market]["groups"]).issubset(set(frame.group)):
        raise ValueError("Every required index group must be present; partial universes are not accepted.")
    def ticker(row):
        supplied=str(row.get("yahoo_symbol", "")).strip()
        if supplied and supplied.lower()!="nan": return supplied
        symbol=row.symbol.upper()
        if market=="US": return symbol.replace(".", "-")
        return symbol if symbol.endswith(".L") else symbol.rstrip(".")+".L"
    frame["ticker"]=frame.apply(ticker,axis=1)
    return frame.groupby("ticker",as_index=False).agg(
        symbol=("symbol","first"),name=("name","first"),
        group=("group",lambda x:" + ".join(sorted(set(x)))))

def parse_table(html, group, symbols, names, minimum, maximum):
    problems=[]
    for table in pd.read_html(StringIO(html)):
        table.columns=[clean(c[-1] if isinstance(c,tuple) else c) for c in table.columns]
        symbol_col=next((c for c in symbols if c in table.columns),None)
        name_col=next((c for c in names if c in table.columns),None)
        if symbol_col is None or name_col is None: continue
        rows=table[[symbol_col,name_col]].dropna().copy()
        rows.columns=["symbol","name"]
        for col in rows: rows[col]=rows[col].map(clean)
        rows=rows[rows.symbol.str.match(r"^[A-Za-z0-9][A-Za-z0-9.\-]*$")]
        rows=rows.drop_duplicates("symbol")
        n=len(rows)
        if not minimum<=n<=maximum:
            problems.append(f"candidate table contained {n} tickers; expected {minimum}–{maximum}")
            continue
        rows["group"]=group
        return rows
    raise ValueError("No validated constituent table. "+"; ".join(problems))

@st.cache_data(ttl=86400, show_spinner=False)
def load(market):
    frames=[]; reports=[]
    for group in MARKETS[market]["groups"]:
        errors=[]; selected=None
        for url,symbols,names,minimum,maximum in SOURCES[group]:
            try:
                response=requests.get(url,headers={"User-Agent":"GlobalHistoricalStudy/1.1 (public constituent research; Python requests)"},timeout=45)
                response.raise_for_status()
                selected=parse_table(response.text,group,symbols,names,minimum,maximum)
                reports.append(dict(group=group,rows=len(selected),source=url,
                    retrieved_utc=pd.Timestamp.now(tz="UTC").isoformat(),
                    validation="Count/column checks only; membership not independently verified"))
                break
            except Exception as error:
                errors.append(f"{url}: {type(error).__name__}: {error}")
        if selected is None:
            raise ValueError(f"{group}: all sources failed. Upload a verified full-universe CSV. Details: "+" | ".join(errors))
        frames.append(selected)
    return normalize(pd.concat(frames,ignore_index=True),market),pd.DataFrame(reports)
