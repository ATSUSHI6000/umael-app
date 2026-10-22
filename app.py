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
import traceback
from google import genai
from google.genai import types
import pandas as pd
import pdfplumber
import pypdf
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials

# 連携対象の「競馬分析用シート」ID
SPREADSHEET_ID = "1-WuffPHvbPHcdgb20pV4k9VZG7jeE8RAEhI83a2ScNo"

# ページ基本設定（ウマエルプロ v3.0 完全統合版）
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
DEFAULT_G1_RULES = """【G1専用・評価表出力ルール（ver.8.3・レース質＆展開予想冒頭配置・頂点実績厳格化・開幕外枠デバフ・鉄砲個別判定・傷病デバフ・タフ馬場補正・単騎逃げ救済・直感相馬眼・YouTubeハイブリッド解析統合版）】
========================================
【G1専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
========================================
■ 0. システム運用・誤入力完全排除規定
・ブラウジング完全禁止、ファクトチェック厳格化。
■ 1. 基本方針・評価スタンス
■ 2. 【G1頂点基準】評価ランク定義とS評価認定必須要件
【S評価】93点以上、【A+評価】88～92点、【A評価】84～87点、【B+評価】80～83点、【B評価】74～79点、【C評価】73点以下。
■ 3. G1デバフ規定（傷病休養、鉄砲不振、距離限界、出遅れ、連戦疲労、タフ馬場ノメり、開幕外枠）
■ 4. G1ボーナス・救済加点規定（イン突き、開幕先行、超Hペース、前走度外視、長距離スロー捲り、単騎逃げ救済等）
■ 5. 表記・プロ評価＆YouTube自動解析統合ルール
■ 6. 【出力順序絶対規定】＆ 解析サイト蓄積用フォーマット
1. 🏁 レース質 ＆ 展開予想シミュレーション
2. 💰 G1限定・推奨券種＆ガミなし資金配分案
3. 📊 ウマエル解析サイト蓄積用データ
■ 7. レース解析冒頭：レース質 ＆ 展開予想シミュレーション必須フォーマット
■ 8. G1各評価点計算式
■ 9. ガミなし資金配分案ルール
"""

DEFAULT_GENERAL_RULES = """【平場・G2・G3専用 評価表出力ルール（ver.8.3・S評価厳格化＆開幕外枠デバフ・鉄砲個別判定・過重ハンデ地力救済・タフ馬場ノメりデバフ・単騎逃げ救済・直感相馬眼・軸飛び防止・前走度外視完全統合版）】
========================================
【平場・G2・G3専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
========================================
■ 0. システム運用・誤入力完全排除規定
■ 1. 基本方針・評価スタンス
■ 2. 評価ランク定義とS評価認定必須要件
■ 3. デバフ規定（傷病、鉄砲不振、距離限界、ハンデ見込まれ、連戦疲労、ノメり、開幕外枠）
■ 4. ボーナス・救済加点規定（ハンデ恵量、実績スランプ、死んだふりイン突き、開幕先行、超Hペース、過重地力救済等）
■ 5. 表記・プロ評価統合ルール
■ 6. 【出力順序絶対規定】
1. 🏁 レース質 ＆ 展開予想シミュレーション
2. 💰 推奨買い目＆資金配分（指示時のみ）
3. 📊 ウマエル解析サイト蓄積用データ
■ 7. レース解析冒頭フォーマット
■ 8. 各評価点計算式
"""

DEFAULT_HOKKAIDO_RULES = """【平場・G2・G3 北海道・洋芝（函館・札幌）専用 評価表出力ルール（ver.8.3・S評価厳格化＆開幕外枠デバフ・鉄砲個別判定・過重ハンデ地力救済・タフ馬場ノメりデバフ・洋芝滞在・単騎逃げ救済・直感相馬眼・軸飛び防止・前走度外視完全統合版）】
========================================
【平場・G2・G3 北海道・洋芝（函館・札幌）専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
========================================
■ 0. システム運用・誤入力完全排除規定
■ 1. 基本方針・洋芝評価スタンス（洋芝滞在・パワー血統・クッション値評価）
■ 2. 評価ランク定義
■ 3. デバフ規定（初の洋芝デバフ、傷病、鉄砲不振、ハンデ見込まれ、開幕外枠等）
■ 4. ボーナス・救済加点規定（洋芝実績・現地滞在ボーナス、洋芝激流対応血統、ハンデ恵量、洋芝イン差し等）
■ 5. 表記・プロ評価統合ルール
■ 6. 【出力順序絶対規定】
■ 7. レース解析冒頭フォーマット
■ 8. 各評価点計算式
"""


# --------------------------------------------------
# 🛠 共通ヘルパー関数・ファイル入出力・正規化定義
# --------------------------------------------------

def load_saved_rules(file_path, default_text):
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
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(rule_text)


def clean_pop_number(val):
    if pd.isna(val) or val is None:
        return ""
    s = str(val).strip()
    if not s or s in ["-", "—", "nan", "None"]:
        return ""
    m = re.search(r"\d+", s)
    return m.group(0) if m else s


def extract_year_from_race_name(race_name):
    current_year = time.strftime("%Y")
    if race_name is None or not str(race_name).strip():
        return current_year
    m = re.search(r"(20\d{2})", str(race_name))
    return m.group(1) if m else current_year


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
                    pdf.pages if page_option == "全ページ読み込む" or page_option == "全ページ" else [pdf.pages[0]]
                )
                for i, page in enumerate(pages_to_process):
                    page_text = page.extract_text(layout=True)
                    if not page_text or len(page_text.strip()) < 30:
                        page_text = page.extract_text()
                    if page_text:
                        text += f"\n--- 【PDF {i+1}ページ目抽出テキスト】 ---\n" + page_text + "\n"
    except Exception:
        pdf_file.seek(0)
        try:
            reader = pypdf.PdfReader(pdf_file)
            if len(reader.pages) > 0:
                pages_to_process = (
                    reader.pages if page_option == "全ページ読み込む" or page_option == "全ページ" else [reader.pages[0]]
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
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=["ja", "en"])
            yt_text = " ".join([item["text"] for item in transcript])
            if yt_text.strip():
                return f"【YouTube字幕テキスト ({url})】:\n" + yt_text[:8000]
        except Exception:
            pass

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
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
            clean_html = re.sub(r"<script.*?>.*?</script>", "", html, flags=re.DOTALL)
            clean_html = re.sub(r"<style.*?>.*?</style>", "", clean_html, flags=re.DOTALL)
            clean_html = re.sub(r"<[^>]+>", " ", clean_html)
            clean_text = re.sub(r"\s+", " ", clean_html).strip()
            return f"【Webページ抽出テキスト ({url})】:\n" + clean_text[:8000]

    except Exception as e:
        return f"【URL読み込みスキップ ({url}): {e}】"


def process_multiple_urls(urls_input_text):
    if not urls_input_text or not urls_input_text.strip():
        return ""

    urls = [line.strip() for line in urls_input_text.strip().splitlines() if line.strip().startswith("http")]
    if not urls:
        return ""

    combined_url_text = "\n=========================================\n【参考URL（YouTube/note/プロ予想）自動抽出データ】\n=========================================\n"
    for url in urls:
        extracted = fetch_text_from_url(url)
        if extracted:
            combined_url_text += extracted + "\n-----------------------------------------\n"

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
                if any(k in fname for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]):
                    prompt_text += f"\n=========================================\n【⚠️注意：ファイル「{fname}」は過去の参考資料です。】\n=========================================\n" + content
                else:
                    prompt_text += f"\n=========================================\n【確定メイン出馬・追加データファイル: {fname}】\n=========================================\n" + content
            else:
                bio = io.BytesIO(file_bytes)
                extracted = extract_text_from_pdf(bio, page_option=pdf_page_option)
                if extracted.strip():
                    if any(k in fname for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]):
                        prompt_text += f"\n=========================================\n【⚠️注意：ファイル「{fname}」は過去の参考資料です】\n=========================================\n" + extracted
                    else:
                        prompt_text += f"\n=========================================\n【確定メイン出馬・追加データ（PDF抽出）: {fname}】\n=========================================\n" + extracted

                if len(extracted.strip()) < 100 or fname.lower().endswith((".png", ".jpg", ".jpeg")):
                    mime = f.type
                    if not mime or mime == "application/octet-stream":
                        if fname.lower().endswith(".pdf"): mime = "application/pdf"
                        elif fname.lower().endswith(".png"): mime = "image/png"
                        elif fname.lower().endswith((".jpg", ".jpeg")): mime = "image/jpeg"

                    if mime:
                        media_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))

    return prompt_text, media_parts


def normalize_race_name_for_comparison(name):
    if not name: return ""
    s = unicodedata.normalize('NFKC', str(name)).lower()
    s = re.sub(r'\s+', '', s)
    return re.sub(r'[_\-\–\—\(\)（）\[\]【】]', '', s)


def find_matching_existing_draft(target_race_name):
    existing_races = list_draft_races()
    target_key = normalize_race_name_for_comparison(target_race_name)
    if not target_key: return None
    for existing_race in existing_races:
        if normalize_race_name_for_comparison(existing_race) == target_key:
            return existing_race
    return None


def clean_race_name_from_filename(filename):
    if not filename: return ""
    base_name = os.path.splitext(filename)[0]
    cleaned = unicodedata.normalize('NFKC', base_name)
    noise_patterns = [r"競馬新聞", r"競馬新", r"新聞", r"出馬表", r"馬柱", r"確定データ", r"確定", r"過去データ", r"過去", r"傾向", r"回顧", r"データ", r"全ページ", r"印刷"]
    for pat in noise_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'[_\s\-\—]?(?:20\d{2})(?:[01]\d[0-3]\d)?', '', cleaned)
    cleaned = re.sub(r'[_\s\-\—]\d+$', '', cleaned)
    cleaned = re.sub(r'\(\d+\)$', '', cleaned)
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", cleaned)
    cleaned = re.sub(r'[_\s\-\—]+', '_', cleaned).strip('_').strip()
    return cleaned if cleaned else re.sub(r'[\\/*?:"<>|]', "_", base_name).strip()


def detect_simple_race_name(files_g1, files_g2, files_g3, files_g4=None):
    check_lists = [files_g1, files_g2, files_g3]
    if files_g4: check_lists.append(files_g4)
    for flist in check_lists:
        if flist:
            for f in flist:
                clean_name = clean_race_name_from_filename(f.name)
                if clean_name: return clean_name
    return f"準備中レース_{time.strftime('%Y%m%d_%H%M%S')}"


def save_draft_data(race_name, files_g1, files_g2, files_g3, files_g4, urls_text):
    ensure_drafts_dir()
    if not race_name or not race_name.strip():
        race_name = detect_simple_race_name(files_g1, files_g2, files_g3, files_g4)
    else:
        race_name = clean_race_name_from_filename(race_name)

    matched_existing_race = find_matching_existing_draft(race_name)
    sanitized_name = matched_existing_race if matched_existing_race else re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')
    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)
    os.makedirs(race_dir, exist_ok=True)

    url_log_path = os.path.join(race_dir, "urls.txt")
    existing_urls = ""
    if os.path.exists(url_log_path):
        with open(url_log_path, "r", encoding="utf-8") as f: existing_urls = f.read()

    new_urls = urls_text.strip()
    if new_urls:
        combined_urls = (existing_urls + "\n" + new_urls).strip()
        with open(url_log_path, "w", encoding="utf-8") as f: f.write(combined_urls)

    saved_count = 0
    timestamp = int(time.time())
    group_tuples = [(1, files_g1), (2, files_g2), (3, files_g3), (4, files_g4)]

    for g_idx, file_list in group_tuples:
        if file_list:
            for idx, f in enumerate(file_list):
                f.seek(0)
                content = f.read()
                save_fname = f"g{g_idx}___{timestamp}___{idx}___{f.name}"
                with open(os.path.join(race_dir, save_fname), "wb") as out_f: out_f.write(content)
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

    t1_all, p1_all, t2_all, p2_all, t3_all, p3_all, t4_all, p4_all = "", [], "", [], "", [], "", []
    file_names = []

    for fname in sorted(os.listdir(race_dir)):
        fpath = os.path.join(race_dir, fname)
        if fname == "urls.txt": continue
        if os.path.isfile(fpath):
            original_fname = fname.split("___")[-1] if "___" in fname else fname
            file_names.append(original_fname)
            with open(fpath, "rb") as f: file_bytes = f.read()

            group_idx = 1
            if fname.startswith("g2_") or fname.startswith("g2___"): group_idx = 2
            elif fname.startswith("g3_") or fname.startswith("g3___"): group_idx = 3
            elif fname.startswith("g4_") or fname.startswith("g4___"): group_idx = 4

            txt_content, media_parts = "", []
            is_past_ref = any(k in original_fname for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"])

            if original_fname.lower().endswith((".txt", ".csv")):
                decoded = file_bytes.decode("utf-8", errors="ignore")
                txt_content += f"\n【{'⚠️注意：過去資料 ' if is_past_ref else '確定メインデータ '}:{original_fname}】\n" + decoded
            else:
                bio = io.BytesIO(file_bytes)
                extracted = extract_text_from_pdf(bio, page_option=pdf_page_option)
                if extracted.strip():
                    txt_content += f"\n【{'⚠️注意：過去資料(PDF) ' if is_past_ref else '確定メインデータ(PDF) '}:{original_fname}】\n" + extracted

                if len(extracted.strip()) < 100 or original_fname.lower().endswith((".png", ".jpg", ".jpeg")):
                    mime = "application/pdf" if original_fname.lower().endswith(".pdf") else ("image/png" if original_fname.lower().endswith(".png") else "image/jpeg")
                    media_parts.append(types.Part.from_bytes(data=file_bytes, mime_type=mime))

            if group_idx == 1: t1_all += txt_content + "\n"; p1_all.extend(media_parts)
            elif group_idx == 2: t2_all += txt_content + "\n"; p2_all.extend(media_parts)
            elif group_idx == 3: t3_all += txt_content + "\n"; p3_all.extend(media_parts)
            elif group_idx == 4: t4_all += txt_content + "\n"; p4_all.extend(media_parts)

    t5_all = ""
    url_log_path = os.path.join(race_dir, "urls.txt")
    if os.path.exists(url_log_path):
        with open(url_log_path, "r", encoding="utf-8") as f:
            urls_text = f.read()
            if urls_text.strip(): t5_all = process_multiple_urls(urls_text)

    return t1_all, p1_all, t2_all, p2_all, t3_all, p3_all, t4_all, p4_all, t5_all, file_names


def delete_draft(race_name):
    ensure_drafts_dir()
    if not race_name or not race_name.strip(): return False
    sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')
    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)
    if os.path.exists(race_dir):
        shutil.rmtree(race_dir)
        return True
    return False


def normalize_horse_num(val):
    if pd.isna(val): return ""
    s = re.sub(r"\D", "", str(val))
    return str(int(s)) if s else ""


def normalize_rank(val):
    if pd.isna(val): return ""
    s = str(val).strip()
    if not s or s in {"-", "—", "取消", "除外", "中止", "失格", "競走中止"}: return ""
    s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    m = re.match(r"^\s*(\d+)\s*(?:着)?\s*$", s)
    return str(int(m.group(1))) if m else ""


def convert_to_circled_numbers(text):
    if not text or not isinstance(text, str): return text
    import string
    tokens = {}

    def save_protected(match):
        key = f"__PROTECTED_TOKEN_{len(tokens)}__"
        tokens[key] = match.group(0)
        return key

    pattern = r'[\d,]+\s*円|\d+\s*点|\d+\s*頭|[1-3]\s*連[複単]|[1-3]\s*着'
    protected_text = re.sub(pattern, save_protected, text)
    circled_map = {str(i): chr(9311 + i) for i in range(1, 21)}

    for num in range(20, 0, -1):
        s_num = str(num)
        protected_text = re.sub(rf'(?<!\d){s_num}(?!\d)', circled_map[s_num], protected_text)

    for key, original_val in tokens.items():
        protected_text = protected_text.replace(key, original_val)

    return protected_text


def safe_int(val, default=0):
    try:
        if isinstance(val, (pd.Series, list)):
            val = val[0] if len(val) > 0 else default
        num = pd.to_numeric(val, errors="coerce")
        return default if pd.isna(num) else int(num)
    except Exception:
        return default


# --------------------------------------------------
# 🧼 データベースクレンジング ＆ マルチフォルダ同期ロジック
# --------------------------------------------------

def sanitize_dataframe_columns(df):
    if df is None or df.empty: return df
    df = df.copy()

    drop_target_cols = [c for c in df.columns if str(c).startswith("Unnamed:")]
    for drop_col in ["総合スコアグラフ", "軸ヒモ切り", "人気"]:
        if drop_col in df.columns: drop_target_cols.append(drop_col)

    if drop_target_cols: df = df.drop(columns=list(set(drop_target_cols)), errors="ignore")
    df = df.loc[:, ~df.columns.duplicated()]

    rename_map = {}
    for orig_c in df.columns:
        c_clean = str(orig_c).strip().replace(" ", "").replace("\n", "").replace("\r", "")
        if c_clean in ["着順", "確定着順", "順位", "着"] and "確定着順" not in rename_map.values(): rename_map[orig_c] = "確定着順"
        elif c_clean in ["レース名", "レース", "Race", "RACE"] and "レース名" not in rename_map.values(): rename_map[orig_c] = "レース名"
        elif c_clean in ["馬名", "競走馬名", "Horse"] and "馬名" not in rename_map.values(): rename_map[orig_c] = "馬名"
        elif c_clean in ["馬番", "馬No", "No"] and "馬番" not in rename_map.values(): rename_map[orig_c] = "馬番"
        elif c_clean in ["予想人気"] and "予想人気" not in rename_map.values(): rename_map[orig_c] = "予想人気"
        elif c_clean in ["単勝人気", "人気"] and "単勝人気" not in rename_map.values(): rename_map[orig_c] = "単勝人気"
        elif "評価" in c_clean and "評価" not in rename_map.values(): rename_map[orig_c] = "評価"
        elif "軸" in c_clean and "軸" not in rename_map.values(): rename_map[orig_c] = "軸"
        elif "ヒモ" in c_clean and "ヒモ" not in rename_map.values(): rename_map[orig_c] = "ヒモ"
        elif "注" in c_clean and "注" not in rename_map.values(): rename_map[orig_c] = "注"
        elif "切り" in c_clean and "切り" not in rename_map.values(): rename_map[orig_c] = "切り"
        elif c_clean in ["メモ", "見解", "短評"] and "メモ" not in rename_map.values(): rename_map[orig_c] = "メモ"
        elif c_clean in ["回顧", "総評", "回顧メモ"] and "回顧メモ" not in rename_map.values(): rename_map[orig_c] = "回顧メモ"
        elif c_clean in ["年度", "年"] and "年" not in rename_map.values(): rename_map[orig_c] = "年"
        elif c_clean in ["レース質展開予想", "展開シミュレーション"] and "レース質展開予想" not in rename_map.values(): rename_map[orig_c] = "レース質展開予想"
        elif c_clean in ["推奨買い目", "買い目"] and "推奨買い目" not in rename_map.values(): rename_map[orig_c] = "推奨買い目"
        elif c_clean in ["信頼度", "軸馬信頼度"] and "信頼度" not in rename_map.values(): rename_map[orig_c] = "信頼度"
        elif c_clean in ["波乱度", "波乱度レベル"] and "波乱度" not in rename_map.values(): rename_map[orig_c] = "波乱度"

    if rename_map: df = df.rename(columns=rename_map)
    df = df.loc[:, ~df.columns.duplicated()]

    if "総合スコア" in df.columns:
        df["総合スコア"] = pd.to_numeric(df["総合スコア"].astype(str).str.replace("点", "").str.strip(), errors="coerce").fillna(0).astype(int)

    if "予想人気" in df.columns: df["予想人気"] = df["予想人気"].apply(clean_pop_number)
    if "単勝人気" in df.columns: df["単勝人気"] = df["単勝人気"].apply(clean_pop_number)

    for col in ["評価", "軸", "ヒモ", "注", "切り", "メモ", "総合スコア", "レース質展開予想", "推奨買い目", "信頼度", "波乱度"]:
        if col not in df.columns: df[col] = ""

    def calc_eval_and_marks(row):
        score_val = row.get("総合スコア", 0)
        try: score = int(float(score_val))
        except (ValueError, TypeError): score = 0

        current_eval = str(row.get("評価", "")).strip()
        if not current_eval or current_eval in ["-", "nan", "None"]:
            if score >= 93: current_eval = "S"
            elif score >= 88: current_eval = "A+"
            elif score >= 84: current_eval = "A"
            elif score >= 80: current_eval = "B+"
            elif score >= 74: current_eval = "B"
            else: current_eval = "C"

        jiku = str(row.get("軸", "")).strip()
        himo = str(row.get("ヒモ", "")).strip()
        chu = str(row.get("注", "")).strip()
        kiri = str(row.get("切り", "")).strip()
        memo_raw = str(row.get("メモ", "")).strip()

        if not (jiku or himo or chu or kiri):
            if current_eval in ["S"]: jiku = "〇"
            elif current_eval in ["A+", "A", "B+"]: himo = "〇"
            elif current_eval in ["B"]: chu = "〇"
            else: kiri = "〇"

        row["評価"] = current_eval
        row["軸"] = jiku
        row["ヒモ"] = himo
        row["注"] = chu
        row["切り"] = kiri
        return row

    df = df.apply(calc_eval_and_marks, axis=1)

    existing_years = df["年"].copy() if "年" in df.columns else pd.Series("", index=df.index)
    years = []
    current_year = time.strftime("%Y")
    for pos, (_, row) in enumerate(df.iterrows()):
        race_name = str(row.get("レース名", "") or "").strip()
        race_year_match = re.search(r"(20\d{2})", race_name)
        if race_year_match: year_val = race_year_match.group(1)
        else:
            raw_year = str(existing_years.iloc[pos] if pos < len(existing_years) else "").strip()
            raw_year_match = re.search(r"(20\d{2})", raw_year)
            year_val = raw_year_match.group(1) if raw_year_match else current_year
        years.append(year_val)

    if "年" in df.columns: df = df.drop(columns=["年"])
    df["年"] = years
    return df[[col for col in df.columns if col != "年"] + ["年"]]


def migrate_and_clean_all_dbs():
    candidates = []
    if os.path.isdir(DATA_DIR):
        for entry in sorted(os.listdir(DATA_DIR)):
            y_dir = os.path.join(DATA_DIR, entry)
            if os.path.isdir(y_dir) and re.fullmatch(r"20\d{2}", entry):
                y_file = os.path.join(y_dir, DB_FILE)
                if os.path.exists(y_file):
                    try:
                        ydf = pd.read_csv(y_file, dtype=str).fillna("")
                        if not ydf.empty:
                            ydf["年"] = entry
                            candidates.append(sanitize_dataframe_columns(ydf))
                    except Exception: pass

    if os.path.exists(DB_FILE):
        try:
            root_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            if not root_df.empty: candidates.append(sanitize_dataframe_columns(root_df))
        except Exception: pass

    if not candidates: return

    try:
        combined = pd.concat(candidates, ignore_index=True, sort=False).fillna("")
        combined = sanitize_dataframe_columns(combined)
        if "レース名" in combined.columns and "馬番" in combined.columns:
            combined = combined.drop_duplicates(subset=["レース名", "馬番"], keep="last").reset_index(drop=True)
        combined.to_csv(DB_FILE, index=False, encoding="utf-8-sig")

        for year_val, year_df in combined.groupby("年"):
            if re.fullmatch(r"20\d{2}", str(year_val)):
                year_dir = os.path.join(DATA_DIR, str(year_val))
                os.makedirs(year_dir, exist_ok=True)
                year_df.to_csv(os.path.join(year_dir, DB_FILE), index=False, encoding="utf-8-sig")
    except Exception: pass


# ==================================================
# 📊 Googleスプレッドシート自動連携コアロジック
# ==================================================

def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    try:
        if "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=scopes)
            return gspread.authorize(creds)
    except Exception: pass
    return None


def load_db_from_sheet():
    gc = get_gspread_client()
    if not gc: return pd.DataFrame()
    try:
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet("重賞レース分析")
        data = worksheet.get_all_records()
        return sanitize_dataframe_columns(pd.DataFrame(data).astype(str).fillna("")) if data else pd.DataFrame()
    except Exception: return pd.DataFrame()


def save_db_to_sheet(df):
    gc = get_gspread_client()
    if not gc or df is None or df.empty: return
    try:
        sh = gc.open_by_key(SPREADSHEET_ID)
        worksheet = sh.worksheet("重賞レース分析")
        clean_df = sanitize_dataframe_columns(df).fillna("").astype(str)
        for col in clean_df.columns:
            clean_df[col] = clean_df[col].str.replace('\r\n', ' / ').str.replace('\n', ' / ')

        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) <= 1:
            worksheet.update('A1', [clean_df.columns.tolist()] + clean_df.values.tolist())
            st.toast("✅ 「重賞レース分析」シートへ全データを新規保存しました！")
            return

        existing_df = pd.DataFrame(all_values[1:], columns=all_values[0])
        incoming_races = clean_df["レース名"].dropna().unique().tolist()
        filtered_df = existing_df[~existing_df["レース名"].isin(incoming_races)] if "レース名" in existing_df.columns else existing_df

        updated_df = pd.concat([filtered_df, clean_df], ignore_index=True)
        worksheet.clear()
        worksheet.update('A1', [updated_df.columns.tolist()] + updated_df.values.tolist())
        st.toast(f"✅ 【上書き完了】 '{', '.join(incoming_races)}' を保存しました！")
    except Exception as e:
        st.error(f"❌ スプレッドシート同期エラー: {e}")


def load_db(selected_year=None):
    if selected_year is None: selected_year = f"{time.strftime('%Y')}年"
    migrate_and_clean_all_dbs()

    sheet_df = load_db_from_sheet()
    if not sheet_df.empty: combined = sheet_df
    else:
        all_dfs = []
        if os.path.exists(DB_FILE):
            try: all_dfs.append(pd.read_csv(DB_FILE, dtype=str).fillna(""))
            except Exception: pass

        if not all_dfs: return pd.DataFrame()
        combined = pd.concat(all_dfs, ignore_index=True)

    combined = sanitize_dataframe_columns(combined)
    if selected_year and selected_year != "全期間":
        target_y = str(selected_year).replace("年", "").strip()
        combined = combined[combined["年"].astype(str) == target_y].reset_index(drop=True)

    return combined


def get_available_years_in_db():
    df = load_db(selected_year="全期間")
    if df.empty or "年" not in df.columns: return [f"{time.strftime('%Y')}年"]
    years = sorted(df["年"].dropna().unique().tolist(), reverse=True)
    return [f"{y}年" for y in years if str(y).isdigit()] or [f"{time.strftime('%Y')}年"]


def save_to_db(new_df):
    if new_df is None or new_df.empty: return load_db()
    clean_save_df = sanitize_dataframe_columns(new_df)
    if "レース名" not in clean_save_df.columns: return load_db("全期間")

    save_races = clean_save_df["レース名"].astype(str).str.strip().unique().tolist()

    root_df = pd.DataFrame()
    if os.path.exists(DB_FILE):
        try: root_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
        except Exception: pass

    if not root_df.empty and "レース名" in root_df.columns:
        root_df = root_df[~root_df["レース名"].astype(str).str.strip().isin(save_races)]

    combined_root = pd.concat([root_df, clean_save_df], ignore_index=True, sort=False)
    combined_root = sanitize_dataframe_columns(combined_root)
    if "レース名" in combined_root.columns and "馬番" in combined_root.columns:
        combined_root = combined_root.drop_duplicates(subset=["レース名", "馬番"], keep="last").reset_index(drop=True)
    combined_root.to_csv(DB_FILE, index=False, encoding="utf-8-sig")

    save_db_to_sheet(combined_root)

    for year_val, year_new_df in clean_save_df.groupby("年", sort=False):
        year_dir = os.path.join(DATA_DIR, str(year_val))
        os.makedirs(year_dir, exist_ok=True)
        year_db_path = os.path.join(year_dir, DB_FILE)

        old_year_df = pd.DataFrame()
        if os.path.exists(year_db_path):
            try: old_year_df = pd.read_csv(year_db_path, dtype=str).fillna("")
            except Exception: pass

        if not old_year_df.empty and "レース名" in old_year_df.columns:
            old_year_df = old_year_df[~old_year_df["レース名"].astype(str).str.strip().isin(save_races)]

        combined_year_df = pd.concat([old_year_df, year_new_df], ignore_index=True, sort=False)
        combined_year_df = sanitize_dataframe_columns(combined_year_df)
        combined_year_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")

    return load_db(selected_year="全期間")


def update_db_with_recap(race_name, result_df, memo_text):
    if not os.path.exists(DB_FILE): return
    try:
        df = pd.read_csv(DB_FILE, dtype=str).fillna("")
        mask = df["レース名"].astype(str).str.strip() == str(race_name).strip()
        if not mask.any(): return

        result_by_num = {normalize_horse_num(r.get("馬番", "")): r for _, r in result_df.iterrows()} if not result_df.empty and "馬番" in result_df.columns else {}
        for col in ["確定着順", "単勝人気", "確定オッズ", "タイム", "上り3F", "勝因・敗因ショートメモ", "回顧メモ"]:
            if col not in df.columns: df[col] = ""

        for idx in df.index[mask]:
            horse_num = normalize_horse_num(df.at[idx, "馬番"] if "馬番" in df.columns else "")
            res_row = result_by_num.get(horse_num)
            if res_row is not None:
                for col in ["確定着順", "単勝人気", "確定オッズ", "タイム", "上り3F", "勝因・敗因ショートメモ"]:
                    if col in result_df.columns and pd.notna(res_row.get(col)):
                        df.at[idx, col] = str(res_row.get(col)).strip()
            df.at[idx, "回顧メモ"] = str(memo_text).strip()

        df = sanitize_dataframe_columns(df)
        df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    except Exception as e:
        st.warning(f"⚠️ 回顧更新注意: {e}")


def delete_race_from_db(race_name):
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            if "レース名" in df.columns:
                df[df["レース名"].astype(str) != str(race_name)].to_csv(DB_FILE, index=False, encoding="utf-8-sig")
                return True
        except Exception: pass
    return False


def clear_db():
    if os.path.exists(DB_FILE):
        try: os.remove(DB_FILE)
        except Exception: pass
    if os.path.exists(DATA_DIR):
        try: shutil.rmtree(DATA_DIR)
        except Exception: pass
    return True


# --------------------------------------------------
# 🧠 AIコア解析 ＆ 構造化JSONパース関数
# --------------------------------------------------

def parse_json_ai_output(result_text):
    all_parsed_rows = []
    if not result_text or not str(result_text).strip(): return pd.DataFrame()

    clean_text = re.sub(r"^```[a-zA-Z]*\n?", "", str(result_text).strip(), flags=re.MULTILINE)
    clean_text = re.sub(r"\n?```$", "", clean_text, flags=re.MULTILINE).strip()

    try: data = json.loads(clean_text)
    except Exception:
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            try: data = json.loads(match.group(0))
            except Exception: return pd.DataFrame()
        else: return pd.DataFrame()

    try:
        race_list = data.get("races", [data]) if isinstance(data, dict) else (data if isinstance(data, list) else [data])
        for race_data in race_list:
            if not isinstance(race_data, dict): continue
            race_title = str(race_data.get("race_name") or "20261008_競馬解析_OP").strip()
            horses = race_data.get("horses") or []

            for idx, h in enumerate(horses):
                if not isinstance(h, dict): continue
                h_num = safe_int(h.get("horse_num"), default=idx + 1)
                h_name = str(h.get("horse_name") or f"競走馬_{h_num}").strip()
                total_score = safe_int(h.get("total_score"), default=80)
                rank_eval = str(h.get("eval") or "A").strip()

                row_dict = {
                    "確定着順": clean_pop_number(h.get("rank", "")),
                    "馬番": h_num, "馬名": h_name, "総合スコア": total_score, "評価": rank_eval,
                    "予想人気": clean_pop_number(h.get("pop", "-")),
                    "単勝人気": clean_pop_number(h.get("single_pop", "")),
                    "確定オッズ": str(h.get("odds") or "").strip(),
                    "タイム": str(h.get("time") or "").strip(),
                    "上り3F": str(h.get("agari") or "").strip(),
                    "勝因・敗因ショートメモ": str(h.get("short_memo") or "").strip(),
                    "出馬表点": safe_int(h.get("score_shubahyou"), total_score),
                    "血統点": safe_int(h.get("score_kettou"), total_score),
                    "調教点": safe_int(h.get("score_choukyou"), total_score),
                    "近5走点": safe_int(h.get("score_kin5so"), total_score),
                    "展開点": safe_int(h.get("score_tenkai"), total_score),
                    "馬場点": safe_int(h.get("score_baba"), total_score),
                    "軸": "〇" if h.get("jiku") == "〇" or rank_eval in ["S", "A+"] else "",
                    "ヒモ": "〇" if h.get("himo") == "〇" or rank_eval in ["A", "B+"] else "",
                    "注": "〇" if h.get("chu") == "〇" or rank_eval == "B" else "",
                    "切り": "〇" if h.get("kiri") == "〇" or rank_eval == "C" else "",
                    "メモ": str(h.get("memo") or "【詳細分析】スコア評価算出。").strip(),
                    "レース名": race_title, "年": extract_year_from_race_name(race_title)
                }
                if race_data.get("confidence"): row_dict["信頼度"] = race_data.get("confidence")
                if race_data.get("risk_level"): row_dict["波乱度"] = race_data.get("risk_level")
                if race_data.get("race_quality_and_tenkai"): row_dict["レース質展開予想"] = race_data.get("race_quality_and_tenkai")
                if race_data.get("recommended_tickets"): row_dict["推奨買い目"] = json.dumps(race_data.get("recommended_tickets"), ensure_ascii=False)
                all_parsed_rows.append(row_dict)
    except Exception: pass

    return pd.DataFrame(all_parsed_rows) if all_parsed_rows else pd.DataFrame()


def analyze_data_with_gemini(api_key, active_rules, t1, p1, t2, p2, t3, p3, t4, p4, t5, model_name):
    client = genai.Client(api_key=api_key)
    json_prompt = f"""{active_rules}

【レース特定・全頭解析絶対ルール】
1. 添付データからレース名・グレードを特定し、race_name を 「YYYYMMDD_レース名_グレード」 形式で生成してください。
2. 今回出走する本物の馬【全頭】を評価してください。
3. 展開シミュレーション文章を race_quality_and_tenkai に出力してください。
4. 推奨買い目を recommended_tickets（丸数字①,②等を使用）に出力してください。

データ1: {t1}
データ2: {t2}
データ3: {t3}
データ4: {t4}
データ5: {t5}

出力JSON形式:
{{
  "race_name": "20261011_毎日王冠_G2",
  "confidence": "S (鉄板軸)",
  "risk_level": "★☆☆ (本命堅調)",
  "race_quality_and_tenkai": "🏁 レース質＆展開予想...",
  "recommended_tickets": ["【馬連】 ⑤ ＝ ①, ②"],
  "horses": [
    {{
      "horse_num": 1, "horse_name": "馬名", "pop": "1", "total_score": 85, "eval": "A",
      "score_shubahyou": 85, "score_kettou": 85, "score_choukyou": 85, "score_kin5so": 85,
      "score_tenkai": 85, "score_baba": 85, "jiku": "〇", "himo": "", "chu": "", "kiri": "",
      "memo": "詳細解説"
    }}
  ]
}}
"""
    contents = [json_prompt] + p1 + p2 + p3 + p4
    response = client.models.generate_content(
        model=model_name, contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0, seed=42)
    )
    return response.text


def reevaluate_race_data_with_gemini(api_key, active_rules, current_df, add_text, add_media_parts, model_name):
    client = genai.Client(api_key=api_key)
    race_title = current_df["レース名"].iloc[0] if "レース名" in current_df.columns else "対象レース"
    cols_horses = [c for c in ["馬番", "馬名", "総合スコア", "評価", "メモ"] if c in current_df.columns]
    
    reeval_prompt = f"""{active_rules}
直前追加データに基づき、【{race_title}】の評価・見解・買い目を再検証・微調整してください。
【現在のデータ】:\n{current_df[cols_horses].to_string(index=False)}
【直前追加情報】:\n{add_text}

JSON形式で has_changes, change_summary, race_quality_and_tenkai, recommended_tickets, horses を返してください。
"""
    response = client.models.generate_content(
        model=model_name, contents=[reeval_prompt] + add_media_parts,
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0, seed=42)
    )
    return response.text


def render_re_evaluation_section(current_df, active_rules, selected_model):
    race_name_val = current_df['レース名'].iloc[0] if "レース名" in current_df.columns else "対象レース"
    with st.expander("🔄 【直前追加データ】パドック・馬体重・直前情報による再評価・微調整", expanded=False):
        col_add1, col_add2 = st.columns([1.5, 1])
        with col_add1:
            add_files = st.file_uploader("📂 追加資料 (.txt / .pdf / 画像)", type=["txt", "pdf", "png", "jpg"], accept_multiple_files=True, key=f"reeval_files_{race_name_val}")
        with col_add2:
            add_memo = st.text_area("✏️ 直前メモ手入力", height=100, key=f"reeval_memo_{race_name_val}")

        if st.button("🚀 直前追加データを含めて再評価を実行", use_container_width=True):
            active_key = load_api_key()
            if not active_key: st.error("⚠️ API Key を設定してください！")
            else:
                with st.spinner("🏇 再評価解析中..."):
                    try:
                        add_text_content, add_media_parts = prepare_file_parts(add_files, pdf_page_option="全ページ")
                        raw_json = reevaluate_race_data_with_gemini(active_key, active_rules, current_df, add_text_content + "\n" + add_memo, add_media_parts, selected_model)
                        updated_df = parse_json_ai_output(raw_json)
                        if not updated_df.empty:
                            save_to_db(updated_df)
                            st.session_state["analyzed_df"] = updated_df
                            st.success("🎉 直前データを反映・更新しました！")
                            st.rerun()
                    except Exception as e: st.error(f"❌ 再評価エラー: {e}")


def analyze_12r_and_select_top5(api_key, rules_text, draft_races_list, model_name):
    client = genai.Client(api_key=api_key)
    all_races_payload_text, media_parts_all = "", []
    for r_name in draft_races_list:
        t1, p1, t2, p2, t3, p3, t4, p4, t5, _ = load_draft_data(r_name)
        all_races_payload_text += f"\n\n=== Race: {r_name} ===\n{t1}\n{t2}\n{t3}\n{t4}\n{t5}"
        media_parts_all.extend(p1 + p2 + p3 + p4)

    prompt = f"{rules_text}\n全レースからメインレース＋勝負上位4Rの計5Rを選出し、詳細評価JSONを出力してください。"
    response = client.models.generate_content(
        model=model_name, contents=[prompt + "\n" + all_races_payload_text] + media_parts_all[:15],
        config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0, seed=42)
    )
    return response.text


def render_field_mode_ui(api_key, active_selected_rule, selected_model):
    st.subheader("🏇 現地観戦用モード：全12Rから勝負5Rを厳選分析")
    draft_list = list_draft_races()
    if st.button("🚀 本日の勝負5Rを一括判定実行", use_container_width=True, type="primary"):
        if not api_key: st.error("⚠️ API Key を設定してください！")
        elif not draft_list: st.warning("⚠️ 下書きデータがありません。")
        else:
            with st.spinner("🏇 勝負5レースを解析中..."):
                try:
                    raw_json = analyze_12r_and_select_top5(api_key, active_selected_rule, draft_list, selected_model)
                    res = json.loads(re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw_json.strip()))
                    st.session_state["field_mode_result"] = res
                    st.success("🎉 勝負5レースの解析が完了しました！")
                    st.rerun()
                except Exception as e: st.error(f"❌ エラー: {e}")


def render_umael_chat_ui(df, race_title):
    st.divider()
    st.subheader(f"💬 ウマエルAIチャット（【{race_title}】質問・追加データ）")
    sanitized_title = re.sub(r'\W+', '_', race_title)
    chat_key = f"chat_history_{sanitized_title}"
    if chat_key not in st.session_state: st.session_state[chat_key] = []

    for msg in st.session_state[chat_key]:
        with st.chat_message(msg["role"]): st.write(msg["content"])

    user_input = st.chat_input(f"「{race_title}」について質問する...")
    if user_input:
        st.session_state[chat_key].append({"role": "user", "content": user_input})
        with st.chat_message("user"): st.write(user_input)
        key = load_api_key()
        if key:
            with st.chat_message("assistant"):
                with st.spinner("🏇 回答中..."):
                    try:
                        client = genai.Client(api_key=key)
                        res = client.models.generate_content(
                            model="gemini-3.8-flash",
                            contents=[f"レース【{race_title}】について回答してください:\n{user_input}"]
                        )
                        st.write(res.text)
                        st.session_state[chat_key].append({"role": "assistant", "content": res.text})
                    except Exception as e: st.error(f"エラー: {e}")


def render_race_evaluation_view(df, is_viewer_mode=False, show_chat=True):
    if df is None or df.empty: return
    df = sanitize_dataframe_columns(df)
    race_title = df["レース名"].iloc[0] if "レース名" in df.columns else "競馬解析"

    st.markdown(f"## 🏇 {race_title}")
    
    view_tab1, view_tab2 = st.tabs(["🌟 サマリー", "📊 詳細データ表"])
    with view_tab1:
        honmei = df.iloc[0] if not df.empty else None
        if honmei is not None:
            st.success(f"◎ 本命推奨馬: 【{honmei.get('馬番')}】 {honmei.get('馬名')} （総合スコア: {honmei.get('総合スコア')}点）")
        
        if "レース質展開予想" in df.columns and str(df["レース質展開予想"].iloc[0]).strip():
            st.subheader("🏁 レース質 ＆ 展開予想")
            st.info(df["レース質展開予想"].iloc[0])

    with view_tab2:
        cols_disp = [c for c in ["馬番", "馬名", "総合スコア", "評価", "予想人気", "軸", "ヒモ", "注", "切り", "メモ"] if c in df.columns]
        st.dataframe(df[cols_disp], use_container_width=True, hide_index=True)

    if not is_viewer_mode:
        render_re_evaluation_section(df, load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES), "gemini-3.8-flash")
    if show_chat:
        render_umael_chat_ui(df, race_title)


# --------------------------------------------------
# 🧭 URLパラメーター共有 ＆ UIスタイル設定
# --------------------------------------------------

query_params = st.query_params
if query_params.get("mode") == "share" and query_params.get("race"):
    race_p = query_params.get("race")
    db_df = load_db(selected_year="全期間")
    if not db_df.empty and "レース名" in db_df.columns:
        m_df = db_df[db_df["レース名"].astype(str) == str(race_p)]
        if not m_df.empty: render_race_evaluation_view(m_df, is_viewer_mode=True, show_chat=False)
    st.stop()


# サイドバーメニュー構成
with st.sidebar:
    st.header("🧭 ナビゲーション")
    selected_menu = st.radio(
        "機能を選択：",
        [
            "📋 レース分析・予想",
            "🏇 現地観戦用（勝負5R厳選）",
            "⚙️ ルール管理・アップデート",
            "🔄 回顧・精度検証",
            "📊 評価データ一覧（プール）",
            "📝 回顧・精度検証一覧（プール）",
            "🗄 過去馬データベース（プール）",
            "📥 過去CSVデータ取込",
        ], index=0
    )
    st.divider()
    saved_key = load_api_key()
    api_key = st.text_input("Gemini API Key", value=saved_key, type="password")
    if api_key != saved_key: save_api_key(api_key)
    selected_model = st.selectbox("🤖 AIモデル", ["gemini-3.8-flash"], index=0)


# ==================================================
# 📋 1. レース分析・予想 メニュー（完全版）
# ==================================================

if selected_menu == "📋 レース分析・予想":
    st.subheader("🎯 解析ルールの選択 ＆ 段階的データ保存")

    rule_type = st.radio(
        "今回解析するレースのルールを選択してください：",
        ["🏆 G1専用ルール", "🏇 平場・G2・G3専用ルール", "🌾 北海道・洋芝専用ルール"],
        horizontal=True
    )

    if "G1専用" in rule_type: active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
    elif "北海道" in rule_type: active_selected_rule = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
    else: active_selected_rule = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)

    st.divider()
    st.subheader("📁 レースデータの蓄積・下書き管理")

    upload_mode = st.radio(
        "運用モードを選択してください：",
        ["📥 金〜日曜のデータを段階的に下書き保存・一括解析", "⚡ 今日届いたデータで直接解析（単発実行）"],
        horizontal=True
    )

    draft_race_name = ""
    existing_drafts = list_draft_races()

    if "段階的" in upload_mode:
        draft_col1, draft_col2 = st.columns([1.5, 1])
        with draft_col1:
            draft_choice = st.selectbox(
                "📂 保存・編集する対象レースを選択（新規または既存）：",
                ["✨ 【新規レースとして保存（馬柱からレース名自動判定）】"] + existing_drafts,
                key="draft_race_select_box"
            )
            if draft_choice == "✨ 【新規レースとして保存（馬柱からレース名自動判定）】":
                draft_race_name = st.text_input("✏️ レース名を手動指定する場合（空欄可）", "")
            else: draft_race_name = draft_choice

        with draft_col2:
            if draft_race_name and draft_race_name not in ["✨ 【新規レースとして保存（馬柱からレース名自動判定）】", ""]:
                _, _, _, _, _, _, _, _, _, saved_fnames = load_draft_data(draft_race_name)
                st.write(f"📦 保存済みファイル: {len(saved_fnames)}件")

    st.divider()
    st.subheader("📂 データのアップロード (.txt / .csv / .pdf / .png / .jpg / URL)")

    col1, col2, col3, col4 = st.columns(4)
    with col1: files_group1 = st.file_uploader("1. 出馬表・枠順・近5走・血統", type=["txt", "csv", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
    with col2:
        files_group2 = st.file_uploader("2. 競馬ブック・調教", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        pdf_page_opt = st.radio("📄 競馬ブックPDF読み込み", ["1ページ目のみ（推奨）", "全ページ読み込む"], index=0)
    with col3: files_group3 = st.file_uploader("3. 傾向・馬場情報", type=["txt", "csv", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
    with col4: files_group4 = st.file_uploader("4. その他各種データ", type=["txt", "csv", "pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)

    urls_group5_input = st.text_area("🔗 5. プロ予想・YouTube・Web参考URL", height=80, placeholder="https://...")

    st.divider()

    if "段階的" in upload_mode:
        btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1.5, 1])
        with btn_col1:
            if st.button("💾 今回のデータを下書き保存する", use_container_width=True):
                if not any([files_group1, files_group2, files_group3, files_group4, urls_group5_input.strip()]):
                    st.warning("⚠️ 保存するデータを選択してください！")
                else:
                    target_n = draft_race_name.strip() if draft_race_name else ""
                    saved_c, actual_n = save_draft_data(target_n, files_group1, files_group2, files_group3, files_group4, urls_group5_input)
                    st.success(f"🎉 レース「{actual_n}」に保存しました！（{saved_c}件）")
                    st.rerun()

        with btn_col2:
            if st.button("🔥 蓄積された全データでAI一括解析を実行", use_container_width=True):
                active_key = load_api_key()
                if not active_key: st.error("⚠️ API Key を設定してください！")
                else:
                    pdf_opt = "1ページ目のみ" if "1ページ目" in pdf_page_opt else "全ページ"
                    target_d = draft_race_name if draft_race_name and draft_race_name != "✨ 【新規レースとして保存（馬柱からレース名自動判定）】" else ""
                    dt1, dp1, dt2, dp2, dt3, dp3, dt4, dp4, dt5, _ = load_draft_data(target_d, pdf_page_option=pdf_opt) if target_d else ("", [], "", [], "", [], "", [], "", [])
                    nt1, np1 = prepare_file_parts(files_group1, pdf_page_option=pdf_opt)
                    nt2, np2 = prepare_file_parts(files_group2, pdf_page_option=pdf_opt)
                    nt3, np3 = prepare_file_parts(files_group3, pdf_page_option=pdf_opt)
                    nt4, np4 = prepare_file_parts(files_group4, pdf_page_option=pdf_opt)
                    nt5 = process_multiple_urls(urls_group5_input)

                    with st.spinner("🏇 一括解析中..."):
                        try:
                            res_text = analyze_data_with_gemini(
                                active_key, active_selected_rule,
                                dt1+"\n"+nt1, dp1+np1, dt2+"\n"+nt2, dp2+np2,
                                dt3+"\n"+nt3, dp3+np3, dt4+"\n"+nt4, dp4+np4,
                                dt5+"\n"+nt5, selected_model
                            )
                            df = parse_json_ai_output(res_text)
                            if not df.empty:
                                save_to_db(df)
                                if target_d: delete_draft(target_d)
                                st.session_state["analyzed_df"] = df
                                st.success("🎉 解析・保存が完了しました！")
                                st.rerun()
                        except Exception as e: st.error(f"❌ 解析エラー: {e}")

        with btn_col3:
            if st.button("🗑️ この下書きを削除", use_container_width=True):
                if draft_race_name:
                    delete_draft(draft_race_name)
                    st.success("🗑️ 下書きを削除しました！")
                    st.rerun()

    else:
        if st.button("🔥 AI分析を実行する", use_container_width=True):
            active_key = load_api_key()
            if not active_key: st.error("⚠️ API Key を設定してください！")
            else:
                with st.spinner("🏇 AI解析中..."):
                    try:
                        pdf_opt = "1ページ目のみ" if "1ページ目" in pdf_page_opt else "全ページ"
                        t1, p1 = prepare_file_parts(files_group1, pdf_page_option=pdf_opt)
                        t2, p2 = prepare_file_parts(files_group2, pdf_page_option=pdf_opt)
                        t3, p3 = prepare_file_parts(files_group3, pdf_page_option=pdf_opt)
                        t4, p4 = prepare_file_parts(files_group4, pdf_page_option=pdf_opt)
                        t5 = process_multiple_urls(urls_group5_input)
                        res_text = analyze_data_with_gemini(active_key, active_selected_rule, t1, p1, t2, p2, t3, p3, t4, p4, t5, selected_model)
                        df = parse_json_ai_output(res_text)
                        if not df.empty:
                            save_to_db(df)
                            st.session_state["analyzed_df"] = df
                            st.success("🎉 解析完了！")
                            st.rerun()
                    except Exception as e: st.error(f"❌ 解析エラー: {e}")

    if "analyzed_df" in st.session_state and not st.session_state["analyzed_df"].empty:
        st.divider()
        render_race_evaluation_view(st.session_state["analyzed_df"], is_viewer_mode=False, show_chat=True)


# --------------------------------------------------
# 🏇 2. 現地観戦用 メニュー
# --------------------------------------------------

elif selected_menu == "🏇 現地観戦用（勝負5R厳選）":
    rule_type = st.radio("評価ルール：", ["🏆 G1専用", "🏇 平場・G2・G3専用", "🌾 北海道・洋芝専用"], horizontal=True)
    if "G1専用" in rule_type: r = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
    elif "北海道" in rule_type: r = load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
    else: r = load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)
    render_field_mode_ui(load_api_key(), r, selected_model)


# --------------------------------------------------
# ⚙️ 3. ルール管理 メニュー
# --------------------------------------------------

elif selected_menu == "⚙️ ルール管理・アップデート":
    st.subheader("⚙️ ルール設定")
    t1, t2, t3 = st.tabs(["🏆 G1専用", "🏇 平場・G2・G3専用", "🌾 北海道・洋芝専用"])
    with t1:
        txt = st.text_area("G1ルール", value=load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES), height=300)
        if st.button("💾 G1ルール保存"): save_rules_to_file(RULE_G1_FILE, txt); st.success("保存しました！")
    with t2:
        txt = st.text_area("平場・G2・G3ルール", value=load_saved_rules(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES), height=300)
        if st.button("💾 平場ルール保存"): save_rules_to_file(RULE_GENERAL_FILE, txt); st.success("保存しました！")
    with t3:
        txt = st.text_area("北海道ルール", value=load_saved_rules(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES), height=300)
        if st.button("💾 北海道ルール保存"): save_rules_to_file(RULE_HOKKAIDO_FILE, txt); st.success("保存しました！")


# --------------------------------------------------
# 🔄 4. 回顧・精度検証 メニュー
# --------------------------------------------------

elif selected_menu == "🔄 回顧・精度検証":
    st.subheader("🔄 レース後回顧 ＆ 全着順自動照合")
    db_df = load_db(selected_year="全期間")
    if not db_df.empty:
        races = db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []
        sel_race = st.selectbox("回顧対象レース", races)
        res_text = st.text_area("結果テキスト貼り付け", height=150)
        if st.button("🏁 回顧・照合実行"):
            st.info("回顧処理を実行中...")


# --------------------------------------------------
# 📊 5. 評価データ一覧 メニュー
# --------------------------------------------------

elif selected_menu == "📊 評価データ一覧（プール）":
    st.subheader("📊 評価データ一覧")
    db_df = load_db(selected_year="全期間")
    if not db_df.empty and "レース名" in db_df.columns:
        sel_r = st.selectbox("レース選択", ["--- 選択 ---"] + db_df["レース名"].unique().tolist())
        if sel_r != "--- 選択 ---":
            render_race_evaluation_view(db_df[db_df["レース名"] == sel_r], is_viewer_mode=False, show_chat=True)


# --------------------------------------------------
# 📝 6. 回顧一覧 メニュー
# --------------------------------------------------

elif selected_menu == "📝 回顧・精度検証一覧（プール）":
    st.subheader("📝 回顧・精度検証一覧")
    db_df = load_db(selected_year="全期間")
    if not db_df.empty and "レース名" in db_df.columns:
        sel_r = st.selectbox("回顧レース選択", ["--- 選択 ---"] + db_df["レース名"].unique().tolist())
        if sel_r != "--- 選択 ---":
            st.dataframe(db_df[db_df["レース名"] == sel_r], use_container_width=True)


# --------------------------------------------------
# 🗄 7. 過去馬データベース メニュー
# --------------------------------------------------

elif selected_menu == "🗄 過去馬データベース（プール）":
    st.subheader("🗄️ 過去馬データベース")
    db_df = load_db(selected_year="全期間")
    if not db_df.empty:
        st.dataframe(db_df, use_container_width=True)


# --------------------------------------------------
# 📥 8. 過去CSVデータ取込 メニュー（詳細表示完全版）
# --------------------------------------------------

elif selected_menu == "📥 過去CSVデータ取込":
    st.subheader("📥 過去CSVデータの一括取り込み・同期")
    st.write("保存・バックアップしてある過去のCSVファイル（一括DB用CSV、または単一レースCSV）をアップロードして、データベースへ一括インポート・同期保存します。")

    uploaded_csv_files = st.file_uploader(
        "📂 バックアップCSVファイルを選択（複数ファイル一括選択可能）",
        type=["csv"],
        accept_multiple_files=True,
        key="backup_csv_uploader",
    )

    if st.button("🚀 過去CSVデータをデータベースへ一括取り込み・同期", use_container_width=True, type="primary"):
        if not uploaded_csv_files:
            st.warning("⚠️ インポートするCSVファイルを1つ以上選択してください！")
        else:
            with st.spinner("📦 CSVデータを読み込み、データベースに自動クレンジング・割り振り保存中..."):
                imported_dfs = []
                failed_files = []

                for csv_file in uploaded_csv_files:
                    try:
                        csv_file.seek(0)
                        try:
                            df_temp = pd.read_csv(csv_file, dtype=str, encoding="utf-8-sig").fillna("")
                        except Exception:
                            csv_file.seek(0)
                            df_temp = pd.read_csv(csv_file, dtype=str, encoding="cp932").fillna("")

                        if not df_temp.empty and "レース名" in df_temp.columns:
                            imported_dfs.append(df_temp)
                        else:
                            failed_files.append(csv_file.name)
                    except Exception as e:
                        failed_files.append(f"{csv_file.name} ({e})")

                if imported_dfs:
                    try:
                        combined_import_df = pd.concat(imported_dfs, ignore_index=True, sort=False)
                        updated_db = save_to_db(combined_import_df)

                        imported_races = (
                            combined_import_df["レース名"]
                            .dropna()
                            .astype(str)
                            .str.strip()
                            .unique()
                            .tolist()
                        )
                        imported_races = [r for r in imported_races if r]

                        st.success(
                            f"🎉 CSVファイルのインポートが完了しました！ (合計 {len(imported_races)} レース分 / {len(combined_import_df)} 件の馬データ)"
                        )

                        # 📋 取り込まれた対象レース一覧の表示
                        st.markdown("#### 📋 取り込まれた対象レース一覧")
                        for r_name in imported_races:
                            st.write(f"・ `{r_name}`")

                        # ⚠️ スキップ・失敗したファイルの警告表示
                        if failed_files:
                            st.warning(
                                f"⚠️ 以下のファイルはフォーマット不備または空のためスキップされました: {', '.join(failed_files)}"
                            )

                    except Exception as e:
                        st.error(f"❌ データベース統合処理中にエラーが発生しました: {e}")
                else:
                    st.error("❌ 有効なCSVデータを取り込めませんでした。ファイルのフォーマットを確認してください。")