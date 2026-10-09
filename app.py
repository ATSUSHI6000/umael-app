import importlib
import io
import json
import os
import re
import shutil
import time
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
    page_title="競馬馬柱解析サイト", page_icon="🏇", layout="wide"
)

# ファイルパス設定
DB_FILE = "umael_database.csv"
RULE_G1_FILE = "saved_rules_g1.txt"
RULE_GENERAL_FILE = "saved_rules_general.txt"
RULE_HOKKAIDO_FILE = "saved_rules_hokkaido.txt"
API_KEY_FILE = "api_key.txt"
DRAFTS_DIR = "race_drafts"


# ドラフト保存用ディレクトリ確保
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


# アップロードデータからレース名を自動探知（フォールバック用）
def detect_simple_race_name(files_g1, files_g2, files_g3):
  text_corpus = ""
  for flist in [files_g1, files_g2, files_g3]:
    if flist:
      for f in flist:
        f.seek(0)
        fname = f.name
        text_corpus += " " + fname
        f.seek(0)

  found = re.findall(r"[a-zA-Z0-9一-龠ぁ-ゔァ-ヴー]+", text_corpus)
  short_label = "_".join(found[:2]) if found else "準備中レース"
  timestamp = time.strftime("%Y%m%d_%H%M%S")
  return f"{short_label}_{timestamp}"


def save_draft_data(race_name, files_g1, files_g2, files_g3, urls_text):
  ensure_drafts_dir()
  if not race_name or not race_name.strip():
    race_name = detect_simple_race_name(files_g1, files_g2, files_g3)

  sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip())
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
  for g_idx, file_list in [(1, files_g1), (2, files_g2), (3, files_g3)]:
    if file_list:
      for f in file_list:
        f.seek(0)
        content = f.read()
        fname = f.name
        timestamp = int(time.time())
        save_fname = f"g{g_idx}_{timestamp}_{fname}"
        with open(os.path.join(race_dir, save_fname), "wb") as out_f:
          out_f.write(content)
        saved_count += 1
  return saved_count, sanitized_name


def load_draft_data(race_name, pdf_page_option="1ページ目のみ"):
  ensure_drafts_dir()
  if not race_name or not race_name.strip():
    return "", [], "", [], "", [], "", []

  sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip())
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
      file_names.append(fname)
      with open(fpath, "rb") as f:
        file_bytes = f.read()

      original_fname = fname.split("_", 2)[-1] if "_" in fname else fname

      group_idx = 1
      if fname.startswith("g2_"):
        group_idx = 2
      elif fname.startswith("g3_"):
        group_idx = 3

      txt_content = ""
      media_parts = []

      if original_fname.lower().endswith(".txt"):
        decoded = file_bytes.decode("utf-8", errors="ignore")
        txt_content += (
            f"\n【保存済みテキストデータ ({original_fname})】:\n" + decoded
        )
      else:
        bio = io.BytesIO(file_bytes)
        extracted = extract_text_from_pdf(bio, page_option=pdf_page_option)
        if extracted.strip():
          txt_content += (
              f"\n【保存済みPDF抽出データ ({original_fname})】:\n"
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
  sanitized_name = re.sub(r'[\\/*?:"<>|]', "_", race_name.strip())
  race_dir = os.path.join(DRAFTS_DIR, sanitized_name)
  if os.path.exists(race_dir):
    shutil.rmtree(race_dir)
    return True
  return False


# APIキーの保存・読み込み関数
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


# 🛠️ 馬番・着順の表記ゆれ正規化クレンジング関数
def normalize_horse_num(val):
  if pd.isna(val):
    return ""
  s = re.sub(r"\D", "", str(val))
  return str(int(s)) if s else ""


def normalize_rank(val):
  """確定着順を安全に正規化。文字列中の別の数字を着順と誤認しない。"""
  if pd.isna(val):
    return ""
  s = str(val).strip()
  if not s or s in {"-", "—", "取消", "除外", "中止", "失格", "競走中止"}:
    return ""
  # 「1」「1着」「１着」など、着順欄そのものの先頭数字だけを採用
  s = s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
  m = re.match(r"^\s*(\d+)\s*(?:着)?\s*$", s)
  if m:
    return str(int(m.group(1)))
  return ""


EVALUATION_MARK_COLUMNS = ["軸", "ヒモ", "注", "切り"]


def evaluation_mark_category(eval_value, row=None):
  """評価ランクを4区分のうち1つだけに対応付ける。"""
  rank = str(eval_value or "").strip().upper().replace(" ", "")
  if rank in {"S", "S+", "A+"}:
    return "軸"
  if rank in {"A", "A-", "B+"}:
    return "ヒモ"
  if rank == "B":
    return "注"
  if rank in {"C", "C+", "C-", "D", "E"}:
    return "切り"

  # 評価ランクが欠落している旧データは、既存印が複数なら優先順で1つに統一。
  if row is not None:
    present = [
        col for col in EVALUATION_MARK_COLUMNS
        if str(row.get(col, "")).strip() == "〇"
    ]
    if len(present) == 1:
      return present[0]
    if present:
      return present[0]
  return "切り"


def enforce_exclusive_evaluation_marks(df):
  """各馬の評価印を評価ランクと連動させ、4列のうち必ず1列だけ〇にする。"""
  if df is None or df.empty:
    return df.copy() if df is not None else pd.DataFrame()

  out = df.copy()
  for col in EVALUATION_MARK_COLUMNS:
    if col not in out.columns:
      out[col] = ""

  for idx, row in out.iterrows():
    category = evaluation_mark_category(row.get("評価", ""), row)
    for col in EVALUATION_MARK_COLUMNS:
      out.at[idx, col] = "〇" if col == category else ""
  return out


# 馬番（1〜20）を丸囲み文字（①〜⑳）に変換する関数
def convert_to_circled_numbers(text):
  circled_map = {
      "1": "①",
      "2": "②",
      "3": "③",
      "4": "④",
      "5": "⑤",
      "6": "⑥",
      "7": "⑦",
      "8": "⑧",
      "9": "⑨",
      "10": "⑩",
      "11": "⑪",
      "12": "⑫",
      "13": "⑬",
      "14": "⑭",
      "15": "⑮",
      "16": "⑯",
      "17": "⑰",
      "18": "⑱",
      "19": "⑲",
      "20": "⑳",
  }

  def replacer(match):
    val = match.group(0)
    return circled_map.get(val, val)

  return re.sub(r"\b(20|1[0-9]|[1-9])\b", replacer, str(text))


# 🌐 Web本文・YouTube字幕テキスト自動取得関数
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


# デフォルトルール定数定義
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
      df = pd.read_csv(DB_FILE)
      # 旧DBに残っている重複印も読み込み時に補正し、CSV本体へ保存する。
      normalized_df = enforce_exclusive_evaluation_marks(df)
      mark_cols = EVALUATION_MARK_COLUMNS
      marks_changed = any(col not in df.columns for col in mark_cols)
      if not marks_changed:
        marks_changed = any(
            df[col].fillna("").astype(str).tolist()
            != normalized_df[col].fillna("").astype(str).tolist()
            for col in mark_cols
        )
      if marks_changed:
        normalized_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
      df = normalized_df
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

      # 印はAIの個別フラグではなく、評価ランクに連動させて必ず1つだけ付ける。
      mark_category = evaluation_mark_category(rank_eval, h)
      jiku = "〇" if mark_category == "軸" else ""
      himo = "〇" if mark_category == "ヒモ" else ""
      注 = "〇" if mark_category == "注" else ""
      kiri = "〇" if mark_category == "切り" else ""

      memo = str(h.get("memo", "")).strip()
      if not memo or len(memo) < 10:
        memo = (
            f"【評価理由】総合スコア{total_score}点。データ・血統・適性面を考慮して評価を算出。"
        )

      if h_num > 0 and h_name:
        parsed_rows.append({
            "確定着順": "",  # 初期値は空文字
            "馬番": h_num,
            "馬名": h_name,
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
            "注": 注,
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
      columns=["レース名", "信頼度", "波乱度", "レース質展開予想", "推奨買い目", "確定着順", "回顧メモ"],
      errors="ignore",
  )

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

  # 🎯 注目波乱馬（【指数75点以上】かつ【C評価除外（B評価以上）】の馬から選出）
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
        f"<h2 style='text-align: center; color: #f39c12;'>🏇 {race_title}"
        " 🏇</h2>",
        unsafe_allow_html=True,
    )
    st.write("")

    # 🌟 1. 「レース展開 & 波乱度判定」カード
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

    # 🌟 2. 本命・穴馬カード（左） / 順位一覧テーブル（右）
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

    # 🌟 3. 買い目の直上に「🏁 レース質 ＆ 展開予想シミュレーション」を表示
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

    # 🌟 4. 推奨買い目フォーメーション
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


# カスタムCSS
st.markdown(
    """
<style>
    /* 🚀 画面幅制限の完全解除 */
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
        padding-top: 1rem !important;
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


# --------------------------------------------------
# 🚀 閲覧専用モード分岐（ポータル機能）
# --------------------------------------------------
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


# --------------------------------------------------
# 👑 通常モード（アニキ専用管理・解析画面）
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


def save_to_db(new_df):
  if new_df.empty:
    return load_db()
  clean_save_df = new_df.drop(columns=["総合スコアグラフ"], errors="ignore")
  clean_save_df = enforce_exclusive_evaluation_marks(clean_save_df)
  if os.path.exists(DB_FILE):
    try:
      old_df = pd.read_csv(DB_FILE)
      if "総合スコアグラフ" in old_df.columns:
        old_df = old_df.drop(columns=["総合スコアグラフ"])

      if "レース名" in new_df.columns and "レース名" in old_df.columns:
        race_n = new_df["レース名"].iloc[0]
        old_df = old_df[old_df["レース名"].astype(str) != str(race_n)]

      combined_df = pd.concat([old_df, clean_save_df], ignore_index=True)
      combined_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
      return combined_df
    except Exception:
      clean_save_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
      return clean_save_df
  else:
    clean_save_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
    return clean_save_df


def update_db_with_recap(race_name, result_df, memo_text):
  """確定着順・結果テーブルの主要項目・レース回顧を過去馬DBへ保存する。"""
  if not os.path.exists(DB_FILE):
    return
  try:
    df = pd.read_csv(DB_FILE, dtype=str).fillna("")
    if "レース名" not in df.columns:
      return

    mask = df["レース名"].astype(str).str.strip() == str(race_name).strip()
    if not mask.any():
      return

    # 馬番を正規化して結果テーブルをDBの各馬に照合する。
    result_by_num = {}
    if not result_df.empty and "馬番" in result_df.columns:
      for _, result_row in result_df.iterrows():
        horse_num = normalize_horse_num(result_row.get("馬番", ""))
        if horse_num:
          result_by_num[horse_num] = result_row

    # 予想時の「評価」列は保持し、レース結果として保存したい列だけを追加・更新する。
    result_columns = [
        "確定着順", "単勝人気", "確定オッズ", "タイム", "上り3F",
        "軸ヒモ切り", "勝因・敗因ショートメモ",
    ]
    for col in result_columns + ["回顧メモ"]:
      if col not in df.columns:
        df[col] = ""

    for idx in df.index[mask]:
      horse_num = normalize_horse_num(df.at[idx, "馬番"] if "馬番" in df.columns else "")
      result_row = result_by_num.get(horse_num)
      if result_row is not None:
        for col in result_columns:
          if col in result_df.columns:
            value = result_row.get(col, "")
            if pd.notna(value) and str(value).strip():
              df.at[idx, col] = str(value).strip()
      df.at[idx, "回顧メモ"] = str(memo_text).strip()

    # 回顧・着順反映後も評価表と同じ4区分に統一し、重複〇を残さない。
    normalized_df = enforce_exclusive_evaluation_marks(df.loc[mask].copy())
    for idx in normalized_df.index:
      for col in EVALUATION_MARK_COLUMNS:
        df.at[idx, col] = normalized_df.at[idx, col]

    df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
  except Exception as e:
    st.warning(f"⚠️ データベースの回顧・着順プール保存中に注意: {e}")


def delete_race_from_db(race_name):
  if os.path.exists(DB_FILE):
    try:
      df = pd.read_csv(DB_FILE)
      if "レース名" in df.columns:
        new_df = df[df["レース名"].astype(str) != str(race_name)]
        new_df.to_csv(DB_FILE, index=False, encoding="utf-8-sig")
        return True
    except Exception:
      pass
  return False


def clear_db():
  if os.path.exists(DB_FILE):
    try:
      os.remove(DB_FILE)
      return True
    except Exception:
      pass
  return False


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

【★レース質 ＆ 展開予想シミュレーションの必須生成指示（ルール■ 7準拠）】
ルール仕様に基づき、本レースの『レース質（瞬発力/持続力/消耗戦/加速戦）』および『展開予想（ペース・脚質位置取り・ハナ主張・中盤隊列・直線の攻防・勝ち馬の決定打）』を臨場感ある文章で詳細に作成し、`race_quality_and_tenkai` フィールドに出力してください。

【最重要・出走馬の確定判定指示（テキスト＆スクショ画像の両方を視覚的に解析せよ）】
添付されているテキストデータおよびスクショ画像/PDFから、今回のレースの【本物の出走馬一覧】を視覚的にも確認して抽出してください。

★【過去データ馬の絶対除外規則】：
資料内に「過去データ」「傾向」などの文脈で含まれている過去の馬は【今回の出走馬ではありません】！絶対に出力に含めないでください！

★【今回の本物出走馬の絶対条件】：
・今回対象レースの「確定出馬表（メイン馬柱スクショまたは確定データ）」に載っている馬です。
・馬番が 1 から順番に最後の馬番まで（1, 2, 3...）連続して並んでいる出走馬【全頭】を抽出してください。

★【グループ4：プロ予想・YouTube・Web参考URLのクロスチェック規則】：
グループ4が含まれている場合は、プロ陣営が本命・穴馬として推奨している馬のコメントや理由を分析に組み込み、総合スコアや『メモ』列の詳細根拠に「※プロ陣営本命推奨」「※プロ陣営注目穴馬」等の補足も含めて反映してください！

【推奨券種・買い目フォーメーション表記の最重要ルール】
買い目に出力する【馬番の数字】は、必ず ①、②、③、④、⑤ ... ⑱ のような【丸囲み数字】で出力してください！

=== 【グループ1：テキスト・スクショ・PDFデータ（出馬表・近5走・血統）】 ===
{text_group1}

=== 【グループ2：競馬ブックデータ（スクショ画像/PDFデータ/調教）】 ===
{text_group2}

=== 【グループ3：前日傾向・当日の馬場情報データ】 ===
{text_group3}

=== 【グループ4：プロ予想・YouTube字幕・Web参考URL抽出データ】 ===
{text_group4}

【出力形式】
以下のJSON形式のみを出力してください。

{{
  "race_name": "必ず YYYYMMDD_レース名_グレード 形式（例：20261011_毎日王冠_G2）",
  "confidence": "軸馬信頼度判定（例：S (鉄板軸) / A (有力軸) / B (波乱含み)）",
  "risk_level": "波乱度判定（例：★☆☆ (本命堅調) / ★★☆ (中波乱警戒) / ★★★ (大波乱混戦)）",
  "race_quality_and_tenkai": "🏁 【対象レース名】レース質 ＆ 展開予想シミュレーション\\n【レース質：持続力戦】\\n（コース特徴と求められる能力の概要）\\n\\n【展開予想】\\nペース：ミドルペース\\n逃げ：①...\\n好位：...\\n中位：...\\n後方：...\\n\\n先頭集団の攻防（ハナ主張）\\n...\\n中盤の隊列と有力馬の位置取り\\n...\\n直線の攻防と勝ち馬のシナリオ\\n...\\n結論：勝ち馬の決定打\\n〇〇（決着型）：...",
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
      "eval": "評価ランク（S, A+, A, A-, B+, B, C等）",
      "score_shubahyou": 出馬表点(0-100),
      "score_kettou": 血統点(0-100),
      "score_choukyou": 調教点(0-100),
      "score_kin5so": 近5走点(0-100),
      "score_tenkai": 展開点(0-100),
      "score_baba": 馬場点(0-100),
      "jiku": "軸なら〇、違えば空文字",
      "himo": "ヒモなら〇、違えば空文字",
      "chu": "注なら〇、違えば空文字",
      "kiri": "切りなら〇、違えば空文字",
      "memo": "本命理由・血統・近5走・展開相性・プロ推奨理由などの長文詳細分析メモ"
    }}
  ]
}}

【最重要遵守事項】
・確定出馬表にある1番〜最終馬番まで絶対に途中で切らず【全頭】出力すること。
・解説文章や挨拶は一切含めず、純粋なJSONのみを出力すること。
・同じ入力データに対しては、常に同一の厳格なロジックで一貫したスコアを算出すること。
・各馬の印は「軸」「ヒモ」「注」「切り」の4区分のうち必ず1つだけに「〇」を付け、1頭に複数の「〇」を絶対に付けないこと。
・印は評価ランクと必ず一致させること：S/S+/A+＝軸、A/A-/B+＝ヒモ、B＝注、C以下・その他の低評価＝切り。
・「注」欄を省略せず、該当馬には chu＝「〇」を出力すること。
"""

  contents_payload = [json_prompt]
  contents_payload.extend(parts_group1)
  contents_payload.extend(parts_group2)
  contents_payload.extend(parts_group3)

  max_retries = 5
  for attempt in range(max_retries):
    try:
      response = client.models.generate_content(
          model=model_name,
          contents=contents_payload,
          config=types.GenerateContentConfig(
              response_mime_type="application/json",
              temperature=0.0,
              seed=42,  # 🔒 乱数シードを42に固定
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
            "⚠️"
            " 本日の無料枠上限に達しました。別アカウントのAPIキーをご使用いただくか明日までお待ちください。"
        )
      else:
        raise e


st.title("競馬馬柱解析サイト v2.7")
st.caption(
    "馬柱・血統・予想オッズ・競馬ブック・馬場情報 一括AI解析＆Webプール"
)

# --------------------------------------------------
# 🧭 左側サイドバー
# --------------------------------------------------
with st.sidebar:
  st.header("🧭 ナビゲーション")

  selected_menu = st.radio(
      "移動する機能を選択してください：",
      [
          "📋 レース分析・予想",
          "⚙️ ルール管理・アップデート",
          "🔄 回顧・精度検証",
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
    st.caption("🔑 APIキー自動保存機能オン")
    st.caption("📱 スマホ表示対応モード動作中")

# --------------------------------------------------
# 🎯 メインエリア画面分岐
# --------------------------------------------------

# --------------------------------------------------
# 1. 📋 レース分析・予想
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

  # ★ 段階的データ保存（下書き）機能
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
      draft_choice = st.selectbox(
          "既存の準備中レースを選択する：",
          ["✨ 【新規レース作成（馬柱からレース名自動判別）】"] + existing_drafts,
      )
      if (
          draft_choice
          == "✨ 【新規レース作成（馬柱からレース名自動判別）】"
      ):
        draft_race_name = st.text_input(
            "レース名を入力（※空欄でもアップロードファイルから自動設定されます）",
            "",
        )
      else:
        draft_race_name = draft_choice

    with draft_col2:
      if draft_race_name and draft_race_name not in [
          "✨ 【新規レース作成（馬柱からレース名自動判別）】",
          "",
      ]:
        st.write("📦 **現在の蓄積状況**")
        _, _, _, _, _, _, _, saved_fnames = load_draft_data(draft_race_name)
        if saved_fnames:
          st.success(f"保存済みファイル: {len(saved_fnames)}件")
          with st.expander("保存中のファイル一覧"):
            for fn in saved_fnames:
              st.caption(f"・{fn}")
        else:
          st.caption("まだ保存されているファイルはありません。")

  st.divider()
  st.subheader("📂 データのアップロード (.txt / .pdf / .png / .jpg / URL)")

  col1, col2, col3 = st.columns(3)

  with col1:
    files_group1 = st.file_uploader(
        "1. 出馬表・枠順・近5走・血統 (.txt / .pdf / .png / .jpg)",
        type=["txt", "pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="fg1",
    )

  with col2:
    files_group2 = st.file_uploader(
        "2. 競馬ブック・調教データ (.pdf / .png / .jpg)",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="fg2",
    )
    pdf_page_opt = st.radio(
        "📄 競馬ブックPDFの読み込み範囲",
        ["1ページ目のみ（推奨）", "全ページ読み込む"],
        index=0,
        key="pdf_page_opt",
    )

  with col3:
    files_group3 = st.file_uploader(
        "3. 当日・前日の傾向・馬場情報 (.txt / .pdf / .png / .jpg)",
        type=["txt", "pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        key="fg3",
    )

  st.write("")
  urls_group4_input = st.text_area(
      "🔗 4. プロ予想・YouTube・Web参考URL（改行して複数貼り付けOK）",
      height=90,
      placeholder="https://www.youtube.com/watch?v=...\nhttps://note.com/...",
      key="ug4",
  )

  st.divider()

  # ボタン処理
  if "段階的" in upload_mode:
    btn_col1, btn_col2, btn_col3 = st.columns([1.2, 1.5, 1])

    with btn_col1:
      if st.button("💾 今回のデータを下書き保存する", use_container_width=True):
        if (
            not files_group1
            and not files_group2
            and not files_group3
            and not urls_group4_input.strip()
        ):
          st.warning("⚠️ 追加保存するファイルまたはURLを入力してください！")
        else:
          target_name = (
              draft_race_name
              if (
                  draft_race_name
                  and draft_race_name.strip()
                  and draft_choice
                  != "✨ 【新規レース作成（馬柱からレース名自動判別）】"
              )
              else ""
          )
          saved_c, actual_draft_name = save_draft_data(
              target_name,
              files_group1,
              files_group2,
              files_group3,
              urls_group4_input,
          )
          st.success(
              f"🎉 レース「{actual_draft_name}」にデータ（ファイル{saved_c}件/URL）を蓄積保存しました！"
          )
          st.session_state.pop("analyzed_df", None)
          st.rerun()

    with btn_col2:
      if st.button(
          "🔥 蓄積された全データでAI一括解析を実行", use_container_width=True
      ):
        if not api_key:
          st.error("⚠️ サイドバーで Gemini API Key を設定してください！")
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
                  != "✨ 【新規レース作成（馬柱からレース名自動判別）】"
              )
              else ""
          )
          dt1, dp1, dt2, dp2, dt3, dp3, dt4, _ = (
              load_draft_data(target_draft, pdf_page_option=pdf_opt_val)
              if target_draft
              else ("", [], "", [], "", [], "", [])
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
          nt4 = process_multiple_urls(urls_group4_input)

          comb_t1 = dt1 + "\n" + nt1
          comb_p1 = dp1 + np1
          comb_t2 = dt2 + "\n" + nt2
          comb_p2 = dp2 + np2
          comb_t3 = dt3 + "\n" + nt3
          comb_p3 = dp3 + np3
          comb_t4 = dt4 + "\n" + nt4

          if (
              not comb_t1.strip()
              and not comb_t2.strip()
              and not comb_t3.strip()
              and not comb_p1
              and not comb_p2
              and not comb_p3
          ):
            st.warning(
                "⚠️"
                " 解析対象のデータが見つかりません。ファイルをアップロードするか、下書きデータを保存してください。"
            )
          else:
            with st.spinner(
                "🏇"
                " 馬柱・出馬表からレース名を自動取得しつつ、全データでAI一括解析中..."
            ):
              try:
                result_text = analyze_data_with_gemini(
                    api_key,
                    active_selected_rule,
                    comb_t1,
                    comb_p1,
                    comb_t2,
                    comb_p2,
                    comb_t3,
                    comb_p3,
                    comb_t4,
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
            "✨ 【新規レース作成（馬柱からレース名自動判別）】",
            "",
        ]:
          delete_draft(draft_race_name)
          st.success(
              f"🗑️ レース「{draft_race_name}」の下書きデータを削除しました！"
          )
          st.session_state.pop("analyzed_df", None)
          st.rerun()

  else:
    # 単発直接解析モード
    if st.button("🔥 AI分析を実行する", use_container_width=True):
      if not api_key:
        st.error("⚠️ サイドバーで Gemini API Key を入力してください！")
      elif (
          not files_group1
          and not files_group2
          and not files_group3
          and not urls_group4_input.strip()
      ):
        st.warning(
            "⚠️ 解析するデータファイルまたはURLを1つ以上入力してください！"
        )
      else:
        with st.spinner(
            "🏇"
            " 馬柱からレース名（YYYYMMDD_レース名_グレード）を自動取得して解析中..."
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
            t4 = process_multiple_urls(urls_group4_input)

            result_text = analyze_data_with_gemini(
                api_key,
                active_selected_rule,
                t1,
                p1,
                t2,
                p2,
                t3,
                p3,
                t4,
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

  # 🔗 メイン階層描画エリア
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
      share_race_name = str(st.session_state["analyzed_df"]["レース名"].iloc[0])
      share_url = (
          "https://umael-pro.streamlit.app/?race="
          + urllib.parse.quote(share_race_name, safe="")
      )
      st.markdown("**🔗 知人共有用URL（評価画面のみ）**")
      st.markdown(f"[共有URLを開く]({share_url})")
      st.code(share_url, language=None)
      st.caption("このURLを開くと、選択したレースの評価画面を閲覧できます。")

    render_race_evaluation_view(
        st.session_state["analyzed_df"], is_viewer_mode=False
    )

# --------------------------------------------------
# 2. ⚙️ ルール管理・アップデート
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
            "🎉"
            " G1専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
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
            "🎉"
            " 平場・G2・G3専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
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
            "🎉"
            " 北海道・洋芝専用ルールをファイルに更新・保存しました！次回からも自動適用されます！"
        )
      else:
        st.error("⚠️ 空のルールは保存できません。")

# --------------------------------------------------
# 3. 🔄 回顧・精度検証
# --------------------------------------------------
elif selected_menu == "🔄 回顧・精度検証":
  st.subheader("🔄 レース後回顧 ＆ 全着順自動照合 ＆ ルール自動検証")
  db_df = load_db()

  if db_df.empty:
    st.info(
        "💡"
        " 過去馬データベースに予想データがありません。「📋"
        " レース分析・予想」で解析を実行してください！"
    )
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
      res_file_input = st.file_uploader(
          "2. 結果ファイル (.txt / .pdf / .png / .jpg)",
          type=["txt", "pdf", "png", "jpg", "jpeg"],
      )

    if st.button(
        "🏁 回顧 ＆ 全着順照合 ＆ ルール検証を実行する", use_container_width=True
    ):
      if not api_key:
        st.error(
            "⚠️"
            " サイドバーの「⚙️"
            " システム設定」を展開し、Gemini API Keyを入力してください！"
        )
      elif not res_text_input and not res_file_input:
        st.warning("⚠️ 結果テキストのコピペまたはファイルを読み込ませてください！")
      else:
        with st.spinner(
            "🏇"
            " AIが全着順を照合・回顧し、評価ルールの見直し要否を検証中..."
        ):
          try:
            raw_result = res_text_input if res_text_input else ""
            if res_file_input:
              if res_file_input.name.lower().endswith(".pdf"):
                raw_result += "\n" + extract_text_from_pdf(
                    res_file_input, page_option="全ページ"
                )
              elif res_file_input.name.lower().endswith(".txt"):
                raw_result += "\n" + res_file_input.read().decode(
                    "utf-8", errors="ignore"
                )

            target_df = db_df[
                db_df["レース名"].astype(str) == str(selected_race)
            ]
            cols = [
                c
                for c in [
                    "馬番",
                    "馬名",
                    "総合スコア",
                    "評価",
                    "軸",
                    "ヒモ",
                    "注",
                    "切り",
                    "メモ",
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

            prompt = f"""あなたは競馬予想プロフェッショナル「AI」です。
以下の「予想データ」「現在適用中の評価ルール」「実際のレース結果データ」を突き合わせ、全着順テーブル、回顧レポート、および【ルール改修案の自動判定】を行ってください。

【予想データ】
{predict_summary}

【現在適用中の評価ルール】
{current_rule}

【実際のレース結果データ】
{raw_result}

【出力フォーマット要求】
1. まず、以下の全頭確定着順テーブルをTSV（タブ区切り）テキストのみで出力してください（コードブロック ```tsv は含めないこと）：

確定着順\t馬番\t馬名\t単勝人気\t確定オッズ\tタイム\t上り3F\t評価\t軸ヒモ切り\t勝因・敗因ショートメモ

※「確定オッズ」および「上り3F」の数値は、5.1 や 37.6 のように小数第1位までの表示とし、5.100000 のような不要な0（00000）は絶対に出力しないでください。

2. テーブルの後に、改行して「---RESULT_MEMO---」という行をはさみ、その下に回顧コメントを出力してください。
3. 回顧コメントの後に、改行して「---RULE_UPDATE---」という行をはさみ、ルール改修案がある場合は必ず以下の【厳格な2ブロック構成】で出力してください：

【★重要規則：バージョン繰り上げ指定】
現在適用中のルールタイトルに記載されているバージョン（例: ver.8.3）を特定し、必ずバージョン番号を「+0.1」繰り上げたタイトル（例: ver.8.4）に改訂・ナンバリングしてください！

[ブロック1：今回の補正・改修部分のみの枠]
【今回追加・修正された改修案（補正内容）】
（例：ver.8.3 → ver.8.4 への改修点、新設・変更された箇条書き条項のみを記述）

---FULL_MERGED_RULE---

[ブロック2：バージョン繰り上げ済みのルール全文枠]
【◯◯専用・評価表出力ルール（ver.8.X・...）】
（※ヘッダータイトルのバージョンをver.8.Xから更新後の新バージョンに変更し、本文内の更新日時も最新にし、補正・改修部分を正しい該当項目内に差し込み・完全統合した状態の『最新ルール全文』を出力してください。末尾への単純追記ではなく、ルール文章全体に適切に挿入・結合された完成版全文にすること）
"""
            client = genai.Client(api_key=api_key)
            contents_list = [prompt]
            if res_file_input and res_file_input.name.lower().endswith(
                (".png", ".jpg", ".jpeg", ".pdf")
            ):
              res_file_input.seek(0)
              contents_list.append(
                  types.Part.from_bytes(
                      data=res_file_input.read(), mime_type=res_file_input.type
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

            # 🛠️ 確定オッズ・上り3Fの小数を自動クレンジング
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

            # 🎯 照合された確定着順をデータベースに確実に反映・保存！
            update_db_with_recap(selected_race, res_df, memo_part)

            def highlight_ranks(row):
              rank_val = normalize_rank(row.get("確定着順", ""))
              if rank_val == "1":
                return [
                    "background-color: #4a3b00; color: #ffd700; font-weight:"
                    " bold;"
                ] * len(row)
              elif rank_val == "2":
                return [
                    "background-color: #223344; color: #00ffff; font-weight:"
                    " bold;"
                ] * len(row)
              elif rank_val == "3":
                return [
                    "background-color: #332211; color: #ffaa55; font-weight:"
                    " bold;"
                ] * len(row)
              return [""] * len(row)

            st.success(
                f"🎉 レース「{selected_race}」の全着順照合 ＆ 回顧 ＆ ルール検証が完了し、データベースに着順がプール保存されました！"
            )

            st.subheader("🏆 全着順 ＆ 予想照合結果")
            st.dataframe(
                res_df.style.hide(axis="index").apply(highlight_ranks, axis=1),
                use_container_width=True,
                height=450,
                hide_index=True,
            )

            st.subheader("📝 回顧 ＆ 今後の注目馬メモ")
            st.info(memo_part.strip())

            st.subheader("⚙️ 評価ルールの見直し・改修結果")
            rule_update_clean = rule_update_part.strip()
            if "【ルール変更なし】" in rule_update_clean:
              st.success(
                  "✅"
                  " 今回のレース検証結果：現行ルール・ロジックのままで問題ありません。"
              )
            else:
              st.warning("⚠️ 新しいルール改修案が提案されました！")
              
              if "---FULL_MERGED_RULE---" in rule_update_clean:
                diff_summary, full_rule_body = rule_update_clean.split("---FULL_MERGED_RULE---", 1)
              else:
                diff_summary = rule_update_clean
                full_rule_body = f"{current_rule}\n\n=========================================\n【今回のレース回顧に基づく追記・改修案】\n=========================================\n{rule_update_clean}"
              
              # ① 補正部分の枠（差分サマリー）
              st.markdown("#### 📌 1. 今回の補正・改修部分（バージョン更新内容）")
              st.code(diff_summary.strip(), language="text")

              # ② バージョン繰り上げ＆補正を挿入した状態の全文の枠
              st.markdown("#### 📋 2. 保存用：バージョン更新済み 完全統合ルール全文（ワンタップコピー用）")
              st.write("💡 **以下の枠内をコピーして「⚙️ ルール管理・アップデート」画面へそのまま貼り付け保存してください：**")
              st.code(full_rule_body.strip(), language="text")

          except Exception as e:
            st.error(f"❌ 回顧処理中にエラーが発生しました: {e}")

# --------------------------------------------------
# 4. 🗄 過去馬データベース（プール）
# --------------------------------------------------
elif selected_menu == "🗄 過去馬データベース（プール）":
  st.subheader("🗄️ 過去馬データベース（プール一覧・評価順）")
  db_df = load_db()

  if not db_df.empty:
    st.success(f"📦 現在 {len(db_df)} 件の解析馬データがプールされています")

    with st.expander("🛠 データベースの削除・整理メニュー", expanded=True):
      col_del_1, col_del_2 = st.columns(2)

      with col_del_1:
        st.markdown("##### 📌 特定のレースデータを削除")
        races_list = (
            db_df["レース名"].unique().tolist()
            if "レース名" in db_df.columns
            else []
        )
        selected_race_to_del = st.selectbox(
            "削除するレースを選択してください", races_list
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

    disp_db_df = db_df.copy()
    
    # 着順・主要列の表示並び替え（確定着順を先頭付近に配置）
    if "確定着順" in disp_db_df.columns:
      cols_order = ["レース名", "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気"] + [c for c in disp_db_df.columns if c not in ["レース名", "確定着順", "馬番", "馬名", "総合スコア", "評価", "予想人気", "確定オッズ", "上り3F", "回顧メモ"]]
      disp_db_df = disp_db_df.reindex(columns=[c for c in cols_order if c in disp_db_df.columns])

    # 🎨 DBプール画面用の確実な1〜3着カラーハイライト関数
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
        "総合スコア": st.column_config.ProgressColumn(
            "総合スコア", format="%d点", min_value=0, max_value=100
        )
    }

    search_race = st.text_input("🔍 レース名で検索", "")
    if search_race:
      filtered_df = disp_db_df[
          disp_db_df["レース名"].astype(str).str.contains(search_race, na=False)
      ]
      st.dataframe(
          filtered_df.style.apply(db_highlight_ranks, axis=1),
          column_config=db_col_config,
          use_container_width=True,
          height=500,
          hide_index=True,
      )
    else:
      st.dataframe(
          disp_db_df.style.apply(db_highlight_ranks, axis=1),
          column_config=db_col_config,
          use_container_width=True,
          height=500,
          hide_index=True,
      )

    csv_data = db_df.to_csv(index=False, encoding="utf-8-sig")
    st.download_button(
        label="📥 データベースをCSVでダウンロード",
        data=csv_data,
        file_name="race_all_database.csv",
        mime="text/csv",
    )
  else:
    st.info("💡 まだプールされたデータはありません。")