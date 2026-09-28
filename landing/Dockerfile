FROM python:3.12-slim

WORKDIR /app
COPY index.html styles.css ./

ENV PORT=8080
EXPOSE 8080

CMD ["sh", "-c", "exec python -m http.server ${PORT} --bind 0.0.0.0"]
