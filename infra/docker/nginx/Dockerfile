FROM nginx:trixie

# テンプレートをコピー（起動時に envsubst で ${API_HOST} を置換して conf.d に出力する）
COPY infra/docker/nginx/default.conf.template /etc/nginx/default.conf.template

# 静的ファイルをコピー（ローカルではボリュームマウントで上書きされる）
COPY front/ /var/www/html/

# ${API_HOST} だけ置換することで nginx 変数（$host 等）は保護する
CMD ["/bin/sh", "-c", "envsubst '${API_HOST}' < /etc/nginx/default.conf.template > /etc/nginx/conf.d/default.conf && nginx -g 'daemon off;'"]
