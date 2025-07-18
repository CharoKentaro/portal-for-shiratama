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
st.set_page_config(page_title="白玉さん専用AIアシスタント", page_icon="⚔️", layout="wide")

# --- ② 認証情報 (Secretsから、サービスアカウント情報を、読み込む) ---
try:
    # ★★★ ここが、最後の、そして、本当の、究極の、バグ修正箇所 ★★★
    # 1. まず、神聖な、金庫（st.secrets）から、データを、そのまま、取り出す
    secrets_creds = st.secrets["gcp_service_account"]
    
    # 2. 別の、普通の、宝箱に、中身を、コピーする
    creds_dict = dict(secrets_creds)
    
    # 3. 普通の、宝箱の、中身を、加工する
    creds_dict["private_key"] = creds_dict["private_key"].replace('\\n', '\n')
    
    # 4. 加工済みの、宝箱を使って、認証を行う
    creds = service_account.Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    )
except (KeyError, FileNotFoundError):
    st.error("🚨 重大なエラー：StreamlitのSecretsに、GCPのサービスアカウント情報が正しく設定されていません。")
    st.stop()

# --- 修正：streamlit-local-storageを安全に初期化 ---
def safe_local_storage_init():
    """Local storageを安全に初期化する関数"""
    try:
        from streamlit_local_storage import LocalStorage
        return LocalStorage()
    except ImportError:
        st.warning("streamlit-local-storageがインストールされていません。APIキーの記憶機能は無効になります。")
        return None
    except Exception as e:
        st.warning(f"Local storageの初期化に失敗しました: {e}")
        return None

# Local storageの初期化
localS = safe_local_storage_init()

def get_saved_api_key():
    """保存されたAPIキーを安全に取得する関数"""
    if localS is None:
        return ""
    
    try:
        saved_key = localS.getItem("gemini_api_key")
        if isinstance(saved_key, dict) and 'value' in saved_key:
            return saved_key['value']
        return ""
    except Exception as e:
        st.warning(f"保存されたAPIキーの取得に失敗しました: {e}")
        return ""

def save_api_key(api_key):
    """APIキーを安全に保存する関数"""
    if localS is None:
        st.warning("Local storageが利用できないため、APIキーを保存できません。")
        return False
    
    try:
        localS.setItem("gemini_api_key", api_key)
        return True
    except Exception as e:
        st.warning(f"APIキーの保存に失敗しました: {e}")
        return False

def run_shiratama_custom(gemini_api_key):
    try:
        st.header("✨ 白玉さん専用AIアシスタント")
               
        st.info("処理したいスクリーンショット画像を、すべて、ここにアップロードしてください。")
        uploaded_files = st.file_uploader("スクリーンショットを選択", accept_multiple_files=True, type=['png', 'jpg', 'jpeg'])
        if st.button("アップロードした画像のデータ抽出を実行する"):
            if not uploaded_files: st.warning("画像がアップロードされていません。"); st.stop()
            if not gemini_api_key: st.warning("サイドバーでGemini APIキーを入力し、保存してください。"); st.stop()
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
            5. プレイヤー名を抽出する際は、文字数も重要な判断基準です。短い名前（例：「暇神」）と長い名前（例：「脱臼大明神」）を正確に区別してください。
            6. 最終的なアウトプットは、一行につき「名前,数値」の形式で、カンマ区切りで出力してください。
            7. いかなる場合でも、ルールに記載された以外の説明、前置き、後書きは、絶対に出力しないでください。
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
                        # 文字数を考慮した改良版マッチング
                        extracted_len = len(extracted_name)
                        
                        # 候補を文字数でフィルタリング（±2文字以内）
                        length_filtered_names = [name for name in correct_names 
                                               if abs(len(name) - extracted_len) <= 2]
                        
                        if length_filtered_names:
                            # 文字数が近い候補の中から最適なマッチを選択
                            best_match, similarity = process.extractOne(extracted_name, length_filtered_names)
                            
                            # 文字数が完全一致する候補があるかチェック
                            exact_length_matches = [name for name in length_filtered_names 
                                                  if len(name) == extracted_len]
                            if exact_length_matches:
                                # 文字数が完全一致する中から最適なマッチを選択
                                best_match, _ = process.extractOne(extracted_name, exact_length_matches)
                            
                            normalized_player_data.append([best_match, score])
                        else:
                            # 文字数フィルタで候補がない場合は、全体から選択
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
        import traceback
        error_details = traceback.format_exc()
        st.error(f"❌ ミッションの途中で予期せぬエラーが発生しました: {e}")
        st.error(f"詳細なエラー情報:")
        st.code(error_details)
        st.error(f"エラーの種類: {type(e).__name__}")
        st.error(f"エラーメッセージ: {str(e)}")

# --- サイドバー ---
with st.sidebar:
    st.title("⚔️ シラタマさん専用")
    st.info("このツールは、特定の業務を自動化するために、特別に設計されています。")
    st.divider()
    
    # APIキーの取得と入力
    default_value = get_saved_api_key()
    gemini_api_key_input = st.text_input("Gemini APIキー", type="password", value=default_value, help="シラタマさんの、個人のGemini APIキー")
    
    # APIキーの保存
    if st.button("このAPIキーをブラウザに記憶させる"):
        if save_api_key(gemini_api_key_input):
            st.success("キーを記憶しました！")
        else:
            st.error("キーの保存に失敗しました。")

# メイン処理の実行
run_shiratama_custom(gemini_api_key_input)
