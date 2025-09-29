import streamlit as st
import gspread
# ↓↓↓【痛恨のミス】この行のタイプミスを修正しました ↓↓↓
import google.generativeai as genai
from googleapiclient.discovery import build
from google.oauth2 import service_account
from PIL import Image
import io
from thefuzz import process
import random
import time
from streamlit_local_storage import LocalStorage

# --- アプリの最上部あたりに追加 ---
st.write(f"現在のgoogle-generativeaiライブラリのバージョン: {genai.__version__}")


# --- ↓ ここから新しいデバッグコードを追加してください ↓ ---
#try:
#    st.subheader("現在利用可能なモデルのリスト:")
#    models_list = []
    # 'generateContent' をサポートするモデルのみをリストアップ
#    for m in genai.list_models():
#        if 'generateContent' in m.supported_generation_methods:
#            models_list.append(m.name)
    
    # 見やすく箇条書きで表示
 #   st.write(models_list)
    
    # 今回使いたいモデルが含まれているかチェック
 #   if 'models/gemini-1.5-flash-latest' in models_list:
 #       st.success("✅ 'gemini-1.5-flash-latest' は利用可能なモデルリストに含まれています。")
 #   else:
 #       st.error("❌ 'gemini-1.5-flash-latest' は利用可能なモデルリストに含まれていません。")

#except Exception as e:
#    st.error(f"モデルリストの取得中にエラーが発生しました: {e}")
# --- ↑ ここまでデバッグコードを追加してください ↑ ---


# --- ① アプリの基本設定 ---
st.set_page_config(page_title="白玉さん専用AIアシスタント", page_icon="⚔️", layout="wide")

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

# --- ③ ローカルストレージの準備 ---
localS = LocalStorage()

# --- ④ メインの処理を実行する関数 ---
def run_shiratama_custom(gemini_api_key):
    try:
        st.header("✨ まほろば！ ✨")
        st.info("処理したいスクリーンショット画像を、すべて、ここにアップロードしてください。")
        uploaded_files = st.file_uploader("スクリーンショットを選択", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])

        if "review_messages" not in st.session_state:
            st.session_state.review_messages = []

        # --- ステップ1：処理の選択 ---
        st.subheader("1. 実行したい処理を選択してください")
        selected_task = st.radio(
            "処理の選択:",
            ("⚔️ 遠征入力", "🗺️ 探索入力"),
            horizontal=True,
            label_visibility="collapsed"
        )
        
        # --- ステップ2：実行 ---
        st.subheader("2. データ抽出を実行します")
        if st.button(f"「{selected_task}」を実行する", use_container_width=True, type="primary"):
            st.session_state.review_messages = []
            if not uploaded_files: st.warning("画像がアップロードされていません。"); st.stop()
            if not gemini_api_key: st.warning("サイドバーでGemini APIキーを入力し、保存してください。"); st.stop()
            
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key('1j-A8Hq5sc4_y0E07wNd9814mHmheNAnaU8iZAr3C6xo')
            member_sheet = spreadsheet.worksheet('メンバー')
            
            genai.configure(api_key=gemini_api_key)
            gemini_model = genai.GenerativeModel('gemini-flash-latest')
            gemini_prompt = """
            あなたは、与えられたゲームのスクリーンショット画像を直接解析する、超高精度のデータ抽出AIです。
            あなたの使命は、画像の中から「プレイヤー名」と「スコア」のペアだけを完璧に抽出し、指定された形式で出力することです。
            #厳格なルール
            1. 画像を直接、あなたの目で見て、文字を認識してください。
            2. 認識した文字の中から、「プレイヤー名」と、その右側あるいは下の行にある「数値（スコア）」のペアのみを抽出対象とします。
            3. 画像に含まれる「ギルド対戦」「ラウンド」「<」「>」「|S」「A」のような、UIテキスト、無関係な記号、ランクを示すアルファベットは、思考の過程から完全に除外してください。
            4. プレイヤー名は、日本語、英語、数字が混在することがあります（例: `korosuke94`, `あーる 0113`）。また、数字のみの場合もあります (例： `3666666666666663`)。これらも、一つの名前として正しく認識してください。
            5. 最終的なアウトプットは、一行につき「名前,数値」の形式で、カンマ区切りで出力してください。
            6. いかなる場合でも、ルールに記載された以外の説明、前置き、後書きは、絶対に出力しないでください。
            このルールを完璧に理解し、最高の精度で、任務を遂行してください。
            #補足
            同じプレイヤー名が重複している場合があります。混乱する必要はありませんので、上記のルールに従ってください。
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
                    time.sleep(1)
            
            with st.spinner("🔄 名前の正規化（デュアルスコアVer）とデータの最終チェック..."):
                correct_names = [name.strip() for name in member_sheet.col_values(1) if name and name.strip()]
                normalized_player_data = []
                similarity_threshold = 85
                if correct_names:
                    for extracted_name, score in all_player_data:
                        best_candidate = None
                        highest_final_score = -1
                        for candidate_name in correct_names:
                            similarity = process.fuzz.ratio(extracted_name, candidate_name)
                            len_diff = abs(len(extracted_name) - len(candidate_name))
                            penalty = len_diff * 15
                            final_score = similarity - penalty
                            if final_score > highest_final_score:
                                highest_final_score = final_score
                                best_candidate = (candidate_name, similarity)
                        
                        if best_candidate:
                            if highest_final_score <= 0:
                                review_message = f"🚨 **処理不可:** AIは「`{extracted_name}`」と読み取りましたが、候補との一致度が0点でした。書き換えを行せず、手動確認をお願いします。"
                                st.session_state.review_messages.append(review_message)
                                normalized_player_data.append([f"【要確認】{extracted_name}", score])
                            else:
                                final_name, final_similarity = best_candidate
                                if highest_final_score < similarity_threshold:
                                    review_message = f"⚠️ **要確認:** AIは「`{extracted_name}`」と読み取りましたが、総合判断の結果「**`{final_name}`**」として処理しました。（総合点: {highest_final_score}点）"
                                    st.session_state.review_messages.append(review_message)
                                normalized_player_data.append([final_name, score])
                        else:
                            review_message = f"🚨 **処理不可:** AIは「`{extracted_name}`」と読み取りましたが、メンバーリストに一致する候補が見つかりませんでした。手動で確認してください。"
                            st.session_state.review_messages.append(review_message)
                            normalized_player_data.append([f"【要確認】{extracted_name}", score])
                else:
                    normalized_player_data = all_player_data
                seen = set()
                unique_player_data = [item for item in normalized_player_data if tuple(item) not in seen and not seen.add(tuple(item))]

            if selected_task == "⚔️ 遠征入力":
                with st.spinner("✍️ スプレッドシートに結果を書き込み中..."):
                    sheet = spreadsheet.worksheet('遠征入力')
                    row3_values = sheet.row_values(3)
                    target_col = len(row3_values) + 1
                    cell_list = []
                    for i, (name, score) in enumerate(unique_player_data):
                        cell_list.append(gspread.Cell(3 + i, target_col, name))
                        cell_list.append(gspread.Cell(3 + i, target_col + 1, score))
                    if cell_list: sheet.update_cells(cell_list, value_input_option='USER_ENTERED')
                st.success(f"🎉 遠征入力完了！ {len(unique_player_data)}件のデータをスプレッドシートに書き込みました。")

            elif selected_task == "🗺️ 探索入力":
                with st.spinner("✍️ スプレッドシートに結果を書き込み中..."):
                    sheet = spreadsheet.worksheet('探索入力')
                    cell_list = []
                    for i, (name, score) in enumerate(unique_player_data):
                        cell_list.append(gspread.Cell(3 + i, 1, name))
                        cell_list.append(gspread.Cell(3 + i, 2, score))
                    if cell_list: sheet.update_cells(cell_list, value_input_option='USER_ENTERED')
                st.success(f"🎉 探索入力完了！ {len(unique_player_data)}件のデータをスプレッドシートに書き込みました。")

            progress_bar.empty()
            st.balloons()
            
        if st.session_state.review_messages:
            st.divider()
            st.warning("🤖 AIからの、確認依頼があります")
            for msg in st.session_state.review_messages:
                st.markdown(msg)

    except Exception as e:
        st.error(f"❌ ミッションの途中で予期せぬエラーが発生しました: {e}")

# --- ⑤ サイドバーと、APIキー入力 ---
with st.sidebar:
    st.title("✨白玉さん専用")
    st.info("このツールは、特定の業務を自動化するために、特別に設計されています。")
    st.divider()
    
    saved_key = localS.getItem("gemini_api_key")
    default_value = saved_key['value'] if isinstance(saved_key, dict) and 'value' in saved_key else ""
    
    gemini_api_key_input = st.text_input(
        "Gemini APIキー", 
        type="password", 
        value=default_value,
        help="白玉さんの、個人のGemini APIキー"
    )
    
    if st.button("このAPIキーをブラウザに記憶させる"):
        localS.setItem("gemini_api_key", gemini_api_key_input)
        st.success("キーを記憶しました！")

# --- ⑥ メイン処理の、実行 ---
run_shiratama_custom(gemini_api_key_input)
