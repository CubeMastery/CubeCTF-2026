FROM python:latest

RUN apt-get update && apt-get install -y gcc passwd && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --trusted-host pypi.org --trusted-host files.pythonhosted.org --no-cache-dir -r requirements.txt

RUN mkdir -p /chroot/template/bin /chroot/template/lib /chroot/template/lib64 /chroot/template/usr/lib \
    /chroot/template/home /chroot/template/etc && \
    echo "root:x:0:0:root:/root:/bin/sh" > /chroot/template/etc/passwd && \
    echo "root:x:0:" > /chroot/template/etc/group

RUN cp /bin/sh /bin/cat /bin/ls /bin/rm /bin/ln /chroot/template/bin/ 2>/dev/null || true; \
    for bin in /chroot/template/bin/*; do \
        ldd "$bin" 2>/dev/null | awk '{print $3}' | grep -v '^$' | while read lib; do \
            [ -f "$lib" ] && mkdir -p "/chroot/template$(dirname $lib)" && cp "$lib" "/chroot/template$lib"; \
        done; \
    done; \
    if [ -f /lib/ld-linux-aarch64.so.1 ]; then \
        real=$(readlink -f /lib/ld-linux-aarch64.so.1); \
        mkdir -p "/chroot/template$(dirname $real)" && cp "$real" "/chroot/template$real"; \
        ln -sf "$real" /chroot/template/lib/ld-linux-aarch64.so.1; \
    fi; \
    if [ -f /lib64/ld-linux-x86-64.so.2 ]; then \
        real=$(readlink -f /lib64/ld-linux-x86-64.so.2); \
        mkdir -p "/chroot/template$(dirname $real)" && cp "$real" "/chroot/template$real"; \
        ln -sf "$real" /chroot/template/lib64/ld-linux-x86-64.so.2; \
    fi; \
    true

COPY share /usr/local/bin/share
RUN chmod u+s /usr/local/bin/share

COPY main.py .
COPY init.sh .
RUN chmod +x init.sh

EXPOSE 8492

CMD ["./init.sh"]
