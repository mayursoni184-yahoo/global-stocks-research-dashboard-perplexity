from io import StringIO
import json
import time
import pandas as pd
import streamlit as st
from core.expanded_us_universe import get_directory, parse_directory, get_dow, combine, universe_hash, URL
from core.data import cap, history, completed
from core.historical import indicators, records, calculate_historical_study_summary
KEY="expanded_us_v1"
THRESHOLD=1_000_000_000

def encode_frame(frame):
    return json.loads(frame.to_json(orient="table",date_format="iso",index=False))

def decode_frame(obj):
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list): raise ValueError("Invalid checkpoint table")
    frame=pd.DataFrame(obj["data"])
    for col in frame:
        if col in ("signal_date","entry_date"): frame[col]=pd.to_datetime(frame[col],errors="raise")
        if col.startswith("hit_10pct_"): frame[col]=pd.array(frame[col],dtype="boolean")
    return frame

def export_state(state):
    return json.dumps(dict(version=KEY,threshold=THRESHOLD,
        universe=encode_frame(state["u"]),source_report=state["source_report"],
        universe_hash=universe_hash(state["u"]),diagnostics=state["diag"],
        signals=encode_frame(state["signals"]),created_utc=state["created_utc"]),allow_nan=False)

def import_state(text):
    obj=json.loads(text)
    if obj.get("version")!=KEY or obj.get("threshold")!=THRESHOLD: raise ValueError("Wrong checkpoint version/threshold")
    u=decode_frame(obj["universe"])
    if not {"ticker","name","group","symbol"}.issubset(u.columns) or u.empty or u.ticker.duplicated().any(): raise ValueError("Invalid checkpoint universe")
    if universe_hash(u)!=obj.get("universe_hash"): raise ValueError("Checkpoint universe hash mismatch")
    diag=obj["diagnostics"]
    if not isinstance(diag,list): raise ValueError("Invalid diagnostics")
    tickers=[r["ticker"] for r in diag]
    if len(set(tickers))!=len(tickers) or not set(tickers).issubset(set(u.ticker)): raise ValueError("Invalid processed tickers")
    signals=decode_frame(obj["signals"])
    if not signals.empty:
        required={"ticker","signal_date","entry_status"}
        for h in ["5d","10d","20d","30d","60d","90d","6m","9m","12m"]:
            required.update(["max_ret_"+h,"hit_10pct_"+h])
        required.update("min_ret_"+h for h in ["30d","60d","90d","6m","12m"])
        if not required.issubset(signals.columns): raise ValueError("Checkpoint signal columns missing")
        if not set(signals.ticker).issubset(set(tickers)): raise ValueError("Signal/processed ticker mismatch")
    return dict(u=u,diag=diag,signals=signals,source_report=obj["source_report"],created_utc=obj["created_utc"])

def scan_remaining(state, pause, progress):
    done={r["ticker"] for r in state["diag"]}
    todo=state["u"].loc[~state["u"].ticker.isin(done)].sort_values("ticker")
    stopped=False
    for _,stock in todo.iterrows():
        row=dict(ticker=stock.ticker,name=stock["name"],group=stock.group,checked_utc=pd.Timestamp.now(tz="UTC").isoformat())
        progress(len(state["diag"]),len(state["u"]),stock.ticker)
        try:
            value,note=cap(stock.ticker,"US")
            row.update(market_cap=value,currency="USD",cap_note=note)
            if value<=THRESHOLD: row.update(status="Below/equal USD1bn",signals=0)
            else:
                data,schedule=completed(history(stock.ticker),"US")
                if len(data)<200: raise ValueError(f"Insufficient completed daily rows: {len(data)}")
                data=indicators(data,schedule)
                r=records(data,stock,value)
                if not r.empty: state["signals"]=pd.concat([state["signals"],r],ignore_index=True)
                row.update(status="Signals found" if len(r) else "No matching signal",signals=len(r),daily_rows=len(data))
        except Exception as e:
            row.update(status="Error",signals=0,reason=f"{type(e).__name__}: {e}")
        state["diag"].append(row)
        progress(len(state["diag"]),len(state["u"]),stock.ticker)
        if row["status"]=="Error" and any(x in row.get("reason","").lower() for x in ["ratelimit","too many requests","rate limit","429"]):
            stopped=True;break
        time.sleep(pause)
    return stopped

def render_expanded():
    st.title("Expanded US — All Nasdaq + Dow")
    st.caption("Simplified full-run interface v2 — one combined study; no manual batch merging.")
    st.info("Current USD market cap strictly greater than $1 billion. Existing US/UK pages and historical engine are unchanged.")
    st.warning("Current listings/current market caps introduce selection and survivorship bias. Directory classification is heuristic; inspect excluded instruments in the audit.")
    with st.expander("Universe source options / audit"):
        st.write("Leave uploads empty for automatic Nasdaq directory + Dow retrieval. Use browser-downloaded source files only if automatic retrieval fails.")
        st.code(URL,language=None)
        directory=st.file_uploader("Optional Nasdaq directory .txt",type=["txt"],key="ex_directory")
        dow_csv=st.file_uploader("Optional Dow CSV: symbol,name (30 distinct tickers)",type=["csv"],key="ex_dow")
        st.caption("Common/ordinary shares, ADRs and beneficial-interest shares are candidates. Funds, tests, warrants, units, preferred shares, rights and unclassified names are excluded by the directory loader rules. USD market-cap validation is checked separately.")
    if st.button("Load expanded universe / Start fresh",key="ex_load"):
        try:
            text=directory.getvalue().decode("utf-8-sig") if directory else get_directory()
            n,audit,source_time=parse_directory(text)
            if dow_csv:
                d=pd.read_csv(dow_csv,dtype=str,keep_default_na=False)
                if not {"symbol","name"}.issubset(d.columns): raise ValueError("Dow CSV requires symbol,name")
                d=d[["symbol","name"]].copy();d["group"]="Dow"
                d["ticker"]=d.symbol.str.strip().str.replace(".","-",regex=False)
                dsource="User CSV; membership not independently verified"
            else: d,dsource=get_dow()
            u=combine(n,d);stamp=pd.Timestamp.now(tz="UTC").isoformat()
            report=dict(nasdaq_source="User directory" if directory else URL,directory_creation=source_time,
                        dow_source=dsource,loaded_utc=stamp,raw_directory_rows=len(audit),nasdaq_candidates=len(n),combined_unique=len(u))
            st.session_state[KEY]=dict(u=u,diag=[],signals=pd.DataFrame(),source_report=report,created_utc=stamp)
            st.session_state[KEY+"_audit"]=audit
        except Exception as e: st.error(f"Universe load failed: {type(e).__name__}: {e}")
    with st.expander("Optional recovery — restore a previous checkpoint"):
        checkpoint=st.file_uploader("Your expanded-US JSON checkpoint",type=["json"],key="ex_restore")
        if st.button("Restore checkpoint",key="ex_restore_go"):
            try:
                if checkpoint is None: raise ValueError("Choose a checkpoint first")
                state=import_state(checkpoint.getvalue().decode("utf-8"))
                st.session_state[KEY]=state;st.session_state.pop(KEY+"_audit",None)
                st.success("Restored combined results and progress; no merging required.")
            except Exception as e: st.error(f"Restore failed: {e}")
    state=st.session_state.get(KEY)
    if state is None:
        st.info("Click Load expanded universe, then Run / Continue Full Study.");return
    st.write(f"Loaded candidate universe: {len(state['u']):,} unique tickers.")
    with st.expander("Loaded source report and full candidate list"):
        st.json(state["source_report"]);st.dataframe(state["u"],hide_index=True)
        st.download_button("Download candidate universe",state["u"].to_csv(index=False),"expanded_us_universe.csv",key="ex_u_dl")
        audit=st.session_state.get(KEY+"_audit")
        if audit is not None:
            st.dataframe(audit,hide_index=True)
            st.download_button("Download inclusion/exclusion audit",audit.to_csv(index=False),"nasdaq_security_audit.csv",key="ex_a_dl")
    with st.expander("Advanced scan controls"):
        pause=st.selectbox("Pause per stock (seconds)",[1,2,3,5],index=1,key="ex_pause")
        if st.button("Requeue failed stocks only",key="ex_requeue"):
            failed={r["ticker"] for r in state["diag"] if r["status"]=="Error"}
            state["diag"]=[r for r in state["diag"] if r["ticker"] not in failed]
            st.info(f"Requeued {len(failed)} errors. Click Run / Continue Full Study to retry them.")
    st.caption("One click processes all remaining candidates automatically. Keep this tab open. It may take a long time; the $1bn filter still requires market-cap lookups. Saved results from earlier batches are reused.")
    if st.button("Run / Continue Full Study",type="primary",key="ex_run_full"):
        bar=st.progress(len(state["diag"])/len(state["u"]));msg=st.empty()
        def progress(done,total,ticker):
            bar.progress(done/total);msg.write(f"Attempted {done:,} / {total:,} — {ticker}")
        stopped=scan_remaining(state,pause,progress)
        bar.empty();msg.empty()
        if stopped: st.warning("Provider rate limit detected. Progress is retained in this session. Wait, then click Run / Continue Full Study for untouched stocks; requeue errors separately when ready.")
    diag=pd.DataFrame(state["diag"]);signals=state["signals"]
    attempted=len(diag);errors=int((diag.status=="Error").sum()) if attempted else 0
    c1,c2,c3=st.columns(3)
    c1.metric("Attempted / candidates",f"{attempted} / {len(state['u'])}");c2.metric("Errors",errors);c3.metric("Signal records",len(signals))
    if attempted<len(state["u"]) or errors: st.warning("Partial / incomplete coverage: remaining candidates or errors exist. Tables combine all successfully evaluated stocks so far.")
    else: st.success("All candidates attempted without recorded errors. Market-cap and other eligibility exclusions still apply.")
    if not signals.empty:
        summary=calculate_historical_study_summary(signals)
        st.subheader("Forward Outcome Summary")
        h=summary["horizon_summary"]
        st.dataframe(h.style.format({c:"{:.2f}%" for c in h if c not in ["Horizon","Completed Signals"]},na_rep="NA"),hide_index=True)
        st.download_button("Download combined outcome summary",h.to_csv(index=False),"expanded_us_outcomes.csv",key="ex_h_dl")
        st.subheader("Historical Signals by Year")
        y=summary["year_summary"]
        st.dataframe(y.style.format({c:"{:.2f}%" for c in y if c not in ["signal_year","total_signal_records","unique_stocks"]},na_rep="NA"),hide_index=True)
        st.download_button("Download combined yearly summary",y.to_csv(index=False),"expanded_us_years.csv",key="ex_y_dl")
        st.subheader("Individual Historical Signal Records")
        st.dataframe(signals.sort_values("signal_date",ascending=False),hide_index=True)
        st.download_button("Download ALL combined signal records",signals.to_csv(index=False),"expanded_us_signals.csv",key="ex_s_dl")
        st.caption("10% hits use future highs, not an executed profit or terminal return. Incomplete horizons are excluded. Overlapping signals are not independent portfolio trades.")
    else: st.info("No signal records yet. Run the study and review diagnostics.")
    st.subheader("Every-stock diagnostics")
    st.dataframe(diag,hide_index=True)
    st.download_button("Download combined diagnostics",diag.to_csv(index=False),"expanded_us_diagnostics.csv",key="ex_d_dl")
    with st.expander("Optional backup — not required to view or combine results"):
        st.write("No downloads or manual merging are required for analysis. A checkpoint is only a recovery backup: progress is in session memory, not durable server storage. A restart/browser reload can lose unsaved work. No background job or automatic durable save is implemented. Mixed-time batches retain earlier observations; start fresh for a new research snapshot.")
        st.download_button("Download checkpoint backup",export_state(state),"expanded_us_checkpoint.json",mime="application/json",key="ex_checkpoint_dl")
