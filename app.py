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

# ページ基本設定
st.set_page_config(
    page_title="ウマエル解析サイト", page_icon="🏇", layout="wide"
)

# ファイルパス設定
DB_FILE = "umael_database.csv"
RULE_G1_FILE = "saved_rules_g1.txt"
RULE_GENERAL_FILE = "saved_rules_general.txt"
RULE_HOKKAIDO_FILE = "saved_rules_hokkaido.txt"
API_KEY_FILE = "api_key.txt"
DRAFTS_DIR = "race_drafts"


# --------------------------------------------------
# 🛠 共通ヘルパー関数・定義
# --------------------------------------------------

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
            soup = BeautifulSoup(html, "parser")
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

            if fname.lower().endswith(".txt"):
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
                        f"\n=========================================\n【確定メイン出馬データファイル:"
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
                            f"\n=========================================\n【確定メイン出馬データ（PDF抽出）:"
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
    """比較用に全角/半角を統一し、スペース・記号・アルファベット小文字化して標準キーを作成"""
    if not name:
        return ""
    # NFKC正規化（全角英数字・記号・カナ等の統一）
    s = unicodedata.normalize('NFKC', str(name))
    # 小文字化
    s = s.lower()
    # 空白（全角半角スペース・タブ）の除去
    s = re.sub(r'\s+', '', s)
    # 記号・アンダースコア・ハイフン・括弧類の除去
    s = re.sub(r'[_\-\–\—\(\)（）\[\]【】]', '', s)
    return s


def find_matching_existing_draft(target_race_name):
    """既存の下書きリストの中から表記揺れを吸収して合致するフォルダ名（既存レース名）を検索"""
    existing_races = list_draft_races()
    target_key = normalize_race_name_for_comparison(target_race_name)
    if not target_key:
        return None
    for existing_race in existing_races:
        if normalize_race_name_for_comparison(existing_race) == target_key:
            return existing_race
    return None


def clean_race_name_from_filename(filename):
    """ファイル名から「競馬新聞」「競馬新」「馬柱」「出馬表」、日付・西暦（_2026など）、連番（_2など）の余分なノイズを除去して純粋なレース名のみを抽出"""
    base_name = os.path.splitext(filename)[0]
    
    # 1. 不要なキーワード群の除去（「競馬新」「競馬新聞」等を確実に削除）
    noise_patterns = [
        r"競馬新聞", r"競馬新", r"新聞", r"出馬表", r"馬柱", r"確定データ", r"確定",
        r"過去データ", r"過去", r"傾向", r"回顧", r"データ", r"全ページ", r"印刷"
    ]
    
    cleaned = base_name
    for pat in noise_patterns:
        cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
    
    # 2. 日付（YYYYMMDD / YYYY）や西暦（202x年/202x）の除去（例: _20261010, 2026, _2026 など）
    cleaned = re.sub(r'[_\s\-\—]?(?:20\d{2})(?:[01]\d[0-3]\d)?', '', cleaned)
    
    # 3. 末尾の連番・枝番（_2, _1, (1), -1 など）の除去
    cleaned = re.sub(r'[_\s\-\—]\d+$', '', cleaned)
    cleaned = re.sub(r'\(\d+\)$', '', cleaned)
    
    # 不可文字の置換と連続する記号・空白の整形
    cleaned = re.sub(r'[\\/*?:"<>|]', "_", cleaned)
    cleaned = re.sub(r'[_\s\-\—]+', '_', cleaned)
    cleaned = cleaned.strip('_').strip()
    
    return cleaned if cleaned else re.sub(r'[\\/*?:"<>|]', "_", base_name).strip()


def detect_simple_race_name(files_g1, files_g2, files_g3):
    for flist in [files_g1, files_g2, files_g3]:
        if flist:
            for f in flist:
                clean_name = clean_race_name_from_filename(f.name)
                if clean_name:
                    return clean_name
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"準備中レース_{timestamp}"


def save_draft_data(race_name, files_g1, files_g2, files_g3, urls_text):
    ensure_drafts_dir()
    if not race_name or not race_name.strip():
        race_name = detect_simple_race_name(files_g1, files_g2, files_g3)
    else:
        race_name = clean_race_name_from_filename(race_name)

    # 表記揺れを吸収して既存の同一レース下書きフォルダが存在するか照合
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
    for g_idx, file_list in [(1, files_g1), (2, files_g2), (3, files_g3)]:
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
        return "", [], "", [], "", [], "", []

    sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip()).strip('_')
    race_dir = os.path.join(DRAFTS_DIR, sanitized_name)

    if not os.path.exists(race_dir):
        return "", [], "", [], "", [], "", []

    t1_all, p1_all = "", []
    t2_all, p2_all = "", []
    t3_all, p3_all = "", []
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

            txt_content = ""
            media_parts = []

            is_past_ref = any(
                k in original_fname
                for k in ["過去", "傾向", "データ", "歴史", "前日", "回顧"]
            )

            if original_fname.lower().endswith(".txt"):
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

    t4_all = ""
    url_log_path = os.path.join(race_dir, "urls.txt")
    if os.path.exists(url_log_path):
        with open(url_log_path, "r", encoding="utf-8") as f:
            urls_text = f.read()
            if urls_text.strip():
                t4_all = process_multiple_urls(urls_text)

    return t1_all, p1_all, t2_all, p2_all, t3_all, p3_all, t4_all, file_names


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


DEFAULT_G1_RULES = """【G1専用・評価表出力ルール（ver.8.3・レース質＆展開予想冒頭配置・頂点実績厳格化・開幕外枠デバフ・鉄砲個別判定・傷病デバフ・タフ馬場補正・単騎逃げ救済・直感相馬眼・YouTubeハイブリッド解析統合版）】
================================================================
【G1専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
================================================================
■ 0. システム運用・誤入力完全排除規定
・ブラウジング完全禁止、ファクトチェック厳格化。
■ 1. 基本方針・評価スタンス
■ 2. 【G1頂点基準】評価ランク定義とS評価認定必須要件
【S評価】93点以上、【A+評価】88～92点、【A評価】84～87点、【B+評価】80～83点、【B評価】74～79点、【C評価】73点以下。
■ 3. G1デバフ規定（傷病休養、鉄砲不振、距離限界、出遅れ、連戦疲労、タフ馬場ノメり、開幕外枠）
■ 4. G1ボーナス・救済加点規定（イン突き、開幕先行、超Hペース、前走度外視、長距離スロー捲り、単騎逃げ救済等）
■ 5. 表記・プロ評価＆YouTube自動解析統合ルール
■ 6. 【出力順序絶対規定】＆ 解析サイト蓄積用（20列TSV）フォーマット
1. 🏁 レース質 ＆ 展開予想シミュレーション
2. 💰 G1限定・推奨券種＆ガミなし資金配分案
3. 📊 ウマエル解析サイト蓄積用データ（20列TSV）
■ 7. レース解析冒頭：レース質 ＆ 展開予想シミュレーション必須フォーマット
■ 8. G1各評価点計算式
■ 9. ガミなし資金配分案ルール
"""

DEFAULT_GENERAL_RULES = """【平場・G2・G3専用 評価表出力ルール（ver.8.3・S評価厳格化＆開幕外枠デバフ・鉄砲個別判定・過重ハンデ地力救済・タフ馬場ノメりデバフ・単騎逃げ救済・直感相馬眼・軸飛び防止・前走度外視完全統合版）】
================================================================
【平場・G2・G3専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
================================================================
■ 0. システム運用・誤入力完全排除規定
■ 1. 基本方針・評価スタンス
■ 2. 評価ランク定義とS評価認定必須要件
■ 3. デバフ規定（傷病、鉄砲不振、距離限界、ハンデ見込まれ、連戦疲労、ノメり、開幕外枠）
■ 4. ボーナス・救済加点規定（ハンデ恵量、実績スランプ、死んだふりイン突き、開幕先行、超Hペース、過重地力救済等）
■ 5. 表記・プロ評価統合ルール
■ 6. 【出力順序絶対規定】＆ 解析サイト蓄積用（20列TSV）フォーマット
1. 🏁 レース質 ＆ 展開予想シミュレーション
2. 💰 推奨買い目＆資金配分（指示時のみ）
3. 📊 ウマエル解析サイト蓄積用データ（20列TSV）
■ 7. レース解析冒頭フォーマット
■ 8. 各評価点計算式
"""

DEFAULT_HOKKAIDO_RULES = """【平場・G2・G3 北海道・洋芝（函館・札幌）専用 評価表出力ルール（ver.8.3・S評価厳格化＆開幕外枠デバフ・鉄砲個別判定・過重ハンデ地力救済・タフ馬場ノメりデバフ・洋芝滞在・単騎逃げ救済・直感相馬眼・軸飛び防止・前走度外視完全統合版）】
================================================================
【平場・G2・G3 北海道・洋芝（函館・札幌）専用 競馬予想評価ロジック＆運用仕様書 ver.8.3（完全統合マスター版）】
改訂日：2026年10月8日（Web解析サイト蓄積・Webアプリ完全適合版）
================================================================
■ 0. システム運用・誤入力完全排除規定
■ 1. 基本方針・洋芝評価スタンス（洋芝滞在・パワー血統・クッション値評価）
■ 2. 評価ランク定義
■ 3. デバフ規定（初の洋芝デバフ、傷病、鉄砲不振、ハンデ見込まれ、開幕外枠等）
■ 4. ボーナス・救済加点規定（洋芝実績・現地滞在ボーナス、洋芝激流対応血統、ハンデ恵量、洋芝イン差し等）
■ 5. 表記・プロ評価統合ルール
■ 6. 【出力順序絶対規定】＆ 解析サイト蓄積用（20列TSV）フォーマット
■ 7. レース解析冒頭フォーマット
■ 8. 各評価点計算式
"""


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


def load_db():
    if os.path.exists(DB_FILE):
        try:
            df = pd.read_csv(DB_FILE, dtype=str).fillna("")
            df = df.replace({"None": "", "none": "", "nan": "", "NaN": ""})
            if "軸ヒモ切り" in df.columns:
                df = df.drop(columns=["軸ヒモ切り"])
            if "総合スコア" in df.columns:
                df["総合スコア"] = (
                    pd.to_numeric(df["総合スコア"], errors="coerce").fillna(0).astype(int)
                )
                df = df.sort_values(by="総合スコア", ascending=False).reset_index(
                    drop=True
                )
            if "総合スコアグラフ" in df.columns:
                df = df.drop(columns=["総合スコアグラフ"])
            return df
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def parse_json_ai_output(result_text):
    parsed_rows = []
    race_title = "20261008_競馬解析_OP"
    confidence = ""
    risk_level = ""
    race_quality_and_tenkai = ""
    recommended_tickets = []

    try:
        clean_text = result_text.strip()
        if "```json" in clean_text:
            clean_text = clean_text.split("```json")[1].split("```")[0].strip()
        elif "```" in clean_text:
            clean_text = clean_text.split("```")[1].split("```")[0].strip()

        data = json.loads(clean_text)
        race_title = data.get("race_name", "20261008_競馬解析_OP")
        confidence = data.get("confidence", "")
        risk_level = data.get("risk_level", "")
        race_quality_and_tenkai = data.get("race_quality_and_tenkai", "")
        recommended_tickets = data.get("recommended_tickets", [])

        horses = data.get("horses", [])

        for h in horses:
            h_num = safe_int(h.get("horse_num", 0))
            h_name = str(h.get("horse_name", "")).strip()
            pop_val = str(h.get("pop", "-")).strip()
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
                parsed_rows.append({
                    "確定着順": "",
                    "馬番": h_num,
                    "馬名": h_name,
                    "人気": "",
                    "予想人気": pop_val,
                    "総合スコア": total_score,
                    "評価": rank_eval,
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
                })

    except Exception as e:
        st.warning(f"⚠️ JSON読み込み処理中: {e}")

    if not parsed_rows:
        return pd.DataFrame()

    df = pd.DataFrame(parsed_rows)
    df["レース名"] = race_title

    if confidence:
        df["信頼度"] = confidence
    if risk_level:
        df["波乱度"] = risk_level
    if race_quality_and_tenkai:
        df["レース質展開予想"] = race_quality_and_tenkai
    if recommended_tickets:
        df["推奨買い目"] = json.dumps(recommended_tickets, ensure_ascii=False)

    return df


def render_race_evaluation_view(df, is_viewer_mode=False):
    if df.empty:
        st.warning("⚠️ 表示できる解析データがありません。再度分析を実行してください。")
        return

    race_title = (
        df["レース名"].iloc[0]
        if "レース名" in df.columns and not df.empty
        else "競馬予想解析"
    )
    view_df = df.drop(
        columns=["レース名", "信頼度", "波乱度", "レース質展開予想", "推奨買い目", "確定着順", "回顧メモ", "軸ヒモ切り"],
        errors="ignore",
    ).fillna("").replace({"None": "", "none": "", "nan": "", "NaN": ""})

    honmei_horse = view_df.iloc[0] if not view_df.empty else None
    h_score = (
        safe_int(honmei_horse.get("総合スコア", 0))
        if honmei_horse is not None
        else 0
    )

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

    h_num = (
        str(safe_int(honmei_horse["馬番"], default=1))
        if honmei_horse is not None and "馬番" in honmei_horse
        else "1"
    )
    h_name = (
        str(honmei_horse["馬名"])
        if honmei_horse is not None and "馬名" in honmei_horse
        else "本命馬"
    )

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

    raw_tickets = (
        df["推奨買い目"].iloc[0] if "推奨買い目" in df.columns else None
    )
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

    view_tab1, view_tab2 = st.tabs(
        ["🌟 推奨評価上位サマリー", "📊 詳細全データ表（評価順）"]
    )

    with view_tab1:
        st.markdown(
            f"<h2 style='text-align: center; color: #f39c12;'>🏇 {race_title} 🏇</h2>",
            unsafe_allow_html=True,
        )
        st.write("")

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
                    "指数合計値", format="%d点", min_value=0, max_value=100
                ),
            }

            top_group = disp_df.head(5)
            sub_group = disp_df.iloc[5:] if len(disp_df) > 5 else pd.DataFrame()

            st.write("🟢 **上位推奨グループ（軸・相手筆頭）**")
            st.dataframe(
                top_group,
                column_config=col_config_sum,
                use_container_width=True,
                hide_index=True,
            )

            if not sub_group.empty:
                st.write("🟡 **相手紐・穴馬グループ**")
                st.dataframe(
                    sub_group,
                    column_config=col_config_sum,
                    use_container_width=True,
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

    with view_tab2:
        st.subheader(f"📊 {race_title} 詳細全データ表（評価順）")
        st.info(
            "💡"
            " **※「メモ（詳細分析）」等の各セルは、枠内をダブルクリック（スマホはダブルタップ）すると全文を拡大表示・コピーできます！**"
        )

        col_config_detail = {
            "馬番": st.column_config.NumberColumn("馬番", width="small"),
            "馬名": st.column_config.TextColumn("馬名", width="medium"),
            "予想人気": st.column_config.TextColumn("予想人気", width="small"),
            "総合スコア": st.column_config.ProgressColumn(
                "総合スコア", format="%d点", min_value=0, max_value=100, width="medium"
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

        st.dataframe(
            view_df,
            column_config=col_config_detail,
            use_container_width=True,
            height=600,
            hide_index=True,
        )


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
        padding-top: 2.5rem !important;
    }

    .main { background-color: #080a0f; }
    h1, h2, h3 { color: #f39c12 !important; font-weight: bold; }

    div[data-testid="stDataFrame"] div[role="progressbar"] {
        height: 14px !important;
        border-radius: 4px !important;
        background-color: #1e2638 !important;
    }
    div[data-testid="stDataFrame"] div[role="progressbar"] > div {
        background: linear-gradient(90deg, #107c41 0%, #21a366 100%) !important;
        border-radius: 4px !important;
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
    
    .stButton>button {
        background: linear-gradient(135deg, #f39c12 0%, #d35400 100%);
        color: #ffffff; font-weight: bold; border-radius: 8px; border: none; padding: 0.6rem 2rem; box-shadow: 0 4px 15px rgba(243, 156, 18, 0.3);
    }
    .stButton>button:hover { background: linear-gradient(135deg, #e67e22 0%, #e74c3c 100%); }
</style>
""",
    unsafe_allow_html=True,
)


query_params = st.query_params

if "race" in query_params:
    target_race_param = query_params["race"]
    db_df = load_db()

    if not db_df.empty and "レース名" in db_df.columns:
        matched_df = db_df[db_df["レース名"].astype(str) == str(target_race_param)]
        if not matched_df.empty:
            render_race_evaluation_view(matched_df, is_viewer_mode=True)
        else:
            st.error(
                f"⚠️ レース「{target_race_param}」の解析データは見つかりませんでした。"
            )
    else:
        st.error("⚠️ データベースに予想データが登録されていません。")

    st.stop()


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
        RULE_H