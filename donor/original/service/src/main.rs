use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

const PORT: u16 = 4739;

#[derive(Clone)]
struct User {
    password: String,
    display: String,
}

#[derive(Clone)]
struct Org {
    slug: String,
    name: String,
    owner: String,
    admins: Vec<String>,
    vault: String,
}

#[derive(Clone)]
struct Campaign {
    id: String,
    org: String,
    title: String,
    story: String,
    goal: u64,
    lane: String,
}

#[derive(Clone)]
struct Donation {
    id: String,
    donor: String,
    org: String,
    campaign: String,
    amount: u64,
    note: String,
    receipt: String,
    settled: bool,
}

#[derive(Default)]
struct AppState {
    users: HashMap<String, User>,
    orgs: HashMap<String, Org>,
    campaigns: HashMap<String, Campaign>,
    donations: HashMap<String, Donation>,
    sessions: HashMap<String, String>,
    handoffs: HashMap<String, String>,
    sequence: u64,
}

struct Request {
    method: String,
    path: String,
    query: HashMap<String, String>,
    headers: HashMap<String, String>,
    body: String,
}

struct Response {
    status: u16,
    content_type: String,
    body: String,
    headers: Vec<(String, String)>,
}

fn main() {
    let state = Arc::new(Mutex::new(AppState::default()));
    let listener = TcpListener::bind(("0.0.0.0", PORT)).expect("bind");
    for stream in listener.incoming().flatten() {
        let state = Arc::clone(&state);
        std::thread::spawn(move || {
            let _ = handle_connection(stream, state);
        });
    }
}

fn handle_connection(mut stream: TcpStream, state: Arc<Mutex<AppState>>) -> std::io::Result<()> {
    let mut buf = [0; 65536];
    let size = stream.read(&mut buf)?;
    if size == 0 {
        return Ok(());
    }
    let raw = String::from_utf8_lossy(&buf[..size]).to_string();
    let response = match parse_request(&raw) {
        Some(req) => route(req, state),
        None => text_response(400, "bad request"),
    };
    write_response(&mut stream, response)
}

fn parse_request(raw: &str) -> Option<Request> {
    let (head, body) = raw.split_once("\r\n\r\n").unwrap_or((raw, ""));
    let mut lines = head.lines();
    let first = lines.next()?;
    let mut parts = first.split_whitespace();
    let method = parts.next()?.to_string();
    let target = parts.next()?.to_string();
    let (path, query) = if let Some((p, q)) = target.split_once('?') {
        (p.to_string(), parse_form(q))
    } else {
        (target, HashMap::new())
    };
    let mut headers = HashMap::new();
    for line in lines {
        if let Some((k, v)) = line.split_once(':') {
            headers.insert(k.trim().to_ascii_lowercase(), v.trim().to_string());
        }
    }
    Some(Request {
        method,
        path,
        query,
        headers,
        body: body.to_string(),
    })
}

fn route(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let path = req.path.clone();
    let segments: Vec<&str> = path.trim_matches('/').split('/').filter(|s| !s.is_empty()).collect();
    match (req.method.as_str(), segments.as_slice()) {
        ("GET", []) => html_response(200, landing_page()),
        ("GET", ["health"]) => json_response(200, r#"{"ok":true}"#.to_string()),
        ("POST", ["api", "register_user"]) => register_user(req, state),
        ("POST", ["api", "register_org"]) => register_org(req, state),
        ("POST", ["api", "login"]) => login(req, state),
        ("POST", ["api", "campaigns"]) => create_campaign(req, state),
        ("GET", ["api", "orgs", slug]) => show_org(slug, state),
        ("GET", ["api", "campaigns", campaign_id]) => show_campaign(campaign_id, state),
        ("POST", ["api", "donations", "quote"]) => donation_quote(req, state),
        ("POST", ["api", "donations", "commit"]) => donation_commit(req, state),
        ("GET", ["api", "me", "donations"]) => my_donations(req, state),
        ("GET", ["api", "orgs", slug, "donations"]) => org_donations(req, slug, state),
        ("GET", ["api", "orgs", slug, "archive"]) => org_archive(req, slug, state),
        ("GET", ["api", "orgs", slug, "handoff"]) => org_handoff(req, slug, state),
        ("POST", ["api", "orgs", slug, "handoff", "accept"]) => accept_handoff(req, slug, state),
        ("POST", ["api", "routing", "ticket"]) => routing_ticket(req, state),
        ("POST", ["api", "routing", "settle"]) => routing_settle(req, state),
        ("GET", ["api", "receipts", receipt]) => receipt_view(req, receipt, state),
        ("GET", ["api", "ledger", "window"]) => ledger_window(req, state),
        _ => text_response(404, "not found"),
    }
}

fn register_user(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let username = clean(form.get("username").map(String::as_str).unwrap_or(""));
    let password = form.get("password").cloned().unwrap_or_default();
    let display = escape(form.get("display").map(String::as_str).unwrap_or(&username));
    if username.len() < 3 || password.len() < 4 {
        return json_response(400, r#"{"error":"invalid registration"}"#.to_string());
    }
    let mut db = state.lock().unwrap();
    if db.users.contains_key(&username) {
        return json_response(409, r#"{"error":"username exists"}"#.to_string());
    }
    db.users.insert(username.clone(), User { password, display });
    json_response(200, format!(r#"{{"username":"{}"}}"#, username))
}

fn register_org(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let username = clean(form.get("username").map(String::as_str).unwrap_or(""));
    let password = form.get("password").cloned().unwrap_or_default();
    let slug = clean(form.get("org_slug").map(String::as_str).unwrap_or(""));
    let name = escape(form.get("org_name").map(String::as_str).unwrap_or(&slug));
    let vault = escape(form.get("vault").map(String::as_str).unwrap_or(""));
    if username.len() < 3 || password.len() < 4 || slug.len() < 3 {
        return json_response(400, r#"{"error":"invalid organization"}"#.to_string());
    }
    let mut db = state.lock().unwrap();
    if db.users.contains_key(&username) || db.orgs.contains_key(&slug) {
        return json_response(409, r#"{"error":"name exists"}"#.to_string());
    }
    db.users.insert(username.clone(), User { password, display: name.clone() });
    db.orgs.insert(slug.clone(), Org {
        slug: slug.clone(),
        name,
        owner: username.clone(),
        admins: vec![username],
        vault,
    });
    json_response(200, format!(r#"{{"org":"{}"}}"#, slug))
}

fn login(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let username = form.get("username").cloned().unwrap_or_default();
    let password = form.get("password").cloned().unwrap_or_default();
    let mut db = state.lock().unwrap();
    let Some(user) = db.users.get(&username) else {
        return json_response(403, r#"{"error":"login failed"}"#.to_string());
    };
    if user.password != password {
        return json_response(403, r#"{"error":"login failed"}"#.to_string());
    }
    let display = user.display.clone();
    let sid = new_id(&mut db, "s");
    db.sessions.insert(sid.clone(), username.clone());
    let mut resp = json_response(200, format!(r#"{{"username":"{}","display":"{}"}}"#, escape(&username), display));
    resp.headers.push(("Set-Cookie".into(), format!("sid={}; Path=/; HttpOnly", sid)));
    resp
}

fn create_campaign(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let mut db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let org = clean(form.get("org").map(String::as_str).unwrap_or(""));
    if !is_admin(&db, &org, &username) {
        return json_response(403, r#"{"error":"org admin required"}"#.to_string());
    }
    let title = escape(form.get("title").map(String::as_str).unwrap_or("Community need"));
    let story = escape(form.get("story").map(String::as_str).unwrap_or(""));
    let goal = form.get("goal").and_then(|v| v.parse::<u64>().ok()).unwrap_or(1000);
    let lane = form.get("lane").map(|v| clean(v)).filter(|v| !v.is_empty()).unwrap_or_else(|| lane_for(&org));
    let id = new_id(&mut db, "c");
    db.campaigns.insert(id.clone(), Campaign {
        id: id.clone(),
        org: org.clone(),
        title,
        story,
        goal,
        lane: lane.clone(),
    });
    json_response(200, format!(r#"{{"campaign":"{}","lane":"{}"}}"#, id, lane))
}

fn show_org(slug: &str, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let Some(org) = db.orgs.get(slug) else {
        return json_response(404, r#"{"error":"missing org"}"#.to_string());
    };
    let mut campaigns = Vec::new();
    for c in db.campaigns.values().filter(|c| c.org == org.slug) {
        campaigns.push(format!(
            r#"{{"id":"{}","title":"{}","goal":{},"lane":"{}"}}"#,
            c.id, c.title, c.goal, c.lane
        ));
    }
    json_response(200, format!(
        r#"{{"slug":"{}","name":"{}","owner":"{}","campaigns":[{}]}}"#,
        org.slug, org.name, org.owner, campaigns.join(",")
    ))
}

fn show_campaign(campaign_id: &str, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let Some(c) = db.campaigns.get(campaign_id) else {
        return json_response(404, r#"{"error":"missing campaign"}"#.to_string());
    };
    json_response(200, format!(
        r#"{{"id":"{}","org":"{}","title":"{}","story":"{}","goal":{},"lane":"{}"}}"#,
        c.id, c.org, c.title, c.story, c.goal, c.lane
    ))
}

fn donation_quote(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let campaign = form.get("campaign").cloned().unwrap_or_default();
    let amount = form.get("amount").and_then(|v| v.parse::<u64>().ok()).unwrap_or(1);
    let Some(c) = db.campaigns.get(&campaign) else {
        return json_response(404, r#"{"error":"missing campaign"}"#.to_string());
    };
    let scope = fold(&format!("{}:{}:{}", username, c.lane, amount));
    let token = format!("{}:{}:{}:{}", campaign, amount, c.lane, scope);
    json_response(200, format!(r#"{{"quote":"{}","org":"{}","lane":"{}"}}"#, token, c.org, c.lane))
}

fn donation_commit(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let mut db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let quote = form.get("quote").cloned().unwrap_or_default();
    let mut parts = quote.split(':');
    let campaign_id = parts.next().unwrap_or("").to_string();
    let amount = parts.next().and_then(|v| v.parse::<u64>().ok()).unwrap_or(0);
    let lane = parts.next().unwrap_or("").to_string();
    let scope = parts.next().unwrap_or("").to_string();
    if fold(&format!("{}:{}:{}", username, lane, amount)) != scope {
        return json_response(403, r#"{"error":"quote expired"}"#.to_string());
    }
    let Some(campaign) = db.campaigns.get(&campaign_id).cloned() else {
        return json_response(404, r#"{"error":"missing campaign"}"#.to_string());
    };
    let note = escape(form.get("note").map(String::as_str).unwrap_or(""));
    let receipt = fold(&format!("{}:{}:{}", username, campaign_id, note));
    let id = new_id(&mut db, "d");
    db.donations.insert(id.clone(), Donation {
        id: id.clone(),
        donor: username,
        org: campaign.org,
        campaign: campaign_id,
        amount,
        note,
        receipt: receipt.clone(),
        settled: false,
    });
    json_response(200, format!(r#"{{"donation":"{}","receipt":"{}"}}"#, id, receipt))
}

fn my_donations(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let items: Vec<String> = db.donations.values()
        .filter(|d| d.donor == username)
        .map(donation_json)
        .collect();
    json_response(200, format!(r#"{{"donations":[{}]}}"#, items.join(",")))
}

fn org_donations(req: Request, slug: &str, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    if !is_admin(&db, slug, &username) {
        return json_response(403, r#"{"error":"org admin required"}"#.to_string());
    }
    let items: Vec<String> = db.donations.values()
        .filter(|d| d.org == slug)
        .map(donation_json)
        .collect();
    let vault = db.orgs.get(slug).map(|o| o.vault.clone()).unwrap_or_default();
    json_response(200, format!(r#"{{"vault":"{}","donations":[{}]}}"#, vault, items.join(",")))
}

fn org_archive(req: Request, slug: &str, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let mark = req.query.get("mark").cloned().unwrap_or_default();
    let Some(org) = db.orgs.get(slug) else {
        return json_response(404, r#"{"error":"missing org"}"#.to_string());
    };
    if fold(&format!("{}:{}", org.slug, org.owner)) != mark {
        return json_response(403, r#"{"error":"archive unavailable"}"#.to_string());
    }
    let items: Vec<String> = db.donations.values()
        .filter(|d| d.org == slug)
        .map(donation_json)
        .collect();
    json_response(200, format!(r#"{{"archive":[{}]}}"#, items.join(",")))
}

fn org_handoff(req: Request, slug: &str, state: Arc<Mutex<AppState>>) -> Response {
    let mut db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    if !is_admin(&db, slug, &username) {
        return json_response(403, r#"{"error":"org admin required"}"#.to_string());
    }
    let stamp = now() / 60;
    let proof = fold(&format!("{}:{}", username, stamp));
    let token = format!("{}.{}.{}", slug, stamp, proof);
    db.handoffs.insert(proof.clone(), username);
    json_response(200, format!(r#"{{"handoff":"{}"}}"#, token))
}

fn accept_handoff(req: Request, slug: &str, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let mut db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let token = form.get("handoff").cloned().unwrap_or_default();
    let pieces: Vec<&str> = token.split('.').collect();
    if pieces.len() != 3 || pieces[1].parse::<u64>().ok().filter(|s| now() / 60 <= *s + 4).is_none() {
        return json_response(403, r#"{"error":"handoff expired"}"#.to_string());
    }
    if !db.handoffs.contains_key(pieces[2]) {
        return json_response(403, r#"{"error":"handoff unknown"}"#.to_string());
    }
    let Some(org) = db.orgs.get_mut(slug) else {
        return json_response(404, r#"{"error":"missing org"}"#.to_string());
    };
    if !org.admins.iter().any(|u| u == &username) {
        org.admins.push(username);
    }
    json_response(200, r#"{"accepted":true}"#.to_string())
}

fn routing_ticket(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let org = clean(form.get("org").map(String::as_str).unwrap_or(""));
    if !is_admin(&db, &org, &username) {
        return json_response(403, r#"{"error":"org admin required"}"#.to_string());
    }
    let lane = form.get("lane").map(|v| clean(v)).unwrap_or_else(|| lane_for(&org));
    let ticket = format!("{}:{}:{}", org, lane, fold(&format!("{}:{}", username, lane)));
    json_response(200, format!(r#"{{"ticket":"{}"}}"#, ticket))
}

fn routing_settle(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let form = parse_form(&req.body);
    let mut db = state.lock().unwrap();
    let Some(username) = session_user(&req, &db) else {
        return json_response(401, r#"{"error":"login required"}"#.to_string());
    };
    let ticket = form.get("ticket").cloned().unwrap_or_default();
    let donation_id = form.get("donation").cloned().unwrap_or_default();
    let pieces: Vec<&str> = ticket.split(':').collect();
    if pieces.len() != 3 || fold(&format!("{}:{}", username, pieces[1])) != pieces[2] {
        return json_response(403, r#"{"error":"ticket rejected"}"#.to_string());
    }
    if !is_admin(&db, pieces[0], &username) {
        return json_response(403, r#"{"error":"org admin required"}"#.to_string());
    }
    let campaign_id = match db.donations.get(&donation_id) {
        Some(d) => d.campaign.clone(),
        None => return json_response(404, r#"{"error":"missing donation"}"#.to_string()),
    };
    let campaign_lane = db.campaigns.get(&campaign_id).map(|c| c.lane.clone()).unwrap_or_default();
    let Some(d) = db.donations.get_mut(&donation_id) else {
        return json_response(404, r#"{"error":"missing donation"}"#.to_string());
    };
    if campaign_lane != pieces[1] {
        return json_response(409, r#"{"error":"routing lane mismatch"}"#.to_string());
    }
    d.org = pieces[0].to_string();
    d.settled = true;
    json_response(200, format!(r#"{{"moved":"{}"}}"#, d.id))
}

fn receipt_view(req: Request, receipt: &str, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let user = session_user(&req, &db);
    for d in db.donations.values() {
        if d.receipt == receipt {
            if Some(d.donor.clone()) == user || user.as_ref().is_some_and(|u| is_admin(&db, &d.org, u)) {
                return json_response(200, donation_json(d));
            }
            return json_response(403, r#"{"error":"receipt locked"}"#.to_string());
        }
    }
    json_response(404, r#"{"error":"missing receipt"}"#.to_string())
}

fn ledger_window(req: Request, state: Arc<Mutex<AppState>>) -> Response {
    let db = state.lock().unwrap();
    let org = clean(req.query.get("org").map(String::as_str).unwrap_or(""));
    let lane = req.query.get("lane").map(|v| clean(v)).unwrap_or_default();
    let digest = req.query.get("digest").cloned().unwrap_or_default();
    if fold(&format!("{}:{}", org, lane)) != digest {
        return json_response(403, r#"{"error":"window closed"}"#.to_string());
    }
    let items: Vec<String> = db.donations.values()
        .filter(|d| db.campaigns.get(&d.campaign).is_some_and(|c| c.org == org || c.lane == lane))
        .map(donation_json)
        .collect();
    json_response(200, format!(r#"{{"entries":[{}]}}"#, items.join(",")))
}

fn session_user(req: &Request, db: &AppState) -> Option<String> {
    let cookie = req.headers.get("cookie")?;
    for part in cookie.split(';') {
        let trimmed = part.trim();
        if let Some(sid) = trimmed.strip_prefix("sid=") {
            return db.sessions.get(sid).cloned();
        }
    }
    None
}

fn is_admin(db: &AppState, org: &str, username: &str) -> bool {
    db.orgs.get(org).is_some_and(|o| o.admins.iter().any(|u| u == username))
}

fn donation_json(d: &Donation) -> String {
    format!(
        r#"{{"id":"{}","donor":"{}","org":"{}","campaign":"{}","amount":{},"note":"{}","receipt":"{}","settled":{}}}"#,
        d.id, d.donor, d.org, d.campaign, d.amount, d.note, d.receipt, d.settled
    )
}

fn new_id(db: &mut AppState, prefix: &str) -> String {
    db.sequence += 1;
    format!("{}{:08x}", prefix, db.sequence)
}

fn parse_form(input: &str) -> HashMap<String, String> {
    let mut form = HashMap::new();
    for pair in input.split('&') {
        if pair.is_empty() {
            continue;
        }
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        form.insert(url_decode(k), url_decode(v));
    }
    form
}

fn url_decode(input: &str) -> String {
    let mut out = String::new();
    let bytes = input.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(' '),
            b'%' if i + 2 < bytes.len() => {
                if let Ok(v) = u8::from_str_radix(&input[i + 1..i + 3], 16) {
                    out.push(v as char);
                    i += 2;
                }
            }
            b => out.push(b as char),
        }
        i += 1;
    }
    out
}

fn clean(input: &str) -> String {
    input.chars()
        .filter(|c| c.is_ascii_alphanumeric() || *c == '-' || *c == '_')
        .take(48)
        .collect::<String>()
        .to_ascii_lowercase()
}

fn escape(input: &str) -> String {
    input.chars()
        .take(500)
        .flat_map(|c| match c {
            '"' => "\\\"".chars().collect::<Vec<_>>(),
            '\\' => "\\\\".chars().collect(),
            '\n' | '\r' => " ".chars().collect(),
            '<' => "&lt;".chars().collect(),
            '>' => "&gt;".chars().collect(),
            '&' => "&amp;".chars().collect(),
            _ => vec![c],
        })
        .collect()
}

fn fold(input: &str) -> String {
    let mut h: u64 = 0xcbf29ce484222325;
    for b in input.bytes() {
        h ^= b as u64;
        h = h.wrapping_mul(0x100000001b3);
        h ^= h.rotate_left(13);
    }
    format!("{:016x}", h)
}

fn lane_for(slug: &str) -> String {
    format!("ln{}", &fold(slug)[..8])
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs()
}

fn write_response(stream: &mut TcpStream, response: Response) -> std::io::Result<()> {
    let reason = match response.status {
        200 => "OK",
        400 => "Bad Request",
        401 => "Unauthorized",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        _ => "Error",
    };
    let mut head = format!(
        "HTTP/1.1 {} {}\r\nContent-Type: {}\r\nContent-Length: {}\r\nConnection: close\r\n",
        response.status,
        reason,
        response.content_type,
        response.body.as_bytes().len()
    );
    for (k, v) in response.headers {
        head.push_str(&format!("{}: {}\r\n", k, v));
    }
    head.push_str("\r\n");
    stream.write_all(head.as_bytes())?;
    stream.write_all(response.body.as_bytes())
}

fn json_response(status: u16, body: String) -> Response {
    Response { status, content_type: "application/json".into(), body, headers: Vec::new() }
}

fn html_response(status: u16, body: String) -> Response {
    Response { status, content_type: "text/html; charset=utf-8".into(), body, headers: Vec::new() }
}

fn text_response(status: u16, body: &str) -> Response {
    Response { status, content_type: "text/plain; charset=utf-8".into(), body: body.into(), headers: Vec::new() }
}

fn landing_page() -> String {
    r#"<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GiveHere</title>
  <style>
    :root { color-scheme: light; --ink:#1f2a32; --muted:#64717b; --paper:#f7f4ed; --panel:#ffffff; --leaf:#2f7d62; --rose:#b95363; --gold:#d89a32; --line:#d8d2c4; }
    * { box-sizing: border-box; }
    body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; background:var(--paper); color:var(--ink); }
    header { min-height:52vh; display:grid; align-items:end; padding:32px; background:linear-gradient(115deg, rgba(31,42,50,.8), rgba(47,125,98,.55)), url('https://images.unsplash.com/photo-1593113598332-cd288d649433?auto=format&fit=crop&w=1600&q=80') center/cover; color:white; }
    .hero { max-width:980px; }
    h1 { font-size:clamp(42px, 7vw, 86px); line-height:.95; margin:0 0 16px; letter-spacing:0; }
    .hero p { max-width:620px; font-size:18px; line-height:1.55; margin:0 0 24px; }
    main { max-width:1120px; margin:-38px auto 48px; padding:0 20px; display:grid; gap:22px; }
    section { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:22px; box-shadow:0 12px 30px rgba(31,42,50,.08); }
    .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); gap:18px; }
    h2 { margin:0 0 14px; font-size:22px; }
    label { display:block; color:var(--muted); font-size:13px; font-weight:700; margin:12px 0 6px; }
    input, textarea { width:100%; border:1px solid var(--line); border-radius:6px; padding:11px 12px; font:inherit; background:#fffdfa; color:var(--ink); }
    textarea { min-height:86px; resize:vertical; }
    button { appearance:none; border:0; border-radius:6px; padding:11px 14px; margin-top:14px; font-weight:800; cursor:pointer; background:var(--leaf); color:white; }
    button.secondary { background:var(--rose); }
    .toolbar { display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .feed { display:grid; gap:10px; }
    .pill { display:inline-flex; align-items:center; min-height:28px; padding:4px 9px; border-radius:999px; background:#f2eadb; color:#5f4a1e; font-size:13px; font-weight:800; }
    pre { white-space:pre-wrap; overflow:auto; background:#1f2a32; color:#edf7f1; border-radius:8px; padding:14px; min-height:76px; }
  </style>
</head>
<body>
  <header><div class="hero"><span class="pill">GiveHere Donation Desk</span><h1>GiveHere</h1><p>Community organizations publish focused campaigns, donors contribute with private notes, and receiving teams manage gift records from a quiet operations console.</p></div></header>
  <main>
    <div class="grid">
      <section>
        <h2>User Access</h2>
        <label>Username</label><input id="u" value="donor">
        <label>Password</label><input id="p" type="password" value="donorpass">
        <div class="toolbar"><button onclick="post('/api/register_user',{username:u.value,password:p.value,display:u.value})">Register User</button><button class="secondary" onclick="post('/api/login',{username:u.value,password:p.value})">Log In</button></div>
      </section>
      <section>
        <h2>Organization Access</h2>
        <label>Admin Username</label><input id="ou" value="harbor-admin">
        <label>Password</label><input id="op" type="password" value="orgpass">
        <label>Organization Slug</label><input id="os" value="harbor-kitchen">
        <label>Organization Name</label><input id="on" value="Harbor Kitchen">
        <button onclick="post('/api/register_org',{username:ou.value,password:op.value,org_slug:os.value,org_name:on.value,vault:'intake desk'})">Create Org</button>
      </section>
      <section>
        <h2>Campaign</h2>
        <label>Org Slug</label><input id="co" value="harbor-kitchen">
        <label>Title</label><input id="ct" value="Weekend pantry drive">
        <label>Story</label><textarea id="cs">Help stock the pantry before Saturday distribution.</textarea>
        <label>Goal</label><input id="cg" value="2500">
        <button onclick="post('/api/campaigns',{org:co.value,title:ct.value,story:cs.value,goal:cg.value})">Post Campaign</button>
      </section>
    </div>
    <section>
      <h2>Donate</h2>
      <div class="grid">
        <div><label>Campaign ID</label><input id="dc"><label>Amount</label><input id="da" value="25"><button onclick="quote()">Prepare Donation</button></div>
        <div><label>Quote</label><input id="dq"><label>Private Note</label><textarea id="dn">For the receiving team only.</textarea><button onclick="post('/api/donations/commit',{quote:dq.value,note:dn.value})">Send Donation</button></div>
      </div>
    </section>
    <section><h2>Console</h2><pre id="out"></pre></section>
  </main>
  <script>
    function enc(o){return Object.entries(o).map(([k,v])=>encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&')}
    async function post(path, data){let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:enc(data)}); out.textContent=await r.text(); return r}
    async function quote(){let r=await post('/api/donations/quote',{campaign:dc.value,amount:da.value}); let j=JSON.parse(out.textContent); dq.value=j.quote||''}
  </script>
</body>
</html>"#.to_string()
}
