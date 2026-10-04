FROM debian:bookworm-slim

WORKDIR /code

RUN apt-get update \
    && apt-get install -y --no-install-recommends lua5.4 lua-socket ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY ./server.lua /code/server.lua

CMD ["lua5.4", "/code/server.lua"]
