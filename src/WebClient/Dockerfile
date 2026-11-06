# Cliente leve: página estática. A imagem nginx "unprivileged" já roda sem root (uid 101) e escuta na 8080.
FROM nginxinc/nginx-unprivileged:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html

EXPOSE 8080
