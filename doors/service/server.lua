local socket = require("socket")

local PORT = tonumber(os.getenv("DOORS_PORT") or "4783")
local PROMPT = "C:\\Doors> "

local users = {}
local fs = {}
local dirs = {}
local clients = {}

local b64chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"

local function trim(s)
    return (s:gsub("^%s+", ""):gsub("%s+$", ""))
end

local function starts_with(s, prefix)
    return s:sub(1, #prefix) == prefix
end

local function path_key(p)
    return p:lower()
end

local function random_string(n)
    local alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    local out = {}
    for i = 1, n do
        local idx = math.random(1, #alphabet)
        out[i] = alphabet:sub(idx, idx)
    end
    return table.concat(out)
end

local function fnv1a(s)
    local h = 2166136261
    for i = 1, #s do
        h = h ~ s:byte(i)
        h = (h * 16777619) & 0xffffffff
    end
    return h
end

local function base36(n)
    local chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if n == 0 then
        return "0"
    end
    local out = ""
    while n > 0 do
        local r = (n % 36) + 1
        out = chars:sub(r, r) .. out
        n = math.floor(n / 36)
    end
    return out
end

local function session_token(user)
    local h = fnv1a(user:lower())
    return "D" .. base36(h) .. "X" .. tostring(#user)
end

local function b64encode(data)
    return ((data:gsub(".", function(x)
        local r, b = "", x:byte()
        for i = 8, 1, -1 do
            r = r .. ((b % 2 ^ i - b % 2 ^ (i - 1) > 0) and "1" or "0")
        end
        return r
    end) .. "0000"):gsub("%d%d%d?%d?%d?%d?", function(x)
        if #x < 6 then
            return ""
        end
        local c = 0
        for i = 1, 6 do
            c = c + ((x:sub(i, i) == "1") and 2 ^ (6 - i) or 0)
        end
        return b64chars:sub(c + 1, c + 1)
    end) .. ({ "", "==", "=" })[#data % 3 + 1])
end

local function b64decode(data)
    data = data:gsub("[^" .. b64chars .. "=]", "")
    return (data:gsub(".", function(x)
        if x == "=" then
            return ""
        end
        local r, f = "", (b64chars:find(x, 1, true) or 1) - 1
        for i = 6, 1, -1 do
            r = r .. ((f % 2 ^ i - f % 2 ^ (i - 1) > 0) and "1" or "0")
        end
        return r
    end):gsub("%d%d%d?%d?%d?%d?%d?%d?", function(x)
        if #x ~= 8 then
            return ""
        end
        local c = 0
        for i = 1, 8 do
            c = c + ((x:sub(i, i) == "1") and 2 ^ (8 - i) or 0)
        end
        return string.char(c)
    end))
end

local function tokenize(line)
    local args, current, quote = {}, {}, nil
    local i = 1
    while i <= #line do
        local ch = line:sub(i, i)
        if quote then
            if ch == quote then
                quote = nil
            else
                current[#current + 1] = ch
            end
        elseif ch == '"' or ch == "'" then
            quote = ch
        elseif ch:match("%s") then
            if #current > 0 then
                args[#args + 1] = table.concat(current)
                current = {}
            end
        else
            current[#current + 1] = ch
        end
        i = i + 1
    end
    if #current > 0 then
        args[#args + 1] = table.concat(current)
    end
    return args
end

local function join_parts(parts)
    if #parts == 0 then
        return "C:"
    end
    return "C:/" .. table.concat(parts, "/")
end

local function normalize_path(raw, cwd)
    raw = tostring(raw or "")
    raw = raw:gsub("\\", "/"):gsub("/+", "/")
    local path
    if raw:match("^[A-Za-z]:/") then
        path = "C:" .. raw:sub(3)
    elseif raw:match("^[A-Za-z]:") then
        path = "C:/" .. raw:sub(3)
    elseif starts_with(raw, "/") then
        path = "C:" .. raw
    else
        path = (cwd or "C:/") .. "/" .. raw
    end

    path = path:gsub("\\", "/"):gsub("/+", "/")
    local rest = path:gsub("^[A-Za-z]:/?", "")
    local parts = {}
    for part in rest:gmatch("[^/]+") do
        if part == "." or part == "" then
        elseif part == ".." then
            if #parts > 0 then
                table.remove(parts)
            end
        else
            parts[#parts + 1] = part
        end
    end
    return join_parts(parts)
end

local function path_for_acl(raw, cwd)
    raw = tostring(raw or ""):gsub("\\", "/"):gsub("/+", "/")
    local path
    if raw:match("^[A-Za-z]:/") then
        path = "C:" .. raw:sub(3)
    elseif raw:match("^[A-Za-z]:") then
        path = "C:/" .. raw:sub(3)
    elseif starts_with(raw, "/") then
        path = "C:" .. raw
    else
        path = (cwd or "C:/") .. "/" .. raw
    end
    return path:gsub("/+$", "")
end

local function parent_path(p)
    local q = p:gsub("/+$", "")
    local parent = q:match("^(.*)/[^/]+$")
    if not parent or parent == "" then
        return "C:"
    end
    return parent
end

local function mkdirp(p)
    local norm = normalize_path(p, "C:/")
    local parts = {}
    dirs[path_key("C:")] = true
    for part in norm:gsub("^C:/?", ""):gmatch("[^/]+") do
        parts[#parts + 1] = part
        dirs[path_key(join_parts(parts))] = true
    end
end

local function file_exists(p)
    return fs[path_key(p)] ~= nil
end

local function read_file(p)
    local item = fs[path_key(p)]
    if item then
        return item.data
    end
    return nil
end

local function write_file(p, data, owner)
    mkdirp(parent_path(p))
    fs[path_key(p)] = {
        path = p,
        data = data,
        owner = owner or "",
        mtime = os.time(),
    }
end

local function visible_to(state, raw)
    if not state.user then
        return false
    end
    local acl = path_for_acl(raw, state.cwd)
    local home = "C:/Users/" .. state.user
    local l_acl = acl:lower()
    return l_acl == home:lower()
        or starts_with(l_acl, (home .. "/"):lower())
        or l_acl == "c:/users/public"
        or starts_with(l_acl, "c:/users/public/")
end

local function real_path(state, raw)
    return normalize_path(raw, state.cwd or "C:/")
end

local function create_user(username, password)
    local salt = random_string(12)
    local passhash = tostring(fnv1a(salt .. ":" .. password))
    users[username:lower()] = {
        name = username,
        salt = salt,
        passhash = passhash,
        session_token = session_token(username),
        created = os.time(),
    }
    local home = "C:/Users/" .. username
    mkdirp(home)
    mkdirp(home .. "/Desktop")
    mkdirp(home .. "/Documents")
    mkdirp(home .. "/Vault")
    mkdirp(home .. "/Public")
    mkdirp(home .. "/Inbox")
    mkdirp(home .. "/AppData/Local/Doors")
    write_file(home .. "/profile.ini", "user=" .. username .. "\ncreated=" .. tostring(os.time()) .. "\n", username)
    write_file(home .. "/Documents/welcome.txt", "Welcome to Doors, " .. username .. ".\n", username)
end

local function check_password(username, password)
    local user = users[username:lower()]
    if not user then
        return false
    end
    return tostring(fnv1a(user.salt .. ":" .. password)) == user.passhash
end

local function set_login(state, username)
    local user = users[username:lower()]
    state.user = user.name
    state.cwd = "C:/Users/" .. user.name
    state.env.USER = user.name
    state.env.HOME = state.cwd
    state.env.CD = state.cwd
end

local function expand_vars(state, s, argv)
    local out = tostring(s or "")
    out = out:gsub("%%(%d)%%", function(n)
        return argv and argv[tonumber(n)] or ""
    end)
    out = out:gsub("%%([%w_]+)%%", function(name)
        return state.env[name] or state.env[name:upper()] or ""
    end)
    return out
end

local function stream_crypt(data, seed)
    local state = seed & 0x7fffffff
    local out = {}
    for i = 1, #data do
        state = (state * 1103515245 + 12345) & 0x7fffffff
        local k = (state >> 16) & 0xff
        out[i] = string.char(data:byte(i) ~ k)
    end
    return table.concat(out)
end

local function recovery_blob(username)
    local user = users[username:lower()]
    if not user then
        return nil
    end
    local root = ("C:/Users/" .. user.name .. "/Vault/"):lower()
    local lines = {}
    for key, item in pairs(fs) do
        if starts_with(key, root) then
            lines[#lines + 1] = item.path:sub(#root + 1) .. ":" .. b64encode(item.data)
        end
    end
    table.sort(lines)
    local nonce = string.format("%08x", (fnv1a(user.name) ~ os.time()) & 0xffffffff)
    local seed = fnv1a(user.name:lower() .. ":" .. nonce)
    return nonce, b64encode(stream_crypt(table.concat(lines, "\n"), seed))
end

local function list_dir(state, raw)
    local p = real_path(state, raw or ".")
    if not visible_to(state, raw or ".") then
        return nil, "access denied"
    end
    local prefix = path_key(p)
    if prefix ~= "c:" then
        prefix = prefix .. "/"
    end
    local children = {}
    for key, _ in pairs(dirs) do
        if starts_with(key, prefix) then
            local rest = key:sub(#prefix + 1)
            if rest ~= "" and not rest:find("/") then
                children[#children + 1] = "[DIR] " .. rest
            end
        end
    end
    for key, item in pairs(fs) do
        if starts_with(key, prefix) then
            local rest = key:sub(#prefix + 1)
            if rest ~= "" and not rest:find("/") then
                children[#children + 1] = string.format("%6d %s", #item.data, rest)
            end
        end
    end
    table.sort(children)
    return table.concat(children, "\n")
end

local function run_script(state, raw_path, argv)
    if not visible_to(state, raw_path) then
        return false, "access denied"
    end
    local script_path = real_path(state, raw_path)
    if not script_path:lower():match("%.door$") then
        return false, "not a door script"
    end
    local body = read_file(script_path)
    if not body then
        return false, "file not found"
    end
    local output = {}
    local count = 0
    for line in (body .. "\n"):gmatch("([^\n]*)\n") do
        count = count + 1
        if count > 48 then
            return false, "script limit exceeded"
        end
        line = trim(line:gsub("\r", ""))
        if line ~= "" and not line:match("^::") and not line:lower():match("^rem%s") then
            local parts = tokenize(line)
            local cmd = (parts[1] or ""):upper()
            if cmd == "ECHO" then
                local msg = line:match("^[^%s]+%s+(.+)$") or ""
                output[#output + 1] = expand_vars(state, msg, argv)
            elseif cmd == "SET" and parts[2] and parts[3] then
                local value = line:match("^%S+%s+%S+%s+(.+)$") or ""
                state.env[parts[2]:upper()] = expand_vars(state, value, argv)
            elseif cmd == "TYPE" and parts[2] then
                if not visible_to(state, parts[2]) then
                    return false, "script read denied"
                end
                local src = real_path(state, expand_vars(state, parts[2], argv))
                local data = read_file(src)
                if data then
                    output[#output + 1] = data
                end
            elseif cmd == "COPY" and parts[2] and parts[3] then
                if not visible_to(state, parts[2]) then
                    return false, "script read denied"
                end
                local src = real_path(state, expand_vars(state, parts[2], argv))
                local dst_arg = expand_vars(state, parts[3], argv)
                if not visible_to(state, dst_arg) then
                    return false, "script write denied"
                end
                local data = read_file(src)
                if not data then
                    return false, "script source missing"
                end
                write_file(real_path(state, dst_arg), data, state.user)
            end
        end
    end
    return true, b64encode(table.concat(output, "\n"))
end

local function require_user(state)
    if not state.user then
        return false, "ERR login required"
    end
    return true
end

local function handle_command(state, line)
    line = trim(line)
    if line == "" then
        return "OK"
    end
    local parts = tokenize(line)
    local cmd = (parts[1] or ""):upper()

    if cmd == "PING" then
        return "OK PONG"
    elseif cmd == "HELP" then
        return "OK REGISTER LOGIN DIR CD MKDIR PUT GET COPY RUN SET SESSION ATTACH RECOVER"
    elseif cmd == "REGISTER" and parts[2] and parts[3] then
        local username = parts[2]
        if not username:match("^[A-Za-z0-9_.-]+$") or #username < 3 or #username > 40 then
            return "ERR invalid user"
        end
        if users[username:lower()] then
            return "ERR exists"
        end
        create_user(username, parts[3])
        return "OK registered"
    elseif cmd == "LOGIN" and parts[2] and parts[3] then
        if not check_password(parts[2], parts[3]) then
            return "ERR auth"
        end
        set_login(state, parts[2])
        return "OK logged in"
    elseif cmd == "ATTACH" and parts[2] then
        for _, user in pairs(users) do
            if user.session_token == parts[2] then
                set_login(state, user.name)
                return "OK attached"
            end
        end
        return "ERR attach"
    elseif cmd == "RECOVER" and parts[2] then
        local nonce, blob = recovery_blob(parts[2])
        if not nonce then
            return "ERR no user"
        end
        return "OK " .. nonce .. " " .. blob
    end

    local ok, msg = require_user(state)
    if not ok then
        return msg
    end

    if cmd == "WHOAMI" then
        return "OK " .. state.user
    elseif cmd == "PWD" or cmd == "CD" then
        if cmd == "CD" and parts[2] then
            local p = real_path(state, parts[2])
            if not visible_to(state, parts[2]) then
                return "ERR access denied"
            end
            mkdirp(p)
            state.cwd = p
            state.env.CD = p
        end
        return "OK " .. state.cwd:gsub("/", "\\")
    elseif cmd == "DIR" then
        local listing, err = list_dir(state, parts[2] or ".")
        if not listing then
            return "ERR " .. err
        end
        return "OK " .. b64encode(listing)
    elseif cmd == "MKDIR" and parts[2] then
        if not visible_to(state, parts[2]) then
            return "ERR access denied"
        end
        mkdirp(real_path(state, parts[2]))
        return "OK created"
    elseif cmd == "PUT" and parts[2] and parts[3] then
        if not visible_to(state, parts[2]) then
            return "ERR access denied"
        end
        local data = b64decode(parts[3])
        write_file(real_path(state, parts[2]), data, state.user)
        return "OK stored"
    elseif cmd == "GET" and parts[2] then
        if not visible_to(state, parts[2]) then
            return "ERR access denied"
        end
        local data = read_file(real_path(state, parts[2]))
        if not data then
            return "ERR missing"
        end
        return "OK " .. b64encode(data)
    elseif cmd == "COPY" and parts[2] and parts[3] then
        if not visible_to(state, parts[2]) or not visible_to(state, parts[3]) then
            return "ERR access denied"
        end
        local data = read_file(real_path(state, parts[2]))
        if not data then
            return "ERR missing"
        end
        write_file(real_path(state, parts[3]), data, state.user)
        return "OK copied"
    elseif cmd == "SET" and parts[2] and parts[3] then
        local value = line:match("^%S+%s+%S+%s+(.+)$") or ""
        state.env[parts[2]:upper()] = value
        return "OK set"
    elseif cmd == "SESSION" then
        return "OK " .. users[state.user:lower()].session_token
    elseif cmd == "RUN" and parts[2] then
        local argv = {}
        for i = 3, #parts do
            argv[#argv + 1] = parts[i]
        end
        local success, result = run_script(state, parts[2], argv)
        if not success then
            return "ERR " .. result
        end
        return "OK " .. result
    else
        return "ERR syntax"
    end
end

local function send_prompt(client, text)
    client:send(text .. "\r\n" .. PROMPT)
end

math.randomseed(os.time() ~ tonumber(tostring({}):match("0x(%x+)"), 16))
mkdirp("C:/Users/Public")
write_file("C:/Users/Public/readme.txt", "Doors command service\n", "SYSTEM")

local server = assert(socket.bind("*", PORT))
server:settimeout(0)
print("doors listening on " .. tostring(PORT))

while true do
    local readset = { server }
    for client, _ in pairs(clients) do
        readset[#readset + 1] = client
    end
    local readable = socket.select(readset, nil, 1)
    for _, s in ipairs(readable) do
        if s == server then
            local client = server:accept()
            if client then
                client:settimeout(0)
                clients[client] = { buffer = "", user = nil, cwd = "C:/", env = {} }
                send_prompt(client, "DOORS 1.0")
            end
        else
            local state = clients[s]
            local chunk, err, partial = s:receive(4096)
            local data = chunk or partial
            if data and #data > 0 then
                state.buffer = state.buffer .. data
                while state.buffer:find("\n", 1, true) do
                    local idx = state.buffer:find("\n", 1, true)
                    local line = state.buffer:sub(1, idx - 1):gsub("\r$", "")
                    state.buffer = state.buffer:sub(idx + 1)
                    local ok_handle, response = pcall(handle_command, state, line)
                    if ok_handle then
                        send_prompt(s, response)
                    else
                        send_prompt(s, "ERR internal")
                    end
                end
            elseif err == "closed" then
                clients[s] = nil
                s:close()
            end
        end
    end
end
