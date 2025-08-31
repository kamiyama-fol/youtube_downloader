from flask import Flask, render_template, request, send_file, flash, jsonify, redirect
import os
import threading
import uuid
import yt_dlp
import shutil # ディレクトリ内のファイルを削除するために追加
from functools import wraps
import requests
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = 'your_secret_key_here' # フラッシュメッセージ用に秘密鍵を設定

# --- ここから追加 ---
# Configuration from environment variables
load_dotenv()  
LARAVEL_URL = os.environ.get('LARAVEL_URL', 'https://keion-reserve.mints.ne.jp')
LARAVEL_AUTH_CHECK_URL = f"{LARAVEL_URL}/api/check-auth"
LARAVEL_LOGIN_URL = f"{LARAVEL_URL}/login"
LARAVEL_COOKIE_NAME = os.environ.get('LARAVEL_COOKIE_NAME', 'ksu_keion_reserve_session')

# アプリケーションのベースディレクトリを取得
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ダウンロードしたファイルを一時的に保存するディレクトリ
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

#Laravelでの認証を要求するデコレーター
# def laravel_auth_required(f):
#     @wraps(f)
#     def decorated_function(*args, **kwargs):
#         # ブラウザからLaravelのセッションクッキーを取得
#         # クッキー名はLaravelの config/session.php の 'cookie' の値です (デフォルトは 'laravel_session')
#         laravel_session_cookie = request.cookies.get(LARAVEL_COOKIE_NAME)

#         if not laravel_session_cookie:
#             # クッキーがなければ未認証なのでログインページへリダイレクト
#             print(f"[DEBUG] Cookie '{LARAVEL_COOKIE_NAME}' not found. Redirecting to login.")
#             return redirect(LARAVEL_LOGIN_URL)

#         # クッキーをそのままLaravelのAPIへ転送して認証状態を確認
#         cookies = {
#             LARAVEL_COOKIE_NAME: laravel_session_cookie
#         }
#         # APIリクエストであることをLaravelに伝えるためのヘッダー
#         headers = {
#             'Accept': 'application/json'
#         }
        
#         print(f"[DEBUG] Sending auth check request to {LARAVEL_AUTH_CHECK_URL}")
#         try:
#             # 本番環境では verify=True にし、適切なSSL証明書を使用してください
#             # allow_redirects=False を追加して、リダイレクトを自動で追跡しないようにする
#             response = requests.get(
#                 LARAVEL_AUTH_CHECK_URL,
#                 cookies=cookies,
#                 headers=headers,
#                 timeout=5,
#                 verify=False,
#                 allow_redirects=False
#             )
            
#             print(f"[DEBUG] Auth check response status code: {response.status_code}")
#             # 認証成功（ステータスコード 200）かチェック
#             if response.status_code == 200:
#                 try:
#                     user_data = response.json()
#                     print(f"[DEBUG] Auth check response JSON: {user_data}")
#                     # レスポンスがJSONで、かつユーザー情報(例: id)が含まれているか確認
#                     if user_data and 'id' in user_data:
#                         # 認証済みなので、元の処理を続行
#                         print("[DEBUG] Authentication successful. Proceeding.")
#                         return f(*args, **kwargs)
#                     else:
#                         # ステータスは200だが、期待したユーザー情報が含まれていない
#                         print("[DEBUG] Status is 200, but user data is invalid. Redirecting to login.")
#                         return redirect(LARAVEL_LOGIN_URL)
#                 except requests.exceptions.JSONDecodeError:
#                     # ステータスは200だが、JSONではない（ログインページHTMLなど）
#                     print("[DEBUG] Status is 200, but response is not JSON. Redirecting to login.")
#                     return redirect(LARAVEL_LOGIN_URL)
#             else:
#                 # 認証失敗（リダイレクト、401 Unauthorizedなど）
#                 print(f"[DEBUG] Auth check failed with status {response.status_code}. Redirecting to login.")
#                 return redirect(LARAVEL_LOGIN_URL)

#         except requests.exceptions.RequestException as e:
#             # Laravelサーバーに接続できない場合のエラーハンドリング
#             print(f"[DEBUG] Exception during auth check request: {e}")
#             return "認証サービスが利用できません。", 503

#     return decorated_function

# ダウンロード進捗と完了状態を管理する辞書
download_progress = {}

# yt-dlpのダウンロードフック
def yt_dlp_progress_hook(d, session_id):
    if session_id not in download_progress:
        download_progress[session_id] = {'status': '初期化中', 'progress': 0, 'download_url': None, 'error': None, 'filename': None, 'title': None, 'download_type': None}

    if d['status'] == 'downloading':
        download_progress[session_id]['status'] = 'ダウンロード中'
        if '_percent_str' in d:
            try:
                percentage_str = d['_percent_str'].strip().replace('%', '')
                download_progress[session_id]['progress'] = int(float(percentage_str))
            except ValueError:
                pass 
        elif 'total_bytes' in d and 'downloaded_bytes' in d:
            if d['total_bytes'] > 0:
                download_progress[session_id]['progress'] = int((d['downloaded_bytes'] / d['total_bytes']) * 100)
        
        if 'speed' in d:
            download_progress[session_id]['speed'] = d['_speed_str']
        if 'eta' in d:
            download_progress[session_id]['eta'] = d['_eta_str']
        
        print(f"[{session_id}] [yt-dlp] {download_progress[session_id]['progress']}% {download_progress[session_id].get('speed', '')} ETA {download_progress[session_id].get('eta', '')}")

    elif d['status'] == 'finished':
        download_progress[session_id]['progress'] = 100
        download_progress[session_id]['status'] = '処理中 (結合)'
        print(f"[{session_id}] [yt-dlp] 個別ダウンロード完了。結合処理を開始します。")

    elif d['status'] == 'error':
        download_progress[session_id]['status'] = 'エラー'
        download_progress[session_id]['error'] = d.get('error', '不明なダウンロードエラー')
        print(f"[{session_id}] [yt-dlp] エラー: {d.get('error')}")

# バックグラウンドダウンロード処理
def background_download(video_url, download_type, session_id, custom_filename=None):
    # 初期状態を設定
    download_progress[session_id] = {
        'status': '準備中', 
        'progress': 0, 
        'download_url': None, 
        'error': None,
        'filename': None,
        'title': None,
        'download_type': download_type
    }

    try:

        # yt-dlpオプションの設定
        ydl_opts = {
            'progress_hooks': [lambda d: yt_dlp_progress_hook(d, session_id)],
            'no_warnings': True,
            'quiet': True,       
            'format': 'bestvideo[ext=mp4][vcodec=h264]+bestaudio[ext=m4a]/best[ext=mp4]',
            'restrictfilenames': True, # ファイル名の制限は維持
            'verbose': True, # デバッグのため詳細ログを有効に（問題解決後は False に戻すか削除）
        }

        # ダウンロード前にメタデータを取得し、タイトルとIDを保存
        info_dict = yt_dlp.YoutubeDL({'quiet': True}).extract_info(video_url, download=False)
        video_title = info_dict.get('title', 'unknown_video')
        video_id = info_dict.get('id', 'unknown_id')
        
        download_progress[session_id]['title'] = video_title 
        download_progress[session_id]['video_id'] = video_id

        # 最終的なファイル名を決定
        # ユーザーがカスタムファイル名を指定した場合、それを使用
        if custom_filename:
            # yt-dlpは自動で拡張子を付与するため、ここでは拡張子なしの名前を指定
            base_filename = custom_filename
            # outtmpl にはディレクトリとベースファイル名を指定
            ydl_opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, base_filename + '.%(ext)s')
            # ダウンロード名として使うための最終的な拡張子を予測
            expected_ext = 'mp4' if download_type == 'mp4' else 'mp3'
            final_download_name = f"{base_filename}.{expected_ext}"
        else:
            # カスタムファイル名がない場合、動画タイトル（安全な形式）か動画IDを使用
            # restrictfilenames: True のため、yt-dlpが安全なファイル名を生成する
            # ここでは、yt-dlpが生成するであろうファイル名を予測する
            # 最も確実なのは %(id)s を使うことだが、ユーザーフレンドリーなタイトルを優先
            # yt-dlpの内部的なファイル名サニタイズを考慮し、ここでは %(title)s を使う
            # ただし、yt-dlpが実際に生成するファイル名と完全に一致させるのは難しい場合がある
            # そのため、最終的なファイルパスは 'info_dict.get('_filename')' で取得するのが理想だが、
            # それが None になる問題が報告されているため、今回はカスタムファイル名優先ロジックを適用
            ydl_opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s')
            expected_ext = 'mp4' if download_type == 'mp4' else 'mp3'
            # ダウンロード名には元の動画タイトルと予測拡張子を使用
            final_download_name = f"{video_title}.{expected_ext}"


        if download_type == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{    
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            # outtmpl は既に上で設定済み

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # 実際のダウンロード処理を実行。FFmpegによる結合・変換もここで完了
            ydl.download([video_url]) 
            
            # yt-dlpのダウンロードとポストプロセッシングが全て完了した後、
            # 最終的なファイルパスをyt-dlpから取得
            # 以前の課題で `_filename` が None になることがあったため、
            # ここで再取得を試みるが、確実性を高めるため予測パスも利用する
            final_info_dict = ydl.extract_info(video_url, download=False)
            yt_dlp_actual_filename = final_info_dict.get('_filename')

            # 最終的に確認するファイルパスを決定
            if yt_dlp_actual_filename and os.path.exists(yt_dlp_actual_filename):
                final_file_path = yt_dlp_actual_filename
                print(f"[{session_id}] Post-download check - Actual final path from yt-dlp: {final_file_path}")
            else:
                # yt-dlpが_filenameを返さない場合やファイルが見つからない場合のフォールバック
                # custom_filenameが指定されていればそれを使用、そうでなければyt-dlpのデフォルト命名規則を予測
                if custom_filename:
                    # ユーザーが指定したファイル名と予測される拡張子でパスを構築
                    final_file_path = os.path.join(DOWNLOAD_DIR, f"{base_filename}.{expected_ext}")
                else:
                    # yt-dlpがタイトルをサニタイズして生成するファイル名を予測
                    # これは正確ではない可能性があるが、他に確実な方法がないため試みる
                    # 最も安全なのは %(id)s を outtmpl に使うことだが、ユーザーフレンドリーなタイトルを優先するため
                    # ここではyt-dlpのデフォルトのファイル名生成ロジックを模倣する
                    # yt-dlpはタイトルに含まれるファイルシステムで無効な文字を自動で置き換える
                    # 厳密な予測は難しいため、ここではyt-dlpが内部的に生成したファイル名を再度取得する試みが重要
                    # しかし、それがNoneになる問題があるため、最終手段としてタイトルベースの予測を行う
                    # もしyt_dlp_actual_filenameがNoneだった場合、yt-dlpのログから実際のファイル名を手動で確認し、
                    # この予測ロジックを調整する必要があるかもしれません。
                    # 現状では、yt-dlpが最終的に作成したファイル名を正確に取得できていないことが根本原因です。
                    # ここでは、yt-dlpが作成したファイル名が何であれ、ダウンロードディレクトリをスキャンして見つけるロジックを検討すべきです。
                    
                    # 暫定的な解決策として、yt-dlpが生成するであろうファイル名を再度予測
                    # 実際にはyt-dlpの内部的なファイル名サニタイズロジックに依存するため、完全ではない
                    # ログから 'Chinozo_by.mp4' のような形式が確認されているため、それを考慮
                    # 厳密には yt-dlp がダウンロード後に返す info_dict['_filename'] が最も正しい
                    # その値が None になる問題が解決されれば、このフォールバックは不要になる
                    # ここでは、yt-dlpが生成するファイル名が予測できない場合の最終手段として、
                    # ダウンロードディレクトリ内の最新のファイルを探すロジックを検討する
                    
                    # 今回は、yt_dlp_actual_filenameがNoneの場合に、
                    # ユーザーが指定したcustom_filenameがある場合はそれを使う、
                    # ない場合はvideo_idをベースにしたファイル名を予測する、というロジックを適用します。
                    # これにより、少なくとも予測可能なファイル名でチェックするようにします。
                    final_file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{expected_ext}")
                
                print(f"[{session_id}] Post-download check - Fallback expected path: {final_file_path}")


            # 最終的なファイルの存在確認とdownload_progressの更新
            if os.path.exists(final_file_path):
                download_progress[session_id]['download_url'] = f'/download_file/{session_id}'
                download_progress[session_id]['actual_file_path'] = final_file_path
                # ユーザーへのダウンロード名には、カスタムファイル名があればそれ、なければ元のタイトルを使用
                download_progress[session_id]['filename'] = final_download_name 
                download_progress[session_id]['status'] = '完了'
                download_progress[session_id]['progress'] = 100
                print(f"[{session_id}] 最終ダウンロード完了: {final_file_path}")
            else:
                download_progress[session_id]['status'] = 'エラー'
                error_message = f"最終ファイルが見つかりません。ダウンロードまたは結合に失敗しました。(パス: '{final_file_path}' にファイルが存在しませんでした。)"
                download_progress[session_id]['error'] = error_message
                print(f"[{session_id}] エラー: {error_message}")


    except yt_dlp.utils.DownloadError as e:
        error_msg = f"yt-dlpダウンロードエラー: {e}"
        download_progress[session_id]['error'] = error_msg
        download_progress[session_id]['status'] = 'エラー'
        print(f"[{session_id}] エラー: {error_msg}")
    except Exception as e:
        error_msg = f"予期せぬエラーが発生しました: {e}"
        download_progress[session_id]['error'] = error_msg
        download_progress[session_id]['status'] = 'エラー'
        print(f"[{session_id}] エラー: {e}")

@app.route('/', methods=['GET', 'POST'])
# @laravel_auth_required
def index():
    if request.method == 'POST':
        video_url = request.form['video_url']
        download_type = request.form['download_type']
        custom_filename = request.form.get('custom_filename') # カスタムファイル名を取得
        session_id = str(uuid.uuid4()) # ユニークなセッションIDを生成

        if not video_url:
            flash('YouTubeのURLを入力してください。', 'error')
            return render_template('index.html')

        # バックグラウンドスレッドでダウンロードを開始
        thread = threading.Thread(target=background_download, args=(video_url, download_type, session_id, custom_filename))
        thread.start()

        flash(f'ダウンロードリクエストを受け付けました。進捗状況を確認してください。', 'info')
        # セッションIDをフロントエンドに渡す
        return render_template('index.html', session_id=session_id)

    return render_template('index.html')

# ダウンロード進捗状況を提供するエンドポイント
@app.route('/progress/<session_id>')
# @laravel_auth_required
def progress(session_id):
    progress_info = download_progress.get(session_id, {'status': '待機中', 'progress': 0, 'error': None})
    return jsonify(progress_info)

# 実際のファイルを送信するエンドポイント
@app.route('/download_file/<session_id>')
#@laravel_auth_required
def download_file(session_id):
    progress_info = download_progress.get(session_id)
    if progress_info and progress_info['status'] == '完了' and progress_info['actual_file_path']:
        file_path = progress_info['actual_file_path']
        filename = progress_info['filename'] # ユーザーに表示するダウンロード名
        if os.path.exists(file_path):
            # ファイル送信後、辞書から情報を削除（任意、サーバー負荷軽減）
            # del download_progress[session_id] # デバッグ中はコメントアウトしても良い
            return send_file(file_path, as_attachment=True, download_name=filename) 
        else:
            return jsonify({'status': 'エラー', 'error': 'ファイルが見つかりません。サーバーから削除された可能性があります。'}), 404
    elif progress_info and progress_info['status'] == 'エラー':
        return jsonify({'status': 'エラー', 'error': progress_info['error']}), 500
    else:
        # ダウンロードが完了していない、または情報がない場合
        return jsonify({'status': '待機中', 'progress': progress_info.get('progress', 0), 'error': 'ダウンロードがまだ完了していません。'}), 202

@app.route('/clear_progress', methods=['POST'])
# @laravel_auth_required
def clear_progress():
    # ダウンロードディレクトリ内の既存ファイルを削除
    print(f"ダウンロードディレクトリ '{DOWNLOAD_DIR}' 内の既存ファイルを削除します。")
    for item in os.listdir(DOWNLOAD_DIR):
        item_path = os.path.join(DOWNLOAD_DIR, item)
        if os.path.isfile(item_path): # ファイルのみを削除（サブディレクトリは削除しない）
            try:
                os.remove(item_path)
                print(f"  - 削除済み: {item_path}")
            except Exception as e:
                print(f"  - 削除失敗: {item_path} - {e}")
    print(f"既存ファイルの削除が完了しました。")
    return jsonify({'status': 'success', 'message': 'ダウンロードディレクトリをクリアしました。'})

if __name__ == '__main__':
    app.run(debug=True, threaded=True)