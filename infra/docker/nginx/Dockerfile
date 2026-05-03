FROM nginx:trixie

# 設定ファイルをコピー（マウントで上書きされるがフォールバックとして配置）
COPY infra/docker/nginx/nginx.conf /etc/nginx/conf.d/default.conf

# 静的ファイルをコピー（ローカルではボリュームマウントで上書きされる）
COPY front/ /var/www/html/
