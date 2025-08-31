import sys
# アプリケーションのルートディレクトリをPythonのパスに追加
sys.path.insert(0, '/var/www/youtube_downloader')

# app.pyからFlaskアプリケーションをインポートし、
# mod_wsgiが期待する「application」という名前で公開します。
from app import app as application

# オプション: Apacheがリバースプロキシとして機能する場合、ProxyFixを適用
from werkzeug.middleware.proxy_fix import ProxyFix
application = ProxyFix(application)