FROM debian:bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends g++ make libsqlite3-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY ./src /build/src
RUN g++ -std=c++17 -O2 -pthread src/main.cpp -lsqlite3 -o telescope-net

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libsqlite3-0 \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /data

COPY --from=build /build/telescope-net /usr/local/bin/telescope-net

EXPOSE 7419
CMD ["/usr/local/bin/telescope-net"]
