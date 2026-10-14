import importlib
import io
import json
import os
import re
import shutil
import time
import unicodedata
import urllib.request
import urllib.parse
from google import genai
from google.genai import types
import pandas as pd
import pdfplumber
import pypdf
import streamlit as st

# ページ基本設定（ウマエルプロ v3.0 完全版）
st.set_page_config(
    page_title="ウマエルプロ v3.0", page_icon="🏇", layout="wide"
)

# ファイルパス・ディレクトリ設定
DB_FILE = "umael_database.csv"
DATA_DIR = "data"
RULE_G1_FILE = "saved_rules_g1.txt"
RULE_GENERAL_FILE = "saved_rules_general.txt"
RULE_HOKKAIDO_FILE = "saved_rules_hokkaido.txt"
API_KEY_FILE = "api_key.txt"
DRAFTS_DIR = "race_drafts"

# デフォルトルールテキスト定義
DEFAULT_G1_RULES = """【G1専用・評価表出力ルール】"""
DEFAULT_GENERAL_RULES = """【平場・G2・G3専用 評価表出力ルール】"""
DEFAULT_HOKKAIDO_RULES = """【北海道・洋芝専用 評価表出力ルール】"""


# --------------------------------------------------
# 🛠 共通ヘルパー関数・ルール読み込み・クレンジング定義
# --------------------------------------------------

def load_saved_rules(file_path, default_text):
    """保存されているルールテキストファイルを安定読み込みする関数"""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                if content.strip():
                    return content
        except Exception:
            return default_text
    return default_text


def save_rules_to_file(file_path, rule_text):
    """ルールテキストをファイルへ保存する関数"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(rule_text)


def apply_top3_highlight(df):
    """1着・2着・3着の行にカラーリングを適用する関数"""
    if df is None or df.empty:
        return df

    rank_col = None
    for col in ["確定着順", "着順", "順位", "着"]:
        if col in df.columns:
            rank_col = col
            break

    if not rank_col:
        return df

    def highlight_row(row):
        val = row.get(rank_col)
        if pd.isna(val) or val is None:
            return [''] * len(row)

        s = re.sub(r"\D", "", str(val))
        if s:
            try:
                rank = int(s)
                if rank == 1:
                    return ['background-color: #4a3b00; color: #ffd700; font-weight: bold;'] * len(row)
                elif rank == 2:
                    return ['background-color: #223344; color: #00ffff; font-weight: bold;'] * len(row)
                elif rank == 3:
                    return ['background-color: #332211; color: #ffaa55; font-weight: bold;'] * len(row)
            except ValueError:
                pass
        return [''] * len(row)

    return df.style.apply(highlight_row, axis=1)


def clean_pop_number(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if not s or s in ["-", "—", "nan", "None"]:
        return ""
    m = re.search(r"\d+", s)
    if m:
        return m.group(0)
    return s


def extract_year_from_race_name(race_name):
    if not race_name:
        return "2026"
    m = re.search(r"(20\d{2})", str(race_name))
    if m:
        return m.group(1)
    return "2026"


def detect_race_grade(race_name):
    if not race_name:
        return "G3"
    name_norm = unicodedata.normalize('NFKC', str(race_name)).upper()
    
    g1_keywords = [
        "G1", "G-1", "JPN1", "JPN-1", "フェブラリーS", "高松宮記念", "大阪杯", "桜花賞", 
        "皐月賞", "天皇賞", "NHKマイルC", "ヴィクトリアマイル", "オークス", "日本ダービー", 
        "安田記念", "宝塚記念", "スプリンターズS", "秋華賞", "菊花賞", "天皇賞(秋)", 
        "エリザベス女王杯", "マイルCS", "ジャパンC", "チャンピオンズC", "阪神JF", 
        "朝日杯FS", "ホープフルS", "有馬記念", "東京大賞典", "川崎記念", "かしわ記念", 
        "帝王賞", "ジャパンダートクラシック", "JBCクラシック", "JBCスプリント", "JBCレディス"
    ]
    for kw in g1_keywords:
        if kw in name_norm or kw in str(race_name):
            return "G1"
            
    if "G2" in name_norm or "G-2" in name_norm or "JPN2" in name_norm:
        return "G2"
    if "G3" in name_norm or "G-3" in name_norm or "JPN3" in name_norm:
        return "G3"
    if "OP" in name_norm or "オープン" in name_norm or "L" in name_norm:
        return "OP"
        
    return "G3"


def ensure_drafts_dir():
    if not os.path.exists(DRAFTS_DIR):
        os.makedirs(DRAFTS_DIR, exist_ok=True)


def list_draft_races():
    ensure_drafts_dir()
    races = []
    for item in os.listdir(DRAFTS_DIR):
        folder_path = os.path.join(DRAFTS_DIR, item)
        if os.path.isdir(folder_path):
            races.append(item)
    return sorted(races)


def load_api_key():
    try:
        if "GEMINI_API_KEY" in st.secrets and st.secrets["GEMINI_API_KEY"].strip():
            return st.secrets["GEMINI_API_KEY"].strip()
    except Exception:
        pass

    if os.path.exists(API_KEY_FILE):
        try:
            with open(API_KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""
    return ""


def save_api_key(key_text):
    try:
        with open(API_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key_text.strip())
    except Exception:
        pass


def extract_text_from_pdf(pdf_file, page_option="1ページ目のみ"):
    text = ""
    pdf_file.seek(0)
    try:
        with pdfplumber.open(pdf_file) as pdf:
            if len(pdf.pages) > 0:
                pages_to_process = (
                    pdf.pages if page_option == "全ページ読み込む" else [pdf.pages[0]]
                )
                for i, page in enumerate(pages_to_process):
                    page_text = page.extract_text(layout=True)
                    if not page_text or len(page_text.strip()) < 30:
                        page_text = page.extract_text()
                    if page_text:
                        text += (
                            f"\n--- 【PDF {i+1}ページ目抽出テキスト】 ---\n" + page_text + "\n"
                        )
    except Exception:
        pdf_file.seek(0)
        try:
            reader = pypdf.PdfReader(pdf_file)
            if len(reader.pages) > 0:
                pages_to_process = (
                    reader.pages if page_option == "全ページ読み込む" else [reader.pages[0]]
                )
                for i, page in enumerate(pages_to_process):
                    t = page.extract_text()
                    if t:
                        text += f"\n--- 【PDF {i+1}ページ目抽出テキスト】 ---\n" + t + "\n"
        except Exception:
            pass
    return text


def fetch_text_from_url(url):
    url = url.strip()
    if not url:
        return ""

    youtube_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
    if youtube_match:
        video_id = youtube_match.group(1)
        try:
            yt_module = importlib.import_module("youtube_transcript_api")
            YouTubeTranscriptApi = getattr(yt_module, "YouTubeTranscriptApi")
            transcript = YouTubeTranscriptApi.get_transcript(
                video_id, languages=["ja", "en"]
            )
            yt_text = " ".join([item["text"] for item in transcript])
            if yt_text.strip():
                return f"【YouTube字幕テキスト ({url})】:\n" + yt_text[:8000]
        except Exception:
            pass

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                    " AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0"
                    " Safari/537.36"
                )
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode("utf-8", errors="ignore")

        try:
            bs4_module = importlib.import_module("bs4")
            BeautifulSoup = getattr(bs4_module, "BeautifulSoup")
            soup = BeautifulSoup(html, "html.parser")
            for s in soup(["script", "style", "header", "footer", "nav"]):
                s.decompose()
            text = soup.get_text(separator=" ")
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = "\n".join(chunk for chunk in chunks if chunk)
            return f"【Webページ抽出テキスト ({url})】:\n" + clean_text[:8000]
        except Exception:
            clean_html = re.sub(
                r"<script.*?>.*?</script>", "", html, flags=re.DOTALL
            )
            clean_html = re.sub(
                r"<style.*?>.*?</style>", "", clean_html, flags=re.DOTALL
            )
            clean_html = re.sub(r"<[^>]+>", " ", clean_html)
            clean_text = re.sub(r"\s+", " ", clean_html).strip()
            return f"【Webページ抽出テキスト ({url})】:\n" + clean_text[:8000]

    except Exception as e:
        return f"【URL読み込みスキップ ({url}): {e}】"


def process_multiple_urls(urls_input_text):
    if not urls_input_text or not urls_input_text.strip():
        return ""

    urls = [
        line.strip()
        for line in urls_input_text.strip().splitlines()
        if line.strip().startswith("http")
    ]
    if not urls:
        return ""

    combined_url_text = (
        "\n=========================================\n【参考URL（YouTube/note/プロ予想）自動抽出データ】\n=========================================\n"
    )
    for url in urls:
        extracted = fetch_text_from_url(url)
        if extracted:
            combined_url_text += (
                extracted + "\n-----------------------------------------\n"
            )

    return combined_url_text


def prepare_file_parts(files_list, pdf_page_option="1ページ目のみ"):
    prompt_text = ""
    media_parts = []

    if files_list:
        for f in files_list:
            fname = f.name
            f.seek(0)
            file_bytes = f.read()

            if fname.lower().endswith((".txt", ".csv")):
                content = file_bytes.decode("utf-8", errors="ignore")
                if any(
                    k in fname
                    for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]
                ):
                    prompt_text += (
                        f"\n=========================================\n【⚠️注意：ファイル「{fname}」は過去の参考資料です。】\n=========================================\n"
                        + content
                    )
                else:
                    prompt_text += (
                        f"\n=========================================\n【確定メイン出馬・追加データファイル:"
                        f" {fname}】\n=========================================\n"
                        + content
                    )

            else:
                extracted = extract_text_from_pdf(f, page_option=pdf_page_option)
                if extracted.strip():
                    if any(
                        k in fname
                        for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]
                    ):
                        prompt_text += (
                            f"\n=========================================\n【⚠️注意：ファイル「{fname}」は過去の参考資料です】\n=========================================\n"
                            + extracted
                        )
                    else:
                        prompt_text += (
                            f"\n=========================================\n【確定メイン出馬・追加データ（PDF抽出）:"
                            f" {fname}】\n=========================================\n"
                            + extracted
                        )

                mime = f.type
                if not mime or mime == "application/octet-stream":
                    if fname.lower().endswith(".pdf"):
                        mime = "application/pdf"
                    elif fname.lower().endswith(".png"):
                        mime = "image/png"
                    elif fname.lower().endswith((".jpg", ".jpeg")):
                        mime = "image/jpeg"

                if mime:
                    media_parts.append(
                        types.Part.from_bytes(data=file_bytes, mime_type=mime)
                    )

    return prompt_text, media_parts


def normalize_race_name_for_comparison(name):
    if not name:
        return ""
    s = unicodedata.normalize('NFKC', str(name))
    s = s.lower()
    s = re.sub(r'\s+', '', s)
    s = re.sub(r'[_\-\–\—\(\)（）\[\]【】]', '', s)
    return s


def find_matching_existing_draft(target_race_name):
    existing_races = list_draft_races()
    target_key = normalize_race_name_for_comparison(target_race_name)
    if not target_key:
        return None
    for existing_race in existing_races:
        if normalize_race_name_for_comparison(existing_race) == target_key:
            return existing_race
    return None


def clean_race_name_from_filename(filename):
    if not filename:
        return ""
    
    base_name = os.path.splitext(filename)[0]
    cleaned = unicodedata.normalize('NFKC', base_name)
    
    noise_patterns = [
        r"競馬新聞", r"競馬新", r"新聞", r"出馬表", r"馬柱", r"確定データ", r"確定",
        r"過去データ", r"過去", r"傾向", r"回顧", r"データ", r"全ページ", r"印刷"
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    
    cleaned = re.sub(r'[_\s\-\—]?(?:20\d{2})(?:[01]\d[0-3]\d)?', '', cleaned)
    cleaned = re.sub(r'[_\s\-\—]\d+$', '', cleaned)
    cleaned = re.sub(r'\(\d+\)$', '', cleaned)
    
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", cleaned)
    cleaned = re.sub(r'[_\s\-\—]+', '_', cleaned)
    cleaned = cleaned.strip('_').strip()
    
    return cleaned if cleaned else re.sub(r'[\\/*?:"<>|]', "_", base_name).strip()


def detect_simple_race_name(files_g1, files_g2, files_g3, files_g4):
    for flist in [files_g1, files_g2, files_g3, files_g4]:
        if flist:
            for f in flist:
                clean_name = clean_race_name_from_filename(f.name)
                if clean_name:
                    return clean_name
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"準備中レース_{timestamp}"


def save_draft_data(race_name, files_g1, files_g2, files_g3, files_g4, urls_text):
    ensure_drafts_dir()
    if not race_name or not race_name.strip():
        race_name = detect_simple_race_name(files_g1, files_g2, files_g3, files_g4)
    else:
        race_name = clean_race_name_from_filename(race_name)

    matched_existing_race = find_matching_existing_draft(race_name)
    if matched_existing_race:
        sanitized_name = matched_existing_race
    else:
        sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')

    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)
    os.makedirs(race_dir, exist_ok=True)

    url_log_path = os.path.join(race_dir, "urls.txt")
    existing_urls = ""
    if os.path.exists(url_log_path):
        with open(url_log_path, "r", encoding="utf-8") as f:
            existing_urls = f.read()

    new_urls = urls_text.strip()
    if new_urls:
        combined_urls = (existing_urls + "\n" + new_urls).strip()
        with open(url_log_path, "w", encoding="utf-8") as f:
            f.write(combined_urls)

    saved_count = 0
    timestamp = int(time.time())
    for g_idx, file_list in [(1, files_g1), (2, files_g2), (3, files_g3), (4, files_g4)]:
        if file_list:
            for idx, f in enumerate(file_list):
                f.seek(0)
                content = f.read()
                fname = f.name
                save_fname = f"g{g_idx}___{timestamp}___{idx}___{fname}"
                with open(os.path.join(race_dir, save_fname), "wb") as out_f:
                    out_f.write(content)
                saved_count += 1
    return saved_count, sanitized_name


def load_draft_data(race_name, pdf_page_option="1ページ目のみ"):
    ensure_drafts_dir()
    if not race_name or not race_name.strip():
        return "", [], "", [], "", [], "", [], "", []

    sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')
    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)

    if not os.path.exists(race_dir):
        return "", [], "", [], "", [], "", [], "", []

    t1_all, p1_all = "", []
    t2_all, p2_all = "", []
    t3_all, p3_all = "", []
    t4_all, p4_all = "", []
    file_names = []

    for fname in sorted(os.listdir(race_dir)):
        fpath = os.path.join(race_dir, fname)
        if fname == "urls.txt":
            continue
        if os.path.isfile(fpath):
            if "___" in fname:
                original_fname = fname.split("___")[-1]
            elif "_" in fname:
                original_fname = fname.split("_", 2)[-1]
            else:
                original_fname = fname

            file_names.append(original_fname)
            with open(fpath, "rb") as f:
                file_bytes = f.read()

            group_idx = 1
            if fname.startswith("g2_") or fname.startswith("g2___"):
                group_idx = 2
            elif fname.startswith("g3_") or fname.startswith("g3___"):
                group_idx = 3
            elif fname.startswith("g4_") or fname.startswith("g4___"):
                group_idx = 4

            txt_content = ""
            media_parts = []

            is_past_ref = any(
                k in original_fname
                for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]
            )

            if original_fname.lower().endswith((".txt", ".csv")):
                decoded = file_bytes.decode("utf-8", errors="ignore")
                if is_past_ref:
                    txt_content += (
                        f"\n=========================================\n【⚠️注意：ファイル「{original_fname}」は過去の参考資料です。】\n=========================================\n"
                        + decoded
                    )
                else:
                    txt_content += (
                        f"\n=========================================\n【確定メイン出馬データファイル:"
                        f" {original_fname}】\n=========================================\n"
                        + decoded
                    )
            else:
                bio = io.BytesIO(file_bytes)
                extracted = extract_text_from_pdf(bio, page_option=pdf_page_option)
                if extracted.strip():
                    if is_past_ref:
                        txt_content += (
                            f"\n=========================================\n【⚠️注意：ファイル「{original_fname}」は過去の参考資料です】\n=========================================\n"
                            + extracted
                        )
                    else:
                        txt_content += (
                            f"\n=========================================\n【確定メイン出馬データ（PDF抽出）:"
                            f" {original_fname}】\n=========================================\n"
                            + extracted
                        )

                mime = None
                if original_fname.lower().endswith(".pdf"):
                    mime = "application/pdf"
                elif original_fname.lower().endswith(".png"):
                    mime = "image/png"
                elif original_fname.lower().endswith((".jpg", ".jpeg")):
                    mime = "image/jpeg"

                if mime:
                    media_parts.append(
                        types.Part.from_bytes(data=file_bytes, mime_type=mime)
                    )

            if group_idx == 1:
                t1_all += txt_content + "\n"
                p1_all.extend(media_parts)
            elif group_idx == 2:
                t2_all += txt_content + "\n"
                p2_all.extend(media_parts)
            elif group_idx == 3:
                t3_all += txt_content + "\n"
                p3_all.extend(media_parts)
            elif group_idx == 4:
                t4_all += txt_content + "\n"
                p4_all.extend(media_parts)

    t5_all = ""
    url_log_path = os.path.join(race_dir, "urls.txt")
    if os.path.exists(url_log_path):
        with open(url_log_path, "r", encoding="utf-8") as f:
            urls_text = f.read()
            if urls_text.strip():
                t5_all = process_multiple_urls(urls_text)

    return t1_all, p1_all, t2_all, p2_all, t3_all, p3_all, t4_all, p4_all, t5_all, file_names


def delete_draft(race_name):
    ensure_drafts_dir()
    if not race_name or not race_name.strip():
        return False
    sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')
    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)
    if os.path.exists(race_dir):
        shutil.rmtree(race_dir)
        return True
    return False


def normalize_horse_num(val):
    if pd.isna(val):
        return ""
    s = re.sub(r"\D", "", str(val))
    return str(int(s)) if s else ""


def normalize_rank(val):
    if pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s in {"-", "—", "取消", "除外", "中止", "失格", "競走中止"}:
        return ""
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.match(r"^\s*(\d+)\s*(?:着)?\s*$", s)
    if m:
        return str(int(m.group(1)))
    return ""


def convert_to_circled_numbers(text):
    circled_map = {
        "1": "①", "2": "②", "3": "③", "4": "④", "5": "⑤",
        "6": "⑥", "7": "⑦", "8": "⑧", "9": "⑨", "10": "⑩",
        "11": "⑪", "12": "⑫", "13": "⑬", "14": "⑭", "15": "⑮",
        "16": "⑯", "17": "⑰", "18": "⑱", "19": "⑲", "20": "⑳",
    }

    def replacer(match):
        val = match.group(0)
        return circled_map.get(val, val)

    return re.sub(r"\b(20|1[0-9]|[1-9])\b", replacer, str(text))


def safe_int(val, default=0):
    try:
        if isinstance(val, (pd.Series, list)):
            val = val[0] if len(val) > 0 else default
        num = pd.to_numeric(val, errors="coerce")
        if pd.isna(num):
            return default
        return int(num)
    except Exception:
        return default


def render_re_evaluation_section(df, active_selected_rule, model_name):
    """評価結果画面内の AI再評価実行セクション"""
    with st.expander("🔄 評価ルールの調整・AI再評価実行", expanded=False):
        st.write("現在のルール設定でこのレースを再解析・評価更新できます。")
        temp_rule = st.text_area("適用ルール", value=active_selected_rule, height=150)
        if st.button("🔥 このルールで再評価を実行", key="btn_re_eval"):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key が設定されていません。")
            else:
                with st.spinner("🏇 ルール適用でAI再評価中..."):
                    try:
                        cols = [c for c in ["馬番", "馬名", "総合スコア", "評価", "メモ"] if c in df.columns]
                        context_str = df[cols].to_string(index=False)
                        res_text = analyze_data_with_gemini(
                            active_key, temp_rule,
                            f"【再解析対象】:\n{context_str}", [],
                            "", [], "", [], "", [], "",
                            model_name
                        )
                        new_df = parse_json_ai_output(res_text)
                        if not new_df.empty:
                            save_to_db(new_df)
                            st.session_state["analyzed_df"] = new_df
                            st.success("🎉 再評価が完了しました！")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ 再評価中にエラーが発生しました: {e}")


def render_field_mode_ui(active_key, active_selected_rule, selected_model):
    """現地観戦用（勝負5R厳選）画面UI"""
    st.subheader("🏇 現地観戦用（勝負5R厳選モード）")
    st.caption("現地やウインズ等で勝負する最大5レースを一括アップロードし、効率的に短時間でAI解析します！")

    field_files = st.file_uploader(
        "📁 厳選レースデータ（最大5レース分） (.txt / .csv / .pdf / .png / .jpg)",
        type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="field_mode_file_uploader"
    )

    if st.button("🔥 厳選5Rを一括解析する", use_container_width=True, key="btn_field_mode_run"):
        if not active_key:
            st.error("⚠️ Gemini API Key が設定されていません。")
        elif not field_files:
            st.warning("⚠️ 解析するレースデータをアップロードしてください！")
        else:
            with st.spinner("🏇 現地観戦用 厳選レースを一括AI解析中..."):
                try:
                    t1, p1 = prepare_file_parts(field_files, pdf_page_option="1ページ目のみ")
                    result_text = analyze_data_with_gemini(
                        active_key, active_selected_rule,
                        t1, p1, "", [], "", [], "", [], "",
                        selected_model
                    )
                    df = parse_json_ai_output(result_text)
                    if not df.empty:
                        save_to_db(df)
                        st.success("🎉 現地観戦用の厳選レース解析が完了し保存されました！")
                        st.dataframe(apply_top3_highlight(df), use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"❌ 解析中にエラーが発生しました: {e}")


# --------------------------------------------------
# 🧼 1. 強化版データクレンジング・自動補完ロジック
# --------------------------------------------------

def sanitize_dataframe_columns(df):
    if df.empty:
        return df
    df = df.copy()

    # 重複列があれば安全に1つに統合（先頭を採用）
    df = df.loc[:, ~df.columns.duplicated()]

    # カラム表記揺れ吸収（リネーム処理）
    rename_map = {}
    for orig_c in df.columns:
        c_clean = str(orig_c).strip().replace(" ", "").replace(" ", "").replace("\n", "").replace("\r", "")
        if c_clean in ["着順", "確定着順", "順位", "着"] and "確定着順" not in rename_map.values():
            rename_map[orig_c] = "確定着順"
        elif c_clean in ["レース名", "レース", "Race", "RACE"] and "レース名" not in rename_map.values():
            rename_map[orig_c] = "レース名"
        elif c_clean in ["馬名", "競走馬名", "Horse", "HORSE"] and "馬名" not in rename_map.values():
            rename_map[orig_c] = "馬名"
        elif c_clean in ["馬番", "馬No", "馬NO", "No", "NO"] and "馬番" not in rename_map.values():
            rename_map[orig_c] = "馬番"
        elif c_clean in ["予想人気"] and "予想人気" not in rename_map.values():
            rename_map[orig_c] = "予想人気"
        elif c_clean in ["単勝人気", "人気"] and "単勝人気" not in rename_map.values():
            rename_map[orig_c] = "単勝人気"
        elif "評価" in c_clean and "評価" not in rename_map.values():
            rename_map[orig_c] = "評価"
        elif "軸" in c_clean and "軸" not in rename_map.values():
            rename_map[orig_c] = "軸"
        elif "ヒモ" in c_clean and "ヒモ" not in rename_map.values():
            rename_map[orig_c] = "ヒモ"
        elif "注" in c_clean and "注" not in rename_map.values():
            rename_map[orig_c] = "注"
        elif "切り" in c_clean and "切り" not in rename_map.values():
            rename_map[orig_c] = "切り"
        elif c_clean in ["メモ", "見解", "短評", "コメント"] and "メモ" not in rename_map.values():
            rename_map[orig_c] = "メモ"
        elif c_clean in ["回顧", "総評", "回顧メモ"] and "回顧メモ" not in rename_map.values():
            rename_map[orig_c] = "回顧メモ"
        elif c_clean in ["年度", "年"] and "年" not in rename_map.values():
            rename_map[orig_c] = "年"

    if rename_map:
        df = df.rename(columns=rename_map)

    df = df.loc[:, ~df.columns.duplicated()]

    # 総合スコアの型変換・数値化クレンジング
    if "総合スコア" in df.columns:
        df["総合スコア"] = pd.to_numeric(
            df["総合スコア"].astype(str).str.replace("点", "").str.strip(), errors="coerce"
        ).fillna(0).astype(int)

    if "予想人気" in df.columns:
        df["予想人気"] = df["予想人気"].apply(clean_pop_number)
    if "単勝人気" in df.columns:
        df["単勝人気"] = df["単勝人気"].apply(clean_pop_number)

    for col in ["評価", "軸", "ヒモ", "注", "切り", "メモ", "総合スコア", "年"]:
        if col not in df.columns:
            df[col] = ""

    # 総合スコアからの「評価（S〜C）」および「軸・ヒモ・注・切り（〇印）」の自動算出・補完
    def calc_eval_and_marks(row):
        score = safe_int(row.get("総合スコア", 0))
        current_eval = str(row.get("評価", "")).strip()

        if not current_eval or current_eval in ["-", "nan", "None"]:
            if score >= 93:
                current_eval = "S"
            elif score >= 88:
                current_eval = "A+"
            elif score >= 84:
                current_eval = "A"
            elif score >= 80:
                current_eval = "B+"
            elif score >= 74:
                current_eval = "B"
            else:
                current_eval = "C"

        jiku = str(row.get("軸", "")).strip()
        himo = str(row.get("ヒモ", "")).strip()
        chu = str(row.get("注", "")).strip()
        kiri = str(row.get("切り", "")).strip()

        memo = str(row.get("メモ", "")).strip()

        if not (jiku or himo or chu or kiri):
            if "【推奨】" in memo or "【軸】" in memo:
                jiku = "〇"
            elif "【ヒモ】" in memo:
                himo = "〇"
            elif "【注】" in memo:
                chu = "〇"
            elif "【切り】" in memo:
                kiri = "〇"
            else:
                if current_eval in ["S"]:
                    jiku = "〇"
                elif current_eval in ["S+", "A+", "A", "B+"]:
                    himo = "〇"
                elif current_eval in ["B"]:
                    chu = "〇"
                else:
                    kiri = "〇"

        row["評価"] = current_eval
        row["軸"] = jiku
        row["ヒモ"] = himo
        row["注"] = chu
        row["切り"] = kiri
        return row

    df = df.apply(calc_eval_and_marks, axis=1)
    return df


# --------------------------------------------------
# 🔄 2. 過去保存済みデータの全自動修復マイグレーション
# --------------------------------------------------

def migrate_and_clean_all_dbs():
    """起動時にデータベース内の過去データをすべてクレンジング・自動修復して安全に上書き保存する"""
    if os.path.exists(DB_FILE):
        try:
            root_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            if not root_df.empty:
                clean_df = sanitize_dataframe_columns(root_df)
                if "年" not in clean_df.columns and "レース名" in clean_df.columns:
                    clean_df["年"] = clean_df["レース名"].apply(extract_year_from_race_name)
                clean_df["年"] = clean_df["年"].replace({"": "2026", "None": "2026", "nan": "2026", "NaN": "2026"})
                clean_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        except Exception:
            pass

    if os.path.exists(DATA_DIR):
        for entry in os.listdir(DATA_DIR):
            y_dir = os.path.join(DATA_DIR, entry)
            if os.path.isdir(y_dir):
                y_file = os.path.join(y_dir, DB_FILE)
                if os.path.exists(y_file):
                    try:
                        ydf = pd.read_csv(y_file, dtype=str).fillna("")
                        if not ydf.empty:
                            clean_ydf = sanitize_dataframe_columns(ydf)
                            if "年" not in clean_ydf.columns and "レース名" in clean_ydf.columns:
                                clean_ydf["年"] = clean_ydf["レース名"].apply(extract_year_from_race_name)
                            clean_ydf["年"] = clean_ydf["年"].replace({"": "2026", "None": "2026", "nan": "2026", "NaN": "2026"})
                            clean_ydf.to_csv(y_file, index=False, encoding="utf-8-sig")
                    except Exception:
                        pass


def load_db(selected_year="2026年"):
    migrate_and_clean_all_dbs()

    all_dfs = []

    year_2026_file = os.path.join(DATA_DIR, "2026", DB_FILE)
    if os.path.exists(year_2026_file):
        try:
            sub_df = pd.read_csv(year_2026_file, dtype=str).fillna("")
            all_dfs.append(sub_df)
        except Exception:
            pass

    if os.path.exists(DB_FILE):
        try:
            m_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            all_dfs.append(m_df)
        except Exception:
            pass

    if os.path.exists(DATA_DIR):
        for entry in os.listdir(DATA_DIR):
            y_dir = os.path.join(DATA_DIR, entry)
            if os.path.isdir(y_dir) and entry != "2026":
                y_file = os.path.join(y_dir, DB_FILE)
                if os.path.exists(y_file):
                    try:
                        sub_df = pd.read_csv(y_file, dtype=str).fillna("")
                        all_dfs.append(sub_df)
                    except Exception:
                        pass

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.replace({"None": "", "none": "", "nan": "", "NaN": ""})

    if "レース名" in combined.columns:
        combined["レース名"] = combined["レース名"].astype(str).str.strip()
        combined = combined[combined["レース名"] != ""]

    combined = combined.drop_duplicates(subset=["レース名", "馬番"], keep="last").reset_index(drop=True)

    if "軸ヒモ切り" in combined.columns:
        combined = combined.drop(columns=["軸ヒモ切り"])
    if "人気" in combined.columns:
        combined = combined.drop(columns=["人気"])

    combined = sanitize_dataframe_columns(combined)

    if "総合スコア" in combined.columns:
        combined["総合スコア_num"] = pd.to_numeric(combined["総合スコア"], errors="coerce").fillna(0).astype(int)
        combined = combined.sort_values(by=["レース名", "総合スコア_num"], ascending=[True, False]).drop(columns=["総合スコア_num"]).reset_index(drop=True)

    if "年" not in combined.columns and "年度" in combined.columns:
        combined["年"] = combined["年度"]
    elif "年" not in combined.columns and "レース名" in combined.columns:
        combined["年"] = combined["レース名"].apply(extract_year_from_race_name)
    elif "年" not in combined.columns:
        combined["年"] = "2026"

    if selected_year and selected_year != "全期間":
        target_y = str(selected_year).replace("年", "").strip()
        combined = combined[combined["年"].astype(str) == target_y].reset_index(drop=True)

    return combined


def get_available_years_in_db():
    df = load_db(selected_year="全期間")
    if df.empty or "年" not in df.columns:
        return ["2026年"]
    years = sorted(df["年"].dropna().unique().tolist(), reverse=True)
    formatted = [f"{y}年" for y in years if str(y).isdigit() and str(y) != "2025"]
    return formatted if formatted else ["2026年"]


def parse_json_ai_output(result_text):
    all_parsed_rows = []

    try:
        clean_text = result_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_text)

        if isinstance(data, dict) and "races" in data and isinstance(data["races"], list):
            race_list = data["races"]
        elif isinstance(data, list):
            race_list = data
        else:
            race_list = [data]

        for race_data in race_list:
            if not isinstance(race_data, dict):
                continue

            race_title = str(race_data.get("race_name", "20261008_競馬解析_OP")).strip()
            confidence = race_data.get("confidence", "")
            risk_level = race_data.get("risk_level", "")
            race_quality_and_tenkai = race_data.get("race_quality_and_tenkai", "")
            recommended_tickets = race_data.get("recommended_tickets", [])
            recap_memo = race_data.get("recap_memo", "")

            horses = race_data.get("horses", [])

            for h in horses:
                if not isinstance(h, dict):
                    continue
                h_num = safe_int(h.get("horse_num", 0))
                h_name = str(h.get("horse_name", "")).strip()
                pop_val = clean_pop_number(h.get("pop", "-"))
                total_score = safe_int(h.get("total_score", 80))
                rank_eval = str(h.get("eval", "A")).strip()

                score_shubahyou = safe_int(h.get("score_shubahyou", total_score))
                score_kettou = safe_int(h.get("score_kettou", total_score))
                score_choukyou = safe_int(h.get("score_choukyou", total_score))
                score_kin5so = safe_int(h.get("score_kin5so", total_score))
                score_tenkai = safe_int(h.get("score_tenkai", total_score))
                score_baba = safe_int(h.get("score_baba", total_score))

                ai_jiku = str(h.get("jiku", "")).strip() == "〇"
                ai_himo = str(h.get("himo", "")).strip() == "〇"
                ai_chu = str(h.get("注", h.get("chu", ""))).strip() == "〇"
                ai_kiri = str(h.get("kiri", "")).strip() == "〇"

                jiku, himo, chu, kiri = "", "", "", ""
                if ai_jiku or rank_eval in ["S", "S+", "A+"]:
                    jiku = "〇"
                elif ai_himo or rank_eval in ["A", "A-", "B+"]:
                    himo = "〇"
                elif ai_chu or rank_eval in ["B", "B-"]:
                    chu = "〇"
                else:
                    kiri = "〇"

                memo = str(h.get("memo", "")).strip()
                if not memo or len(memo) < 10:
                    memo = (
                        f"【評価理由】総合スコア{total_score}点。データ・血統・適性面を考慮して評価を算出。"
                    )

                if h_num > 0 and h_name:
                    row_dict = {
                        "レース名": race_title,
                        "年": extract_year_from_race_name(race_title),
                        "確定着順": clean_pop_number(h.get("rank", "")),
                        "馬番": h_num,
                        "馬名": h_name,
                        "総合スコア": total_score,
                        "評価": rank_eval,
                        "予想人気": pop_val,
                        "単勝人気": clean_pop_number(h.get("single_pop", "")),
                        "確定オッズ": str(h.get("odds", "")).strip(),
                        "タイム": str(h.get("time", "")).strip(),
                        "上り3F": str(h.get("agari", "")).strip(),
                        "勝因・敗因ショートメモ": str(h.get("short_memo", "")).strip(),
                        "出馬表点": score_shubahyou,
                        "血統点": score_kettou,
                        "調教点": score_choukyou,
                        "近5走点": score_kin5so,
                        "展開点": score_tenkai,
                        "馬場点": score_baba,
                        "軸": jiku,
                        "ヒモ": himo,
                        "注": chu,
                        "切り": kiri,
                        "メモ": memo,
                    }
                    if confidence:
                        row_dict["信頼度"] = confidence
                    if risk_level:
                        row_dict["波乱度"] = risk_level
                    if race_quality_and_tenkai:
                        row_dict["レース質展開予想"] = race_quality_and_tenkai
                    if recommended_tickets:
                        row_dict["推奨買い目"] = json.dumps(recommended_tickets, ensure_ascii=False)
                    if recap_memo:
                        row_dict["回顧メモ"] = recap_memo

                    all_parsed_rows.append(row_dict)

    except Exception as e:
        st.warning(f"⚠️ JSON読み込み処理中: {e}")

    if not all_parsed_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_parsed_rows)
    return df


# --------------------------------------------------
# 💬 Gemini API 連携 ウマエルAIチャットUI
# --------------------------------------------------

def render_umael_chat_ui(df, race_title):
    st.divider()
    st.subheader(f"💬 ウマエルAIチャット（【{race_title}】マルチ分析・質問）")
    st.caption("パドック写真・馬体重スクショ・直前メモなどを添付して、ウマエルAIに多角的な質問が可能です！")

    sanitized_title = re.sub(r'\W+', '_', race_title)
    chat_key = f"chat_history_{sanitized_title}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    gemini_key = load_api_key()

    chat_uploaded_files = st.file_uploader(
        "📎 チャット用画像・パドック写真・追加資料（任意添付）",
        type=["png", "jpg", "jpeg", "pdf", "txt", "csv"],
        accept_multiple_files=True,
        key=f"chat_files_{sanitized_title}",
    )

    for msg in st.session_state[chat_key]:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])

    user_input = st.chat_input(f"「{race_title}」について画像添付や質問をする...")

    if user_input:
        st.session_state[chat_key].append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.write(user_input)

        if not gemini_key:
            with st.chat_message("assistant"):
                st.error("⚠️ Gemini API Key が読み込めません。システム設定で API Key を設定してください！")
            return

        with st.chat_message("assistant"):
            with st.spinner("🏇 ウマエルAIが添付データとレース評価を全頭チェックして回答中..."):
                try:
                    cols_to_include = [c for c in ["馬番", "馬名", "総合スコア", "評価", "予想人気", "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点", "軸", "ヒモ", "注", "切り", "メモ"] if c in df.columns]
                    race_context_str = df[cols_to_include].to_string(index=False)

                    system_instruction = f"""あなたは頼れる競馬AIプロフェッショナル「ウマエル」です。
ユーザー（アニキ）からの質問・添付資料に対し、以下の対象レースの全頭評価データを客観的・多角的な根拠として分析し、親しみやすく頼もしい口調で的確に回答してください。

【対象レース名】: {race_title}
【対象レース全頭評価データ】:
{race_context_str}

【回答ルール・ペルソナ】:
- 「アニキ」と呼びかけ、頼もしく誠実・丁寧に回答してください。
- 総合スコア、各種評価点、パドック写真・添付資料の気配などの具体的要素を根拠として挙げてください。
"""

                    history_text = ""
                    for m in st.session_state[chat_key][:-1]:
                        role_name = "アニキ (ユーザー)" if m["role"] == "user" else "ウマエル (AI)"
                        history_text += f"{role_name}: {m['content']}\n"

                    full_prompt_text = f"{system_instruction}\n\n【これまでの会話履歴】:\n{history_text}\n\nアニキの最新の質問: {user_input}"

                    contents_payload = [full_prompt_text]

                    if chat_uploaded_files:
                        for cfile in chat_uploaded_files:
                            cfile.seek(0)
                            cbytes = cfile.read()
                            fname_l = cfile.name.lower()
                            if fname_l.endswith((".txt", ".csv")):
                                contents_payload.append(f"\n【添付テキスト ({cfile.name})】:\n" + cbytes.decode("utf-8", errors="ignore"))
                            elif fname_l.endswith(".pdf"):
                                bio = io.BytesIO(cbytes)
                                pdf_txt = extract_text_from_pdf(bio, page_option="全ページ")
                                contents_payload.append(f"\n【添付PDF ({cfile.name})】:\n" + pdf_txt)
                                contents_payload.append(types.Part.from_bytes(data=cbytes, mime_type="application/pdf"))
                            elif fname_l.endswith((".png", ".jpg", ".jpeg")):
                                m_type = "image/png" if fname_l.endswith(".png") else "image/jpeg"
                                contents_payload.append(types.Part.from_bytes(data=cbytes, mime_type=m_type))

                    client = genai.Client(api_key=gemini_key)
                    response = client.models.generate_content(
                        model="gemini-3.8-flash",
                        contents=contents_payload,
                        config=types.GenerateContentConfig(
                            temperature=0.3,
                            seed=42,
                        ),
                    )

                    ai_reply = response.text
                    st.write(ai_reply)
                    st.session_state[chat_key].append({"role": "assistant", "content": ai_reply})

                except Exception as e:
                    st.error(f"❌ チャット処理中にエラーが発生しました: {e}")


# --------------------------------------------------
# 🎨 デザインCSS定義（アクションボタン オレンジ系カラー一括統一）
# --------------------------------------------------

st.markdown(
    """
<style>
    [data-testid="stAppViewContainer"] {
        width: 100% !important;
    }
    .main .block-container,
    div[data-testid="stMainBlockContainer"],
    div[data-testid="stAppViewBlockContainer"],
    section.main > div {
        max-width: 98% !important;
        width: 98% !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        padding-top: 1.5rem !important;
    }

    .main { background-color: #0b0e14; }
    h1, h2, h3 { color: #f39c12 !important; font-weight: bold; }

    /* データフレーム・プログレスバー */
    div[data-testid="stDataFrame"] div[role="progressbar"] {
        height: 12px !important;
        border-radius: 4px !important;
        background-color: #1e2638 !important;
    }
    div[data-testid="stDataFrame"] div[role="progressbar"] > div {
        background: #0bce0e !important;
        border-radius: 4px !important;
    }
    
    /* -------------------------------------------------- */
    /* 🎨 アクションボタン オレンジ系一括統一設定 */
    /* -------------------------------------------------- */
    div.stButton > button,
    button[data-testid="stBaseButton-secondary"],
    button[data-testid="stBaseButton-primary"] {
        background-color: #d84315 !important;
        background: #d84315 !important;
        color: #ffffff !important;
        border: 1px solid #ff5722 !important;
        font-weight: bold !important;
        box-shadow: 0 2px 5px rgba(216, 67, 21, 0.4) !important;
    }
    div.stButton > button:hover,
    button[data-testid="stBaseButton-secondary"]:hover,
    button[data-testid="stBaseButton-primary"]:hover {
        background-color: #bf360c !important;
        background: #bf360c !important;
        border-color: #ff7043 !important;
        box-shadow: 0 0 12px rgba(255, 87, 34, 0.7) !important;
    }
    
    /* 波乱度判定カード */
    .risk-card {
        background: linear-gradient(135deg, #0a192f 0%, #0f2b46 100%);
        border: 2px solid #00f0ff; 
        border-radius: 10px; 
        padding: 16px; 
        text-align: center; 
        margin-bottom: 20px; 
        box-shadow: 0 0 15px rgba(0, 240, 255, 0.25);
    }
    
    /* 本命馬カード */
    .honmei-card {
        background: linear-gradient(135deg, #2a1c00 0%, #422d00 100%);
        border: 2px solid #f39c12; 
        border-radius: 10px; 
        padding: 16px; 
        margin-bottom: 15px; 
        box-shadow: 0 0 12px rgba(243, 156, 18, 0.35);
    }
    
    /* 穴馬カード */
    .anaba-card {
        background: linear-gradient(135deg, #330005 0%, #52000a 100%);
        border: 2px solid #e74c3c; 
        border-radius: 10px; 
        padding: 16px; 
        margin-bottom: 15px; 
        box-shadow: 0 0 12px rgba(231, 76, 60, 0.35);
    }
    
    /* 買い目カード */
    .kaime-card-item {
        background: #0d1117; 
        border: 2px solid #f39c12; 
        border-left: 6px solid #f39c12; 
        border-radius: 8px; 
        padding: 12px 18px; 
        margin-bottom: 10px; 
        font-size: 1.1rem; 
        color: #ffffff; 
        box-shadow: 0 0 10px rgba(243, 156, 18, 0.2);
    }

    .card-title { font-size: 1.1rem; font-weight: bold; color: #ffffff; margin-bottom: 5px; }
    
    .card-horse-name { 
        font-size: 1.45rem !important; 
        font-weight: bold; 
        color: #ffffff; 
        margin: 4px 0 10px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .card-val-gold { font-size: 2.2rem; font-weight: bold; color: #f39c12; line-height: 1; }
    .card-val-red { font-size: 2.2rem; font-weight: bold; color: #ff4d4d; line-height: 1; }
</style>
""",
    unsafe_allow_html=True,
)


def render_race_evaluation_view(df, is_viewer_mode=False, show_chat=True):
    if df.empty:
        st.warning("⚠️ 表示できる解析データがありません。")
        return

    df = sanitize_dataframe_columns(df)
    df = df[df["馬名"].astype(str).str.strip() != ""].dropna(how="all").reset_index(drop=True)
    if df.empty:
        st.warning("⚠️ 有効な出走馬データが見つかりませんでした。")
        return

    race_title = (
        df["レース名"].iloc[0]
        if "レース名" in df.columns and not df.empty
        else "競馬予想解析"
    )

    view_df = df.drop(
        columns=["レース名", "信頼度", "波乱度", "レース質展開予想", "推奨買い目", "確定着順", "回顧メモ", "軸ヒモ切り", "人気", "年度", "年"],
        errors="ignore",
    ).fillna("").replace({"None": "", "none": "", "nan": "", "NaN": ""})

    target_order = [
        "馬番", "馬名", "総合スコア", "評価", "予想人気",
        "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点",
        "軸", "ヒモ", "注", "切り", "メモ"
    ]
    existing_cols = [c for c in target_order if c in view_df.columns]
    other_cols = [c for c in view_df.columns if c not in target_order]
    view_df = view_df[existing_cols + other_cols]

    honmei_horse = view_df.iloc[0] if not view_df.empty else None
    h_score = safe_int(honmei_horse.get("総合スコア", 0)) if honmei_horse is not None else 0

    if "信頼度" in df.columns and str(df["信頼度"].iloc[0]).strip():
        jiku_rank = str(df["信頼度"].iloc[0])
    else:
        jiku_rank = "A (有力軸)" if h_score >= 87 else "B (波乱含み)"

    if "波乱度" in df.columns and str(df["波乱度"].iloc[0]).strip():
        risk_level = str(df["波乱度"].iloc[0])
    else:
        risk_level = "★★☆ (中波乱警戒)"

    df_copy = view_df.copy()
    other_horses = df_copy.iloc[1:].copy() if len(df_copy) > 1 else pd.DataFrame()
    ana_horse = other_horses.iloc[0] if not other_horses.empty else honmei_horse

    h_num = str(safe_int(honmei_horse.get("馬番", 1))) if honmei_horse is not None else "1"
    h_name = str(honmei_horse.get("馬名", "本命馬")) if honmei_horse is not None else "本命馬"

    raw_tickets = df["推奨買い目"].iloc[0] if "推奨買い目" in df.columns else None
    tickets_list = []
    if raw_tickets:
        try:
            tickets_list = json.loads(raw_tickets)
        except Exception:
            pass

    if not tickets_list:
        aite_rows = view_df.iloc[1:6] if len(view_df) > 1 else view_df
        aite_nums = [str(safe_int(r.get("馬番", i + 1))) for i, (_, r) in enumerate(aite_rows.iterrows())]
        aite_str = ", ".join(aite_nums)
        tickets_list = [
            f"【単勝】 {h_num} ({h_name})",
            f"【馬連 軸1頭流し】 {h_num} ＝ {aite_str}",
            f"【ワイド 流し】 {h_num} ＝ {aite_str}",
            f"【3連複 フォーメーション】 {h_num} － {aite_str}",
        ]

    if not is_viewer_mode:
        encoded_race = urllib.parse.quote(str(race_title))
        share_url = f"https://umael-pro.streamlit.app/?mode=share&race={encoded_race}"
        st.info("🔗 **レース名入り評価結果 専用共有URL:**")
        st.code(share_url, language="text")

        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
        render_re_evaluation_section(df, active_selected_rule, "gemini-3.8-flash")

    view_tab1, view_tab2 = st.tabs(["🌟 推奨評価上位サマリー", "📊 詳細全データ表（評価順）"])

    with view_tab1:
        st.markdown(
            f"<h2 style='text-align: center; color: #f39c12; margin-bottom: 20px;'>🏇 {race_title} 🏇</h2>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="risk-card">
                <div style="font-size:1.15rem; font-weight:bold; color:#fff; margin-bottom:12px;">🔥 レース展開 ＆ 波乱度判定</div>
                <div style="display:flex; justify-content:space-around; align-items:center; flex-wrap:wrap; gap:15px;">
                    <div style="flex:1; min-width:160px; text-align:center;">
                        <span style="color:#aaa; font-size:0.85rem;">軸馬信頼度</span><br>
                        <b style="font-size:1.4rem; color:#00f0ff;">{jiku_rank}</b>
                    </div>
                    <div style="flex:1; min-width:160px; text-align:center;">
                        <span style="color:#aaa; font-size:0.85rem;">波乱度レベル</span><br>
                        <b style="font-size:1.4rem; color:#ffd700;">{risk_level}</b>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        col_left, col_right = st.columns([1, 1.3])

        with col_left:
            if honmei_horse is not None:
                raw_pop = clean_pop_number(honmei_horse.get("予想人気", "-"))
                h_pop_str = f"{raw_pop}人気" if raw_pop else "-"
                st.markdown(
                    f"""
                    <div class="honmei-card">
                        <div class="card-title">◎ 本命推奨馬</div>
                        <div class="card-horse-name">【{h_num}】{h_name}</div>
                        <div style="display:flex; justify-content:space-around; align-items:center; margin-top:8px;">
                            <div style="flex:1; text-align:center;">
                                <span style="color:#aaa; font-size:0.8rem;">想定人気</span><br>
                                <b style="font-size:1.2rem; color:#fff;">{h_pop_str}</b>
                            </div>
                            <div style="flex:1; text-align:center;">
                                <span style="color:#aaa; font-size:0.8rem;">指数合計値</span><br>
                                <b class="card-val-gold">{h_score}</b>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if ana_horse is not None:
                a_num = str(safe_int(ana_horse.get("馬番", 1)))
                a_name = str(ana_horse.get("馬名", "穴馬"))
                raw_a_pop = clean_pop_number(ana_horse.get("予想人気", "-"))
                a_pop_str = f"{raw_a_pop}人気" if raw_a_pop else "-"
                a_score = safe_int(ana_horse.get("総合スコア", 0))
                st.markdown(
                    f"""
                    <div class="anaba-card">
                        <div class="card-title">⚠ 注目波乱馬（穴馬）</div>
                        <div class="card-horse-name">【{a_num}】{a_name}</div>
                        <div style="display:flex; justify-content:space-around; align-items:center; margin-top:8px;">
                            <div style="flex:1; text-align:center;">
                                <span style="color:#aaa; font-size:0.8rem;">想定人気</span><br>
                                <b style="font-size:1.2rem; color:#fff;">{a_pop_str}</b>
                            </div>
                            <div style="flex:1; text-align:center;">
                                <span style="color:#aaa; font-size:0.8rem;">指数合計値</span><br>
                                <b class="card-val-red">{a_score}</b>
                            </div>
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        with col_right:
            st.subheader("📊 総合評価順位一覧")

            sub_cols = [c for c in ["馬番", "馬名", "予想人気", "総合スコア"] if c in view_df.columns]
            disp_df = view_df[sub_cols].copy()

            if "予想人気" in disp_df.columns:
                disp_df["予想人気"] = disp_df["予想人気"].apply(lambda x: f"{clean_pop_number(x)}人気" if clean_pop_number(x) else "")

            if "馬番" in disp_df.columns:
                disp_df["馬番"] = pd.to_numeric(disp_df["馬番"], errors="coerce").fillna(0).astype(int)
            if "総合スコア" in disp_df.columns:
                disp_df["総合スコア"] = pd.to_numeric(disp_df["総合スコア"], errors="coerce").fillna(0).astype(int)

            col_config_sum = {
                "馬番": st.column_config.NumberColumn("馬番", width="small"),
                "馬名": st.column_config.TextColumn("馬名", width="medium"),
                "予想人気": st.column_config.TextColumn("予想人気", width="small"),
                "総合スコア": st.column_config.ProgressColumn(
                    "指数合計値", format="%d点", min_value=0, max_value=100, color="#0bce0e"
                ),
            }

            top_group = disp_df.head(5)
            sub_group = disp_df.iloc[5:] if len(disp_df) > 5 else pd.DataFrame()

            st.write("🟢 **上位推奨グループ（軸・相手筆頭）**")
            st.dataframe(top_group, column_config=col_config_sum, use_container_width=True, hide_index=True)

            if not sub_group.empty:
                st.write("🟡 **相手紐・穴馬グループ**")
                st.dataframe(sub_group, column_config=col_config_sum, use_container_width=True, hide_index=True)

        st.divider()

        if "レース質展開予想" in df.columns and str(df["レース質展開予想"].iloc[0]).strip():
            tenkai_text = str(df["レース質展開予想"].iloc[0]).strip()
            st.subheader("🏁 レース質 ＆ 展開予想シミュレーション")
            st.markdown(
                f"""
                <div style="background-color: #0c1424; border: 2px solid #2563eb; border-radius: 10px; padding: 18px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.7; color: #f1f5f9; font-size: 0.98rem; box-shadow: 0 0 15px rgba(37, 99, 235, 0.25);">
{tenkai_text}
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("💡 推奨買い目フォーメーション")

        for t_item in tickets_list:
            clean_t = re.sub(r"<[^>]+>", "", str(t_item)).strip()
            if clean_t:
                circled_t = convert_to_circled_numbers(clean_t)
                st.markdown(
                    f"""
                    <div class="kaime-card-item">
                        📌 <b>{circled_t}</b>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with view_tab2:
        st.subheader(f"📊 {race_title} 詳細全データ表（評価順）")
        st.info("💡 **※「メモ（詳細分析）」等の各セルは、枠内をダブルクリック（スマホはダブルタップ）すると全文を拡大表示・コピーできます！**")

        col_config_detail = {
            "馬番": st.column_config.NumberColumn("馬番", width="small"),
            "馬名": st.column_config.TextColumn("馬名", width="medium"),
            "予想人気": st.column_config.TextColumn("予想人気", width="small"),
            "総合スコア": st.column_config.ProgressColumn(
                "総合スコア", format="%d点", min_value=0, max_value=100, width="medium", color="#0bce0e"
            ),
            "評価": st.column_config.TextColumn("評価", width="small"),
            "出馬表点": st.column_config.NumberColumn("出馬表点", width="small"),
            "血統点": st.column_config.NumberColumn("血統点", width="small"),
            "調教点": st.column_config.NumberColumn("調教点", width="small"),
            "近5走点": st.column_config.NumberColumn("近5走点", width="small"),
            "展開点": st.column_config.NumberColumn("展開点", width="small"),
            "馬場点": st.column_config.NumberColumn("馬場点", width="small"),
            "軸": st.column_config.TextColumn("軸", width="small"),
            "ヒモ": st.column_config.TextColumn("ヒモ", width="small"),
            "注": st.column_config.TextColumn("注", width="small"),
            "切り": st.column_config.TextColumn("切り", width="small"),
            "メモ": st.column_config.TextColumn("メモ（詳細分析）", width="large"),
        }

        calc_table_height = min(600, (len(view_df) + 1) * 35 + 38)

        st.dataframe(
            view_df,
            column_config=col_config_detail,
            use_container_width=True,
            height=calc_table_height,
            hide_index=True,
        )

    if show_chat:
        render_umael_chat_ui(df, race_title)


# URLパラメータ共有ビュー分岐
query_params = st.query_params
mode_param = query_params.get("mode", "")
race_param = query_params.get("race", "")

if mode_param == "share" and race_param:
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none !important; }
        div[data-testid="stSidebarCollapseButton"] { display: none !important; }
        header[data-testid="stHeader"] { display: none !important; }
        footer { display: none !important; }
        .main .block-container,
        div[data-testid="stMainBlockContainer"],
        div[data-testid="stAppViewBlockContainer"] {
            max-width: 100% !important;
            width: 100% !important;
            padding-left: 1rem !important;
            padding-right: 1rem !important;
            padding-top: 1rem !important;
            padding-bottom: 1rem !important;
        }
    </style>
    """, unsafe_allow_html=True)

    db_df = load_db(selected_year="2026年")
    if not db_df.empty and "レース名" in db_df.columns:
        matched_df = db_df[db_df["レース名"].astype(str).str.strip() == str(race_param).strip()]
        if not matched_df.empty:
            render_race_evaluation_view(matched_df, is_viewer_mode=True, show_chat=True)
        else:
            st.error(f"⚠️ レース「{race_param}」の解析データは見つかりませんでした。")
    else:
        st.error("⚠️ データベースに予想データが登録されていません。")

    st.stop()


# セッションステート初期化（ルール読込の安定化）
if "g1_text_val" not in st.session_state:
    st.session_state["g1_text_val"] = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)

if "gen_text_val" not in st.session_state:
    st.session_state["gen_text_val"] = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)

if "hok_text_val" not in st.session_state:
    st.session_state["hok_text_val"] = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)

if "uploader_key_ver" not in st.session_state:
    st.session_state["uploader_key_ver"] = 0


def save_to_db(new_df):
    if new_df is None or new_df.empty:
        return load_db(selected_year="2026年")
    
    clean_save_df = sanitize_dataframe_columns(new_df)
    clean_save_df = clean_save_df.drop(columns=["総合スコアグラフ", "軸ヒモ切り", "人気"], errors="ignore")

    if "レース名" not in clean_save_df.columns:
        return load_db(selected_year="2026年")

    clean_save_df["レース名"] = clean_save_df["レース名"].astype(str).str.strip()
    clean_save_df = clean_save_df[clean_save_df["レース名"] != ""]

    if "年" not in clean_save_df.columns:
        clean_save_df["年"] = clean_save_df["レース名"].apply(extract_year_from_race_name)
    clean_save_df["年"] = clean_save_df["年"].replace({"": "2026", "None": "2026", "nan": "2026", "NaN": "2026"})

    races = clean_save_df["レース名"].unique()

    for race_n in races:
        race_sub_df = clean_save_df[clean_save_df["レース名"] == race_n].copy()
        if race_sub_df.empty:
            continue

        target_year = "2026"

        if os.path.exists(DB_FILE):
            try:
                old_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
                old_df = old_df.drop(columns=["総合スコアグラフ", "軸ヒモ切り", "人気"], errors="ignore")
                if "レース名" in old_df.columns:
                    old_df = old_df[old_df["レース名"].astype(str).str.strip() != str(race_n)]
                combined_df = pd.concat([old_df, race_sub_df], ignore_index=True)
                combined_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
            except Exception:
                race_sub_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        else:
            race_sub_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")

        year_dir = os.path.join(DATA_DIR, target_year)
        os.makedirs(year_dir, exist_ok=True)
        year_db_path = os.path.join(year_dir, DB_FILE)

        if os.path.exists(year_db_path):
            try:
                old_y_df = pd.read_csv(year_db_path, dtype=str).fillna("")
                if "レース名" in old_y_df.columns:
                    old_y_df = old_y_df[old_y_df["レース名"].astype(str).str.strip() != str(race_n)]
                combined_y_df = pd.concat([old_y_df, race_sub_df], ignore_index=True)
                combined_y_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")
            except Exception:
                race_sub_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")
        else:
            race_sub_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")

    return load_db(selected_year="2026年")


def update_db_with_recap(race_name, result_df, memo_text):
    if not os.path.exists(DB_FILE):
        return
    try:
        df = pd.read_csv(DB_FILE, dtype=str).fillna("")
        df = sanitize_dataframe_columns(df)
        df = df.replace({"None": "", "none": "", "nan": "", "NaN": ""})

        if "レース名" not in df.columns:
            return

        mask = df["レース名"].astype(str).str.strip() == str(race_name).strip()
        if not mask.any():
            return

        result_by_num = {}
        if not result_df.empty and "馬番" in result_df.columns:
            for _, result_row in result_df.iterrows():
                horse_num = normalize_horse_num(result_row.get("馬番", ""))
                if horse_num:
                    result_by_num[horse_num] = result_row

        result_columns = [
            "確定着順", "単勝人気", "確定オッズ", "タイム", "上り3F",
            "勝因・敗因ショートメモ",
        ]
        for col in result_columns + ["回顧メモ"]:
            if col not in df.columns:
                df[col] = ""

        for idx in df.index[mask]:
            horse_num = normalize_horse_num(df.at[idx, "馬番"] if "馬番" in df.columns else "")
            result_row = result_by_num.get(horse_num)
            if result_row is not None:
                pop_val = clean_pop_number(result_row.get("単勝人気", result_row.get("人気", "")))
                if pop_val:
                    df.at[idx, "単勝人気"] = pop_val
                for col in result_columns:
                    if col in result_df.columns and col != "単勝人気":
                        value = result_row.get(col, "")
                        if pd.notna(value) and str(value).strip():
                            val_clean = clean_pop_number(value) if col == "確定着順" else str(value).strip()
                            df.at[idx, col] = val_clean
            df.at[idx, "回顧メモ"] = str(memo_text).strip()

        df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")

        year_db_path = os.path.join(DATA_DIR, "2026", DB_FILE)
        os.makedirs(os.path.join(DATA_DIR, "2026"), exist_ok=True)
        df.to_csv(year_db_path, index=False, encoding="utf-8-sig")

    except Exception as e:
        st.warning(f"⚠️ データベースの回顧・着順プール保存中に注意: {e}")


def delete_race_from_db(race_name):
    """データベースから特定のレースを完全に削除する関数"""
    if not race_name or not str(race_name).strip():
        return False
    
    target_race_str = str(race_name).strip()
    success = False

    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            if "レース名" in df.columns:
                new_df = df[df["レース名"].astype(str).str.strip() != target_race_str]
                new_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
                success = True
        except Exception:
            pass

    if os.path.exists(DATA_DIR):
        for entry in os.listdir(DATA_DIR):
            y_dir = os.path.join(DATA_DIR, entry)
            if os.path.isdir(y_dir):
                y_file = os.path.join(y_dir, DB_FILE)
                if os.path.exists(y_file):
                    try:
                        ydf = pd.read_csv(y_file, dtype=str).fillna("")
                        if "レース名" in ydf.columns:
                            new_ydf = ydf[ydf["レース名"].astype(str).str.strip() != target_race_str]
                            new_ydf.to_csv(y_file, index=False, encoding="utf-8-sig")
                            success = True
                    except Exception:
                        pass
    return success


def analyze_data_with_gemini(
    api_key, active_rules,
    text_group1, parts_group1,
    text_group2, parts_group2,
    text_group3, parts_group3,
    text_group4, parts_group4,
    text_group5,
    model_name="gemini-3.8-flash",
):
    client = genai.Client(api_key=api_key)

    json_prompt = f"""{active_rules}

【★レース名・グレードの厳格特定＆適合ルール（絶対厳守）】
1. 添付されたデータから、「開催日（西暦8桁 YYYYMMDD）」「正確なレース名」「実際のレースグレード（G1, Jpn1, G2, G3, L, OP等）」を正確に検知し、`race_name` は必ず YYYYMMDD_レース名_グレード 形式で生成すること。
2. 予想人気、単勝人気、着順の出力は数字のみ（例: 1, 2）とすること。

=== 【グループ1：出馬表・枠順・近5走・血統】 ===
{text_group1}

=== 【グループ2：競馬ブック・調教データ】 ===
{text_group2}

=== 【グループ3：当日・前日の傾向・馬場情報】 ===
{text_group3}

=== 【グループ4：その他各種データ等】 ===
{text_group4}

=== 【グループ5：プロ予想・YouTube字幕・Web参考URL】 ===
{text_group5}

【出力形式】
純粋なJSONのみを出力してください。
"""

    contents_payload = [json_prompt]
    contents_payload.extend(parts_group1)
    contents_payload.extend(parts_group2)
    contents_payload.extend(parts_group3)
    contents_payload.extend(parts_group4)

    max_retries = 5
    for attempt in range(max_retries):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=contents_payload,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                    seed=42,
                ),
            )
            return response.text
        except Exception as e:
            err_msg = str(e)
            if "503" in err_msg or "UNAVAILABLE" in err_msg:
                if attempt < max_retries - 1:
                    time.sleep(5)
                    continue
                else:
                    raise Exception("⚠️ Googleサーバーが一時的に混雑しています。再度実行してください。")
            elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                raise Exception("⚠️ 本日の無料枠上限に達しました。")
            else:
                raise e


# --------------------------------------------------
# 🧭 UI・画面メイン構成
# --------------------------------------------------

if "draft_toast_msg" in st.session_state:
    msg_type, msg_text = st.session_state.pop("draft_toast_msg")
    if msg_type == "success":
        st.success(msg_text)
        st.toast(msg_text, icon="✅")
    elif msg_type == "warning":
        st.warning(msg_text)
        st.toast(msg_text, icon="⚠️")
    elif msg_type == "error":
        st.error(msg_text)
        st.toast(msg_text, icon="❌")

st.markdown("<div style='padding-top: 15px;'></div>", unsafe_allow_html=True)

st.title("ウマエルプロ v3.0")
st.caption("馬柱・血統・予想オッズ・競馬ブック・各種データ・回顧 一括AI解析＆年度別プール Webアプリ")

with st.sidebar:
    st.header("🧭 ナビゲーション")

    selected_menu = st.radio(
        "移動する機能を選択してください：",
        [
            "📋 レース分析・予想",
            "📜 過去レース評価・結果・回顧（一括登録）",
            "🏇 現地観戦用（勝負5R厳選）",
            "⚙️ ルール管理・アップデート",
            "🔄 回顧・精度検証",
            "📊 評価データ一覧（プール）",
            "📝 回顧・精度検証一覧（プール）",
            "🗄 過去馬データベース（プール）",
        ],
        index=0,
    )

    st.divider()

    with st.expander("⚙️ システム設定", expanded=False):
        saved_key = load_api_key()
        api_key = st.text_input(
            "Gemini API Key",
            value=saved_key,
            type="password",
            help="入力すると自動で保存され、次回から自動ロードされます",
        )

        if api_key and api_key != saved_key:
            save_api_key(api_key)

        selected_model = st.selectbox(
            "🤖 使用AIモデル",
            ["gemini-3.8-flash"],
            index=0,
            help="推奨モデル: gemini-3.8-flash",
        )
        st.caption("🔑 st.secrets / APIキー自動設定機能オン")
        st.caption("📱 スマホ表示対応モード動作中")


if selected_menu == "📋 レース分析・予想":
    st.subheader("🎯 解析ルールの選択 ＆ 段階的データ保存")

    rule_type = st.radio(
        "今回解析するレースのルールを選択してください：",
        [
            "🏆 G1専用ルール",
            "🏇 平場・G2・G3専用ルール",
            "🌾 北海道・洋芝専用ルール",
        ],
        horizontal=True,
    )

    # ルールテキストの動的安定読込
    if "G1専用" in rule_type:
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
        st.info("💡 現在 【 🏆 G1専用ルール 】 が選択されています。")
    elif "北海道" in rule_type:
        active_selected_rule = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
        st.info("💡 現在 【 🌾 北海道・洋芝専用ルール 】 が選択されています。")
    else:
        active_selected_rule = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)
        st.info("💡 現在 【 🏇 平場・G2・G3専用ルール 】 が選択されています。")

    st.divider()

    st.subheader("📁 レースデータの蓄積・下書き管理")

    upload_mode = st.radio(
        "運用モードを選択してください：",
        [
            "📥 金〜日曜のデータを段階的に下書き保存・一括解析",
            "⚡ 今日届いたデータで直接解析（単発実行）",
        ],
        horizontal=True,
    )

    draft_race_name = ""
    draft_choice = ""
    existing_drafts = list_draft_races()

    if "段階的" in upload_mode:
        draft_col1, draft_col2 = st.columns([1.5, 1])

        with draft_col1:
            default_idx = 0
            if "selected_draft_race" in st.session_state and st.session_state["selected_draft_race"] in existing_drafts:
                default_idx = existing_drafts.index(st.session_state["selected_draft_race"]) + 1

            draft_choice = st.selectbox(
                "📂 保存・編集する対象レースを選択（新規または既存）：",
                ["✨ 【新規レースとして保存（馬柱からレース名自動判定）】"] + existing_drafts,
                index=default_idx,
                key="draft_race_select_box"
            )
            
            if draft_choice == "✨ 【新規レースとして保存（馬柱からレース名自動判定）】":
                draft_race_name = st.text_input(
                    "✏️ レース名を手動指定する場合（※空欄ならファイル名から自動設定されます）",
                    "",
                )
                display_target_name = draft_race_name.strip() if draft_race_name.strip() else "✨ 新規レース（自動判定）"
            else:
                draft_race_name = draft_choice
                display_target_name = draft_choice

                # 💡【機能自動復元】下書き選択時、データベースに一致する解析済みデータがあれば自動ロードして画面描画
                db_df_check = load_db(selected_year="2026年")
                if not db_df_check.empty and "レース名" in db_df_check.columns:
                    matched_draft_df = db_df_check[db_df_check["レース名"].astype(str).str.strip() == str(draft_choice).strip()]
                    if not matched_draft_df.empty:
                        st.session_state["analyzed_df"] = matched_draft_df

            st.info(f"🎯 **現在の操作対象:** ` {display_target_name} `")

        with draft_col2:
            if draft_race_name and draft_race_name not in [
                "✨ 【新規レースとして保存（馬柱からレース名自動判定）】",
                "",
            ]:
                st.write("📦 **選択中レースの蓄積状況**")
                _, _, _, _, _, _, _, _, _, saved_fnames = load_draft_data(draft_race_name)
                if saved_fnames:
                    st.success(f"保存済みファイル: {len(saved_fnames)}件")
                    with st.expander("保存中のファイル一覧"):
                        for fn in saved_fnames:
                            st.caption(f"・{fn}")
                else:
                    st.caption("まだ保存されているファイルはありません。")

    st.divider()
    st.subheader("📂 データのアップロード（5項目構成）")

    uploader_ver = st.session_state["uploader_key_ver"]

    col1, col2 = st.columns(2)
    with col1:
        files_group1 = st.file_uploader(
            "1. 出馬表・枠順・近5走・血統 (.txt / .csv / .pdf / .png / .jpg)",
            type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"fg1_{uploader_ver}",
        )
    with col2:
        files_group2 = st.file_uploader(
            "2. 競馬ブック・調教データ (.pdf / .png / .jpg)",
            type=["pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"fg2_{uploader_ver}",
        )
        pdf_page_opt = st.radio(
            "📄 競馬ブックPDFの読み込み範囲",
            ["1ページ目のみ（推奨）", "全ページ読み込む"],
            index=0,
            key="pdf_page_opt",
        )

    col3, col4 = st.columns(2)
    with col3:
        files_group3 = st.file_uploader(
            "3. 当日・前日の傾向・馬場情報 (.txt / .csv / .pdf / .png / .jpg)",
            type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"fg3_{uploader_ver}",
        )
    with col4:
        files_group4 = st.file_uploader(
            "4. その他各種データ等 (.txt / .csv / .pdf / .png / .jpg) 【新規】",
            type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"fg4_{uploader_ver}",
        )

    st.write("")
    urls_group5_input = st.text_area(
        "🔗 5. プロ予想・YouTube・Web参考URL（改行して複数貼り付けOK）",
        height=90,
        placeholder="https://www.youtube.com/watch?v=...\nhttps://note.com/...",
        key=f"ug5_{uploader_ver}",
    )

    st.divider()

    if "段階的" in upload_mode:
        btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1.5, 1])

        with btn_col1:
            if st.button("💾 今回のデータを下書き保存する", use_container_width=True):
                if (
                    not files_group1 and not files_group2 and not files_group3
                    and not files_group4 and not urls_group5_input.strip()
                ):
                    st.session_state["draft_toast_msg"] = ("warning", "⚠️ 追加保存するファイルまたはURLを入力してください！")
                    st.rerun()
                else:
                    with st.spinner("💾 ファイル・データを下書き保存中..."):
                        target_name = draft_race_name.strip() if draft_race_name and draft_race_name.strip() else ""
                        try:
                            saved_c, actual_draft_name = save_draft_data(
                                target_name,
                                files_group1,
                                files_group2,
                                files_group3,
                                files_group4,
                                urls_group5_input,
                            )
                            st.session_state["uploader_key_ver"] += 1
                            st.session_state["selected_draft_race"] = actual_draft_name
                            st.session_state["draft_toast_msg"] = (
                                "success",
                                f"🎉 レース「{actual_draft_name}」にデータ（ファイル{saved_c}件/URL）を下書き保存しました！"
                            )
                            st.session_state.pop("analyzed_df", None)
                            st.rerun()
                        except Exception as e:
                            st.session_state["draft_toast_msg"] = ("error", f"❌ 保存中にエラーが発生しました: {e}")
                            st.rerun()

        with btn_col2:
            if st.button("🔥 蓄積された全データでAI一括解析を実行", use_container_width=True):
                active_key = load_api_key()
                if not active_key:
                    st.error("⚠️ Gemini API Key が設定されていません。")
                else:
                    pdf_opt_val = "1ページ目のみ" if "1ページ目のみ" in pdf_page_opt else "全ページ"
                    target_draft = draft_race_name if (draft_race_name and draft_choice != "✨ 【新規レースとして保存（馬柱からレース名自動判定）】") else ""

                    dt1, dp1, dt2, dp2, dt3, dp3, dt4, dp4, dt5, _ = (
                        load_draft_data(target_draft, pdf_page_option=pdf_opt_val)
                        if target_draft else ("", [], "", [], "", [], "", [], "", [])
                    )

                    nt1, np1 = prepare_file_parts(files_group1, pdf_page_option=pdf_opt_val)
                    nt2, np2 = prepare_file_parts(files_group2, pdf_page_option=pdf_opt_val)
                    nt3, np3 = prepare_file_parts(files_group3, pdf_page_option=pdf_opt_val)
                    nt4, np4 = prepare_file_parts(files_group4, pdf_page_option=pdf_opt_val)
                    nt5 = process_multiple_urls(urls_group5_input)

                    comb_t1, comb_p1 = dt1 + "\n" + nt1, dp1 + np1
                    comb_t2, comb_p2 = dt2 + "\n" + nt2, dp2 + np2
                    comb_t3, comb_p3 = dt3 + "\n" + nt3, dp3 + np3
                    comb_t4, comb_p4 = dt4 + "\n" + nt4, dp4 + np4
                    comb_t5 = dt5 + "\n" + nt5

                    if not any([comb_t1.strip(), comb_t2.strip(), comb_t3.strip(), comb_t4.strip(), comb_p1, comb_p2, comb_p3, comb_p4]):
                        st.warning("⚠️ 解析対象のデータが見つかりません。")
                    else:
                        with st.spinner("🏇 全データでAI一括解析中..."):
                            try:
                                result_text = analyze_data_with_gemini(
                                    active_key, active_selected_rule,
                                    comb_t1, comb_p1, comb_t2, comb_p2, comb_t3, comb_p3, comb_t4, comb_p4, comb_t5,
                                    selected_model
                                )
                                df = parse_json_ai_output(result_text)
                                if not df.empty:
                                    save_to_db(df)
                                    if target_draft:
                                        delete_draft(target_draft)
                                        st.session_state.pop("selected_draft_race", None)
                                    st.session_state["analyzed_df"] = df
                                    st.success("🎉 AI自動解析が完了し、2026年データベースに保存されました！")
                                    st.rerun()
                            except Exception as e:
                                st.error(f"❌ 解析中にエラーが発生しました: {e}")

        with btn_col3:
            if st.button("🗑️ この下書きを削除", use_container_width=True):
                if draft_race_name and draft_choice != "✨ 【新規レースとして保存（馬柱からレース名自動判定）】":
                    delete_draft(draft_race_name)
                    st.session_state.pop("selected_draft_race", None)
                    st.session_state.pop("analyzed_df", None)
                    st.session_state["draft_toast_msg"] = ("success", f"🗑️ 下書きデータ「{draft_race_name}」を削除しました！")
                    st.rerun()

    else:
        if st.button("🔥 AI分析を実行する", use_container_width=True):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key が設定されていません。")
            elif not any([files_group1, files_group2, files_group3, files_group4, urls_group5_input.strip()]):
                st.warning("⚠️ 解析するデータを入力してください！")
            else:
                with st.spinner("🏇 AI解析を実行中..."):
                    try:
                        pdf_opt_val = "1ページ目のみ" if "1ページ目のみ" in pdf_page_opt else "全ページ"
                        t1, p1 = prepare_file_parts(files_group1, pdf_page_option=pdf_opt_val)
                        t2, p2 = prepare_file_parts(files_group2, pdf_page_option=pdf_opt_val)
                        t3, p3 = prepare_file_parts(files_group3, pdf_page_option=pdf_opt_val)
                        t4, p4 = prepare_file_parts(files_group4, pdf_page_option=pdf_opt_val)
                        t5 = process_multiple_urls(urls_group5_input)

                        result_text = analyze_data_with_gemini(
                            active_key, active_selected_rule,
                            t1, p1, t2, p2, t3, p3, t4, p4, t5,
                            selected_model
                        )
                        df = parse_json_ai_output(result_text)
                        if not df.empty:
                            save_to_db(df)
                            st.session_state["analyzed_df"] = df
                            st.success("🎉 解析が完了し、2026年データベースに保存されました！")
                            st.rerun()
                    except Exception as e:
                        st.error(f"❌ 解析中にエラーが発生しました: {e}")

    # 💡【レンダリング完全復元】解析完了後・下書きロード時の評価結果エリア確実描画処理
    if "analyzed_df" in st.session_state and not st.session_state["analyzed_df"].empty:
        st.divider()
        render_race_evaluation_view(st.session_state["analyzed_df"], is_viewer_mode=False, show_chat=True)


elif selected_menu == "📜 過去レース評価・結果・回顧（一括登録）":
    st.subheader("📜 過去レース評価・結果・回顧（一括登録）")
    st.caption("全107レース・2,600行超が縦連結されたCSVやテキストをPandasで直接・一瞬で超高速パースし、`data/2026/` へ一括保存登録します！")

    rule_type = st.radio(
        "適用する基本評価ルールを選択：",
        ["🏆 G1専用ルール", "🏇 平場・G2・G3専用ルール", "🌾 北海道・洋芝専用ルール"],
        horizontal=True,
        key="past_batch_rule_radio"
    )
    if "G1専用" in rule_type:
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
    elif "北海道" in rule_type:
        active_selected_rule = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
    else:
        active_selected_rule = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)

    st.divider()

    col_p1, col_p2 = st.columns([1.5, 1])
    with col_p1:
        past_files = st.file_uploader(
            "📁 過去データファイル (.txt / .csv / .pdf / .png / .jpg 一括選択可)",
            type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="past_batch_files"
        )
    with col_p2:
        past_text_memo = st.text_area(
            "✏️ 過去レース手入力メモ・結果テキスト（CSV/TSVコピペ対応）",
            height=150,
            placeholder="例: 2026年菊花賞の確定着順・オッズ・コメント等、またはCSV/TSVテキストを直接貼り付け",
            key="past_batch_memo"
        )

    if st.button("🚀 過去レースを一括解析して2026年データベースへ保存登録", use_container_width=True):
        active_key = load_api_key()
        if not past_files and not past_text_memo.strip():
            st.warning("⚠️ 過去データファイルまたはメモを入力してください！")
        else:
            with st.spinner("🏇 過去データから「全レース評価・見解・結果・回顧」を一括抽出・個別保存中..."):
                try:
                    direct_csv_dfs = []
                    remaining_files = []

                    if past_files:
                        for pf in past_files:
                            pf.seek(0)
                            fname_l = pf.name.lower()
                            if fname_l.endswith((".csv", ".txt", ".tsv")):
                                bytes_data = pf.read()
                                parsed_direct_df = None
                                for enc in ["utf-8-sig", "utf-8", "cp932", "shift_jis"]:
                                    try:
                                        raw_text = bytes_data.decode(enc)
                                        lines = raw_text.splitlines()
                                        
                                        header_idx = -1
                                        for idx, line in enumerate(lines[:15]):
                                            if any(kw in line for kw in ["レース名", "レース", "着順", "馬名", "馬番"]):
                                                header_idx = idx
                                                break
                                        
                                        if header_idx != -1:
                                            clean_csv_text = "\n".join(lines[header_idx:])
                                            temp_df = pd.read_csv(io.StringIO(clean_csv_text), dtype=str).fillna("")
                                            
                                            if not temp_df.empty and len(temp_df.columns) >= 2:
                                                temp_df = sanitize_dataframe_columns(temp_df)
                                                parsed_direct_df = temp_df
                                                break
                                    except Exception:
                                        continue
                                
                                if parsed_direct_df is not None and not parsed_direct_df.empty:
                                    direct_csv_dfs.append(parsed_direct_df)
                                else:
                                    remaining_files.append(pf)
                            else:
                                remaining_files.append(pf)

                    memo_text_remaining = past_text_memo.strip()
                    if memo_text_remaining:
                        lines = memo_text_remaining.splitlines()
                        header_idx = -1
                        for idx, line in enumerate(lines[:15]):
                            if any(kw in line for kw in ["レース名", "レース", "着順", "馬名", "馬番"]):
                                header_idx = idx
                                break
                        if header_idx != -1:
                            clean_csv_text = "\n".join(lines[header_idx:])
                            try:
                                temp_df = pd.read_csv(io.StringIO(clean_csv_text), dtype=str).fillna("")
                                if not temp_df.empty and len(temp_df.columns) >= 2:
                                    temp_df = sanitize_dataframe_columns(temp_df)
                                    direct_csv_dfs.append(temp_df)
                                    memo_text_remaining = ""
                            except Exception:
                                pass

                    saved_races_list = []
                    total_rows_saved = 0

                    if direct_csv_dfs:
                        for c_df in direct_csv_dfs:
                            c_df = sanitize_dataframe_columns(c_df)
                            
                            if "レース名" not in c_df.columns or c_df["レース名"].dropna().empty:
                                c_df["レース名"] = "20261008_過去一括登録レース_OP"

                            c_df["レース名"] = c_df["レース名"].astype(str).str.strip()
                            c_df["年"] = "2026"

                            if "回顧メモ" not in c_df.columns:
                                c_df["回顧メモ"] = ""

                            for r_name, group in c_df.groupby("レース名"):
                                if not str(r_name).strip():
                                    continue
                                
                                sub_race_df = group.copy().reset_index(drop=True)
                                
                                if not any(g in r_name for g in ["_G1", "_G2", "_G3", "_OP", "_L", "_Jpn1"]):
                                    grade = detect_race_grade(r_name)
                                    r_name_updated = f"{r_name}_{grade}"
                                    sub_race_df["レース名"] = r_name_updated
                                    r_name = r_name_updated

                                recap_list = []
                                for _, r_row in sub_race_df.iterrows():
                                    h_no = r_row.get("馬番", "")
                                    h_nm = r_row.get("馬名", "")
                                    h_memo = str(r_row.get("メモ", "")).strip()
                                    h_rank = r_row.get("確定着順", "")
                                    if h_memo:
                                        rank_str = f"[{h_rank}着] " if h_rank else ""
                                        recap_list.append(f"・{rank_str}【{h_no}】{h_nm}: {h_memo}")
                                
                                if recap_list:
                                    generated_recap = "📌 【レース回顧・各馬勝因敗因分析】\n" + "\n".join(recap_list)
                                    sub_race_df["回顧メモ"] = sub_race_df["回顧メモ"].apply(
                                        lambda x: str(x).strip() if str(x).strip() else generated_recap
                                    )

                                save_to_db(sub_race_df)
                                saved_races_list.append(r_name)
                                total_rows_saved += len(sub_race_df)

                    if saved_races_list:
                        unique_saved = sorted(list(set(saved_races_list)))
                        race_list_str = "\n".join([f"・{r}" for r in unique_saved[:15]])
                        more_str = f"\n...ほか全 {len(unique_saved)} レース" if len(unique_saved) > 15 else ""
                        st.success(f"🎉 計 {len(unique_saved)} レース（全 {total_rows_saved} 件）の取り込みが完了しました！\n\n【登録完了レース（一部表示）】\n{race_list_str}{more_str}")
                        st.rerun()
                    else:
                        st.error("❌ データのパース・取り込みに失敗しました。ファイル内容をご確認ください。")

                except Exception as e:
                    st.error(f"❌ 一括登録中にエラーが発生しました: {e}")


elif selected_menu == "🏇 現地観戦用（勝負5R厳選）":
    rule_type = st.radio(
        "今回適用する評価ルールを選択してください：",
        ["🏆 G1専用ルール", "🏇 平場・G2・G3専用ルール", "🌾 北海道・洋芝専用ルール"],
        horizontal=True,
    )
    if "G1専用" in rule_type:
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
    elif "北海道" in rule_type:
        active_selected_rule = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
    else:
        active_selected_rule = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)

    active_key = load_api_key()
    render_field_mode_ui(active_key, active_selected_rule, selected_model)


# --------------------------------------------------
# ⚙️ ルール管理・アップデート（ルールファイルアップロード機能）
# --------------------------------------------------

elif selected_menu == "⚙️ ルール管理・アップデート":
    st.subheader("⚙️ 解析ルールの管理・アップデート")
    sub_tab1, sub_tab2, sub_tab3 = st.tabs([
        "🏆 G1専用ルールの設定", "🏇 平場・G2・G3専用ルールの設定", "🌾 北海道・洋芝専用ルールの設定"
    ])

    with sub_tab1:
        st.write("📄 **G1専用ルールファイルのアップロード（.txt）**")
        uploaded_g1 = st.file_uploader("G1ルールファイルを選択してください", type=["txt"], key="upload_g1_rule")
        if uploaded_g1 is not None:
            uploaded_g1_text = uploaded_g1.read().decode("utf-8", errors="ignore")
            if uploaded_g1_text.strip():
                st.session_state["g1_text_val"] = uploaded_g1_text
                st.success("📂 ファイルからG1ルールテキストを正常に読み込みました！下のテキストエリアを確認後、保存してください。")

        st.text_area("G1専用ルールテキスト", height=300, key="g1_text_val")
        if st.button("💾 G1専用ルールとして更新・保存", use_container_width=True, key="btn_save_g1_rule"):
            save_rules_to_file(RULE_G1_FILE, st.session_state["g1_text_val"])
            st.success("🎉 G1専用ルールを更新保存しました！")

    with sub_tab2:
        st.write("📄 **平場・G2・G3専用ルールファイルのアップロード（.txt）**")
        uploaded_gen = st.file_uploader("平場・G2・G3ルールファイルを選択してください", type=["txt"], key="upload_gen_rule")
        if uploaded_gen is not None:
            uploaded_gen_text = uploaded_gen.read().decode("utf-8", errors="ignore")
            if uploaded_gen_text.strip():
                st.session_state["gen_text_val"] = uploaded_gen_text
                st.success("📂 ファイルから平場・G2・G3ルールテキストを正常に読み込みました！下のテキストエリアを確認後、保存してください。")

        st.text_area("平場・G2・G3専用ルールテキスト", height=300, key="gen_text_val")
        if st.button("💾 平場・G2・G3専用ルールとして更新・保存", use_container_width=True, key="btn_save_gen_rule"):
            save_rules_to_file(RULE_GENERAL_FILE, st.session_state["gen_text_val"])
            st.success("🎉 平場・G2・G3専用ルールを更新保存しました！")

    with sub_tab3:
        st.write("📄 **北海道・洋芝専用ルールファイルのアップロード（.txt）**")
        uploaded_hok = st.file_uploader("北海道・洋芝ルールファイルを選択してください", type=["txt"], key="upload_hok_rule")
        if uploaded_hok is not None:
            uploaded_hok_text = uploaded_hok.read().decode("utf-8", errors="ignore")
            if uploaded_hok_text.strip():
                st.session_state["hok_text_val"] = uploaded_hok_text
                st.success("📂 ファイルから北海道・洋芝ルールテキストを正常に読み込みました！下のテキストエリアを確認後、保存してください。")

        st.text_area("北海道・洋芝専用ルールテキスト", height=300, key="hok_text_val")
        if st.button("💾 北海道・洋芝専用ルールとして更新・保存", use_container_width=True, key="btn_save_hok_rule"):
            save_rules_to_file(RULE_HOKKAIDO_FILE, st.session_state["hok_text_val"])
            st.success("🎉 北海道・洋芝専用ルールを更新保存しました！")


elif selected_menu == "🔄 回顧・精度検証":
    st.subheader("🔄 レース後回顧 ＆ 全着順自動照合 ＆ ルール自動検証")
    
    avail_years = ["2026年"] + [y for y in get_available_years_in_db() if y != "2026年"]
    selected_year_filter = st.selectbox("📅 表示対象の年を選択", avail_years, key="recap_year_select")

    db_df = load_db(selected_year=selected_year_filter)

    if db_df.empty:
        st.info("💡 対象年に予想データがありません。")
    else:
        races_in_db = sorted(db_df["レース名"].dropna().astype(str).str.strip().unique().tolist()) if "レース名" in db_df.columns else []
        selected_race = st.selectbox("🎯 回顧対象のレースを選択してください", races_in_db)

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            res_text_input = st.text_area("1. 結果テキストのコピペ", height=180)
        with col_r2:
            res_file_inputs = st.file_uploader(
                "2. 結果ファイル (.txt / .csv / .pdf / .png / .jpg)",
                type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="recap_multi_file_uploader",
            )

        if st.button("🏁 回顧 ＆ 全着順照合 ＆ ルール検証を実行する", use_container_width=True):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key が設定されていません。")
            elif not res_text_input and not res_file_inputs:
                st.warning("⚠️ 結果データを取り込んでください！")
            else:
                with st.spinner("🏇 AIが全結果データを統合し照合・回顧中..."):
                    try:
                        raw_result = res_text_input if res_text_input else ""
                        if res_file_inputs:
                            for res_file in res_file_inputs:
                                res_file.seek(0)
                                if res_file.name.lower().endswith(".pdf"):
                                    pdf_txt = extract_text_from_pdf(res_file, page_option="全ページ")
                                    raw_result += f"\n【結果ファイル: {res_file.name}】\n" + pdf_txt
                                elif res_file.name.lower().endswith((".txt", ".csv")):
                                    txt_data = res_file.read().decode("utf-8", errors="ignore")
                                    raw_result += f"\n【結果ファイル: {res_file.name}】\n" + txt_data

                        target_df = db_df[db_df["レース名"].astype(str).str.strip() == str(selected_race).strip()]
                        cols = [c for c in ["馬番", "馬名", "総合スコア", "評価", "軸", "ヒモ", "注", "切り", "メモ"] if c in target_df.columns]
                        predict_summary = target_df[cols].to_string(index=False)

                        current_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)

                        prompt = (
                            "あなたは競馬予想プロフェッショナル「AI」です。\n"
                            "予想データと結果データを突き合わせ、全頭確定着順テーブル（TSV形式）および詳細回顧レポートを作成してください。\n"
                            "単勝人気や確定着順から「人気」「着」を除去し、数字のみで出力すること。\n\n"
                            f"【予想データ】\n{predict_summary}\n\n【結果データ】\n{raw_result}\n\n"
                            "出力は TSVテーブル ---RESULT_MEMO--- 回顧文章 ---RULE_UPDATE--- ルール改修案 の形式にすること。"
                        )

                        client = genai.Client(api_key=active_key)
                        response = client.models.generate_content(
                            model=selected_model,
                            contents=[prompt],
                            config=types.GenerateContentConfig(temperature=0.0, seed=42),
                        )
                        ai_res_out = response.text

                        tbl_part = ai_res_out
                        memo_part = "回顧コメントの抽出を完了しました。"

                        if "---RESULT_MEMO---" in ai_res_out:
                            tbl_part, rest_part = ai_res_out.split("---RESULT_MEMO---", 1)
                            memo_part = rest_part.split("---RULE_UPDATE---", 1)[0] if "---RULE_UPDATE---" in rest_part else rest_part

                        clean_tbl = tbl_part.replace("```tsv", "").replace("```", "").strip()
                        res_df = pd.read_csv(io.StringIO(clean_tbl), sep="\t", dtype=str, on_bad_lines="skip")
                        res_df = sanitize_dataframe_columns(res_df)

                        update_db_with_recap(selected_race, res_df, memo_part)
                        st.success(f"🎉 レース「{selected_race}」の回顧・照合結果を2026年データベースに保存しました！")
                        
                        styled_res_df = apply_top3_highlight(res_df)
                        st.dataframe(styled_res_df, use_container_width=True, hide_index=True)

                        st.markdown(
                            f"""
                            <div style="background-color: #0c1424; border: 2px solid #2563eb; border-radius: 10px; padding: 18px; margin-top: 15px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.7; color: #f1f5f9; font-size: 0.98rem; box-shadow: 0 0 15px rgba(37, 99, 235, 0.25);">
{memo_part}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    except Exception as e:
                        st.error(f"❌ 回顧処理中にエラーが発生しました: {e}")


# --------------------------------------------------
# 📊 評価データ一覧（プール）【削除機能復元】
# --------------------------------------------------

elif selected_menu == "📊 評価データ一覧（プール）":
    st.subheader("📊 評価データ一覧（プール閲覧専用画面）")
    
    avail_years = ["2026年"] + [y for y in get_available_years_in_db() if y != "2026年"]
    selected_year_filter = st.selectbox("📅 表示対象の年を選択", avail_years, key="eval_year_select")

    db_df = load_db(selected_year=selected_year_filter)

    if db_df.empty:
        st.info("💡 保存されている予想データがありません。")
    else:
        all_races = sorted(db_df["レース名"].dropna().astype(str).str.strip().unique().tolist()) if "レース名" in db_df.columns else []
        eval_options = ["🔍 レースを選択してください..."] + all_races
        selected_eval_race = st.selectbox("🎯 閲覧・再評価する予想データ（レース）を選択してください：", eval_options, index=0, key="eval_pool_race_select")

        if selected_eval_race and selected_eval_race != "🔍 レースを選択してください...":
            with st.expander("🗑️ 選択中のレースデータの削除", expanded=False):
                st.warning(f"⚠️ レース「{selected_eval_race}」の評価・予想データをデータベースから完全に削除します。")
                confirm_del_eval = st.checkbox(f"本当に「{selected_eval_race}」のデータを削除しますか？", key="del_chk_eval_pool")
                if st.button("🗑️ 選択中のレースデータを削除", key="del_btn_eval_pool", disabled=not confirm_del_eval):
                    if delete_race_from_db(selected_eval_race):
                        st.success(f"🎉 レース「{selected_eval_race}」のデータをデータベースから正常に削除しました！")
                        st.rerun()
                    else:
                        st.error("❌ 削除処理に失敗しました。")

            matched_df = db_df[db_df["レース名"].astype(str).str.strip() == str(selected_eval_race).strip()].copy()
            render_race_evaluation_view(matched_df, is_viewer_mode=True, show_chat=True)
        else:
            st.info("💡 上のメニューから閲覧したいレースを選択してください。")


# --------------------------------------------------
# 📝 回顧・精度検証一覧（プール）【削除機能復元】
# --------------------------------------------------

elif selected_menu == "📝 回顧・精度検証一覧（プール）":
    st.subheader("📝 回顧・精度検証データ一覧（プール閲覧専用画面）")

    avail_years = ["2026年"] + [y for y in get_available_years_in_db() if y != "2026年"]
    selected_year_filter = st.selectbox("📅 表示対象の年を選択", avail_years, key="recap_pool_year_select")

    db_df = load_db(selected_year=selected_year_filter)

    if db_df.empty:
        st.info("💡 回顧データが見つかりません。")
    else:
        all_races = sorted(db_df["レース名"].dropna().astype(str).str.strip().unique().tolist()) if "レース名" in db_df.columns else []
        recap_options = ["🔍 レースを選択してください..."] + all_races
        selected_recap_race = st.selectbox("🏁 閲覧する回顧データ（レース）を選択してください：", recap_options, index=0, key="recap_pool_race_select")

        if selected_recap_race and selected_recap_race != "🔍 レースを選択してください...":
            with st.expander("🗑️ 選択中のレースデータの削除", expanded=False):
                st.warning(f"⚠️ レース「{selected_recap_race}」の回顧・照合データをデータベースから完全に削除します。")
                confirm_del_recap = st.checkbox(f"本当に「{selected_recap_race}」のデータを削除しますか？", key="del_chk_recap_pool")
                if st.button("🗑️ 選択中のレースデータを削除", key="del_btn_recap_pool", disabled=not confirm_del_recap):
                    if delete_race_from_db(selected_recap_race):
                        st.success(f"🎉 レース「{selected_recap_race}」のデータをデータベースから正常に削除しました！")
                        st.rerun()
                    else:
                        st.error("❌ 削除処理に失敗しました。")

            race_df = db_df[db_df["レース名"].astype(str).str.strip() == str(selected_recap_race).strip()].copy()
            recap_text = race_df["回顧メモ"].iloc[0] if "回顧メモ" in race_df.columns and str(race_df["回顧メモ"].iloc[0]).strip() else ""

            target_cols = [c for c in ["確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気", "単勝人気", "確定オッズ", "タイム", "上り3F", "勝因・敗因ショートメモ"] if c in race_df.columns]
            disp_result_df = sanitize_dataframe_columns(race_df[target_cols].copy())

            st.markdown(f"### 🏆 【{selected_recap_race}】 全頭確定着順 ＆ 照合結果")
            
            styled_disp_df = apply_top3_highlight(disp_result_df)
            st.dataframe(styled_disp_df, use_container_width=True, hide_index=True)

            if recap_text:
                st.markdown(
                    f"""
                    <div style="background-color: #0c1424; border: 2px solid #2563eb; border-radius: 10px; padding: 18px; margin-top: 15px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.7; color: #f1f5f9; font-size: 0.98rem; box-shadow: 0 0 15px rgba(37, 99, 235, 0.25);">
{recap_text}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.info("💡 上のメニューから閲覧したいレースを選択してください。")


# --------------------------------------------------
# 🗄 過去馬データベース（プール）【削除機能復元】
# --------------------------------------------------

elif selected_menu == "🗄 過去馬データベース（プール）":
    st.subheader("🗄️ 過去馬データベース（プール一覧・データ管理）")

    avail_years = ["2026年"] + [y for y in get_available_years_in_db() if y != "2026年"]
    selected_year_filter = st.selectbox("📅 表示対象の年を選択", avail_years, key="db_year_select")

    db_df = load_db(selected_year=selected_year_filter)

    if not db_df.empty:
        st.success(f"📦 現在 【{selected_year_filter}】 のデータ: {len(db_df)} 件")

        all_races_in_db = sorted(db_df["レース名"].dropna().astype(str).str.strip().unique().tolist()) if "レース名" in db_df.columns else []
        race_selector_options = ["🌐 すべてのレース（全件一括表示）"] + all_races_in_db

        selected_db_race = st.selectbox("📂 表示・閲覧するレースを選択してください：", race_selector_options, key="db_race_filter_selectbox")

        # 個別レース削除ボタン
        if selected_db_race and selected_db_race != "🌐 すべてのレース（全件一括表示）":
            with st.expander("🗑️ 選択中のレースデータの削除", expanded=False):
                st.warning(f"⚠️ レース「{selected_db_race}」の出走馬・成績データを過去馬データベースから完全に削除します。")
                confirm_del_db = st.checkbox(f"本当に「{selected_db_race}」のデータを削除しますか？", key="del_chk_db_pool")
                if st.button("🗑️ 選択中のレースデータを削除", key="del_btn_db_pool", disabled=not confirm_del_db):
                    if delete_race_from_db(selected_db_race):
                        st.success(f"🎉 レース「{selected_db_race}」のデータを過去馬データベースから正常に削除しました！")
                        st.rerun()
                    else:
                        st.error("❌ 削除処理に失敗しました。")

        disp_db_df = sanitize_dataframe_columns(db_df.copy().fillna(""))
        disp_db_df = disp_db_df.drop(columns=["軸ヒモ切り", "人気", "年度"], errors="ignore")

        # アニキ指定の厳格カラム並び順（29項目）
        specified_column_order = [
            "確定着順", "馬番", "馬名", "確定オッズ", "単勝人気", "予想人気", "総合スコア", "評価",
            "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点", "軸", "ヒモ", "注", "切り",
            "メモ", "レース名", "信頼度", "波乱度", "推奨買い目", "レース質展開予想", "回顧メモ",
            "タイム", "上り3F", "勝因・敗因ショートメモ", "年"
        ]

        existing_cols = [c for c in specified_column_order if c in disp_db_df.columns]
        disp_db_df = disp_db_df[existing_cols]

        # プログレスバー（緑色グラフ付き）設定
        col_config_db = {
            "総合スコア": st.column_config.ProgressColumn(
                "総合スコア",
                format="%d点",
                min_value=0,
                max_value=100,
                width="medium",
                color="#0bce0e"
            ),
            "馬番": st.column_config.NumberColumn("馬番", width="small"),
            "確定着順": st.column_config.TextColumn("確定着順", width="small"),
            "予想人気": st.column_config.TextColumn("予想人気", width="small"),
            "単勝人気": st.column_config.TextColumn("単勝人気", width="small"),
            "メモ": st.column_config.TextColumn("メモ", width="large"),
            "勝因・敗因ショートメモ": st.column_config.TextColumn("勝因・敗因ショートメモ", width="large"),
        }

        if selected_db_race != "🌐 すべてのレース（全件一括表示）":
            filtered_df = disp_db_df[disp_db_df["レース名"].astype(str).str.strip() == str(selected_db_race).strip()]
            styled_df = apply_top3_highlight(filtered_df)
            st.dataframe(styled_df, column_config=col_config_db, use_container_width=True, hide_index=True)
        else:
            search_race = st.text_input("🔍 部分一致テキスト検索（レース名や馬名）", "")
            if search_race:
                mask = disp_db_df["レース名"].astype(str).contains(search_race, na=False) | disp_db_df["馬名"].astype(str).contains(search_race, na=False)
                styled_df = apply_top3_highlight(disp_db_df[mask])
            else:
                styled_df = apply_top3_highlight(disp_db_df)
            
            st.dataframe(styled_df, column_config=col_config_db, use_container_width=True, hide_index=True)

        csv_data = db_df.to_csv(index=False, encoding="utf-8-sig")
        st.download_button("📦 CSVで一括ダウンロード", data=csv_data, file_name=f"umael_db_{selected_year_filter}.csv", mime="text/csv")
    else:
        st.info("💡 まだプールされたデータはありません。")