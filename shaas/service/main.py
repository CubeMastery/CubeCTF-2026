import socket
import threading
import os
import re
import shutil
import subprocess
import time
import logging
from passlib.hash import sha512_crypt
import secrets
import pwd

logging.basicConfig(
    level=os.environ.get("SHAAS_LOG", "DEBUG").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("shaas")

HOST = "0.0.0.0"
PORT = 8492
CHROOT_BASE = "/chroot"
USERS_DB = "/etc/shaas_users"

CONNECT_TIMEOUT = 30
MAX_CONNECTIONS = 256
MAX_SUBPROCESSES = 32
SHARE_TIMEOUT = 30
USERADD_TIMEOUT = 20

os.makedirs(CHROOT_BASE, exist_ok=True)

sessions = {}
session_lock = threading.Lock()

user_db = {}
user_db_lock = threading.RLock()

connection_sem = threading.Semaphore(MAX_CONNECTIONS)
subprocess_sem = threading.Semaphore(MAX_SUBPROCESSES)

WELCOME = """shaas - shell as a service
type 'help' for commands"""

HELP = """register <username> <password>  create a new account
login    <username> <password>  sign in
write    <filename> <content>   write a file
read     <filename>             read a file
cmd      <command>              execute a shell command
share    <filename> <target>    share a file with another user
files                          list your files
whoami                         show current user
logout                         sign out
help                           show this help
quit                           disconnect"""


def _load_user_db():
    global user_db
    try:
        with open(USERS_DB, "r") as f:
            for line in f:
                line = line.strip()
                if ":" in line:
                    u, h = line.split(":", 1)
                    user_db[u] = h
    except FileNotFoundError:
        pass


def _add_user_db(username, pw_hash):
    with user_db_lock:
        user_db[username] = pw_hash
        tmp = USERS_DB + ".tmp"
        with open(tmp, "w") as f:
            for u, h in user_db.items():
                f.write(f"{u}:{h}\n")
        os.replace(tmp, USERS_DB)


def get_user_hash(username):
    with user_db_lock:
        return user_db.get(username)


def hash_password(password):
    return sha512_crypt.using(rounds=1000).hash(password)


def verify_password(password, hash_val):
    try:
        return sha512_crypt.verify(password, hash_val)
    except Exception:
        return False


def setup_chroot(username):
    user_chroot = f"{CHROOT_BASE}/{username}"
    if os.path.exists(user_chroot):
        return

    try:
        shutil.copytree(f"{CHROOT_BASE}/template", user_chroot, symlinks=True, copy_function=os.link)
    except OSError:
        if os.path.exists(user_chroot):
            shutil.rmtree(user_chroot)
        shutil.copytree(f"{CHROOT_BASE}/template", user_chroot, symlinks=True)

    # etc/passwd and etc/group get appended to below; they must not share
    # storage with the template (fall back handled above)
    for rel in ("etc/passwd", "etc/group"):
        p = os.path.join(user_chroot, rel)
        if os.path.exists(p):
            os.unlink(p)
        shutil.copy2(os.path.join(CHROOT_BASE, "template", rel), p)

    home_in_chroot = f"{user_chroot}/home/{username}"
    os.makedirs(home_in_chroot, exist_ok=True)

    real_home = f"/home/{username}"
    os.makedirs(real_home, exist_ok=True)

    share_dst = f"{user_chroot}/bin/share"
    if os.path.exists("/usr/local/bin/share") and not os.path.exists(share_dst):
        try:
            os.link("/usr/local/bin/share", share_dst)
        except OSError:
            shutil.copy2("/usr/local/bin/share", share_dst)
        os.chmod(share_dst, 0o4755)

    try:
        pw = pwd.getpwnam(username)
        uid = pw.pw_uid
        gid = pw.pw_gid
        os.chown(home_in_chroot, uid, gid)
        os.chown(real_home, uid, gid)

        etc_passwd = os.path.join(user_chroot, "etc", "passwd")
        with open(etc_passwd, "a") as f:
            f.write(f"{username}:x:{uid}:{gid}::/home/{username}:/bin/sh\n")
        etc_group = os.path.join(user_chroot, "etc", "group")
        with open(etc_group, "a") as f:
            f.write(f"{username}:x:{gid}:\n")
    except KeyError:
        pass


def execute_command(username, command):
    chroot_path = f"{CHROOT_BASE}/{username}"
    if not os.path.exists(chroot_path):
        return "chroot not found"

    try:
        with subprocess_sem:
            result = subprocess.run(
                ["/usr/sbin/chroot", "--userspec", f"{username}:{username}", chroot_path, "/bin/sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=30,
                env={"HOME": f"/home/{username}", "USER": username, "PATH": "/bin"},
            )
        output = result.stdout + result.stderr
        return output if output else "(no output)"
    except subprocess.TimeoutExpired:
        log.warning("cmd timed out as %s: %s", username, command[:120])
        return "Command timed out"
    except Exception as e:
        return f"Error: {str(e)}"


def handle_client(conn, addr):
    token = None
    username = None

    log.debug("conn from %s (%d active threads)", addr, threading.active_count())
    try:
        conn.settimeout(CONNECT_TIMEOUT)
        conn.sendall(f"{WELCOME}\r\n".encode())

        while True:
            conn.sendall(b"> ")

            try:
                data = conn.recv(65536).decode(errors="replace").strip()
                if not data:
                    break
            except socket.timeout:
                log.warning("conn from %s timed out waiting for data as %s", addr, username)
                break
            except Exception:
                log.warning("conn from %s recv error as %s", addr, username, exc_info=True)
                break

            if not data:
                continue

            parts = data.split()
            cmd = parts[0].lower()
            r = None
            t0 = time.monotonic()
            log.info("cmd from %s as %s: %s", addr, username or "-", data[:200])

            if cmd == "help":
                r = HELP

            elif cmd == "register":
                if len(parts) < 3:
                    r = "usage: register <username> <password>"
                else:
                    uname = parts[1]
                    pw_str = parts[2]

                    if not re.match(r'^[a-z][a-z0-9_]{2,31}$', uname):
                        r = "ERROR: invalid username format"
                    elif len(pw_str) < 8 or len(pw_str) > 64:
                        r = "ERROR: invalid password length"
                    else:
                        try:
                            pwd.getpwnam(uname)
                            r = "ERROR: user already exists"
                        except KeyError:
                            pass

                    if r is None:
                        log.info("register %s start", uname)
                        pw_hash = hash_password(pw_str)
                        try:
                            with subprocess_sem:
                                subprocess.run(
                                    ["useradd", "-m", "-d", f"/home/{uname}", "-s", "/bin/sh", uname],
                                    check=True, capture_output=True, timeout=USERADD_TIMEOUT,
                                )
                                subprocess.run(
                                    ["chpasswd", "-e"],
                                    input=f"{uname}:{pw_hash}\n",
                                    check=True, capture_output=True, text=True, timeout=USERADD_TIMEOUT,
                                )
                            try:
                                setup_chroot(uname)
                            except Exception:
                                try:
                                    shutil.rmtree(f"{CHROOT_BASE}/{uname}", ignore_errors=True)
                                    subprocess.run(["userdel", "-r", uname], capture_output=True, timeout=USERADD_TIMEOUT)
                                except Exception:
                                    pass
                                log.error("setup_chroot failed for %s", uname, exc_info=True)
                                r = "ERROR: failed to create user"
                            if r is None:
                                _add_user_db(uname, pw_hash)
                                r = "OK"
                            log.info("register %s OK", uname)
                        except subprocess.CalledProcessError:
                            r = "ERROR: failed to create user"
                        except subprocess.TimeoutExpired:
                            r = "ERROR: failed to create user"

            elif cmd == "login":
                if len(parts) < 3:
                    r = "usage: login <username> <password>"
                else:
                    uname = parts[1]
                    pw_str = parts[2]

                    pw_hash = get_user_hash(uname)
                    if pw_hash is None:
                        r = "ERROR: invalid credentials"
                        log.warning("login %s: no such user", uname)
                    elif not verify_password(pw_str, pw_hash):
                        r = "ERROR: invalid credentials"
                        log.warning("login %s: bad password", uname)
                    else:
                        token = secrets.token_hex(32)
                        with session_lock:
                            sessions[token] = uname
                        username = uname
                        r = f"OK {token}"

            elif cmd == "logout":
                if token:
                    with session_lock:
                        if token in sessions:
                            del sessions[token]
                token = None
                username = None
                r = "OK"

            elif cmd == "whoami":
                if username:
                    r = username
                else:
                    r = "ERROR: not authenticated"

            elif cmd == "quit":
                if token:
                    with session_lock:
                        if token in sessions:
                            del sessions[token]
                break

            elif not username:
                r = "ERROR: not authenticated, use 'login' first"

            elif cmd == "write":
                if len(parts) < 3:
                    r = "usage: write <filename> <content>"
                else:
                    fn = parts[1]
                    content = " ".join(parts[2:])
                    user_home = f"{CHROOT_BASE}/{username}/home/{username}"
                    file_path = os.path.join(user_home, fn)
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "w") as f:
                        f.write(content)
                    try:
                        pw_entry = pwd.getpwnam(username)
                        os.chown(file_path, pw_entry.pw_uid, pw_entry.pw_gid)
                    except KeyError:
                        pass
                    r = "OK"

            elif cmd == "read":
                if len(parts) < 2:
                    r = "usage: read <filename>"
                else:
                    fn = parts[1]
                    user_home = f"{CHROOT_BASE}/{username}/home/{username}"
                    file_path = os.path.join(user_home, fn)
                    if not os.path.exists(file_path) or not os.path.isfile(file_path):
                        r = "ERROR: file not found"
                    else:
                        with open(file_path, "r") as f:
                            content = f.read()
                        r = content

            elif cmd == "cmd":
                if len(parts) < 2:
                    r = "usage: cmd <command>"
                else:
                    command = " ".join(parts[1:])
                    output = execute_command(username, command)
                    r = output

            elif cmd == "share":
                if len(parts) < 3:
                    r = "usage: share <filename> <target_user>"
                else:
                    fn = parts[1]
                    target = " ".join(parts[2:])
                    proc = None
                    log.info("share %s -> %s as %s", fn, target, username)
                    try:
                        with subprocess_sem:
                            proc = subprocess.Popen(
                                ["/usr/local/bin/share", username, fn, target],
                                stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                            )
                        try:
                            first = proc.stdout.readline()
                        except Exception:
                            first = ""
                        if not first:
                            r = "ERROR: share binary failed"
                        elif "Are you sure" in first:
                            conn.sendall(first.encode())
                            conn.sendall(b"> ")
                            try:
                                answer = conn.recv(4096).decode(errors="replace").strip()
                            except socket.timeout:
                                answer = ""
                                log.warning("share answer timed out from %s", addr)
                            try:
                                proc.stdin.write((answer + "\n") if answer else "n\n")
                                proc.stdin.flush()
                                proc.stdin.close()
                            except Exception:
                                pass
                            try:
                                proc.wait(timeout=SHARE_TIMEOUT)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                                r = "ERROR: share timed out"
                                log.warning("share process killed after timeout (%s)", username)
                            if r is None:
                                rest = proc.stdout.read()
                                r = rest.strip() if rest.strip() else "OK"
                        else:
                            try:
                                proc.stdin.close()
                            except Exception:
                                pass
                            try:
                                proc.wait(timeout=SHARE_TIMEOUT)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                            r = first.strip()
                    except Exception as e:
                        r = f"ERROR: {str(e)}"
                    finally:
                        if proc is not None:
                            try:
                                if proc.poll() is None:
                                    proc.kill()
                                proc.wait()
                            except Exception:
                                pass

            elif cmd == "files":
                user_dir = f"{CHROOT_BASE}/{username}/home/{username}"
                if not os.path.exists(user_dir):
                    r = "(no files)"
                else:
                    entries = []
                    try:
                        for fname in os.listdir(user_dir):
                            full_path = os.path.join(user_dir, fname)
                            if os.path.isfile(full_path):
                                entries.append(f"{fname} ({os.path.getsize(full_path)} bytes)")
                    except PermissionError:
                        pass
                    r = "\n".join(entries) if entries else "(no files)"

            else:
                r = f"ERROR: unknown command '{cmd}', type 'help'"

            if r is not None:
                try:
                    conn.sendall((r + "\r\n").encode())
                except Exception as e:
                    log.warning("send to %s failed: %s", addr, e)
                    break
            elapsed = time.monotonic() - t0
            if elapsed > 5:
                log.warning("slow cmd '%s' took %.1fs as %s", cmd, elapsed, username or "-")
            else:
                log.debug("cmd '%s' response in %.2fs: %s", cmd, elapsed, str(r)[:120])

    except Exception:
        log.error("handle_client crash as %s", username, exc_info=True)
    finally:
        if token:
            with session_lock:
                if token in sessions:
                    del sessions[token]
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        conn.close()


def main():
    _load_user_db()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(128)

    while True:
        conn, addr = server.accept()
        if not connection_sem.acquire(blocking=False):
            log.warning("rejecting conn from %s: server busy", addr)
            try:
                conn.sendall(b"ERROR: server busy\r\n")
                conn.close()
            except Exception:
                pass
            continue

        def _run(conn=conn, addr=addr):
            try:
                handle_client(conn, addr)
            finally:
                connection_sem.release()

        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()


if __name__ == "__main__":
    main()
