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
from streamlit_local_storage import LocalStorage

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


# --- A. 画像からデータを抽出する共通関数 ---
def extract_data_from_images(uploaded_files, gemini_model, gemini_prompt):
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
            
    progress_bar.empty()
    return all_player_data

# --- B. 名前を正規化する共通関数 ---
def normalize_names(all_player_data, member_sheet):
    with st.spinner("🔄 名前の正規化（デュアルスコアVer）とデータの最終チェック..."):
        correct_names = [name.strip() for name in member_sheet.col_values(1) if name and name.strip()]
        normalized_player_data = []
        review_messages = []
        similarity_threshold = 85

        if not correct_names:
            return all_player_data, ["⚠️メンバーリストが取得できませんでした。名前の正規化をスキップします。"]

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
                final_name, final_similarity = best_candidate
                if highest_final_score >= similarity_threshold:
                    normalized_player_data.append([final_name, score])
                else:
                    review_message = f"⚠️ **要確認:** AIは「`{extracted_name}`」と読み取りました。最も近い候補は「**`{final_name}`**」ですが、スコアが低かったため書き換えませんでした。手動で確認してください。（総合点: {highest_final_score}点 / 類似度: {final_similarity}点）"
                    review_messages.append(review_message)
                    normalized_player_data.append([f"【要確認】{extracted_name}", score])
            else:
                review_message = f"🚨 **処理不可:** AIは「`{extracted_name}`」と読み取りましたが、メンバーリストに一致する候補が見つかりませんでした。手動で確認してください。"
                review_messages.append(review_message)
                normalized_player_data.append([f"【要確認】{extracted_name}", score])
        
        seen = set()
        unique_player_data = [item for item in normalized_player_data if tuple(item) not in seen and not seen.add(tuple(item))]
        return unique_player_data, review_messages

# --- C. スプレッドシートに書き込む共通関数 ---
def write_data_to_sheet(sheet, data, start_row, name_col, score_col):
    with st.spinner("✍️ スプレッドシートに結果を書き込み中..."):
        cell_list = []
        for i, (name, score) in enumerate(data):
            cell_list.append(gspread.Cell(start_row + i, name_col, name))
            cell_list.append(gspread.Cell(start_row + i, score_col, score))
        if cell_list:
            sheet.update_cells(cell_list, value_input_option='USER_ENTERED')

# --- ④ メインの処理を実行する関数 ---
def run_shiratama_custom(gemini_api_key):
    try:
        st.header("✨ まほろば！ ✨")
        
        # --- ステップ1：処理の選択 ---
        st.subheader("1. 実行したい処理を選択してください")
        selected_task = st.radio(
            "処理の選択:",
            ("⚔️ 遠征データ抽出", "🗺️ 探索結果抽出"),
            horizontal=True,
            label_visibility="collapsed"
        )

        if "review_messages" not in st.session_state:
            st.session_state.review_messages = []

        if selected_task:
            # --- ステップ2：画像のアップロード ---
            st.subheader("2. 処理したいスクリーンショット画像をアップロードしてください")
            uploaded_files = st.file_uploader(
                "スクリーンショットを選択",
                accept_multiple_files=True,
                type=['png', 'jpg', 'jpeg'],
                key=f"uploader_{selected_task}" # 選択に応じてキーを変更
            )

            # --- ステップ3：実行ボタン ---
            st.subheader("3. データ抽出を実行します")
            if st.button(f"「{selected_task}」を実行する", use_container_width=True, type="primary"):
                st.session_state.review_messages = []
                if not uploaded_files: st.warning("画像がアップロードされていません。"); st.stop()
                if not gemini_api_key: st.warning("サイドバーでGemini APIキーを入力し、保存してください。"); st.stop()
                
                # GeminiとGoogle Sheetsの準備
                gc = gspread.authorize(creds)
                spreadsheet = gc.open_by_key('1j-A8Hq5sc4_y0E07wNd9814mHmheNAnaU8iZAr3C6xo')
                member_sheet = spreadsheet.worksheet('メンバー')
                genai.configure(api_key=gemini_api_key)
                gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
                
                # 選択されたタスクに応じて処理を分岐
                if selected_task == "⚔️ 遠征データ抽出":
                    gemini_prompt = """
                    あなたは、与えられたゲームのスクリーンショット画像を直接解析する、超高精度のデータ抽出AIです。
                    あなたの使命は、画像の中から「プレイヤー名」と「スコア」のペアだけを完璧に抽出し、指定された形式で出力することです。
                    #厳格なルール
                    (以下、プロンプト内容は既存のものと同じなので省略)
                    """
                    # ステップ実行
                    all_data = extract_data_from_images(uploaded_files, gemini_model, gemini_prompt)
                    unique_data, review_msgs = normalize_names(all_data, member_sheet)
                    st.session_state.review_messages.extend(review_msgs)
                    
                    # 「遠征入力」シートの書き込み位置を計算
                    sheet_to_write = spreadsheet.worksheet('遠征入力')
                    row3_values = sheet_to_write.row_values(3)
                    target_col = len(row3_values) + 1
                    write_data_to_sheet(sheet_to_write, unique_data, start_row=3, name_col=target_col, score_col=target_col + 1)
                    
                    st.success(f"🎉 遠征データ抽出完了！ {len(unique_data)}件のデータをスプレッドシートに書き込みました。")
                    st.balloons()
                
                elif selected_task == "🗺️ 探索結果抽出":
                    gemini_prompt = """
                    あなたは、与えられたゲームのスクリーンショット画像を直接解析する、超高精度のデータ抽出AIです。
                    あなたの使命は、画像の中から「キャラクター名」と「スコア」のペアだけを完璧に抽出し、指定された形式で出力することです。
                    #厳格なルール
                    (以下、プロンプト内容は既存のものとほぼ同じ。「プレイヤー名」を「キャラクター名」に変更)
                    """
                    # ステップ実行
                    all_data = extract_data_from_images(uploaded_files, gemini_model, gemini_prompt)
                    unique_data, review_msgs = normalize_names(all_data, member_sheet)
                    st.session_state.review_messages.extend(review_msgs)

                    # 「探索入力」シートのA3, B3から書き込み
                    sheet_to_write = spreadsheet.worksheet('探索入力')
                    write_data_to_sheet(sheet_to_write, unique_data, start_row=3, name_col=1, score_col=2)
                    
                    st.success(f"🎉 探索結果抽出完了！ {len(unique_data)}件のデータをスプレッドシートに書き込みました。")
                    st.balloons()

        # --- 処理完了後の共通メッセージ表示 ---
        if st.session_state.review_messages:
            st.divider()
            st.warning("🤖 AIからの、確認依頼があります")
            for msg in st.session_state.review_messages:
                st.markdown(msg)

    except gspread.exceptions.WorksheetNotFound as e:
        st.error(f"🚨 重大なエラー：指定されたワークシートが見つかりません。シート名を確認してください: {e}")
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
