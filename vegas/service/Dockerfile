FROM python:3.13-slim

WORKDIR /app
RUN useradd --system --create-home vegas

COPY ./main.py /app/main.py
COPY ./vegas /app/vegas

USER vegas
EXPOSE 7770

CMD ["python", "/app/main.py"]
