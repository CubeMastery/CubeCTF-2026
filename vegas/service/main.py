#!/usr/bin/env python3

from vegas.config import PORT
from vegas.server import serve


def main():
    serve(("0.0.0.0", PORT))


if __name__ == "__main__":
    main()
