import streamlit as st
import gspread
import google.generativeai as genai
from googleapiclient.discovery import build
from google.oauth2 import service_account
from PIL import Image
import io
from thefuzz import process
import random
import time

# --- ① アプリの基本設定 ---
st.set_page_config(page_title="シラタマさん専用AIアシスタント", page_icon="⚔️", layout="wide")

# --- ② 認証情報 (Secretsから、サービスアカウント情報を、読み込む) ---
try:
    creds_dict = st.secrets["gcp_service_account"]
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
except (KeyError, FileNotFoundError):
    st.error("🚨 重大なエラー：StreamlitのSecretsに、GCPのサービスアカウント情報が正しく設定されていません。")
    st.stop()

# --- ③ メインの処理を実行する関数 ---
def run_shiratama_custom(gemini_api_key):
    try:
        st.header("⚔️ シラタマさん専用AIアシスタント")
        st.info("処理したいスクリーンショット画像を、すべて、ここにアップロードしてください。")
        uploaded_files = st.file_uploader("スクリーンショットを選択", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
        if st.button("アップロードした画像のデータ抽出を実行する"):
            if not uploaded_files: st.warning("画像がアップロードされていません。"); st.stop()
            if not gemini_api_key: st.warning("サイドバーでGemini APIキーを入力してください。"); st.stop()
            
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key('1j-A8Hq5sc4_y0E07wNd9814mHmheNAnaU8iZAr3C6xo')
            sheet = spreadsheet.worksheet('遠征入力')
            member_sheet = spreadsheet.worksheet('メンバー')
            
            genai.configure(api_key=gemini_api_key)
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            gemini_prompt = """
            あなたは、与えられたゲームのスクリーンショット画像を直接解析する、超高精度のデータ抽出AIです。
            あなたの使命は、画像の中から「プレイヤー名」と「スコア」のペアだけを完璧に抽出し、指定された形式で出力することです。
            #厳格なルール
            1. 画像を直接、あなたの目で見て、文字を認識してください。
            2. 認識した文字の中から、「プレイヤー名」と、その右側あるいは下の行にある「数値（スコア）」のペアのみを抽出対象とします。
            3. 画像に含まれる「ギルド対戦」「ラウンド」「<」「>」「|S」「A」のような、UIテキスト、無関係な記号、ランクを示すアルファベットは、思考の過程から完全に除外してください。
            4. プレイヤー名は、日本語、英語、数字が混在することがあります（例: `korosuke94`, `あーる 0113`）。これらも、一つの名前として正しく認識してください。
            5. 最終的なアウトプットは、一行につき「名前,数値」の形式で、カンマ区切りで出力してください。
            6. いかなる場合でも、ルールに記載された以外の説明、前置き、後書きは、絶対に出力しないでください。
            このルールを完璧に理解し、最高の精度で、任務を遂行してください。
            """
            all_player_data = []
            max_retries = 3
            progress_bar = st.progress(0, text="処理を開始します...")
            for i, uploaded_file in enumerate(uploaded_files):
                file_name = uploaded_file.name
                progress_text = f"処理中: {i+1}/{len(uploaded_files)} - {file_name}"
                progress_bar.progress((i+1)/len(uploaded_files), text=progress_text)
                with st.spinner(f"🖼️ 画像「{file_name}」を最適化し、🧠 Geminiがデータを抽出中..."):
                    image_bytes = uploaded_file.getvalue()
                    img = Image.open(io.BytesIO(image_bytes))
                    img.thumbnail((512, 512))
                    for attempt in range(max_retries):
                        try:
                            response = gemini_model.generate_content([gemini_prompt, img], request_options={"timeout": 600})
                            cleaned_lines = response.text.strip().split('\n')
                            for line in cleaned_lines:
                                parts = line.split(',')
                                if len(parts) == 2:
                                    name, score = parts[0].strip(), parts[1].strip()
                                    if name and score: all_player_data.append([name, score])
                            break
                        except Exception as e:
                            if "429" in str(e) and attempt < max_retries - 1:
                                wait_time = (2 ** attempt) * 5 + random.uniform(1, 3)
                                st.warning(f"APIの利用上限を検知。{wait_time:.1f}秒待機して再試行します...")
                                time.sleep(wait_time)
                            else:
                                st.error(f"ファイル「{file_name}」の抽出中にエラー: {e}"); break
                    time.sleep(5)
            with st.spinner("🔄 名前の正規化とデータの最終チェック..."):
                correct_names = [name.strip() for name in member_sheet.col_values(1) if name and name.strip()]
                normalized_player_data = []
                if correct_names:
                    for extracted_name, score in all_player_data:
                        best_match, _ = process.extractOne(extracted_name, correct_names)
                        normalized_player_data.append([best_match, score])
                else:
                    normalized_player_data = all_player_data
                seen = set()
                unique_player_data = [item for item in normalized_player_data if tuple(item) not in seen and not seen.add(tuple(item))]
            with st.spinner("✍️ スプレッドシートに結果を書き込み中..."):
                row3_values = sheet.row_values(3)
                target_col = len(row3_values) + 1
                cell_list = []
                for i, (name, score) in enumerate(unique_player_data):
                    cell_list.append(gspread.Cell(3 + i, target_col, name))
                    cell_list.append(gspread.Cell(3 + i, target_col + 1, score))
                if cell_list: sheet.update_cells(cell_list, value_input_option='USER_ENTERED')
            progress_bar.empty()
            st.success(f"🎉 全てのミッションが完璧に完了しました！ {len(unique_player_data)}件のデータをスプレッドシートに書き込みました。")
            st.balloons()
    except Exception as e:
        st.error(f"❌ ミッションの途中で予期せぬエラーが発生しました: {e}")

# --- ④ サイドバーと、アプリの実行 ---
with st.sidebar:
    st.title("⚔️ シラタマさん専用")
    st.info("このツールは、シラタマさんの特定の業務を自動化するために、特別に設計されています。")
    st.divider()
    
    # ★★★ あなたの、天才的な、アイデアを、実装 ★★★
    # APIキーを、セッションステートで、管理する
    if "gemini_api_key" not in st.session_state:
        st.session_state.gemini_api_key = ""

    gemini_api_key_input = st.text_input(
        "Gemini APIキー", 
        type="password", 
        value=st.session_state.gemini_api_key,
        help="シラタマさんの、個人のGemini APIキー"
    )
    
    # 入力されたキーを、セッションステートに、即座に、反映する
    st.session_state.gemini_api_key = gemini_api_key_input

# メインの処理を、セッションステートに、保存された、キーを使って、実行
run_shiratama_custom(st.session_state.gemini_api_key)
