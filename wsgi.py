import sys
import os

# プロジェクトのルートディレクトリをPythonのパスに追加
# 'your_username' と 'youtube_downloader_app' は実際のパスに合わせてください
PROJECT_HOME = u'/home/ksu-keion/www/youtube_downloader'
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

# 仮想環境のアクティベート
# 'venv' は仮想環境のディレクトリ名
activate_this = os.path.join(PROJECT_HOME, 'venv', 'bin', 'activate_this.py')
with open(activate_this) as f:
    exec(f.read(), dict(__file__=activate_this))

# Flaskアプリケーションをインポート
# 'app' は app.py の Flask インスタンスの名前（通常は app = Flask(__name__) の app）
from app import app as application

# GunicornなどWSGIサーバーはこの application オブジェクトを呼び出します