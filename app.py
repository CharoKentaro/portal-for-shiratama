import streamlit as st
import gspread
import google.generativeai as genai
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import streamlit_authenticator as stauth
from PIL import Image
import io
from thefuzz import process
import random
import time

# --- ① アプリの基本設定 ---
st.set_page_config(page_title="シラタマさん専用AIアシスタント", page_icon="⚔️", layout="wide")

# --- ② Google認証情報 (Secretsから読み込む) ---
try:
    google_client_id = st.secrets["GOOGLE_CLIENT_ID"]
    google_client_secret = st.secrets["GOOGLE_CLIENT_SECRET"]
    # ★重要★ デプロイ後に、Google Cloud Consoleで設定した、アプリのURL
    google_redirect_uri = st.secrets["GOOGLE_REDIRECT_URI"] 
except (KeyError, FileNotFoundError):
    st.error("🚨 重大なエラー：StreamlitのSecretsに、Google認証情報が設定されていません。")
    st.stop()

# --- ③ Streamlit Authenticator の設定 ---
authenticator = stauth.Authenticate(
    dict(st.secrets['credentials']), # Cookieの署名キー (これもSecretsで管理)
    'some_cookie_name',              # Cookie名
    'some_signature_key',            # Cookieキー
    30,                              # Cookieの有効期限（日）
    []                               # preauthorized（今回は使わない）
)

# Google OAuthのためのURLを生成
auth_url = authenticator.get_authorization_url(provider='google', 
                                              client_id=google_client_id, 
                                              redirect_uri=google_redirect_uri,
                                              scope=["https://www.googleapis.com/auth/spreadsheets", 
                                                     "https://www.googleapis.com/auth/drive"])

# --- ④ メインの処理を実行する関数 (あなたの魂のコードを移植) ---
def run_shiratama_custom(creds):
    try:
        st.header("⚔️ シラタマさん専用AIアシスタント")
        st.info("処理したいスクリーンショット画像を、すべて、ここにアップロードしてください。")

        # ファイルアップローダー
        uploaded_files = st.file_uploader("スクリーンショットを選択", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])

        if st.button("アップロードした画像のデータ抽出を実行する"):
            if not uploaded_files:
                st.warning("画像がアップロードされていません。")
                st.stop()

            # --- ここから、あなたのColabコードのロジックが、輝き始めます ---
            drive_service = build('drive', 'v3', credentials=creds)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open_by_key('1j-A8Hq5sc4_y0E07wNd9814mHmheNAnaU8iZAr3C6xo')
            sheet = spreadsheet.worksheet('遠征入力')
            member_sheet = spreadsheet.worksheet('メンバー')
            
            gemini_model = genai.GenerativeModel('gemini-1.5-flash-latest')
            gemini_prompt = """ (あなたの、あの、完璧なプロンプト) """ # (ここに、あなたのGeminiプロンプトをそのまま貼り付け)

            all_player_data = []
            max_retries = 3
            progress_bar = st.progress(0, text="処理を開始します...")

            for i, uploaded_file in enumerate(uploaded_files):
                file_name = uploaded_file.name
                progress_text = f"処理中: {i+1}/{len(uploaded_files)} - {file_name}"
                progress_bar.progress((i+1)/len(uploaded_files), text=progress_text)
                
                with st.spinner(f"🖼️ 画像を最適化し、🧠 Geminiがデータを抽出中..."):
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
                                    if name and score:
                                        all_player_data.append([name, score])
                            break # 成功したらループを抜ける
                        except Exception as e:
                            if "429" in str(e) and attempt < max_retries - 1:
                                wait_time = (2 ** attempt) * 5 + random.uniform(1, 3)
                                st.warning(f"APIの利用上限を検知。{wait_time:.1f}秒待機して再試行します...")
                                time.sleep(wait_time)
                            else:
                                st.error(f"ファイル「{file_name}」の抽出中にエラーが発生しました: {e}")
                                break
                    
                    # APIへの思いやりタイム
                    time.sleep(5)

            with st.spinner("🔄 名前の正規化と、データの最終チェックを行っています..."):
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

            with st.spinner("✍️ スプレッドシートに、結果を書き込んでいます..."):
                row3_values = sheet.row_values(3)
                target_col = len(row3_values) + 1
                cell_list = []
                for i, (name, score) in enumerate(unique_player_data):
                    cell_list.append(gspread.Cell(3 + i, target_col, name))
                    cell_list.append(gspread.Cell(3 + i, target_col + 1, score))
                
                if cell_list:
                    sheet.update_cells(cell_list, value_input_option='USER_ENTERED')

            progress_bar.empty()
            st.success(f"🎉 全てのミッションが、完璧に、完了しました！ {len(unique_player_data)}件のデータをスプレッドシートに書き込みました。")
            st.balloons()

    except Exception as e:
        st.error(f"❌ ミッションの途中で、予期せぬエラーが発生しました: {e}")


# --- ⑤ ログイン処理と、アプリの実行 ---
# URLのクエリパラメータから、認証コードを取得
try:
    auth_code = st.query_params['code']
except:
    auth_code = None

# 認証コードがあれば、トークンを取得
if auth_code:
    token = authenticator.get_token(provider='google', 
                                    client_id=google_client_id, 
                                    client_secret=google_client_secret, 
                                    redirect_uri=google_redirect_uri, 
                                    code=auth_code)
    # 取得したトークンを、Cookieに保存
    st.session_state['credentials'] = token
    # クエリパラメータを削除して、リダイレクト
    st.query_params.clear()
    st.rerun()

# Cookieに、有効なトークンがあれば、アプリを実行
if 'credentials' in st.session_state and st.session_state['credentials']:
    credentials = Credentials(**st.session_state['credentials'])
    # ★★★ ここで、メインの処理を、呼び出す！ ★★★
    run_shiratama_custom(credentials)

# 何もなければ、ログインボタンを表示
else:
    st.title("ようこそ、シラタマさん！")
    st.info("このAIアシスタントを使うには、Googleアカウントとの連携が必要です。")
    st.link_button("
