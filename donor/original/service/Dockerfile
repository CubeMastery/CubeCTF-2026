FROM rust:1-bookworm AS builder

WORKDIR /code
COPY Cargo.toml ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
WORKDIR /app
COPY --from=builder /code/target/release/givehere /app/givehere
EXPOSE 4739
CMD ["/app/givehere"]
