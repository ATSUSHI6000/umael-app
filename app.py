import os
import io
import json
import glob
import pandas as pd
import streamlit as st
import google.generativeai as genai

# ==========================================
# 0. 基本設定 & 定数設定
# ==========================================
APP_TITLE = "競馬プロ解析AI「ウマエルプロ v3.0」"
DOMAIN_URL = "https://umael-pro.streamlit.app/"
DATA_DIR_2026 = "data/2026"
ROOT_DB_PATH = "umael_database.csv"
YEAR_DB_PATH = os.path.join(DATA_DIR_2026, "umael_database.csv")

# フォルダの自動作成
os.makedirs(DATA_DIR_2026, exist_ok=True)

# Streamlit ページ設定
st.set_page_config(
    page_title=APP_TITLE,
    page_icon="🏇",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Gemini API 設定 (通常レース解析等で使用)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 着順カラーリングスタイルの定義
COLOR_1ST_BG = "#4a3b00"
COLOR_1ST_TXT = "#ffd700"
COLOR_2ND_BG = "#223344"
COLOR_2ND_TXT = "#00ffff"
COLOR_3RD_BG = "#332211"
COLOR_3RD_TXT = "#ffaa55"

def apply_rank_style(val):
    """確定着順に応じたセルスタイリング"""
    s_val = str(val).strip()
    if s_val in ["1", "1着"]:
        return f"background-color: {COLOR_1ST_BG}; color: {COLOR_1ST_TXT}; font-weight: bold;"
    elif s_val in ["2", "2着"]:
        return f"background-color: {COLOR_2ND_BG}; color: {COLOR_2ND_TXT}; font-weight: bold;"
    elif s_val in ["3", "3着"]:
        return f"background-color: {COLOR_3RD_BG}; color: {COLOR_3RD_TXT}; font-weight: bold;"
    return ""

# ==========================================
# 1. 共通データヘルパー関数
# ==========================================
def load_all_races_data():
    """data/2026/ およびルートDBから全レースデータを集約して読み込み"""
    races = {}
    
    # 1. JSONファイル群からの読み込み
    json_files = glob.glob(os.path.join(DATA_DIR_2026, "*.json"))
    for file_path in json_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                race_name = data.get("race_name") or os.path.splitext(os.path.basename(file_path))[0]
                races[race_name] = data
        except Exception:
            pass

    # 2. CSV DB（年度別・ルート）からの補完読み込み
    db_paths = [YEAR_DB_PATH, ROOT_DB_PATH]
    for db_p in db_paths:
        if os.path.exists(db_p):
            try:
                # 文字コードの判定試行
                try:
                    df = pd.read_csv(db_p, encoding="utf-8-sig")
                except Exception:
                    df = pd.read_csv(db_p, encoding="cp932")
                
                if "レース名" in df.columns:
                    for r_name, group in df.groupby("レース名"):
                        if r_name not in races:
                            horses = group.to_dict(orient="records")
                            races[r_name] = {
                                "race_name": r_name,
                                "horses": horses,
                                "memo": "\n".join([str(h.get("メモ", "")) for h in horses if pd.notna(h.get("メモ"))])
                            }
            except Exception:
                pass

    return races

def save_race_data_to_storage(race_name, race_dict):
    """単一レースデータを JSON および CSV DB へ安全に保存・同期"""
    # 1. JSONファイル保存
    file_name = f"{race_name}.json".replace("/", "_").replace("\\", "_")
    json_path = os.path.join(DATA_DIR_2026, file_name)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(race_dict, f, ensure_ascii=False, indent=2)

    # 2. CSV DB への同期保存
    horses = race_dict.get("horses", [])
    if horses:
        new_df = pd.DataFrame(horses)
        new_df["レース名"] = race_name
        
        for db_path in [YEAR_DB_PATH, ROOT_DB_PATH]:
            if os.path.exists(db_path):
                try:
                    try:
                        exist_df = pd.read_csv(db_path, encoding="utf-8-sig")
                    except Exception:
                        exist_df = pd.read_csv(db_path, encoding="cp932")
                    # 同一レースのデータを上書き置換
                    exist_df = exist_df[exist_df["レース名"] != race_name]
                    combined_df = pd.concat([exist_df, new_df], ignore_index=True)
                except Exception:
                    combined_df = new_df
            else:
                combined_df = new_df
            
            combined_df.to_csv(db_path, index=False, encoding="utf-8-sig")

def delete_race_data(race_name):
    """指定されたレースのデータを JSONファイル・CSV DB から一括削除"""
    # 1. JSONファイル削除
    file_name = f"{race_name}.json".replace("/", "_").replace("\\", "_")
    json_path = os.path.join(DATA_DIR_2026, file_name)
    if os.path.exists(json_path):
        os.remove(json_path)

    # 2. CSV DB からの削除
    for db_path in [YEAR_DB_PATH, ROOT_DB_PATH]:
        if os.path.exists(db_path):
            try:
                try:
                    df = pd.read_csv(db_path, encoding="utf-8-sig")
                except Exception:
                    df = pd.read_csv(db_path, encoding="cp932")
                if "レース名" in df.columns:
                    df = df[df["レース名"] != race_name]
                    df.to_csv(db_path, index=False, encoding="utf-8-sig")
            except Exception:
                pass

# ==========================================
# 2. Pandasによる一括パースコア処理（AI不使用）
# ==========================================
def process_bulk_csv_with_pandas(uploaded_file):
    """
    Gemini APIを使わず Pandas で直接CSVを完全パースし、
    107レース一括分割・メモ抽出・自動保存を行う
    """
    bytes_data = uploaded_file.read()
    
    # 複数エンコーディングの自動試行
    df = None
    for enc in ["utf-8-sig", "utf-8", "cp932", "shift_jis"]:
        try:
            df = pd.read_csv(io.BytesIO(bytes_data), encoding=enc)
            break
        except Exception:
            continue
            
    if df is None:
        raise ValueError("CSVファイルの読み込みに失敗しました。文字コードを確認してください。")

    # 列名の正規化（空白除去等）
    df.columns = [str(col).strip() for col in df.columns]

    # レース名キーの特定
    race_col = None
    for possible_col in ["レース名", "race_name", "Race", "レース"]:
        if possible_col in df.columns:
            race_col = possible_col
            break

    if not race_col:
        raise KeyError("CSV内に『レース名』列が見つかりません。")

    # NaNの空文字置換
    df = df.fillna("")

    processed_count = 0
    grouped = df.groupby(race_col)

    for race_name, group in grouped:
        race_name_str = str(race_name).strip()
        if not race_name_str:
            continue

        horses_list = group.to_dict(orient="records")
        
        # 回顧メモの自動構築（メモ列の収集）
        memo_list = []
        for horse in horses_list:
            memo_val = str(horse.get("メモ", "")).strip()
            if memo_val:
                memo_list.append(f"・{horse.get('馬名', '')}: {memo_val}")
        
        race_memo_text = "\n".join(memo_list)

        race_dict = {
            "race_name": race_name_str,
            "horses": horses_list,
            "memo": race_memo_text
        }

        # 二重同期保存実行
        save_race_data_to_storage(race_name_str, race_dict)
        processed_count += 1

    return processed_count

# ==========================================
# 3. アプリケーション メイン UI
# ==========================================
def main():
    st.sidebar.title("🏇 ウマエルプロ v3.0")
    st.sidebar.markdown(f"**固定共有URL**: [{DOMAIN_URL}]({DOMAIN_URL})")
    
    # データのロード・同期
    all_races = load_all_races_data()
    race_list = sorted(list(all_races.keys()))

    menu = st.sidebar.radio(
        "メインメニュー",
        [
            "📊 通常レース解析",
            "📁 過去レース一括登録",
            "📋 評価データ一覧",
            "📝 回顧・精度検証一覧",
            "🐎 過去馬データベース"
        ]
    )

    # ------------------------------------------
    # メニュー 1: 通常レース解析
    # ------------------------------------------
    if menu == "📊 通常レース解析":
        st.header("📊 通常レース解析")
        st.info("出馬表やテキストを入力して `gemini-3.8-flash` による高精度予想を出力します。")
        
        selected_race = st.selectbox("登録済み過去レースを選択", ["-- 選択してください --"] + race_list)
        if selected_race != "-- 選択してください --":
            r_data = all_races.get(selected_race, {})
            st.subheader(f"【レース名】{selected_race}")
            if r_data.get("horses"):
                df_show = pd.DataFrame(r_data["horses"])
                if "確定着順" in df_show.columns:
                    st.dataframe(df_show.style.applymap(apply_rank_style, subset=["確定着順"]), use_container_width=True)
                else:
                    st.dataframe(df_show, use_container_width=True)
            if r_data.get("memo"):
                st.markdown("**【見解・回顧メモ】**")
                st.text_area("メモ内容", r_data["memo"], height=150, disabled=True)

    # ------------------------------------------
    # メニュー 2: 過去レース一括登録 (Pandas直接パース)
    # ------------------------------------------
    elif menu == "📁 過去レース一括登録":
        st.header("📁 過去レース一括登録")
        st.markdown("""
        縦連結された大容量CSV（『競馬分析用シート_2026.csv』等）をアップロードしてください。  
        **Gemini APIを使用せず、Pandasで高速・直接パースして全レース（107レース対応）を自動分割・保存します。**
        """)

        uploaded_file = st.file_uploader("競馬分析用CSVファイルをアップロード", type=["csv"])

        if uploaded_file is not None:
            if st.button("🚀 一括パース＆全レース自動登録を実行"):
                with st.spinner("Pandas直接パースにて全レース分割および一括保存処理中..."):
                    try:
                        count = process_bulk_csv_with_pandas(uploaded_file)
                        st.success(f"🎉 処理完了！ 合計 {count} レースのデータを正常に自動分割＆保存しました！")
                        st.balloons()
                        # 全画面同期のため再読み込み
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ パース処理中にエラーが発生しました: {str(e)}")

    # ------------------------------------------
    # メニュー 3: 評価データ一覧 (削除機能付き)
    # ------------------------------------------
    elif menu == "📋 評価データ一覧":
        st.header("📋 評価データ一覧（プール）")
        
        if not race_list:
            st.warning("登録されているレースデータがありません。")
        else:
            selected_race = st.selectbox("対象レースを選択", race_list, key="eval_race_select")
            r_data = all_races.get(selected_race, {})

            # 🗑️ レースデータ削除UI
            st.markdown("---")
            col_del1, col_del2 = st.columns([1, 2])
            with col_del1:
                confirm_del = st.checkbox("削除を確認する", key="del_confirm_eval")
            with col_del2:
                if st.button("🗑️ 選択中のレースデータを削除", key="btn_del_eval", disabled=not confirm_del):
                    delete_race_data(selected_race)
                    st.success(f"『{selected_race}』のデータを完全削除しました。")
                    st.rerun()
            st.markdown("---")

            if r_data.get("horses"):
                df_eval = pd.DataFrame(r_data["horses"])
                st.subheader(f"出走馬評価一覧: {selected_race}")
                if "確定着順" in df_eval.columns:
                    st.dataframe(df_eval.style.applymap(apply_rank_style, subset=["確定着順"]), use_container_width=True)
                else:
                    st.dataframe(df_eval, use_container_width=True)

    # ------------------------------------------
    # メニュー 4: 回顧・精度検証一覧 (削除機能付き)
    # ------------------------------------------
    elif menu == "📝 回顧・精度検証一覧":
        st.header("📝 回顧・精度検証一覧（プール）")

        if not race_list:
            st.warning("登録されているレースデータがありません。")
        else:
            selected_race = st.selectbox("対象レースを選択", race_list, key="review_race_select")
            r_data = all_races.get(selected_race, {})

            # 🗑️ レースデータ削除UI
            st.markdown("---")
            col_del1, col_del2 = st.columns([1, 2])
            with col_del1:
                confirm_del = st.checkbox("削除を確認する", key="del_confirm_review")
            with col_del2:
                if st.button("🗑️ 選択中のレースデータを削除", key="btn_del_review", disabled=not confirm_del):
                    delete_race_data(selected_race)
                    st.success(f"『{selected_race}』のデータを完全削除しました。")
                    st.rerun()
            st.markdown("---")

            st.subheader(f"回顧＆短評メモ: {selected_race}")
            if r_data.get("memo"):
                st.text_area("レース回顧メモ・各馬短評", r_data["memo"], height=250)
            else:
                st.info("このレースには回顧メモが登録されていません。")

            if r_data.get("horses"):
                st.markdown("**【確定着順＆最終評価】**")
                df_rev = pd.DataFrame(r_data["horses"])
                if "確定着順" in df_rev.columns:
                    st.dataframe(df_rev.style.applymap(apply_rank_style, subset=["確定着順"]), use_container_width=True)
                else:
                    st.dataframe(df_rev, use_container_width=True)

    # ------------------------------------------
    # メニュー 5: 過去馬データベース (削除機能付き)
    # ------------------------------------------
    elif menu == "🐎 過去馬データベース":
        st.header("🐎 過去馬データベース（プール）")

        if not race_list:
            st.warning("登録されているレースデータがありません。")
        else:
            selected_race = st.selectbox("絞り込み対象レース", ["-- 全レース対象 --"] + race_list, key="db_race_select")

            if selected_race != "-- 全レース対象 --":
                # 🗑️ レースデータ削除UI
                st.markdown("---")
                col_del1, col_del2 = st.columns([1, 2])
                with col_del1:
                    confirm_del = st.checkbox("削除を確認する", key="del_confirm_db")
                with col_del2:
                    if st.button("🗑️ 選択中のレースデータを削除", key="btn_del_db", disabled=not confirm_del):
                        delete_race_data(selected_race)
                        st.success(f"『{selected_race}』のデータを完全削除しました。")
                        st.rerun()
                st.markdown("---")

                r_data = all_races.get(selected_race, {})
                df_db = pd.DataFrame(r_data.get("horses", []))
            else:
                # 全馬データの結合
                all_horses = []
                for r_name, r_dict in all_races.items():
                    for h in r_dict.get("horses", []):
                        h_copy = dict(h)
                        h_copy["レース名"] = r_name
                        all_horses.append(h_copy)
                df_db = pd.DataFrame(all_horses)

            if not df_db.empty:
                search_horse = st.text_input("🔍 馬名で検索", "")
                if search_horse:
                    df_db = df_db[df_db["馬名"].astype(str).str.contains(search_horse)]

                if "確定着順" in df_db.columns:
                    st.dataframe(df_db.style.applymap(apply_rank_style, subset=["確定着順"]), use_container_width=True)
                else:
                    st.dataframe(df_db, use_container_width=True)
            else:
                st.info("該当する競走馬データが存在しません。")

if __name__ == "__main__":
    main()