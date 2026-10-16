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
                    pdf.pages if page_option == "全ページ読み込む" or page_option == "全ページ" else [pdf.pages[0]]
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
                bio = io.BytesIO(file_bytes)
                extracted = extract_text_from_pdf(bio, page_option=pdf_page_option)
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

                if len(extracted.strip()) < 100 or fname.lower().endswith((".png", ".jpg", ".jpeg")):
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


def detect_simple_race_name(files_g1, files_g2, files_g3, files_g4=None):
    check_lists = [files_g1, files_g2, files_g3]
    if files_g4:
        check_lists.append(files_g4)
        
    for flist in check_lists:
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
    
    group_tuples = [(1, files_g1), (2, files_g2), (3, files_g3), (4, files_g4)]

    for g_idx, file_list in group_tuples:
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

                if len(extracted.strip()) < 100 or original_fname.lower().endswith((".png", ".jpg", ".jpeg")):
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


# --------------------------------------------------
# 🧼 データベースクレンジング ＆ マルチフォルダ同期ロジック
# --------------------------------------------------

def sanitize_dataframe_columns(df):
    if df is None or df.empty:
        return df
    df = df.copy()

    # 1. 不要な空白列（Unnamed列）および不要な「総合スコアグラフ」列を一括削除
    drop_target_cols = [c for c in df.columns if str(c).startswith("Unnamed:")]
    for drop_col in ["総合スコアグラフ", "軸ヒモ切り", "人気"]:
        if drop_col in df.columns:
            drop_target_cols.append(drop_col)

    if drop_target_cols:
        df = df.drop(columns=list(set(drop_target_cols)), errors="ignore")

    df = df.loc[:, ~df.columns.duplicated()]

    # 2. 列名の自動正規化・表記揺れ吸収
    rename_map = {}
    for orig_c in df.columns:
        c_clean = str(orig_c).strip().replace(" ", "").replace("\n", "").replace("\r", "")
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
        elif c_clean in ["レース質展開予想", "展開シミュレーション", "レース質"] and "レース質展開予想" not in rename_map.values():
            rename_map[orig_c] = "レース質展開予想"
        elif c_clean in ["推奨買い目", "買い目", "買い目フォーメーション"] and "推奨買い目" not in rename_map.values():
            rename_map[orig_c] = "推奨買い目"
        elif c_clean in ["信頼度", "軸馬信頼度"] and "信頼度" not in rename_map.values():
            rename_map[orig_c] = "信頼度"
        elif c_clean in ["波乱度", "波乱度レベル"] and "波乱度" not in rename_map.values():
            rename_map[orig_c] = "波乱度"

    if rename_map:
        df = df.rename(columns=rename_map)

    df = df.loc[:, ~df.columns.duplicated()]

    if "総合スコア" in df.columns:
        df["総合スコア"] = pd.to_numeric(
            df["総合スコア"].astype(str).str.replace("点", "").str.strip(), errors="coerce"
        ).fillna(0).astype(int)

    if "予想人気" in df.columns:
        df["予想人気"] = df["予想人気"].apply(clean_pop_number)
    if "単勝人気" in df.columns:
        df["単勝人気"] = df["単勝人気"].apply(clean_pop_number)

    # 3. 必須・全頭共通カラムの補完と安全確保
    for col in ["評価", "軸", "ヒモ", "注", "切り", "メモ", "総合スコア", "年", "レース質展開予想", "推奨買い目", "信頼度", "波乱度"]:
        if col not in df.columns:
            df[col] = ""

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


def migrate_and_clean_all_dbs():
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
    formatted = [f"{y}年" for y in years if str(y).isdigit()]
    return formatted if formatted else ["2026年"]


def save_to_db(new_df):
    if new_df is None or new_df.empty:
        return load_db()

    clean_save_df = sanitize_dataframe_columns(new_df)
    
    if "年" not in clean_save_df.columns or clean_save_df["年"].iloc[0] == "":
        race_n = clean_save_df["レース名"].iloc[0] if "レース名" in clean_save_df.columns else ""
        clean_save_df["年"] = extract_year_from_race_name(race_n)

    year_val = str(clean_save_df["年"].iloc[0]).strip()
    if not year_val or year_val in ["None", "nan"]:
        year_val = "2026"

    # 1. ルート直下 umael_database.csv 保存
    if os.path.exists(DB_FILE):
        try:
            old_df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            if "レース名" in clean_save_df.columns and "レース名" in old_df.columns:
                race_n = clean_save_df["レース名"].iloc[0]
                old_df = old_df[old_df["レース名"].astype(str) != str(race_n)]
            combined_df = pd.concat([old_df, clean_save_df], ignore_index=True)
            combined_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        except Exception:
            clean_save_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    else:
        clean_save_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")

    # 2. data/YYYY/umael_database.csv 保存
    year_dir = os.path.join(DATA_DIR, year_val)
    os.makedirs(year_dir, exist_ok=True)
    year_db_path = os.path.join(year_dir, DB_FILE)

    if os.path.exists(year_db_path):
        try:
            old_ydf = pd.read_csv(year_db_path, dtype=str).fillna("")
            if "レース名" in clean_save_df.columns and "レース名" in old_ydf.columns:
                race_n = clean_save_df["レース名"].iloc[0]
                old_ydf = old_ydf[old_ydf["レース名"].astype(str) != str(race_n)]
            combined_ydf = pd.concat([old_ydf, clean_save_df], ignore_index=True)
            combined_ydf.to_csv(year_db_path, index=False, encoding="utf-8-sig")
        except Exception:
            clean_save_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")
    else:
        clean_save_df.to_csv(year_db_path, index=False, encoding="utf-8-sig")

    return load_db(f"{year_val}年")


def update_db_with_recap(race_name, result_df, memo_text):
    if not os.path.exists(DB_FILE):
        return
    try:
        df = pd.read_csv(DB_FILE, dtype=str).fillna("")
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
                pop_val = result_row.get("単勝人気", result_row.get("人気", ""))
                if pd.notna(pop_val) and str(pop_val).strip():
                    df.at[idx, "単勝人気"] = str(pop_val).strip()
                for col in result_columns:
                    if col in result_df.columns and col != "単勝人気":
                        value = result_row.get(col, "")
                        if pd.notna(value) and str(value).strip():
                            df.at[idx, col] = str(value).strip()
            df.at[idx, "回顧メモ"] = str(memo_text).strip()

        df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        
        # 年度サブフォルダにも反映
        year_val = extract_year_from_race_name(race_name)
        year_db_path = os.path.join(DATA_DIR, year_val, DB_FILE)
        if os.path.exists(year_db_path):
            df.to_csv(year_db_path, index=False, encoding="utf-8-sig")

    except Exception as e:
        st.warning(f"⚠️ データベースの回顧・着順プール保存中に注意: {e}")


def delete_race_from_db(race_name):
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE)
            if "レース名" in df.columns:
                new_df = df[df["レース名"].astype(str) != str(race_name)]
                new_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
                
                year_val = extract_year_from_race_name(race_name)
                year_db_path = os.path.join(DATA_DIR, year_val, DB_FILE)
                if os.path.exists(year_db_path):
                    ydf = pd.read_csv(year_db_path)
                    if "レース名" in ydf.columns:
                        new_ydf = ydf[ydf["レース名"].astype(str) != str(race_name)]
                        new_ydf.to_csv(year_db_path, index=False, encoding="utf-8-sig")
                return True
        except Exception:
            pass
    return False


def clear_db():
    if os.path.exists(DB_FILE):
        try:
            os.remove(DB_FILE)
        except Exception:
            pass
    if os.path.exists(DATA_DIR):
        try:
            shutil.rmtree(DATA_DIR)
        except Exception:
            pass
    return True


# --------------------------------------------------
# 🧠 AIコア解析 ＆ 構造化JSONパース関数
# --------------------------------------------------

def parse_json_ai_output(result_text):
    all_parsed_rows = []

    if not result_text or not str(result_text).strip():
        st.error("⚠️ AIからの返却レスポンスが空でした。")
        return pd.DataFrame()

    raw_text = str(result_text).strip()
    
    clean_text = re.sub(r"^```[a-zA-Z]*\n?", "", raw_text, flags=re.MULTILINE)
    clean_text = re.sub(r"\n?```$", "", clean_text, flags=re.MULTILINE).strip()

    data = None
    parse_error = None

    try:
        data = json.loads(clean_text)
    except Exception as e1:
        parse_error = str(e1)
        match = re.search(r'\{.*\}', clean_text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                parse_error = None
            except Exception as e2:
                parse_error = f"1次エラー: {e1} | 2次(フォールバック)エラー: {e2}"

    if data is None or parse_error:
        st.error("❌ Gemini APIからの返却JSONのパースに失敗しました。")
        with st.expander("🛠️ デバッグ用：エラー内容 ＆ Rawレスポンス（クリックで展開）", expanded=True):
            st.code(f"エラー詳細: {parse_error}", language="text")
            st.text_area("AIから返ってきたRawレスポンス", value=raw_text, height=250)
        return pd.DataFrame()

    try:
        if isinstance(data, dict) and "races" in data and isinstance(data["races"], list):
            race_list = data["races"]
        elif isinstance(data, list):
            race_list = data
        else:
            race_list = [data]

        for race_data in race_list:
            if not isinstance(race_data, dict):
                continue

            race_title = str(race_data.get("race_name") or "20261008_競馬解析_OP").strip()
            confidence = race_data.get("confidence") or ""
            risk_level = race_data.get("risk_level") or ""
            race_quality_and_tenkai = race_data.get("race_quality_and_tenkai") or ""
            recommended_tickets = race_data.get("recommended_tickets") or []
            recap_memo = race_data.get("recap_memo") or ""

            horses = race_data.get("horses") or []

            for idx, h in enumerate(horses):
                if not isinstance(h, dict):
                    continue

                raw_h_num = h.get("horse_num")
                h_num = safe_int(raw_h_num, default=idx + 1)
                
                raw_h_name = h.get("horse_name")
                h_name = str(raw_h_name).strip() if raw_h_name is not None and str(raw_h_name).strip() != "" else f"競走馬_{h_num}"

                pop_val = clean_pop_number(h.get("pop", "-"))
                total_score = safe_int(h.get("total_score"), default=80)
                rank_eval = str(h.get("eval") or "A").strip()

                score_shubahyou = safe_int(h.get("score_shubahyou"), default=total_score)
                score_kettou = safe_int(h.get("score_kettou"), default=total_score)
                score_choukyou = safe_int(h.get("score_choukyou"), default=total_score)
                score_kin5so = safe_int(h.get("score_kin5so"), default=total_score)
                score_tenkai = safe_int(h.get("score_tenkai"), default=total_score)
                score_baba = safe_int(h.get("score_baba"), default=total_score)

                ai_jiku = str(h.get("jiku") or "").strip() == "〇"
                ai_himo = str(h.get("himo") or "").strip() == "〇"
                ai_chu = str(h.get("注") or h.get("chu") or "").strip() == "〇"
                ai_kiri = str(h.get("kiri") or "").strip() == "〇"

                jiku, himo, chu, kiri = "", "", "", ""
                if ai_jiku or rank_eval in ["S", "S+", "A+"]:
                    jiku = "〇"
                elif ai_himo or rank_eval in ["A", "A-", "B+"]:
                    himo = "〇"
                elif ai_chu or rank_eval in ["B", "B-"]:
                    chu = "〇"
                else:
                    kiri = "〇"

                memo = str(h.get("memo") or "").strip()
                if not memo or len(memo) < 10:
                    memo = (
                        f"【評価理由】総合スコア{total_score}点。データ・血統・適性面を考慮して評価を算出。"
                    )

                row_dict = {
                    "確定着順": clean_pop_number(h.get("rank", "")),
                    "馬番": h_num,
                    "馬名": h_name,
                    "総合スコア": total_score,
                    "評価": rank_eval,
                    "予想人気": pop_val,
                    "単勝人気": clean_pop_number(h.get("single_pop", "")),
                    "確定オッズ": str(h.get("odds") or "").strip(),
                    "タイム": str(h.get("time") or "").strip(),
                    "上り3F": str(h.get("agari") or "").strip(),
                    "勝因・敗因ショートメモ": str(h.get("short_memo") or "").strip(),
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
                    "レース名": race_title,
                    "年": extract_year_from_race_name(race_title)
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
        st.error(f"⚠️ 解析構造のデータ変換中にエラーが発生しました: {e}")

    if not all_parsed_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_parsed_rows)
    return df


def analyze_data_with_gemini(
    api_key,
    active_rules,
    text_group1,
    parts_group1,
    text_group2,
    parts_group2,
    text_group3,
    parts_group3,
    text_group4,
    parts_group4,
    text_group5,
    model_name,
):
    client = genai.Client(api_key=api_key)

    json_prompt = f"""{active_rules}

【★レース名・グレードの厳格特定＆適合ルール（絶対厳守）】
1. 添付された出馬表・馬柱データから、「開催日（西暦8桁 YYYYMMDD）」「正確なレース名」「実際のレースグレード（G1, Jpn1, G2, Jpn2, G3, Jpn3, L, OP, 3歳以上1勝クラス等）」を正確に検知してください。
2. 上記で適用指示された評価ルールに基づき評価を行いますが、実際のレースデータがG1/Jpn1以外のグレード（例: G2, G3, OP, 条件戦など）である場合、G1専用の評価基準や表記を誤って全適用してはいけません。実際のレースのグレードに完全に合致させた出力を行ってください。
3. `race_name` は必ず以下のフォーマットで生成・出力してください！

フォーマット： YYYYMMDD_レース名_グレード
（例：20261007_ジャパンダートクラシック_Jpn1）
（例：20261011_毎日王冠_G2）
（例：20261025_菊花賞_G1）
（例：20261012_東京11Rペルセウスステークス_OP）

【★レース質 ＆ 展開予想シミュレーションの必須生成指示】
ルール仕様に基づき、本レースの『レース質（瞬発力/持続力/消耗戦/加速戦）』および『展開予想（ペース・脚質位置取り・ハナ主張・中盤隊列・直線の攻防・勝ち馬の決定打）』を臨場感ある文章で詳細に作成し、`race_quality_and_tenkai` フィールドに出力してください。

【最重要・出走馬の確定判定指示】
添付されているテキストデータおよびスクショ画像/PDFから、今回のレースの【本物の出走馬一覧】を視覚的にも確認して抽出してください。

★【過去データ馬の絶対除外規則】：
資料内に「過去データ」「傾向」などの文脈で含まれている過去の馬は【今回の出走馬ではありません】！絶対に出力に含めないでください！

★【今回の本物出走馬の絶対条件】：
・今回対象レースの「確定出馬表（メイン馬柱スクショまたは確定データ）」に載っている馬です。
・馬番が 1 から順番に最後の馬番まで（1, 2, 3...）連続して並んでいる出走馬【全頭】を抽出してください。

★【印の絶対排他規則】：
各馬に対し、「軸」「ヒモ」「注」「切り」のいずれか【必ず1つだけ】に「〇」を付けてください。同一の馬に2つ以上の「〇」を重複させることは厳禁です。

★【参考グループ：プロ予想・YouTube・Web参考URLのクロスチェック規則】：
参考グループが含まれている場合は、プロ陣営が本命・穴馬として推奨している馬のコメントや理由を分析に組み込み、総合スコアや『メモ』列の詳細根拠に補足も含めて反映してください！

【推奨券種・買い目フォーメーション表記の最重要ルール】
買い目に出力する【馬番の数字】は、必ず ①、②、③、④、⑤ ... ⑱ のような【丸囲み数字】で出力してください！

=== 【グループ1：テキスト・スクショ・PDFデータ（出馬表・近5走・血統）】 ===
{text_group1}

=== 【グループ2：競馬ブックデータ（スクショ画像/PDFデータ/調教）】 ===
{text_group2}

=== 【グループ3：前日傾向・当日の馬場情報データ】 ===
{text_group3}

=== 【グループ4：その他各種追加データ（テキスト・CSV・PDF・画像）】 ===
{text_group4}

=== 【グループ5：プロ予想・YouTube字幕・Web参考URL抽出データ】 ===
{text_group5}

【出力形式】
以下のJSON形式のみを出力してください。

{{
  "race_name": "必ず YYYYMMDD_レース名_グレード 形式（例：20261011_毎日王冠_G2）",
  "confidence": "軸馬信頼度判定（例：S (鉄板軸) / A (有力軸) / B (波乱含み)）",
  "risk_level": "波乱度判定（例：★☆☆ (本命堅調) / ★★☆ (中波乱警戒) / ★★★ (大波乱混戦)）",
  "race_quality_and_tenkai": "🏁 【対象レース名】レース質 ＆ 展開予想シミュレーション\\n【レース質：持続力戦】\\n...\\n\\n【展開予想】\\nペース：ミドルペース\\n逃げ：①...\\n...",
  "recommended_tickets": [
    "【単勝】 ⑤ （馬名）",
    "【馬連 軸1頭流し】 ⑤ ＝ ①, ②, ⑯, ⑰",
    "【3連複 フォーメーション】 ⑤ － ①, ②, ⑯ － ①, ②, ⑧, ⑨, ⑪, ⑯, ⑰"
  ],
  "horses": [
    {{
      "horse_num": 1,
      "horse_name": "メイン出馬表に存在する正確な馬名",
      "pop": "予想人気",
      "total_score": 85,
      "eval": "評価ランク（S, A+, A, B+, B, C等）",
      "score_shubahyou": 85,
      "score_kettou": 85,
      "score_choukyou": 85,
      "score_kin5so": 85,
      "score_tenkai": 85,
      "score_baba": 85,
      "jiku": "軸なら〇、違えば空文字",
      "himo": "ヒモなら〇、違えば空文字",
      "chu": "注なら〇、違えば空文字",
      "kiri": "切りなら〇、違えば空文字",
      "memo": "本命理由・血統・近5走・展開相性・プロ推奨理由などの詳細分析メモ"
    }}
  ]
}}
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
                    raise Exception(
                        "⚠️ Googleサーバーが一時的に混雑しています。15秒ほど置いて再度実行ボタンを押してください。"
                    )
            elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                raise Exception(
                    "⚠️ 本日の無料枠上限に達しました。別アカウントのAPIキーをご使用いただくか明日までお待ちください。"
                )
            else:
                raise e


# --------------------------------------------------
# 🔄 直前追加データ（パドック・馬体重）再評価＆微調整ロジック
# --------------------------------------------------

def reevaluate_race_data_with_gemini(api_key, active_rules, current_df, add_text, add_media_parts, model_name):
    """既存の評価データ＋直前追加情報（パドック・馬体重）を統合し、見解・買い目・スコアの修正／現状維持を自動判定"""
    client = genai.Client(api_key=api_key)

    race_title = current_df["レース名"].iloc[0] if "レース名" in current_df.columns else "対象レース"
    current_tenkai = current_df["レース質展開予想"].iloc[0] if "レース質展開予想" in current_df.columns else ""
    current_tickets = current_df["推奨買い目"].iloc[0] if "推奨買い目" in current_df.columns else ""
    
    cols_horses = [c for c in ["馬番", "馬名", "総合スコア", "評価", "予想人気", "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点", "軸", "ヒモ", "注", "切り", "メモ"] if c in current_df.columns]
    current_horses_str = current_df[cols_horses].to_string(index=False)

    reeval_prompt = f"""{active_rules}

【★評価済みレースの直前追加データ再検証・見解/買い目修正＆微調整プロンプト】
あなたは競馬プロ解析AI「ウマエル」です。
事前に解析・算出済みの【現在のレース評価データ・展開見解・買い目】に対し、直前に届いた【追加情報（パドック気配、馬体重増減、直前馬場、ニュース、メモ、画像等）】を統合解析し、評価スコア・展開見解・推奨買い目の修正または現状維持を判定してください。

【現在のレース全頭評価データ】:
{current_horses_str}

【現在の展開見解（レース質＆展開予想）】:
{current_tenkai}

【現在の推奨買い目】:
{current_tickets}

【直前に届いた追加データ（テキスト・メモ）】:
{add_text}

【判定・出力ルール（厳格厳守）】:
1. 追加データを精査し、既存の「スコア・印」「レース展開見解」「推奨買い目」に変更を加えるべきか慎重に判断してください。
2. **【評価・見解・買い目に変化がない場合】**:
   - `has_changes` を `false` に設定してください。
   - `change_summary` に「追加情報を解析しましたが、現在の評価・総合スコアに変更はありません（現状維持）。」と明記してください。
   - `race_quality_and_tenkai` および `recommended_tickets` には現在の内容をそのまま格納してください。
   - `horses` には現在の評価データをそのまま格納してください。
3. **【評価・見解・買い目に修正・変化がある場合】**:
   - `has_changes` を `true` に設定してください。
   - `change_summary` に「どの馬の評価・スコアをなぜ微調整したか（変更前後のスコア比較含む）、展開見解や買い目をどう変更したか」の詳細理由を明確に記述してください。
   - `race_quality_and_tenkai` には修正後の最新レース展開見解を格納してください。
   - `recommended_tickets` には修正後の最新推奨買い目リスト（丸囲み数字 ①, ②... を使用）を格納してください。
   - `horses` には修正後の全出走馬データを格納してください。

【出力形式】:
以下のJSON形式のみを出力してください。

{{
  "has_changes": true または false,
  "change_summary": "現状維持の理由 または 修正・微調整されたポイントの詳細解説",
  "race_name": "{race_title}",
  "confidence": "軸馬信頼度",
  "risk_level": "波乱度判定",
  "race_quality_and_tenkai": "修正後（または維持）のレース質＆展開予想シミュレーション文章",
  "recommended_tickets": [
    "修正後（または維持）の推奨買い目1",
    "修正後（または維持）の推奨買い目2"
  ],
  "horses": [
    {{
      "horse_num": 1,
      "horse_name": "馬名",
      "pop": "予想人気",
      "total_score": 85,
      "eval": "評価ランク",
      "score_shubahyou": 85,
      "score_kettou": 85,
      "score_choukyou": 85,
      "score_kin5so": 85,
      "score_tenkai": 85,
      "score_baba": 85,
      "jiku": "〇または空文字",
      "himo": "〇または空文字",
      "chu": "〇または空文字",
      "kiri": "〇または空文字",
      "memo": "詳細分析メモ（追加データ反映版）"
    }}
  ]
}}
"""

    contents = [reeval_prompt]
    contents.extend(add_media_parts)

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            seed=42,
        ),
    )
    return response.text


def render_re_evaluation_section(current_df, active_rules, selected_model):
    """評価画面内に直前追加データによる再評価・微調整UIを描画"""
    race_name_val = current_df['レース名'].iloc[0] if "レース名" in current_df.columns else "対象レース"
    
    with st.expander("🔄 【直前追加データ】パドック・馬体重・直前情報による再評価・見解/買い目修正", expanded=False):
        st.write("パドック気配、馬体重発表、直前馬場状態などの追加データを投入して、スコア・印だけでなく**「展開見解」**や**「推奨買い目」**も含めて再検証・微調整できます。")

        col_add1, col_add2 = st.columns([1.5, 1])

        with col_add1:
            add_files = st.file_uploader(
                "📂 追加資料・スクショ・テキスト (.txt / .pdf / .png / .jpg 一括添付可)",
                type=["txt", "pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key=f"reeval_files_{race_name_val}",
            )
        with col_add2:
            add_memo = st.text_area(
                "✏️ 直前メモ・馬体重・パドック手入力",
                height=100,
                placeholder="例：①番パドック気配絶好、馬体重+8kg太目感なし。馬場は内伸び顕著のため逃げ・内枠を上方修正。",
                key=f"reeval_memo_{race_name_val}",
            )

        if st.button("🚀 直前追加データを含めて再評価・見解/買い目修正を実行", use_container_width=True):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key を設定してください！")
            elif not add_files and not add_memo.strip():
                st.warning("⚠️ 追加するファイルまたはメモテキストを入力してください！")
            else:
                with st.spinner("🏇 直前追加データと既存評価を統合解析し、見解・買い目・スコアを再検証中..."):
                    try:
                        add_text_content, add_media_parts = prepare_file_parts(add_files, pdf_page_option="全ページ")
                        combined_add_text = add_text_content + "\n" + add_memo.strip()

                        raw_json = reevaluate_race_data_with_gemini(
                            active_key, active_rules, current_df, combined_add_text, add_media_parts, selected_model
                        )

                        clean_json = raw_json.strip()
                        if "```json" in clean_json:
                            clean_json = clean_json.split("```json")[1].split("```")[0].strip()
                        elif "```" in clean_json:
                            clean_json = clean_json.split("```")[1].split("```")[0].strip()

                        eval_result = json.loads(clean_json)
                        has_changes = eval_result.get("has_changes", False)
                        summary_msg = eval_result.get("change_summary", "")

                        if not has_changes:
                            st.info(f"ℹ️ **【現状維持】** {summary_msg}")
                        else:
                            st.success(f"✨ **【評価・見解・買い目に修正あり】**\n\n{summary_msg}")
                            
                            updated_df = parse_json_ai_output(raw_json)
                            if not updated_df.empty:
                                st.session_state["temp_updated_df"] = updated_df
                                
                                st.markdown("#### 📌 修正後の展開見解・買い目プレビュー")
                                if "レース質展開予想" in updated_df.columns and str(updated_df["レース質展開予想"].iloc[0]).strip():
                                    st.caption("🏁 **【修正後のレース質・展開予想】**")
                                    st.info(updated_df["レース質展開予想"].iloc[0])
                                
                                if "推奨買い目" in updated_df.columns and str(updated_df["推奨買い目"].iloc[0]).strip():
                                    st.caption("💡 **【修正後の推奨買い目】**")
                                    raw_tkts = updated_df["推奨買い目"].iloc[0]
                                    try:
                                        tkts = json.loads(raw_tkts)
                                        for tk in tkts:
                                            st.write(f"・{tk}")
                                    except Exception:
                                        st.write(raw_tkts)

                                st.markdown("#### 📊 修正後の馬別スコア一覧")
                                st.dataframe(
                                    updated_df[["馬番", "馬名", "総合スコア", "評価", "予想人気", "軸", "ヒモ", "注", "切り", "メモ"]],
                                    use_container_width=True
                                )

                                if st.button("💾 この微調整後の評価データで上書き保存する", type="primary"):
                                    save_to_db(updated_df)
                                    st.session_state["analyzed_df"] = updated_df
                                    st.success("🎉 データベースの評価・見解・買い目データを最新の修正版で更新しました！")
                                    st.rerun()

                    except Exception as e:
                        st.error(f"❌ 再評価処理中にエラーが発生しました: {e}")


# --------------------------------------------------
# 🏇 現地観戦用（全12R・勝負5R厳選）ヘルパー関数
# --------------------------------------------------

def parse_json_selected_5r(result_text):
    try:
        clean_text = result_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()
        return json.loads(clean_text)
    except Exception as e:
        st.error(f"⚠️ JSONパースエラー: {e}")
        return None


def analyze_12r_and_select_top5(api_key, rules_text, draft_races_list, model_name):
    client = genai.Client(api_key=api_key)

    all_races_payload_text = ""
    media_parts_all = []

    for r_name in draft_races_list:
        t1, p1, t2, p2, t3, p3, t4, p4, t5, _ = load_draft_data(r_name)
        combined_r_text = f"\n\n=========================================\n【対象レースデータ: {r_name}】\n=========================================\n"
        combined_r_text += f"{t1}\n{t2}\n{t3}\n{t4}\n{t5}"
        all_races_payload_text += combined_r_text
        media_parts_all.extend(p1 + p2 + p3 + p4)

    selection_prompt = f"""{rules_text}

【★現地観戦用：全12Rから勝負5R厳選＆全頭分析プロンプト】
あなたは競馬プロ解析AI「ウマエル」です。
提供された本日の全12レース（および裏開催重賞）のデータから、本日勝負すべき【厳選5レース】を選出し、その5レースについて詳細解析を出力してください。

【厳選5レースの選定絶対条件】
1. **メインレース（11RまたはG1/G2/G3/Jpn1等の重賞）は【必ず（マストで）】選出に含めること。**
2. 残りの4レースは、データ・展開・オッズ乖離から「軸馬の信頼度が高い」「穴馬の妙味が大きい」「勝負期待値が高い」レースを厳選すること。
3. 条件を満たせば、裏開催の重賞レースを選出対象に含めてもよい。

【出力形式】
必ず以下のJSONフォーマットのみを出力してください。

{{
  "selected_races_summary": [
    {{
      "race_name": "選出されたレース名（例: 20261011_東京11R毎日王冠_G2）",
      "is_main": true,
      "reason": "選定理由（例: 本日のメイン重賞かつ軸信頼度Sのためマスト選出）",
      "confidence": "S (鉄板軸) / A (有力軸) / B (波乱含み)",
      "risk_level": "★☆☆ (本命堅調) / ★★☆ (中波乱警戒) / ★★★ (大波乱混戦)"
    }}
  ],
  "races_detail": [
    {{
      "race_name": "20261011_東京11R毎日王冠_G2",
      "confidence": "S (鉄板軸)",
      "risk_level": "★☆☆ (本命堅調)",
      "race_quality_and_tenkai": "🏁 レース質 ＆ 展開予想シミュレーション...",
      "recommended_tickets": [
        "【単勝】 ⑤ （馬名）",
        "【馬連 軸1頭流し】 ⑤ ＝ ①, ②, ⑯, ⑰"
      ],
      "horses": [
        {{
          "horse_num": 1,
          "horse_name": "馬名",
          "pop": "1",
          "total_score": 92,
          "eval": "S",
          "score_shubahyou": 90,
          "score_kettou": 92,
          "score_choukyou": 95,
          "score_kin5so": 90,
          "score_tenkai": 90,
          "score_baba": 92,
          "jiku": "〇",
          "himo": "",
          "chu": "",
          "kiri": "",
          "memo": "詳細分析メモ"
        }}
      ]
    }}
  ]
}}
"""

    contents = [selection_prompt + "\n\n" + all_races_payload_text]
    contents.extend(media_parts_all[:15])

    response = client.models.generate_content(
        model=model_name,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.0,
            seed=42,
        ),
    )
    return response.text


def render_field_mode_ui(api_key, active_selected_rule, selected_model):
    st.subheader("🏇 現地観戦用モード：全12Rから勝負5Rを厳選分析")
    st.caption("当日の全12レース（＋裏重賞）を蓄積し、メインレース必須＋勝負期待値の高い4Rを一括抽出します。")

    draft_list = list_draft_races()

    col_left, col_right = st.columns([1, 1.2])

    with col_left:
        st.markdown("### 📥 1. 当日レースデータの蓄積状況")
        if draft_list:
            st.success(f"現在 **{len(draft_list)} レース分** の下書きデータが保存されています。")
            with st.expander("📂 保存中レース一覧を表示", expanded=True):
                for r_item in draft_list:
                    st.write(f"・`{r_item}`")
        else:
            st.warning("⚠️ まだ下書き保存されたレースデータがありません。")
            st.info("💡 「📋 レース分析・予想」の【段階的に下書き保存】機能を使って、1R〜12Rのデータを保存してください。")

    with col_right:
        st.markdown("### 🔥 2. 勝負レース5R一括判定")
        st.write("蓄積されたレースデータの中からAIが**「メインレース＋勝負度上位4R」**を自動分析・選出します。")
        
        if st.button("🚀 本日の勝負5R（メインR＋厳選4R）を一括判定実行", use_container_width=True, type="primary"):
            if not api_key:
                st.error("⚠️ サイドバーで Gemini API Key を設定してください！")
            elif len(draft_list) < 1:
                st.warning("⚠️ 下書き保存されたレースデータがありません。")
            else:
                with st.spinner("🏇 全レースの期待値・波乱度を分析し、勝負5レースを厳選算出中..."):
                    try:
                        raw_json = analyze_12r_and_select_top5(
                            api_key, active_selected_rule, draft_list, selected_model
                        )
                        parsed_data = parse_json_selected_5r(raw_json)
                        if parsed_data:
                            st.session_state["field_mode_result"] = parsed_data
                            st.success("🎉 勝負5レースの厳選・詳細分析が完了しました！")
                            st.rerun()
                        else:
                            st.error("❌ 解析データの生成に失敗しました。再度実行してください。")
                    except Exception as e:
                        st.error(f"❌ 解析処理中にエラーが発生しました: {e}")

    if "field_mode_result" in st.session_state and st.session_state["field_mode_result"]:
        res_data = st.session_state["field_mode_result"]
        st.divider()
        st.markdown("## 🎯 本日のウマエル厳選勝負5レース")

        summaries = res_data.get("selected_races_summary", [])
        sum_cols = st.columns(len(summaries) if summaries else 1)
        for idx, s in enumerate(summaries):
            with sum_cols[idx % len(sum_cols)]:
                badge = "⭐ [メインマスト]" if s.get("is_main") else f"🔥 勝負R {idx+1}"
                st.markdown(f"#### {badge}")
                st.markdown(f"**{s.get('race_name')}**")
                st.caption(f"信頼度: {s.get('confidence')} | 波乱度: {s.get('risk_level')}")
                st.write(f"💡 {s.get('reason')}")

        st.divider()

        details = res_data.get("races_detail", [])
        if details:
            tab_titles = [f"🏇 {d.get('race_name', f'R{i+1}')}" for i, d in enumerate(details)]
            tabs = st.tabs(tab_titles)

            for idx, tab in enumerate(tabs):
                with tab:
                    r_detail = details[idx]
                    h_list = r_detail.get("horses", [])
                    if h_list:
                        df_r = pd.DataFrame(h_list)
                        df_r["レース名"] = r_detail.get("race_name", "")
                        df_r["信頼度"] = r_detail.get("confidence", "")
                        df_r["波乱度"] = r_detail.get("risk_level", "")
                        df_r["レース質展開予想"] = r_detail.get("race_quality_and_tenkai", "")
                        df_r["推奨買い目"] = json.dumps(r_detail.get("recommended_tickets", []), ensure_ascii=False)
                        
                        save_to_db(df_r)
                        render_race_evaluation_view(df_r, is_viewer_mode=False, show_chat=True)


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
# 📊 レース評価・表示メインコンポーネント
# --------------------------------------------------

def render_race_evaluation_view(df, is_viewer_mode=False, show_chat=True):
    if df is None or df.empty:
        st.warning("⚠️ 表示できる解析データがありません。再度分析を実行してください。")
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
        if h_score >= 92:
            jiku_rank = "S (鉄板軸)"
        elif h_score >= 87:
            jiku_rank = "A (有力軸)"
        else:
            jiku_rank = "B (波乱含み)"

    if "波乱度" in df.columns and str(df["波乱度"].iloc[0]).strip():
        risk_level = str(df["波乱度"].iloc[0])
    else:
        top5_diff = (
            (
                safe_int(view_df.iloc[0]["総合スコア"])
                - safe_int(view_df.iloc[4]["総合スコア"])
            )
            if len(view_df) >= 5
            else 0
        )
        if top5_diff >= 10:
            risk_level = "★☆☆ (本命堅調)"
        elif top5_diff >= 5:
            risk_level = "★★☆ (中波乱警戒)"
        else:
            risk_level = "★★★ (大波乱混戦)"

    df_copy = view_df.copy()
    other_horses = df_copy.iloc[1:].copy() if len(df_copy) > 1 else pd.DataFrame()

    if not other_horses.empty:
        other_horses["pop_num"] = (
            pd.to_numeric(other_horses["予想人気"], errors="coerce")
            .fillna(99)
            .astype(int)
        )
        other_horses["score_num"] = (
            pd.to_numeric(other_horses["総合スコア"], errors="coerce")
            .fillna(0)
            .astype(int)
        )
        other_horses["eval_clean"] = (
            other_horses["評価"].astype(str).str.strip().str.upper()
        )
        other_horses["eval_rank"] = range(2, len(other_horses) + 2)
        other_horses["gap"] = (
            other_horses["pop_num"] - other_horses["eval_rank"]
        )

        ana_filtered = other_horses[
            (other_horses["score_num"] >= 75) & (other_horses["eval_clean"] != "C")
        ]

        if not ana_filtered.empty:
            best_ana = ana_filtered.sort_values(
                by=["gap", "eval_rank"], ascending=[False, True]
            ).iloc[0]
            ana_horse = best_ana
        else:
            non_c_horses = other_horses[other_horses["eval_clean"] != "C"]
            if not non_c_horses.empty:
                ana_horse = non_c_horses.sort_values(
                    by=["gap", "eval_rank"], ascending=[False, True]
                ).iloc[0]
            else:
                ana_horse = other_horses.iloc[0]
    else:
        ana_horse = honmei_horse

    h_num = str(safe_int(honmei_horse["馬番"], default=1)) if honmei_horse is not None and "馬番" in honmei_horse else "1"
    h_name = str(honmei_horse["馬名"]) if honmei_horse is not None and "馬名" in honmei_horse else "本命馬"

    aite_rows = view_df.iloc[1:6] if len(view_df) > 1 else view_df
    aite_nums = (
        [
            str(safe_int(r["馬番"], default=i + 1))
            for i, (_, r) in enumerate(aite_rows.iterrows())
        ]
        if "馬番" in view_df.columns
        else ["1", "2", "3"]
    )
    aite_str = ", ".join(aite_nums)

    raw_tickets = df["推奨買い目"].iloc[0] if "推奨買い目" in df.columns else None
    tickets_list = []
    if raw_tickets:
        try:
            tickets_list = json.loads(raw_tickets)
        except Exception:
            pass

    if not tickets_list:
        tickets_list = [
            f"【単勝・複勝】 {h_num} （{h_name}）",
            f"【馬連・ワイド 軸1頭流し】 {h_num} ＝ {aite_str}",
            f"【3連複 軸1頭流し】 {h_num} － {aite_str}",
        ]

    encoded_race = urllib.parse.quote(str(race_title))
    share_url = f"https://umael-pro.streamlit.app/?mode=share&race={encoded_race}"

    if not is_viewer_mode:
        st.info("🔗 **レース名入り評価結果 専用共有URL（コピーして共有できます）:**")
        st.code(share_url, language="text")

        # 直前追加データによる再評価・見解/買い目修正UIの描画（管理画面でのみ表示）
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
        render_re_evaluation_section(df, active_selected_rule, "gemini-3.8-flash")

    # サマリー本文描画処理
    def render_summary_body():
        st.markdown(
            f"<h2 style='text-align: center; color: #f39c12; margin-bottom:20px;'>🏇 {race_title} 🏇</h2>",
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="risk-card">
                <div class="card-title" style="font-size:1.2rem; margin-bottom:10px;">🔥 レース展開 ＆ 波乱度判定</div>
                <div style="display:flex; justify-content:space-around; align-items:center; flex-wrap:wrap; gap:15px;">
                    <div style="flex:1; min-width:180px; text-align:center;">
                        <span style="color:#aaa; font-size:0.9rem;">軸馬信頼度</span><br>
                        <b style="font-size:1.5rem; color:#00f0ff;">{jiku_rank}</b>
                    </div>
                    <div style="flex:1; min-width:180px; text-align:center;">
                        <span style="color:#aaa; font-size:0.9rem;">波乱度レベル</span><br>
                        <b style="font-size:1.5rem; color:#ffd700;">{risk_level}</b>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.write("")

        col_left, col_right = st.columns([1, 1.8])

        with col_left:
            if honmei_horse is not None:
                h_pop = honmei_horse.get("予想人気", "-")
                st.markdown(
                    f"""
                        <div class="honmei-card">
                            <div class="card-title">◎ 本命推奨馬</div>
                            <div class="card-horse-name">【{h_num}】{h_name}</div>
                            <div style="display:flex; justify-content:space-around; margin-top:10px;">
                                <div style="flex:1; text-align:center;">
                                    <span style="color:#aaa; font-size:0.85rem;">想定人気</span><br>
                                    <b style="font-size:1.3rem; color:#fff;">{h_pop} 人気</b>
                                </div>
                                <div style="flex:1; text-align:center;">
                                    <span style="color:#aaa; font-size:0.85rem;">指数合計値</span><br>
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
                a_pop = ana_horse.get("予想人気", "-")
                a_score = safe_int(ana_horse.get("総合スコア", 0))
                st.markdown(
                    f"""
                        <div class="anaba-card">
                            <div class="card-title">⚠ 注目波乱馬（穴馬）</div>
                            <div class="card-horse-name">【{a_num}】{a_name}</div>
                            <div style="display:flex; justify-content:space-around; margin-top:10px;">
                                <div style="flex:1; text-align:center;">
                                    <span style="color:#aaa; font-size:0.85rem;">想定人気</span><br>
                                    <b style="font-size:1.3rem; color:#fff;">{a_pop} 人気</b>
                                </div>
                                <div style="flex:1; text-align:center;">
                                    <span style="color:#aaa; font-size:0.85rem;">指数合計値</span><br>
                                    <b class="card-val-red">{a_score}</b>
                                </div>
                            </div>
                        </div>
                        """,
                    unsafe_allow_html=True,
                )

        with col_right:
            st.subheader("📊 総合評価順位一覧")

            sub_cols = [
                c
                for c in ["馬番", "馬名", "予想人気", "総合スコア"]
                if c in view_df.columns
            ]
            disp_df = view_df[sub_cols].copy()
            if "馬番" in disp_df.columns:
                disp_df["馬番"] = (
                    pd.to_numeric(disp_df["馬番"], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )
            if "総合スコア" in disp_df.columns:
                disp_df["総合スコア"] = (
                    pd.to_numeric(disp_df["総合スコア"], errors="coerce")
                    .fillna(0)
                    .astype(int)
                )

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

            top_height = min(300, (len(top_group) + 1) * 35 + 38)
            st.write("🟢 **上位推奨グループ（軸・相手筆頭）**")
            st.dataframe(
                top_group,
                column_config=col_config_sum,
                use_container_width=True,
                height=top_height,
                hide_index=True,
            )

            if not sub_group.empty:
                sub_height = min(400, (len(sub_group) + 1) * 35 + 38)
                st.write("🟡 **相手紐・穴馬グループ**")
                st.dataframe(
                    sub_group,
                    column_config=col_config_sum,
                    use_container_width=True,
                    height=sub_height,
                    hide_index=True,
                )

        st.divider()

        if "レース質展開予想" in df.columns and str(
            df["レース質展開予想"].iloc[0]
        ).strip():
            tenkai_text = str(df["レース質展開予想"].iloc[0]).strip()
            st.subheader("🏁 レース質 ＆ 展開予想シミュレーション")
            st.markdown(
                f"""
                <div style="background-color: #0f172a; border: 2px solid #3b82f6; border-radius: 10px; padding: 18px; margin-bottom: 25px; white-space: pre-wrap; line-height: 1.7; color: #f1f5f9; font-size: 1.0rem; box-shadow: 0 0 15px rgba(59, 130, 246, 0.3);">
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

    if is_viewer_mode:
        # ★共有モード（ビューアー表示）の場合は買い目描画で即座にピタッと終了！チャット・詳細データ表等は完全非表示
        render_summary_body()
        return

    # 管理・通常閲覧モード時のタブ構成
    view_tab1, view_tab2 = st.tabs(
        ["🌟 推奨評価上位サマリー", "📊 詳細全データ表（評価順）"]
    )

    with view_tab1:
        render_summary_body()

    with view_tab2:
        st.subheader(f"📊 {race_title} 詳細全データ表（評価順）")
        st.info(
            "💡 **※「メモ（詳細分析）」等の各セルは、枠内をダブルクリック（スマホはダブルタップ）すると全文を拡大表示・コピーできます！**"
        )

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
            "メモ": st.column_config.TextColumn(
                "メモ（詳細分析）", width="large"
            ),
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


# --------------------------------------------------
# 🎨 デザインCSS定義
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

    .main { background-color: #080a0f; }
    h1, h2, h3 { color: #f39c12 !important; font-weight: bold; }

    div[data-testid="stDataFrame"] div[role="progressbar"] {
        height: 14px !important;
        border-radius: 4px !important;
        background-color: #1e2638 !important;
    }
    div[data-testid="stDataFrame"] div[role="progressbar"] > div {
        background: #0bce0e !important;
        border-radius: 4px !important;
    }
    
    /* アクションボタン オレンジ系統一 */
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
    
    .risk-card {
        background: linear-gradient(135deg, #0f2027 0%, #203a43 50%, #2c5364 100%);
        border: 2px solid #00f0ff; border-radius: 10px; padding: 18px; text-align: center; margin-bottom: 15px; box-shadow: 0 0 15px rgba(0, 240, 255, 0.3);
    }
    .honmei-card {
        background: linear-gradient(135deg, #2b1e00 0%, #4a3500 100%);
        border: 2px solid #f39c12; border-radius: 10px; padding: 15px; margin-bottom: 15px; box-shadow: 0 0 15px rgba(243, 156, 18, 0.4);
    }
    .anaba-card {
        background: linear-gradient(135deg, #3a0007 0%, #5c000b 100%);
        border: 2px solid #e74c3c; border-radius: 10px; padding: 15px; margin-bottom: 15px; box-shadow: 0 0 15px rgba(231, 76, 60, 0.4);
    }
    .kaime-card-item {
        background: #111622; border: 2px solid #ffd700; border-left: 6px solid #ffd700; border-radius: 8px; padding: 12px 18px; margin-bottom: 12px; font-size: 1.15rem; color: #ffffff; box-shadow: 0 0 10px rgba(255, 215, 0, 0.2);
    }
    .recap-box {
        background-color: #0d1117;
        border: 2px solid #10b981;
        border-radius: 10px;
        padding: 20px;
        margin-bottom: 25px;
        white-space: pre-wrap;
        line-height: 1.8;
        color: #e6edf3;
        font-size: 1.0rem;
        box-shadow: 0 0 15px rgba(16, 185, 129, 0.25);
    }
    .card-title { font-size: 1.05rem; font-weight: bold; color: #ffffff; }
    
    .card-horse-name { 
        font-size: 1.4rem !important; 
        font-weight: bold; 
        color: #ffffff; 
        margin: 6px 0;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    
    .card-val-gold { font-size: 2.0rem; font-weight: bold; color: #f39c12; }
    .card-val-red { font-size: 2.0rem; font-weight: bold; color: #ff4d4d; }
</style>
""",
    unsafe_allow_html=True,
)


# --------------------------------------------------
# 🧭 URLパラメーター共有ロジック
# --------------------------------------------------

query_params = st.query_params
mode_param = query_params.get("mode", "")
race_param = query_params.get("race", "")

if mode_param == "share" and race_param:
    st.markdown("""
    <style>
        [data-testid="stSidebar"] { display: none !important; }
        div[data-testid="stSidebarCollapseButton"] { display: none !important; }
        .main .block-container { max-width: 100% !important; padding-top: 1rem !important; }
    </style>
    """, unsafe_allow_html=True)

    db_df = load_db(selected_year="全期間")
    if not db_df.empty and "レース名" in db_df.columns:
        matched_df = db_df[db_df["レース名"].astype(str) == str(race_param)]
        if not matched_df.empty:
            render_race_evaluation_view(matched_df, is_viewer_mode=True, show_chat=False)
        else:
            st.error(f"⚠️ レース「{race_param}」の解析データは見つかりませんでした。")
    else:
        st.error("⚠️ データベースに予想データが登録されていません。")

    st.stop()

elif "race" in query_params and not mode_param:
    target_race_param = query_params["race"]
    db_df = load_db(selected_year="全期間")

    if not db_df.empty and "レース名" in db_df.columns:
        matched_df = db_df[db_df["レース名"].astype(str) == str(target_race_param)]
        if not matched_df.empty:
            render_race_evaluation_view(matched_df, is_viewer_mode=True, show_chat=False)
        else:
            st.error(
                f"⚠️ レース「{target_race_param}」の解析データは見つかりませんでした。"
            )
    else:
        st.error("⚠️ データベースに予想データが登録されていません。")

    st.stop()


# --------------------------------------------------
# 🧭 メインUI構成 ＆ ナビゲーション
# --------------------------------------------------

if "g1_text_val" not in st.session_state:
    st.session_state["g1_text_val"] = load_saved_rules(
        RULE_G1_FILE, DEFAULT_G1_RULES
    )

if "gen_text_val" not in st.session_state:
    st.session_state["gen_text_val"] = load_saved_rules(
        RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES
    )

if "hok_text_val" not in st.session_state:
    st.session_state["hok_text_val"] = load_saved_rules(
        RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES
    )

if "uploader_key_ver" not in st.session_state:
    st.session_state["uploader_key_ver"] = 0

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

st.title("ウマエルプロ Ver 3.0")
st.caption(
    "馬柱・血統・予想オッズ・競馬ブック・馬場情報 一括AI解析＆Webプール＆現地観戦厳選"
)

with st.sidebar:
    st.header("🧭 ナビゲーション")

    selected_menu = st.radio(
        "移動する機能を選択してください：",
        [
            "📋 レース分析・予想",
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
            help="現行推奨モデル: gemini-3.8-flash",
        )
        st.caption("🔑 st.secrets / APIキー自動設定機能オン")
        st.caption("📱 スマホ表示対応モード動作中")


# --------------------------------------------------
# 📋 1. レース分析・予想 メニュー
# --------------------------------------------------

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

    if "G1専用" in rule_type:
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
        st.info("💡 現在 【 🏆 G1専用ルール 】 が選択されています。")
    elif "北海道" in rule_type:
        active_selected_rule = load_saved_rules(
            RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES
        )
        st.info("💡 現在 【 🌾 北海道・洋芝専用ルール 】 が選択されています。")
    else:
        active_selected_rule = load_saved_rules(
            RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES
        )
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
    st.subheader("📂 データのアップロード (.txt / .csv / .pdf / .png / .jpg / URL)")

    uploader_ver = st.session_state["uploader_key_ver"]

    col1, col2, col3, col4 = st.columns(4)

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

    with col3:
        files_group3 = st.file_uploader(
            "3. 当日・前日の傾向・馬場情報 (.txt / .csv / .pdf / .png / .jpg)",
            type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key=f"fg3_{uploader_ver}",
        )

    with col4:
        files_group4 = st.file_uploader(
            "4. その他各種データ (.txt / .csv / .pdf / .png / .jpg)",
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
                    not files_group1
                    and not files_group2
                    and not files_group3
                    and not files_group4
                    and not urls_group5_input.strip()
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
            if st.button(
                "🔥 蓄積された全データでAI一括解析を実行", use_container_width=True
            ):
                active_key = load_api_key()
                if not active_key:
                    st.error("⚠️ Gemini API Key が設定されていません。`st.secrets` またはシステム設定で入力してください！")
                else:
                    pdf_opt_val = (
                        "1ページ目のみ"
                        if "1ページ目のみ" in pdf_page_opt
                        else "全ページ"
                    )

                    target_draft = (
                        draft_race_name
                        if (
                            draft_race_name
                            and draft_choice
                            != "✨ 【新規レースとして保存（馬柱からレース名自動判定）】"
                        )
                        else ""
                    )
                    dt1, dp1, dt2, dp2, dt3, dp3, dt4, dp4, dt5, _ = (
                        load_draft_data(target_draft, pdf_page_option=pdf_opt_val)
                        if target_draft
                        else ("", [], "", [], "", [], "", [], "", [])
                    )

                    nt1, np1 = prepare_file_parts(
                        files_group1, pdf_page_option=pdf_opt_val
                    )
                    nt2, np2 = prepare_file_parts(
                        files_group2, pdf_page_option=pdf_opt_val
                    )
                    nt3, np3 = prepare_file_parts(
                        files_group3, pdf_page_option=pdf_opt_val
                    )
                    nt4, np4 = prepare_file_parts(
                        files_group4, pdf_page_option=pdf_opt_val
                    )
                    nt5 = process_multiple_urls(urls_group5_input)

                    comb_t1 = dt1 + "\n" + nt1
                    comb_p1 = dp1 + np1
                    comb_t2 = dt2 + "\n" + nt2
                    comb_p2 = dp2 + np2
                    comb_t3 = dt3 + "\n" + nt3
                    comb_p3 = dp3 + np3
                    comb_t4 = dt4 + "\n" + nt4
                    comb_p4 = dp4 + np4
                    comb_t5 = dt5 + "\n" + nt5

                    if (
                        not comb_t1.strip()
                        and not comb_t2.strip()
                        and not comb_t3.strip()
                        and not comb_t4.strip()
                        and not comb_p1
                        and not comb_p2
                        and not comb_p3
                        and not comb_p4
                    ):
                        st.warning(
                            "⚠️ 解析対象のデータが見つかりません。ファイルをアップロードするか、下書きデータを保存してください。"
                        )
                    else:
                        with st.spinner(
                            "🏇 馬柱・出馬表からレース名を自動取得しつつ、全データでAI一括解析中..."
                        ):
                            try:
                                result_text = analyze_data_with_gemini(
                                    active_key,
                                    active_selected_rule,
                                    comb_t1,
                                    comb_p1,
                                    comb_t2,
                                    comb_p2,
                                    comb_t3,
                                    comb_p3,
                                    comb_t4,
                                    comb_p4,
                                    comb_t5,
                                    selected_model,
                                )
                                df = parse_json_ai_output(result_text)
                                if not df.empty and "総合スコア" in df.columns:
                                    df["総合スコア"] = (
                                        pd.to_numeric(df["総合スコア"], errors="coerce")
                                        .fillna(0)
                                        .astype(int)
                                    )
                                    df = df.sort_values(
                                        by="総合スコア", ascending=False
                                    ).reset_index(drop=True)

                                    auto_race_title = (
                                        df["レース名"].iloc[0]
                                        if "レース名" in df.columns
                                        else "20261008_競馬解析_OP"
                                    )
                                    save_to_db(df)

                                    if target_draft:
                                        delete_draft(target_draft)
                                        if "selected_draft_race" in st.session_state:
                                            del st.session_state["selected_draft_race"]

                                    st.session_state["analyzed_df"] = df
                                    st.session_state["analysis_success_msg"] = (
                                        f"🎉 【{auto_race_title}】の自動解析が完了し、データベースに保存されました！"
                                    )
                                    st.rerun()
                                else:
                                    st.error(
                                        "⚠️ 解析結果から出走馬データを抽出できませんでした。"
                                    )
                            except Exception as e:
                                st.error(f"❌ 解析中にエラーが発生しました: {e}")

        with btn_col3:
            if st.button("🗑️ この下書きを削除", use_container_width=True):
                if draft_race_name and draft_race_name not in [
                    "✨ 【新規レースとして保存（馬柱からレース名自動判定）】",
                    "",
                ]:
                    with st.spinner("🗑️ 下書きデータを削除中..."):
                        delete_draft(draft_race_name)
                        if "selected_draft_race" in st.session_state:
                            del st.session_state["selected_draft_race"]
                        st.session_state["draft_toast_msg"] = ("success", f"🗑️ レース「{draft_race_name}」の下書きデータを削除しました！")
                        st.session_state.pop("analyzed_df", None)
                        st.rerun()

    else:
        if st.button("🔥 AI分析を実行する", use_container_width=True):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key が設定されていません。`st.secrets` またはシステム設定で入力してください！")
            elif (
                not files_group1
                and not files_group2
                and not files_group3
                and not files_group4
                and not urls_group5_input.strip()
            ):
                st.warning(
                    "⚠️ 解析するデータファイルまたはURLを1つ以上入力してください！"
                )
            else:
                with st.spinner(
                    "🏇 馬柱からレース名（YYYYMMDD_レース名_グレード）を自動取得して解析中..."
                ):
                    try:
                        pdf_opt_val = (
                            "1ページ目のみ"
                            if "1ページ目のみ" in pdf_page_opt
                            else "全ページ"
                        )

                        t1, p1 = prepare_file_parts(
                            files_group1, pdf_page_option=pdf_opt_val
                        )
                        t2, p2 = prepare_file_parts(
                            files_group2, pdf_page_option=pdf_opt_val
                        )
                        t3, p3 = prepare_file_parts(
                            files_group3, pdf_page_option=pdf_opt_val
                        )
                        t4, p4 = prepare_file_parts(
                            files_group4, pdf_page_option=pdf_opt_val
                        )
                        t5 = process_multiple_urls(urls_group5_input)

                        result_text = analyze_data_with_gemini(
                            active_key,
                            active_selected_rule,
                            t1,
                            p1,
                            t2,
                            p2,
                            t3,
                            p3,
                            t4,
                            p4,
                            t5,
                            selected_model,
                        )

                        df = parse_json_ai_output(result_text)

                        if not df.empty and "総合スコア" in df.columns:
                            df["総合スコア"] = (
                                pd.to_numeric(df["総合スコア"], errors="coerce")
                                .fillna(0)
                                .astype(int)
                            )
                            df = df.sort_values(
                                by="総合スコア", ascending=False
                            ).reset_index(drop=True)

                            auto_race_title = (
                                df["レース名"].iloc[0]
                                if "レース名" in df.columns
                                else "レース解析"
                            )
                            save_to_db(df)

                            st.session_state["analyzed_df"] = df
                            st.session_state["analysis_success_msg"] = (
                                f"🎉 【{auto_race_title}】の自動解析が完了し、データベースに保存されました！"
                            )
                            st.rerun()
                        else:
                            st.error(
                                "⚠️ アップロードされたデータから出走馬を検出できませんでした。"
                            )

                    except Exception as e:
                        st.error(f"❌ 解析中にエラーが発生しました:\n{e}")

    if (
        "analyzed_df" in st.session_state
        and not st.session_state["analyzed_df"].empty
    ):
        st.divider()
        if (
            "analysis_success_msg" in st.session_state
            and st.session_state["analysis_success_msg"]
        ):
            st.success(st.session_state["analysis_success_msg"])

        render_race_evaluation_view(
            st.session_state["analyzed_df"], is_viewer_mode=False, show_chat=True
        )


# --------------------------------------------------
# 🏇 2. 現地観戦用（勝負5R厳選） メニュー
# --------------------------------------------------

elif selected_menu == "🏇 現地観戦用（勝負5R厳選）":
    rule_type = st.radio(
        "今回適用する評価ルールを選択してください：",
        [
            "🏆 G1専用ルール",
            "🏇 平場・G2・G3専用ルール",
            "🌾 北海道・洋芝専用ルール",
        ],
        horizontal=True,
    )

    if "G1専用" in rule_type:
        active_selected_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
    elif "北海道" in rule_type:
        active_selected_rule = load_saved_rules(
            RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES
        )
    else:
        active_selected_rule = load_saved_rules(
            RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES
        )

    active_key = load_api_key()
    render_field_mode_ui(active_key, active_selected_rule, selected_model)


# --------------------------------------------------
# ⚙️ 3. ルール管理・アップデート メニュー
# --------------------------------------------------

elif selected_menu == "⚙️ ルール管理・アップデート":
    st.subheader("⚙️ 解析ルールの管理・アップデート")
    st.write(
        "「G1専用」「平場・G2・G3専用」「北海道・洋芝専用」の各ルールテキストをアップロード＆保存して更新できます。"
    )

    sub_tab1, sub_tab2, sub_tab3 = st.tabs([
        "🏆 G1専用ルールの設定",
        "🏇 平場・G2・G3専用ルールの設定",
        "🌾 北海道・洋芝専用ルールの設定",
    ])

    with sub_tab1:
        st.markdown("#### 🏆 G1専用ルールのアップロード ＆ 保存")
        col_g1_1, col_g1_2 = st.columns([2, 1])

        with col_g1_1:
            up_g1 = st.file_uploader(
                "G1用ルールテキスト (.txt)", type=["txt"], key="up_g1_file"
            )
            if up_g1 is not None:
                if st.button(
                    "📥 アップロードしたテキストを画面に読み込む", key="btn_load_g1"
                ):
                    st.session_state["g1_text_val"] = up_g1.read().decode(
                        "utf-8", errors="ignore"
                    )
                    st.rerun()

        with col_g1_2:
            if st.button("🔄 G1初期ルールに戻す", key="btn_g1_def"):
                st.session_state["g1_text_val"] = DEFAULT_G1_RULES
                save_rules_to_file(RULE_G1_FILE, DEFAULT_G1_RULES)
                st.rerun()

        st.text_area(
            "G1専用ルールテキスト（直接編集可能）", height=300, key="g1_text_val"
        )

        if st.button(
            "💾 G1専用ルールとして更新・保存する",
            use_container_width=True,
            key="save_g1_btn",
        ):
            rule_content = st.session_state["g1_text_val"]
            if rule_content.strip():
                save_rules_to_file(RULE_G1_FILE, rule_content)
                st.success(
                    "🎉 G1専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
                )
            else:
                st.error("⚠️ 空のルールは保存できません。")

    with sub_tab2:
        st.markdown("#### 🏇 平場・G2・G3専用ルールのアップロード ＆ 保存")
        col_gen_1, col_gen_2 = st.columns([2, 1])

        with col_gen_1:
            up_gen = st.file_uploader(
                "平場・G2・G3用ルールテキスト (.txt)",
                type=["txt"],
                key="up_gen_file",
            )
            if up_gen is not None:
                if st.button(
                    "📥 アップロードしたテキストを画面に読み込む", key="btn_load_gen"
                ):
                    st.session_state["gen_text_val"] = up_gen.read().decode(
                        "utf-8", errors="ignore"
                    )
                    st.rerun()

        with col_gen_2:
            if st.button("🔄 平場・G2・G3初期ルールに戻す", key="btn_gen_def"):
                st.session_state["gen_text_val"] = DEFAULT_GENERAL_RULES
                save_rules_to_file(RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES)
                st.rerun()

        st.text_area(
            "平場・G2・G3専用ルールテキスト（直接編集可能）",
            height=300,
            key="gen_text_val",
        )

        if st.button(
            "💾 平場・G2・G3専用ルールとして更新・保存する",
            use_container_width=True,
            key="save_gen_btn",
        ):
            rule_content = st.session_state["gen_text_val"]
            if rule_content.strip():
                save_rules_to_file(RULE_GENERAL_FILE, rule_content)
                st.success(
                    "🎉 平場・G2・G3専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
                )
            else:
                st.error("⚠️ 空のルールは保存できません。")

    with sub_tab3:
        st.markdown("#### 🌾 北海道・洋芝専用ルールのアップロード ＆ 保存")
        col_hok_1, col_hok_2 = st.columns([2, 1])

        with col_hok_1:
            up_hok = st.file_uploader(
                "北海道・洋芝用ルールテキスト (.txt)",
                type=["txt"],
                key="up_hok_file",
            )
            if up_hok is not None:
                if st.button(
                    "📥 アップロードしたテキストを画面に読み込む", key="btn_load_hok"
                ):
                    st.session_state["hok_text_val"] = up_hok.read().decode(
                        "utf-8", errors="ignore"
                    )
                    st.rerun()

        with col_hok_2:
            if st.button("🔄 北海道・洋芝初期ルールに戻す", key="btn_hok_def"):
                st.session_state["hok_text_val"] = DEFAULT_HOKKAIDO_RULES
                save_rules_to_file(RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES)
                st.rerun()

        st.text_area(
            "北海道・洋芝専用ルールテキスト（直接編集可能）",
            height=300,
            key="hok_text_val",
        )

        if st.button(
            "💾 北海道・洋芝専用ルールとして更新・保存する",
            use_container_width=True,
            key="save_hok_btn",
        ):
            rule_content = st.session_state["hok_text_val"]
            if rule_content.strip():
                save_rules_to_file(RULE_HOKKAIDO_FILE, rule_content)
                st.success(
                    "🎉 北海道・洋芝専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
                )
            else:
                st.error("⚠️ 空のルールは保存できません。")


# --------------------------------------------------
# 🔄 4. 回顧・精度検証 メニュー
# --------------------------------------------------

elif selected_menu == "🔄 回顧・精度検証":
    st.subheader("🔄 レース後回顧 ＆ 全着順自動照合 ＆ ルール自動検証")
    db_df = load_db(selected_year="全期間")

    if db_df.empty:
        st.info("💡 過去馬データベースに予想データがありません。「📋 レース分析・予想」で解析を実行してください！")
    else:
        races_in_db = (
            db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []
        )
        selected_race = st.selectbox(
            "🎯 回顧対象のレースを選択してください", races_in_db
        )

        col_r1, col_r2 = st.columns(2)
        with col_r1:
            res_text_input = st.text_area(
                "1. 結果テキストのコピペ（netkeiba/JRA結果画面等）", height=180
            )
        with col_r2:
            res_file_inputs = st.file_uploader(
                "2. 複数ソース結果ファイル (.txt / .csv / .pdf / .png / .jpg 一括選択可)",
                type=["txt", "csv", "pdf", "png", "jpg", "jpeg"],
                accept_multiple_files=True,
                key="recap_multi_file_uploader",
            )

        if st.button(
            "🏁 回顧 ＆ 全着順照合 ＆ ルール検証を実行する", use_container_width=True
        ):
            active_key = load_api_key()
            if not active_key:
                st.error("⚠️ Gemini API Key が設定されていません。`st.secrets` またはシステム設定で入力してください！")
            elif not res_text_input and not res_file_inputs:
                st.warning("⚠️ 結果テキストのコピペまたはファイルを1つ以上読み込ませてください！")
            else:
                with st.spinner(
                    "🏇 AIが全結果データを統合し、全着順を照合・深掘り長文回顧＆ルール検証中..."
                ):
                    try:
                        raw_result = res_text_input if res_text_input else ""
                        
                        if res_file_inputs:
                            for res_file in res_file_inputs:
                                res_file.seek(0)
                                if res_file.name.lower().endswith(".pdf"):
                                    pdf_txt = extract_text_from_pdf(res_file, page_option="全ページ")
                                    raw_result += f"\n=========================================\n【結果ファイル: {res_file.name}】\n=========================================\n" + pdf_txt
                                elif res_file.name.lower().endswith((".txt", ".csv")):
                                    txt_data = res_file.read().decode("utf-8", errors="ignore")
                                    raw_result += f"\n=========================================\n【結果ファイル: {res_file.name}】\n=========================================\n" + txt_data

                        target_df = db_df[
                            db_df["レース名"].astype(str) == str(selected_race)
                        ]
                        cols = [
                            c
                            for c in [
                                "馬番", "馬名", "総合スコア", "評価", "軸", "ヒモ", "注", "切り", "メモ",
                            ]
                            if c in target_df.columns
                        ]
                        predict_summary = target_df[cols].to_string(index=False)

                        is_g1_race = "G1" in selected_race or "Ｇ１" in selected_race or "Jpn1" in selected_race or "Ｊｐｎ１" in selected_race
                        is_hok_race = any(
                            k in selected_race for k in ["函館", "札幌", "洋芝"]
                        )

                        if is_g1_race:
                            current_rule = load_saved_rules(RULE_G1_FILE, DEFAULT_G1_RULES)
                        elif is_hok_race:
                            current_rule = load_saved_rules(
                                RULE_HOKKAIDO_FILE, DEFAULT_HOKKAIDO_RULES
                            )
                        else:
                            current_rule = load_saved_rules(
                                RULE_GENERAL_FILE, DEFAULT_GENERAL_RULES
                            )

                        prompt = (
                            "あなたは競馬予想プロフェッショナル「AI」です。\n"
                            "以下の「予想データ」「現在適用中の評価ルール」「実際のレース結果データ（複数ソース統合版）」を突き合わせ、全着順テーブル、プロ視点による詳細で長文の【本格レース回顧・見解レポート】、および【ルール改修案の自動判定】を行ってください。\n\n"
                            f"【予想データ】\n{predict_summary}\n\n"
                            f"【現在適用中の評価ルール】\n{current_rule}\n\n"
                            f"【実際のレース結果データ（複数ソース統合版）】\n{raw_result}\n\n"
                            "【出力フォーマット要求】\n"
                            "1. まず、以下の全頭確定着順テーブルをTSV（タブ区切り）テキストのみで出力してください（コードブロック ```tsv は含めないこと）：\n\n"
                            "確定着順\t馬番\t馬名\t単勝人気\t確定オッズ\tタイム\t上り3F\t評価\t勝因・敗因ショートメモ\n\n"
                            "※「確定オッズ」および「上り3F」の数値は、5.1 や 37.6 のように小数第1位までの表示とし、5.100000 のような不要な0（00000）は絶対に出力しないでください。\n\n"
                            "2. テーブルの後に、改行して「---RESULT_MEMO---」という行をはさみ、その下に【詳細レース回顧・プロの長文見解】を以下の5項目構成で長文かつ具体的に深掘りして出力してください：\n\n"
                            "   📌 1. 【レース全体の展開 ＆ 馬場・ペース振り返り】\n"
                            "   ・スタートから道中のペース（ハイ・ミドル・スロー）とトラックバイアス（内外・前後有利）の分析\n"
                            "   ・事前予想の展開シミュレーションとの合致点・乖離点の検証\n\n"
                            "   🏆 2. 【上位入線馬（1〜3着馬）の勝因・勝負の分かれ目】\n"
                            "   ・勝ち馬および好走馬の勝因（展開の助け、コース取り、馬場適性、騎手好判断など）の詳細見解\n\n"
                            "   ⚠️ 3. 【人気裏切り馬・凡走馬の敗因分析】\n"
                            "   ・1〜3番人気で敗れた馬や注目馬の敗因（出遅れ、展開不向き、馬場ノメり、距離限界、疲労、傷病等）を深掘り\n\n"
                            "   🎯 4. 【次走巻き返し注目馬 ＆ 危険な人気馬メモ】\n"
                            "   ・不利や展開不向きで崩れた「次走狙い目馬」\n"
                            "   ・今回展開や恵まれた枠順で激走した「次走過剰人気注意馬」\n\n"
                            "   📊 5. 【予想ロジック・指数との整合性検証】\n"
                            "   ・指数・評価（S, A, B等）通りに好走した馬の検証、および評価から外れた波乱要素の要因特定\n\n"
                            "3. 回顧コメントの後に、改行して「---RULE_UPDATE---」という行をはさみ、ルール改修案がある場合は必ず以下の【厳格な2ブロック構成】で出力してください：\n\n"
                            "【★重要規則：バージョン繰り上げ指定】\n"
                            "現在適用中のルールタイトルに記載されているバージョン（例: ver.8.3）を特定し、必ずバージョン番号を「+0.1」繰り上げたタイトル（例: ver.8.4）に改訂・ナンバリングしてください！\n\n"
                            "[ブロック1：今回の補正・改修部分のみの枠]\n"
                            "【今回追加・修正された改修案（補正内容）】\n"
                            "（例：ver.8.3 → ver.8.4 への改修点、新設・変更された箇条書き条項のみを記述）\n\n"
                            "---FULL_MERGED_RULE---\n\n"
                            "[ブロック2：バージョン繰り上げ済みのルール全文枠]\n"
                            "【◯◯専用・評価表出力ルール（ver.8.X・...）】\n"
                            "（※ヘッダータイトルのバージョンをver.8.Xから更新後の新バージョンに変更し、本文内の更新日時も最新にし、補正・改修部分を正しい該当項目内に差し込み・完全統合した状態の『最新ルール全文』を出力してください。末尾への単純追記ではなく、ルール文章全体に適切に挿入・結合された完成版全文にすること）\n"
                        )

                        client = genai.Client(api_key=active_key)
                        contents_list = [prompt]
                        
                        if res_file_inputs:
                            for res_file in res_file_inputs:
                                if res_file.name.lower().endswith((".png", ".jpg", ".jpeg", ".pdf")):
                                    res_file.seek(0)
                                    mime_t = res_file.type
                                    if not mime_t or mime_t == "application/octet-stream":
                                        if res_file.name.lower().endswith(".pdf"):
                                            mime_t = "application/pdf"
                                        elif res_file.name.lower().endswith(".png"):
                                            mime_t = "image/png"
                                        elif res_file.name.lower().endswith((".jpg", ".jpeg")):
                                            mime_t = "image/jpeg"
                                    if mime_t:
                                        contents_list.append(
                                            types.Part.from_bytes(
                                                data=res_file.read(), mime_type=mime_t
                                            )
                                        )

                        response = client.models.generate_content(
                            model=selected_model,
                            contents=contents_list,
                            config=types.GenerateContentConfig(
                                temperature=0.0, seed=42
                            ),
                        )
                        ai_res_out = response.text

                        tbl_part = ai_res_out
                        memo_part = "回顧コメントの抽出を完了しました。"
                        rule_update_part = (
                            "【ルール変更なし】現行ロジックのままで問題ありません。"
                        )

                        if "---RESULT_MEMO---" in ai_res_out:
                            tbl_part, rest_part = ai_res_out.split("---RESULT_MEMO---", 1)
                            if "---RULE_UPDATE---" in rest_part:
                                memo_part, rule_update_part = rest_part.split(
                                    "---RULE_UPDATE---", 1
                                )
                            else:
                                memo_part = rest_part
                        elif "---RULE_UPDATE---" in ai_res_out:
                            tbl_part, rule_update_part = ai_res_out.split(
                                "---RULE_UPDATE---", 1
                            )

                        clean_tbl = (
                            tbl_part.replace("```tsv", "").replace("```", "").strip()
                        )
                        res_df = pd.read_csv(
                            io.StringIO(clean_tbl),
                            sep="\t",
                            dtype=str,
                            on_bad_lines="skip",
                        )

                        res_df = res_df.drop(columns=["軸ヒモ切り", "人気"], errors="ignore").fillna("").replace({"None": "", "none": "", "nan": "", "NaN": ""})

                        for col_name in ["確定オッズ", "上り3F"]:
                            if col_name in res_df.columns:
                                def clean_decimal(v):
                                    if pd.isna(v) or not str(v).strip():
                                        return ""
                                    try:
                                        val = float(str(v).strip())
                                        return f"{val:.1f}"
                                    except Exception:
                                        return str(v)
                                res_df[col_name] = res_df[col_name].apply(clean_decimal)

                        update_db_with_recap(selected_race, res_df, memo_part)

                        def highlight_ranks(row):
                            rank_val = normalize_rank(row.get("確定着順", ""))
                            if rank_val == "1":
                                return [
                                    "background-color: #4a3b00; color: #ffd700; font-weight: bold;"
                                ] * len(row)
                            elif rank_val == "2":
                                return [
                                    "background-color: #223344; color: #00ffff; font-weight: bold;"
                                ] * len(row)
                            elif rank_val == "3":
                                return [
                                    "background-color: #332211; color: #ffaa55; font-weight: bold;"
                                ] * len(row)
                            return [""] * len(row)

                        st.success(
                            f"🎉 レース「{selected_race}」の複数ソース統合照合 ＆ 深掘り回顧 ＆ ルール検証が完了し、データベースに着順がプール保存されました！"
                        )

                        calc_res_height = min(500, (len(res_df) + 1) * 35 + 38)
                        st.subheader("🏆 全着順 ＆ 予想照合結果")
                        st.dataframe(
                            res_df.style.hide(axis="index").apply(highlight_ranks, axis=1),
                            use_container_width=True,
                            height=calc_res_height,
                            hide_index=True,
                        )

                        st.subheader("📝 詳細レース回顧・プロの長文見解")
                        st.markdown(
                            f"""
                            <div class="recap-box">
{memo_part.strip()}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        st.subheader("⚙️ 評価ルールの見直し・改修結果")
                        rule_update_clean = rule_update_part.strip()
                        if "【ルール変更なし】" in rule_update_clean:
                            st.success(
                                "✅ 今回のレース検証結果：現行ルール・ロジックのままで問題ありません。"
                            )
                        else:
                            st.warning("⚠️ 新しいルール改修案が提案されました！")

                            if "---FULL_MERGED_RULE---" in rule_update_clean:
                                diff_summary, full_rule_body = rule_update_clean.split("---FULL_MERGED_RULE---", 1)
                            else:
                                diff_summary = rule_update_clean
                                full_rule_body = f"{current_rule}\n\n=========================================\n【今回のレース回顧に基づく追記・改修案】\n=========================================\n{rule_update_clean}"

                            st.markdown("#### 📌 1. 今回の補正・改修部分（バージョン更新内容）")
                            st.code(diff_summary.strip(), language="text")

                            st.markdown("#### 📋 2. 保存用：バージョン更新済み 完全統合ルール全文（ワンタップコピー用）")
                            st.write("💡 **以下の枠内をコピーして「⚙️ ルール管理・アップデート」画面へそのまま貼り付け保存してください：**")
                            st.code(full_rule_body.strip(), language="text")

                    except Exception as e:
                        st.error(f"❌ 回顧処理中にエラーが発生しました: {e}")


# --------------------------------------------------
# 📊 5. 評価データ一覧（プール） メニュー
# --------------------------------------------------

elif selected_menu == "📊 評価データ一覧（プール）":
    st.subheader("📊 評価データ一覧（プール閲覧専用画面）")
    
    available_years = get_available_years_in_db()
    selected_year = st.selectbox("📅 閲覧する年度を選択してください：", available_years + ["全期間"], index=0)

    db_df = load_db(selected_year=selected_year)

    if db_df.empty:
        st.info("💡 選択された年度にデータベースデータがありません。")
    else:
        all_races = db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []

        eval_race_options = ["--- 🎯 レースを選択してください ---"] + all_races

        selected_eval_race = st.selectbox(
            "🎯 閲覧・再評価する予想データ（レース）を選択してください：",
            eval_race_options,
            index=0,
            key="eval_pool_race_select"
        )

        if selected_eval_race and selected_eval_race != "--- 🎯 レースを選択してください ---":
            matched_df = db_df[db_df["レース名"].astype(str) == str(selected_eval_race)].copy()
            if not matched_df.empty:
                render_race_evaluation_view(matched_df, is_viewer_mode=False, show_chat=True)
            else:
                st.error(f"⚠️ 選択されたレース「{selected_eval_race}」のデータが見つかりませんでした。")
        else:
            st.info("👆 上のドロップダウンから閲覧・表示したいレースを選択してください。")


# --------------------------------------------------
# 📝 6. 回顧・精度検証一覧（プール） メニュー
# --------------------------------------------------

elif selected_menu == "📝 回顧・精度検証一覧（プール）":
    st.subheader("📝 回顧・精度検証データ一覧（プール閲覧専用画面）")
    
    available_years = get_available_years_in_db()
    selected_year = st.selectbox("📅 閲覧する年度を選択してください：", available_years + ["全期間"], index=0, key="recap_year_select")

    db_df = load_db(selected_year=selected_year)

    if db_df.empty:
        st.info("💡 選択された年度に予想・回顧データが見つかりません。")
    else:
        if "回顧メモ" in db_df.columns or "確定着順" in db_df.columns:
            recap_mask = (
                (db_df.get("回顧メモ", pd.Series([""]*len(db_df))).astype(str).str.strip() != "") |
                (db_df.get("確定着順", pd.Series([""]*len(db_df))).astype(str).str.strip() != "")
            )
            recap_races = db_df[recap_mask]["レース名"].unique().tolist() if "レース名" in db_df.columns else []
            all_races = db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []
        else:
            recap_races = []
            all_races = db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []

        if not recap_races:
            st.warning("⚠️ 回顧・着順データが保存されているレースがまだありません。")
            st.info("💡 サイドバーの「🔄 回顧・精度検証」メニューからレース結果を取り込むと、ここに自動プールされます！")
            target_race_options = all_races
        else:
            st.success(f"📦 回顧・検証済みレース: 全 {len(recap_races)} 件")
            target_race_options = recap_races + [r for r in all_races if r not in recap_races]

        recap_race_options = ["--- 🎯 レースを選択してください ---"] + target_race_options

        selected_recap_race = st.selectbox(
            "🏁 閲覧する回顧データ（レース）を選択してください：",
            recap_race_options,
            index=0,
            key="recap_pool_race_select"
        )

        if selected_recap_race and selected_recap_race != "--- 🎯 レースを選択してください ---":
            race_df = db_df[db_df["レース名"].astype(str) == str(selected_recap_race)].copy()

            recap_text = ""
            if "回顧メモ" in race_df.columns:
                recap_memos = race_df["回顧メモ"].dropna().unique()
                non_empty = [m for m in recap_memos if str(m).strip()]
                if non_empty:
                    recap_text = str(non_empty[0]).strip()

            target_cols = [
                c for c in [
                    "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気",
                    "単勝人気", "確定オッズ", "タイム", "上り3F", "勝因・敗因ショートメモ"
                ] if c in race_df.columns
            ]
            disp_result_df = race_df[target_cols].copy()

            def highlight_ranks_view(row):
                rank_val = normalize_rank(row.get("確定着順", ""))
                if rank_val == "1":
                    return ["background-color: #4a3b00; color: #ffd700; font-weight: bold;"] * len(row)
                elif rank_val == "2":
                    return ["background-color: #223344; color: #00ffff; font-weight: bold;"] * len(row)
                elif rank_val == "3":
                    return ["background-color: #332211; color: #ffaa55; font-weight: bold;"] * len(row)
                return [""] * len(row)

            st.markdown(f"### 🏆 【{selected_recap_race}】 全頭確定着順 ＆ 照合結果")

            calc_height = min(500, (len(disp_result_df) + 1) * 35 + 38)
            st.dataframe(
                disp_result_df.style.apply(highlight_ranks_view, axis=1),
                column_config={
                    "総合スコア": st.column_config.ProgressColumn(
                        "総合スコア", format="%d点", min_value=0, max_value=100, color="#0bce0e"
                    ),
                },
                use_container_width=True,
                height=calc_height,
                hide_index=True,
            )

            st.divider()

            st.markdown("### 📝 詳細レース回顧・プロの見解レポート")
            if recap_text:
                st.markdown(
                    f"""
                    <div class="recap-box">
{recap_text}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info("ℹ️ このレースにはまだプロ回顧コメントレポートが入力されていません。")
        else:
            st.info("👆 上のドロップダウンから閲覧したい回顧レースを選択してください。")


# --------------------------------------------------
# 🗄 7. 過去馬データベース（プール） メニュー
# --------------------------------------------------

elif selected_menu == "🗄 過去馬データベース（プール）":
    st.subheader("🗄️ 過去馬データベース（プール一覧・レース別閲覧）")
    
    available_years = get_available_years_in_db()
    selected_year = st.selectbox("📅 閲覧する年度を選択してください：", available_years + ["全期間"], index=0, key="db_year_select")

    db_df = load_db(selected_year=selected_year)

    if not db_df.empty:
        st.success(f"📦 現在 {len(db_df)} 件の解析馬データがプールされています")

        with st.expander("🛠 データベースの削除・整理メニュー", expanded=False):
            col_del_1, col_del_2 = st.columns(2)

            with col_del_1:
                st.markdown("##### 📌 特定のレースデータを削除")
                races_list_del = (
                    db_df["レース名"].unique().tolist()
                    if "レース名" in db_df.columns
                    else []
                )
                selected_race_to_del = st.selectbox(
                    "削除するレースを選択してください", races_list_del, key="db_del_select"
                )
                if st.button("🗑️ 選択したレースを削除する", key="btn_del_race"):
                    if selected_race_to_del:
                        delete_race_from_db(selected_race_to_del)
                        st.success(
                            f"✅ レース「{selected_race_to_del}」のデータを削除しました！"
                        )
                        st.rerun()

            with col_del_2:
                st.markdown("##### 💣 全件一括削除")
                confirm_clear = st.checkbox(
                    "本当にすべてのデータを一括削除します", key="chk_confirm_clear"
                )
                if st.button("💥 データベースを全件クリアする", key="btn_clear_all"):
                    if confirm_clear:
                        clear_db()
                        st.success("💥 データベースを全件削除し、完全リセットしました！")
                        st.rerun()

        st.divider()

        all_races_in_db = (
            db_df["レース名"].unique().tolist() if "レース名" in db_df.columns else []
        )
        race_selector_options = ["🌐 すべてのレース（全件一括表示）"] + all_races_in_db

        selected_db_race = st.selectbox(
            "📂 表示・閲覧するレースを選択してください：",
            race_selector_options,
            index=0,
            key="db_race_filter_selectbox",
        )

        st.write("")

        disp_db_df = db_df.copy().fillna("").replace({"None": "", "none": "", "nan": "", "NaN": ""})
        disp_db_df = disp_db_df.drop(columns=["軸ヒモ切り", "人気"], errors="ignore")

        def db_highlight_ranks(row):
            rank_val = normalize_rank(row.get("確定着順", ""))
            if rank_val == "1":
                return ["background-color: #4a3b00; color: #ffd700; font-weight: bold;"] * len(row)
            elif rank_val == "2":
                return ["background-color: #223344; color: #00ffff; font-weight: bold;"] * len(row)
            elif rank_val == "3":
                return ["background-color: #332211; color: #ffaa55; font-weight: bold;"] * len(row)
            return [""] * len(row)

        db_col_config = {
            "確定着順": st.column_config.TextColumn("着順", width="small"),
            "馬番": st.column_config.NumberColumn("馬番", width="small"),
            "単勝人気": st.column_config.TextColumn("単勝人気", width="small"),
            "予想人気": st.column_config.TextColumn("予想人気", width="small"),
            "総合スコア": st.column_config.ProgressColumn(
                "総合スコア", format="%d点", min_value=0, max_value=100, color="#0bce0e"
            ),
            "メモ": st.column_config.TextColumn("メモ（詳細分析）", width="large"),
        }

        if selected_db_race != "🌐 すべてのレース（全件一括表示）":
            filtered_df = disp_db_df[disp_db_df["レース名"].astype(str) == str(selected_db_race)]
            
            st.markdown(f"### 🏇 【{selected_db_race}】 解析データ（出走頭数: {len(filtered_df)}頭）")

            single_race_cols = [
                c for c in [
                    "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気",
                    "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点",
                    "軸", "ヒモ", "注", "切り", "単勝人気", "確定オッズ", "タイム", "上り3F",
                    "勝因・敗因ショートメモ", "メモ"
                ] if c in filtered_df.columns
            ]
            disp_single_df = filtered_df[single_race_cols]
            disp_single_df = disp_single_df[disp_single_df["馬名"].astype(str).str.strip() != ""].dropna(how="all")

            calc_db_single_height = min(600, (len(disp_single_df) + 1) * 35 + 38)

            st.dataframe(
                disp_single_df.style.apply(db_highlight_ranks, axis=1),
                column_config=db_col_config,
                use_container_width=True,
                height=calc_db_single_height,
                hide_index=True,
            )

            dl_col1, dl_col2 = st.columns(2)
            with dl_col1:
                single_csv_data = filtered_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label=f"📥 「{selected_db_race}」のみCSVダウンロード",
                    data=single_csv_data,
                    file_name=f"{selected_db_race}_database.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            with dl_col2:
                all_csv_data = db_df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="📦 全データベース（一括）CSVダウンロード",
                    data=all_csv_data,
                    file_name="race_all_database.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

        else:
            st.markdown("### 🌐 プール済み全レース・全頭一覧")
            
            if "確定着順" in disp_db_df.columns:
                cols_order = [
                    "レース名", "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気",
                    "軸", "ヒモ", "注", "切り", "単勝人気", "確定オッズ", "タイム", "上り3F",
                    "勝因・敗因ショートメモ", "メモ"
                ] + [
                    c for c in disp_db_df.columns if c not in [
                        "レース名", "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気",
                        "軸", "ヒモ", "注", "切り", "単勝人気", "確定オッズ", "タイム", "上り3F",
                        "勝因・敗因ショートメモ", "メモ", "回顧メモ", "軸ヒモ切り", "人気"
                    ]
                ]
                disp_db_df = disp_db_df.reindex(columns=[c for c in cols_order if c in disp_db_df.columns])

            search_race = st.text_input("🔍 部分一致テキスト検索（レース名や馬名で絞り込み）", "")
            if search_race:
                mask = (
                    disp_db_df["レース名"].astype(str).str.contains(search_race, na=False) |
                    disp_db_df["馬名"].astype(str).str.contains(search_race, na=False)
                )
                filtered_all_df = disp_db_df[mask]
                filtered_all_df = filtered_all_df[filtered_all_df["馬名"].astype(str).str.strip() != ""].dropna(how="all")
                calc_all_height = min(600, (len(filtered_all_df) + 1) * 35 + 38)
                st.dataframe(
                    filtered_all_df.style.apply(db_highlight_ranks, axis=1),
                    column_config=db_col_config,
                    use_container_width=True,
                    height=calc_all_height,
                    hide_index=True,
                )
            else:
                disp_db_df = disp_db_df[disp_db_df["馬名"].astype(str).str.strip() != ""].dropna(how="all")
                calc_all_height = min(600, (len(disp_db_df) + 1) * 35 + 38)
                st.dataframe(
                    disp_db_df.style.apply(db_highlight_ranks, axis=1),
                    column_config=db_col_config,
                    use_container_width=True,
                    height=calc_all_height,
                    hide_index=True,
                )

            csv_data = db_df.to_csv(index=False, encoding="utf-8-sig")
            st.download_button(
                label="📦 データベースをCSVで一括ダウンロード",
                data=csv_data,
                file_name="race_all_database.csv",
                mime="text/csv",
            )
    else:
        st.info("💡 まだプールされたデータはありません。")