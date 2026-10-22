import glob
import os
import pandas as pd

# ---------------------------------------------------------
# 1. ウマエルプロ最新フォーマット（全29項目）
# ---------------------------------------------------------
TARGET_COLUMNS = [
    "確定着順", "レース名", "馬番", "馬名", "予想人気", "総合スコア", "評価",
    "出馬表点", "血統点", "調教点", "近5走点", "展開点", "馬場点",
    "軸", "ヒモ", "注", "切り", "メモ", "レース質展開予想", "推奨買い目",
    "信頼度", "波乱度", "単勝人気", "確定オッズ", "タイム", "上り3F",
    "勝因・敗因ショートメモ", "回顧メモ", "年"
]

# ---------------------------------------------------------
# 2. 旧項目の名前揺れを最新の列名に変換するルール
# ---------------------------------------------------------
COLUMN_MAPPING = {
    "着順": "確定着順",
    "人気": "単勝人気",
    "評価（S.A+.A.B+.B.C）": "評価",
    "軸（〇）": "軸",
    "ヒモ（〇）": "ヒモ",
    "注（〇）": "注",
    "切り（〇）": "切り"
}

# 変換対象のCSVが入っているフォルダ
TARGET_DIR = "data/2026"
target_files = glob.glob(os.path.join(TARGET_DIR, "*.csv"))

if not target_files:
    print(f"⚠️ {TARGET_DIR} フォルダ内にCSVが見つかりません。")
    exit()

for file_path in target_files:
    try:
        try:
            df = pd.read_csv(file_path, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(file_path, encoding="cp932")

        # 列名の余計な空白を除去
        df.columns = [str(col).strip() for col in df.columns]

        # ① 旧項目名を最新項目名に自動書き換え（ここが超重要！）
        df = df.rename(columns=COLUMN_MAPPING)

        # ② 元データにない最新項目だけを「空欄("")」で補填
        for col in TARGET_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        # ③ 最新の29列順にピッタリ並び替え
        df_fixed = df[TARGET_COLUMNS].copy()

        # ④ 改行(\n)を「 / 」に変換（1行スッキリ化）
        for col in df_fixed.columns:
            df_fixed[col] = (
                df_fixed[col]
                .astype(str)
                .str.replace("\r\n", " / ")
                .str.replace("\n", " / ")
                .replace("nan", "")
            )

        # ⑤ 上書き保存（BOM付きUTF-8）
        df_fixed.to_csv(file_path, index=False, encoding="utf-8-sig")
        print(f"✅ 成形完了: {os.path.basename(file_path)}")

    except Exception as e:
        print(f"❌ エラー発生 ({file_path}): {e}")

print("\n🎉 全てのCSVフォーマット統一が完了しました！")