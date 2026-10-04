#include <arpa/inet.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <sqlite3.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <map>
#include <mutex>
#include <random>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

static constexpr int PORT = 7419;
static constexpr const char *DB_PATH = "/data/telescope.db";

struct Calibration {
    char owner[48];
    char scope[48];
    char preview[160];
    double terms[8];
    int quality;
};

struct Session {
    bool authed = false;
    std::string user;
    std::string scratch;
    Calibration *cal = nullptr;
};

static sqlite3 *g_db = nullptr;
static std::mutex g_db_mu;
static std::atomic<uint64_t> g_jobs{41000};
static const uint32_t g_station_seed = 0x6d3a4f19u;

static std::string trim_cr(std::string s) {
    while (!s.empty() && (s.back() == '\r' || s.back() == '\n')) s.pop_back();
    return s;
}

static std::vector<std::string> split(const std::string &line) {
    std::vector<std::string> out;
    std::istringstream in(line);
    std::string part;
    while (in >> part) out.push_back(part);
    return out;
}

static std::string tail_after(const std::string &line, size_t fields) {
    size_t pos = 0;
    for (size_t i = 0; i < fields; ++i) {
        while (pos < line.size() && line[pos] == ' ') pos++;
        while (pos < line.size() && line[pos] != ' ') pos++;
    }
    while (pos < line.size() && line[pos] == ' ') pos++;
    return line.substr(pos);
}

static std::string hex64(uint64_t v) {
    std::ostringstream out;
    out << std::hex << std::setw(16) << std::setfill('0') << v;
    return out.str();
}

static uint64_t fnv1a(const std::string &s) {
    uint64_t h = 1469598103934665603ULL;
    for (unsigned char c : s) {
        h ^= c;
        h *= 1099511628211ULL;
    }
    return h;
}

static std::string now_bucket() {
    auto now = std::chrono::system_clock::now().time_since_epoch();
    auto minutes = std::chrono::duration_cast<std::chrono::minutes>(now).count();
    return std::to_string(minutes / 10);
}

static bool exec_sql(const std::string &sql) {
    char *err = nullptr;
    int rc = sqlite3_exec(g_db, sql.c_str(), nullptr, nullptr, &err);
    if (err) sqlite3_free(err);
    return rc == SQLITE_OK;
}

static bool bind_text(sqlite3_stmt *st, int idx, const std::string &v) {
    return sqlite3_bind_text(st, idx, v.c_str(), -1, SQLITE_TRANSIENT) == SQLITE_OK;
}

static std::string scalar(const std::string &sql, const std::vector<std::string> &args) {
    std::lock_guard<std::mutex> lock(g_db_mu);
    sqlite3_stmt *st = nullptr;
    std::string out;
    if (sqlite3_prepare_v2(g_db, sql.c_str(), -1, &st, nullptr) != SQLITE_OK) return out;
    for (int i = 0; i < static_cast<int>(args.size()); ++i) bind_text(st, i + 1, args[i]);
    if (sqlite3_step(st) == SQLITE_ROW) {
        const unsigned char *txt = sqlite3_column_text(st, 0);
        if (txt) out = reinterpret_cast<const char *>(txt);
    }
    sqlite3_finalize(st);
    return out;
}

static bool run_stmt(const std::string &sql, const std::vector<std::string> &args) {
    std::lock_guard<std::mutex> lock(g_db_mu);
    sqlite3_stmt *st = nullptr;
    if (sqlite3_prepare_v2(g_db, sql.c_str(), -1, &st, nullptr) != SQLITE_OK) return false;
    for (int i = 0; i < static_cast<int>(args.size()); ++i) bind_text(st, i + 1, args[i]);
    int rc = sqlite3_step(st);
    sqlite3_finalize(st);
    return rc == SQLITE_DONE || rc == SQLITE_ROW;
}

static std::string first_note_for(const std::string &user) {
    return scalar("SELECT body FROM notes WHERE owner=? ORDER BY id DESC LIMIT 1", {user});
}

static std::string escape_field(std::string s) {
    for (char &c : s) {
        if (c == '\n' || c == '\r' || c == '|') c = ' ';
    }
    return s;
}

static bool init_db() {
    if (sqlite3_open(DB_PATH, &g_db) != SQLITE_OK) return false;
    std::lock_guard<std::mutex> lock(g_db_mu);
    bool ok = exec_sql("PRAGMA journal_mode=WAL;")
        && exec_sql("CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, pass TEXT NOT NULL, home TEXT, created INTEGER DEFAULT (strftime('%s','now')));")
        && exec_sql("CREATE TABLE IF NOT EXISTS telescopes(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, name TEXT, lat TEXT, lon TEXT, aperture TEXT, mount TEXT);")
        && exec_sql("CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, scope TEXT, title TEXT, body TEXT, private INTEGER DEFAULT 1);")
        && exec_sql("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, requester TEXT, target TEXT, status TEXT, result TEXT);")
        && exec_sql("CREATE TABLE IF NOT EXISTS calibrations(id INTEGER PRIMARY KEY AUTOINCREMENT, owner TEXT, scope TEXT, memo TEXT, quality INTEGER);");
    if (!ok) return false;
    sqlite3_exec(g_db, "ALTER TABLE users ADD COLUMN old TEXT DEFAULT ''", nullptr, nullptr, nullptr);
    return true;
}

static bool password_acceptable(const std::string &user, const std::string &hash) {
    std::string current = scalar("SELECT pass FROM users WHERE username=?", {user});
    if (current.empty()) return false;
    if (current == hash) return true;
    std::string olds = scalar("SELECT old FROM users WHERE username=?", {user});
    std::istringstream in(olds);
    std::string part;
    while (std::getline(in, part, ',')) {
        if (part == hash) return true;
    }
    return false;
}

static ssize_t send_line(int fd, const std::string &line) {
    std::string data = line + "\n";
    return send(fd, data.data(), data.size(), MSG_NOSIGNAL);
}

static bool recv_line(int fd, std::string &line) {
    line.clear();
    char ch;
    while (line.size() < 8192) {
        ssize_t n = recv(fd, &ch, 1, 0);
        if (n <= 0) return false;
        if (ch == '\n') {
            line = trim_cr(line);
            return true;
        }
        line.push_back(ch);
    }
    return false;
}

static bool valid_name(const std::string &s) {
    if (s.empty() || s.size() > 40) return false;
    return std::all_of(s.begin(), s.end(), [](unsigned char c) {
        return std::isalnum(c) || c == '_' || c == '-' || c == '.';
    });
}

static void log_action(const std::string &user, const std::string &cmd, const std::string &detail = "") {
    std::cerr << "[ACTION] user=" << user << " cmd=" << cmd;
    if (!detail.empty()) std::cerr << " " << detail;
    std::cerr << "\n";
}

static std::string handle(Session &sess, const std::string &line) {
    auto args = split(line);
    if (args.empty()) return "ERR empty";
    std::string cmd = args[0];
    std::transform(cmd.begin(), cmd.end(), cmd.begin(), ::toupper);

    if (cmd == "PING") return "OK ORION";
    if (cmd == "BANNER") return "OK TelescopeNet station=mesquite seed=" + std::to_string(g_station_seed);

    if (cmd == "REGISTER") {
        if (args.size() < 3 || !valid_name(args[1])) return "ERR register";
        log_action("?", cmd, "user=" + args[1]);
        bool ok = run_stmt("INSERT INTO users(username,pass,home) VALUES(?,?,?)", {args[1], hex64(fnv1a(args[2])), "Mesquite Ridge"});
        return ok ? "OK registered" : "ERR exists";
    }

    if (cmd == "LOGIN") {
        if (args.size() < 3) return "ERR login";
        log_action("?", cmd, "user=" + args[1]);
        if (password_acceptable(args[1], hex64(fnv1a(args[2])))) {
            sess.authed = true;
            sess.user = args[1];
            log_action(sess.user, cmd, "success");
            return "OK session " + args[1];
        }
        log_action(args[1], cmd, "failed");
        return "ERR auth";
    }

    if (cmd == "RESET_PREP") {
        if (args.size() < 2) return "ERR reset";
        log_action("?", cmd, "user=" + args[1]);
        std::string home = scalar("SELECT home FROM users WHERE username=?", {args[1]});
        if (home.empty()) return "ERR unknown";
        uint64_t ticket = fnv1a(args[1] + ":" + home + ":" + now_bucket() + ":" + std::to_string(g_station_seed));
        run_stmt("UPDATE users SET home=? WHERE username=?", {"Mesquite Ridge " + hex64(ticket).substr(0, 5), args[1]});
        return "OK prep " + home + " " + now_bucket();
    }

    if (cmd == "RESET_FINISH") {
        if (args.size() < 4) return "ERR reset";
        log_action("?", cmd, "user=" + args[1]);
        std::string home = scalar("SELECT home FROM users WHERE username=?", {args[1]});
        std::string stable_home = home.substr(0, home.find(" "));
        uint64_t token = fnv1a(args[1] + ":" + stable_home + ":" + now_bucket() + ":" + std::to_string(g_station_seed));
        uint64_t prev = fnv1a(args[1] + ":" + stable_home + ":" + std::to_string(std::stoll(now_bucket()) - 1) + ":" + std::to_string(g_station_seed));
        if (args[2] == hex64(token).substr(0, 10) || args[2] == hex64(prev).substr(0, 10)) {
            std::string cur = scalar("SELECT pass FROM users WHERE username=?", {args[1]});
            std::string olds = scalar("SELECT old FROM users WHERE username=?", {args[1]});
            std::vector<std::string> history;
            std::istringstream in(olds);
            std::string part;
            while (std::getline(in, part, ',')) if (!part.empty()) history.push_back(part);
            if (!cur.empty()) history.push_back(cur);
            while (history.size() > 64) history.erase(history.begin());
            std::string joined;
            for (size_t i = 0; i < history.size(); ++i) joined += (i ? "," : "") + history[i];
            run_stmt("UPDATE users SET old=?, pass=? WHERE username=?", {joined, hex64(fnv1a(args[3])), args[1]});
            log_action(args[1], cmd, "success");
            return "OK changed";
        }
        log_action(args[1], cmd, "token_fail");
        return "ERR token";
    }

    if (!sess.authed) return "ERR noauth";

    if (cmd == "ADD_SCOPE") {
        if (args.size() < 6) return "ERR scope";
        log_action(sess.user, cmd, "scope=" + args[1]);
        bool ok = run_stmt("INSERT INTO telescopes(owner,name,lat,lon,aperture,mount) VALUES(?,?,?,?,?,?)",
                           {sess.user, args[1], args[2], args[3], args[4], tail_after(line, 5)});
        return ok ? "OK scope" : "ERR scope";
    }

    if (cmd == "LIST_SCOPES") {
        log_action(sess.user, cmd);
        std::lock_guard<std::mutex> lock(g_db_mu);
        sqlite3_stmt *st = nullptr;
        std::string out = "OK";
        sqlite3_prepare_v2(g_db, "SELECT name,lat,lon,aperture,mount FROM telescopes WHERE owner=? ORDER BY id", -1, &st, nullptr);
        bind_text(st, 1, sess.user);
        while (sqlite3_step(st) == SQLITE_ROW) {
            out += "|";
            for (int i = 0; i < 5; ++i) {
                if (i) out += ",";
                const unsigned char *txt = sqlite3_column_text(st, i);
                out += escape_field(txt ? reinterpret_cast<const char *>(txt) : "");
            }
        }
        sqlite3_finalize(st);
        return out;
    }

    if (cmd == "STORE_NOTE") {
        if (args.size() < 4) return "ERR note";
        log_action(sess.user, cmd, "scope=" + args[1] + " title=" + args[2]);
        std::string body = tail_after(line, 3);
        bool ok = run_stmt("INSERT INTO notes(owner,scope,title,body,private) VALUES(?,?,?,?,1)", {sess.user, args[1], args[2], body});
        return ok ? "OK note" : "ERR note";
    }

    if (cmd == "GET_NOTE") {
        if (args.size() < 2) return "ERR note";
        log_action(sess.user, cmd, "title=" + args[1]);
        std::string body = scalar("SELECT body FROM notes WHERE owner=? AND title=? ORDER BY id DESC LIMIT 1", {sess.user, args[1]});
        return body.empty() ? "ERR missing" : "OK " + escape_field(body);
    }

    if (cmd == "LIST_NOTES") {
        log_action(sess.user, cmd);
        std::lock_guard<std::mutex> lock(g_db_mu);
        sqlite3_stmt *st = nullptr;
        std::string out = "OK";
        sqlite3_prepare_v2(g_db, "SELECT title,scope FROM notes WHERE owner=? ORDER BY id DESC", -1, &st, nullptr);
        bind_text(st, 1, sess.user);
        while (sqlite3_step(st) == SQLITE_ROW) {
            const unsigned char *title = sqlite3_column_text(st, 0);
            const unsigned char *scope = sqlite3_column_text(st, 1);
            out += "|" + escape_field(title ? reinterpret_cast<const char *>(title) : "");
            out += "," + escape_field(scope ? reinterpret_cast<const char *>(scope) : "");
        }
        sqlite3_finalize(st);
        return out;
    }

    if (cmd == "CONSTELLATIONS") {
        if (args.size() < 4) return "ERR sky";
        static const std::vector<std::string> winter = {"Orion", "Taurus", "CanisMajor", "Gemini"};
        static const std::vector<std::string> spring = {"Leo", "Virgo", "Bootes", "ComaBerenices"};
        static const std::vector<std::string> summer = {"Cygnus", "Lyra", "Aquila", "Scorpius"};
        static const std::vector<std::string> autumn = {"Pegasus", "Andromeda", "Cetus", "Cassiopeia"};
        int month = std::max(1, std::min(12, std::atoi(args[3].c_str())));
        const auto *set = month <= 2 || month == 12 ? &winter : month <= 5 ? &spring : month <= 8 ? &summer : &autumn;
        std::string out = "OK";
        for (const auto &c : *set) out += " " + c;
        return out;
    }

    if (cmd == "EPHEMERIS") {
        if (args.size() < 3) return "ERR eph";
        log_action(sess.user, cmd, "target=" + args[1] + " epoch=" + args[2]);
        uint64_t h = fnv1a(sess.user + args[1] + args[2]);
        int alt = 20 + (h % 58);
        int az = h % 360;
        int seeing = 1 + ((h >> 8) % 5);
        return "OK alt=" + std::to_string(alt) + " az=" + std::to_string(az) + " seeing=" + std::to_string(seeing);
    }

    if (cmd == "QUEUE_AUDIT") {
        if (args.size() < 2) return "ERR job";
        log_action(sess.user, cmd, "target=" + args[1]);
        std::string id = hex64(fnv1a(sess.user + ":" + args[1] + ":" + std::to_string(g_jobs.fetch_add(1))));
        std::string note = first_note_for(args[1]);
        std::string result = "audit target=" + args[1] + " last-note=" + escape_field(note);
        run_stmt("INSERT INTO jobs(id,requester,target,status,result) VALUES(?,?,?,?,?)", {id, sess.user, args[1], "ready", result});
        return "OK job " + id;
    }

    if (cmd == "JOB_RESULT") {
        if (args.size() < 2) return "ERR job";
        log_action(sess.user, cmd, "job=" + args[1]);
        std::string res = scalar("SELECT result FROM jobs WHERE id=?", {args[1]});
        return res.empty() ? "ERR missing" : "OK " + res;
    }

    if (cmd == "CAL_OPEN") {
        if (args.size() < 2) return "ERR cal";
        log_action(sess.user, cmd, "scope=" + args[1]);
        if (sess.cal) delete sess.cal;
        sess.cal = new Calibration();
        std::memset(sess.cal, 0, sizeof(Calibration));
        std::strncpy(sess.cal->owner, sess.user.c_str(), sizeof(sess.cal->owner) - 1);
        std::strncpy(sess.cal->scope, args[1].c_str(), sizeof(sess.cal->scope) - 1);
        sess.cal->quality = 7;
        return "OK cal";
    }

    if (cmd == "CAL_DISCARD") {
        log_action(sess.user, cmd);
        if (!sess.cal) return "ERR cal";
        sess.cal->quality = -1;
        return "OK discarded";
    }

    if (cmd == "CAL_PREFETCH") {
        if (args.size() < 2) return "ERR cal";
        log_action(sess.user, cmd, "scope=" + args[1]);
        Calibration *tmp = new Calibration();
        std::memset(tmp, 0, sizeof(Calibration));
        std::strncpy(tmp->owner, args[1].c_str(), sizeof(tmp->owner) - 1);
        std::string body = first_note_for(args[1]);
        std::strncpy(tmp->preview, body.c_str(), sizeof(tmp->preview) - 1);
        tmp->quality = static_cast<int>(fnv1a(args[1]) % 10);
        if (sess.cal) std::memcpy(sess.cal, tmp, sizeof(Calibration));
        delete tmp;
        return "OK prefetched";
    }

    if (cmd == "CAL_COMMIT") {
        log_action(sess.user, cmd);
        if (!sess.cal) return "ERR cal";
        std::string owner = sess.cal->owner;
        std::string memo = sess.cal->preview;
        run_stmt("INSERT INTO calibrations(owner,scope,memo,quality) VALUES(?,?,?,?)",
                 {owner, sess.cal->scope, memo, std::to_string(sess.cal->quality)});
        if (owner == sess.user) delete sess.cal;
        sess.cal = nullptr;
        return memo.empty() ? "OK committed" : "OK committed " + escape_field(memo);
    }

    return "ERR unknown";
}

static void client_thread(int fd) {
    Session sess;
    send_line(fd, "OK TelescopeNet/1.0");
    std::cerr << "[CONNECT] fd=" << fd << "\n";
    std::string line;
    while (recv_line(fd, line)) {
        if (line == "QUIT") {
            log_action(sess.authed ? sess.user : "?", "QUIT");
            send_line(fd, "OK bye");
            break;
        }
        std::string response = handle(sess, line);
        if (send_line(fd, response) <= 0) break;
    }
    if (sess.cal) delete sess.cal;
    std::cerr << "[DISCONNECT] fd=" << fd << "\n";
    close(fd);
}

int main() {
    if (!init_db()) {
        std::cerr << "database init failed\n";
        return 1;
    }
    int server = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(server, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));
    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(PORT);
    if (bind(server, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) != 0) {
        std::cerr << "bind failed\n";
        return 1;
    }
    if (listen(server, 128) != 0) {
        std::cerr << "listen failed\n";
        return 1;
    }
    while (true) {
        int fd = accept(server, nullptr, nullptr);
        if (fd < 0) continue;
        std::thread(client_thread, fd).detach();
    }
}
