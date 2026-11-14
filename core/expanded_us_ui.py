from io import StringIO
import json
import time
import pandas as pd
import streamlit as st
from core.expanded_us_universe import get_directory,parse_directory,get_dow,combine,universe_hash,URL
from core.data import cap,history,completed
from core.historical import indicators,records,calculate_historical_study_summary
KEY="expanded_us_v1"
THRESHOLD=1_000_000_000

def encode_frame(frame):
    return json.loads(frame.to_json(orient="table",date_format="iso",index=False))

def decode_frame(obj):
    # JSON records are intentionally used instead of pickle or executable uploads.
    if not isinstance(obj,dict) or not isinstance(obj.get("data"),list): raise ValueError("Invalid checkpoint table")
    frame=pd.DataFrame(obj["data"])
    for col in frame:
        if col in ("signal_date","entry_date"): frame[col]=pd.to_datetime(frame[col],errors="raise")
        if col.startswith("hit_10pct_"): frame[col]=pd.array(frame[col],dtype="boolean")
    return frame

def export_state(state):
    return json.dumps({"version":KEY,"threshold":THRESHOLD,"universe":encode_frame(state["u"]),
      "source_report":state["source_report"],"universe_hash":universe_hash(state["u"]),
      "diagnostics":state["diag"],"signals":encode_frame(state["signals"]),
      "created_utc":state["created_utc"]},allow_nan=False)

def import_state(text):
    obj=json.loads(text)
    if obj.get("version")!=KEY or obj.get("threshold")!=THRESHOLD: raise ValueError("Wrong checkpoint version/threshold")
    u=decode_frame(obj["universe"])
    if not {"ticker","name","group","symbol"}.issubset(u.columns) or u.empty or u.ticker.duplicated().any(): raise ValueError("Invalid checkpoint universe")
    if universe_hash(u)!=obj.get("universe_hash"): raise ValueError("Checkpoint universe hash mismatch")
    diag=obj["diagnostics"]
    if not isinstance(diag,list): raise ValueError("Invalid diagnostic records")
    tickers=[r["ticker"] for r in diag]
    if len(set(tickers))!=len(tickers) or not set(tickers).issubset(set(u.ticker)): raise ValueError("Invalid processed tickers")
    signals=decode_frame(obj["signals"])
    if not signals.empty:
        required={"ticker","signal_date","entry_status"}
        for h in ["5d","10d","20d","30d","60d","90d","6m","9m","12m"]:
            required.update(["max_ret_"+h,"hit_10pct_"+h])
        required.update("min_ret_"+h for h in ["30d","60d","90d","6m","12m"])
        if not required.issubset(signals): raise ValueError("Checkpoint signal columns missing")
        if not set(signals.ticker).issubset(set(tickers)): raise ValueError("Signals not matched to processed stocks")
    return dict(u=u,diag=diag,signals=signals,source_report=obj["source_report"],created_utc=obj["created_utc"])

def render_expanded():
    st.title("Expanded US — All Nasdaq + Dow")
    st.info("Separate study: current USD market cap strictly greater than $1 billion. Existing US and UK pages are unchanged.")
    st.caption("Build: expanded_us_v1. Same shared historical engine, entry convention, technical rules and high/low outcome summaries as the existing pages.")
    st.warning("Current listings/current market caps introduce survivorship and selection bias. Directory name-based classification is not a verified security master. Company common/ordinary shares, ADRs and beneficial-interest shares are candidates; unclassified securities are excluded for review. No financial-status exclusion is applied.")
    with st.expander("Larger-universe scan and checkpoint instructions"):
        st.write("1. Load Nasdaq directory + Dow. 2. Inspect inclusion/exclusion audit. 3. Run a batch. 4. Download a checkpoint after EACH batch. 5. Continue until every candidate is attempted. Upload that checkpoint to resume after a restart.")
        st.write("Progress is held in session memory, not durable server storage. A batch is committed stock by stock in memory; a process failure loses progress since the last downloaded checkpoint. No automatic background scan runs. JSON checkpoints contain research data, not verified market data—upload only your own files.")
        st.write("The USD1bn filter is checked before long price histories are fetched, but market cap must still be obtained for every candidate. Missing/unsupported currency or data errors are exclusions recorded separately. Partial summaries are not full-universe results.")
    directory=st.file_uploader("Optional Nasdaq directory .txt (download in browser if cloud retrieval fails)",type=["txt"],key="ex_directory")
    st.code(URL,language=None)
    dow_csv=st.file_uploader("Optional Dow CSV (symbol,name; exactly 30 rows) if Dow live source fails",type=["csv"],key="ex_dow")
    if st.button("Load expanded universe",key="ex_load"):
        try:
            text=directory.getvalue().decode("utf-8-sig") if directory else get_directory()
            n,audit,source_time=parse_directory(text)
            if dow_csv:
                d=pd.read_csv(dow_csv,dtype=str,keep_default_na=False)
                if not {"symbol","name"}.issubset(d): raise ValueError("Dow CSV needs symbol,name")
                d=d[["symbol","name"]].copy();d["group"]="Dow";d["ticker"]=d.symbol.str.strip().str.replace(".","-",regex=False)
                dsource="User-provided Dow CSV; membership not independently verified"
            else: d,dsource=get_dow()
            u=combine(n,d)
            stamp=pd.Timestamp.now(tz="UTC").isoformat()
            report={"nasdaq_source":"User directory upload" if directory else URL,"directory_creation":source_time,"dow_source":dsource,"loaded_utc":stamp,"raw_directory_rows":len(audit),"nasdaq_candidates":len(n),"combined_unique":len(u)}
            st.session_state[KEY]=dict(u=u,diag=[],signals=pd.DataFrame(),source_report=report,created_utc=stamp)
            st.session_state[KEY+"_audit"]=audit
        except Exception as e: st.error(f"Universe load failed: {type(e).__name__}: {e}")
    checkpoint=st.file_uploader("Restore your downloaded expanded-US JSON checkpoint",type=["json"],key="ex_restore")
    if st.button("Restore checkpoint",key="ex_restore_go"):
        try:
            if checkpoint is None: raise ValueError("Select a checkpoint file first")
            state=import_state(checkpoint.getvalue().decode("utf-8"))
            st.session_state[KEY]=state;st.session_state.pop(KEY+"_audit",None)
            st.success("Restored checkpoint; prior full directory audit is not included, but the candidate universe is retained.")
        except Exception as e: st.error(f"Restore failed: {e}")
    state=st.session_state.get(KEY)
    if state is None: return
    st.json(state["source_report"])
    with st.expander("Candidate universe and directory exclusion audit"):
        st.dataframe(state["u"],hide_index=True)
        st.download_button("Download expanded candidate universe",state["u"].to_csv(index=False),"expanded_us_universe.csv",key="ex_u_dl")
        audit=st.session_state.get(KEY+"_audit")
        if audit is not None:
            st.dataframe(audit,hide_index=True)
            st.download_button("Download directory inclusion/exclusion audit",audit.to_csv(index=False),"nasdaq_security_audit.csv",key="ex_a_dl")
    batch=st.selectbox("Stocks per batch",[20,50,100,250],key="ex_batch")
    pause=st.selectbox("Pause after each stock (seconds)",[1,2,3,5],index=1,key="ex_pause")
    if st.button("Requeue failed stocks only",key="ex_requeue"):
        failed={r["ticker"] for r in state["diag"] if r["status"]=="Error"}
        state["diag"]=[r for r in state["diag"] if r["ticker"] not in failed]
        st.info(f"Requeued {len(failed)} failed stocks. Successful stocks and below-threshold exclusions are retained.")
    if st.button("Run next batch",type="primary",key="ex_run"):
        done={r["ticker"] for r in state["diag"]}
        todo=state["u"].loc[~state["u"].ticker.isin(done)].sort_values("ticker").head(batch)
        bar=st.progress(0);msg=st.empty()
        for pos,(_,stock) in enumerate(todo.iterrows(),1):
            row=dict(ticker=stock.ticker,name=stock["name"],group=stock.group,checked_utc=pd.Timestamp.now(tz="UTC").isoformat())
            try:
                msg.write(f"{pos}/{len(todo)} — {stock.ticker}")
                value,note=cap(stock.ticker,"US")
                row.update(market_cap=value,currency="USD",cap_note=note)
                if value<=THRESHOLD: row.update(status="Below/equal USD1bn",signals=0)
                else:
                    data,schedule=completed(history(stock.ticker),"US")
                    if len(data)<200: raise ValueError(f"Insufficient completed daily rows: {len(data)}")
                    data=indicators(data,schedule);r=records(data,stock,value)
                    if not r.empty: state["signals"]=pd.concat([state["signals"],r],ignore_index=True)
                    row.update(status="Signals found" if len(r) else "No matching signal",signals=len(r),daily_rows=len(data))
            except Exception as e: row.update(status="Error",signals=0,reason=f"{type(e).__name__}: {e}")
            state["diag"].append(row);bar.progress(pos/len(todo))
            time.sleep(pause)
            if row["status"]=="Error" and any(x in row.get("reason","").lower() for x in ["ratelimit","too many requests","rate limit","429"]):
                st.warning("Rate-limit response detected: batch stopped. Pause before retrying; use Requeue failed stocks later.");break
        bar.empty();msg.empty()
    diagnostics=pd.DataFrame(state["diag"])
    attempted=len(diagnostics);total=len(state["u"])
    errors=int((diagnostics.status=="Error").sum()) if attempted else 0
    signals=state["signals"]
    c1,c2,c3=st.columns(3)
    c1.metric("Attempted / candidates",f"{attempted} / {total}");c2.metric("Errors",errors);c3.metric("Signal records",len(signals))
    if attempted<total or errors:
        st.warning("PARTIAL / INCOMPLETE COVERAGE — pending candidates or failed stocks remain. Summaries cover only successfully evaluated stocks so far.")
    else: st.success("Every candidate has been processed without recorded errors. Eligibility exclusions still apply.")
    st.caption("Batches reuse provider caches; cap and price observations can have different timestamps. Checkpoints restored much later should be replaced by a fresh study for a consistent research period.")
    st.download_button("Download checkpoint — save after each batch",export_state(state),"expanded_us_checkpoint.json",mime="application/json",key="ex_checkpoint_dl")
    if not signals.empty:
        summary=calculate_historical_study_summary(signals)
        st.subheader("Forward Outcome Summary")
        hs=summary["horizon_summary"]
        st.dataframe(hs.style.format({c:"{:.2f}%" for c in hs if c not in ["Horizon","Completed Signals"]},na_rep="NA"),hide_index=True)
        st.download_button("Download outcome summary",hs.to_csv(index=False),"expanded_us_outcomes.csv",key="ex_h_dl")
        st.subheader("Historical Signals by Year")
        ys=summary["year_summary"]
        st.dataframe(ys.style.format({c:"{:.2f}%" for c in ys if c not in ["signal_year","total_signal_records","unique_stocks"]},na_rep="NA"),hide_index=True)
        st.download_button("Download yearly summary",ys.to_csv(index=False),"expanded_us_years.csv",key="ex_y_dl")
        st.subheader("Individual Historical Signal Records")
        st.dataframe(signals.sort_values("signal_date",ascending=False),hide_index=True)
        st.download_button("Download signal records",signals.to_csv(index=False),"expanded_us_signals.csv",key="ex_s_dl")
        st.caption("10% hits use future daily highs, not realised portfolio returns. Overlapping signals are not independent trades. Incomplete horizons are excluded.")
    else: st.info("No signal records yet. Run batches and inspect diagnostics.")
    st.subheader("Every-stock diagnostics")
    st.dataframe(diagnostics,hide_index=True)
    st.download_button("Download expanded diagnostics",diagnostics.to_csv(index=False),"expanded_us_diagnostics.csv",key="ex_d_dl")
