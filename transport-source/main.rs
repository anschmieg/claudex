use std::io;
use std::net::{IpAddr, SocketAddr};
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{SystemTime, UNIX_EPOCH};

use anyhow::{Context, Result, bail};
use axum::{
    Router,
    body::{Body, Bytes},
    extract::{DefaultBodyLimit, State},
    http::{
        HeaderMap, HeaderName, HeaderValue, Request, Response, StatusCode,
        header::{AUTHORIZATION, CONTENT_TYPE, WWW_AUTHENTICATE},
    },
    middleware::{self, Next},
    response::IntoResponse,
    routing::{get, post},
};
use clap::Parser;
use codex_http_client::{HttpClientFactory, OutboundProxyPolicy};
use codex_login::{
    AgentIdentityAuthPolicy, AuthCredentialsStoreMode, AuthKeyringBackendKind, AuthManager,
    AuthRouteConfig, default_client,
};
use codex_model_provider::{
    AgentIdentitySessionFallback, ProviderAuthScope, SharedModelProvider, WorkspaceRoutingContext,
    create_model_provider,
};
use codex_model_provider_info::ModelProviderInfo;
use codex_protocol::protocol::SessionSource;
use codex_websocket_client::WebSocketConnector;
use futures::{SinkExt, StreamExt};
use serde_json::Value;
use tokio::{net::TcpListener, process::Command, sync::Mutex};
use tokio_tungstenite::tungstenite::{
    Message,
    client::IntoClientRequest,
    extensions::{ExtensionsConfig, compression::deflate::DeflateConfig},
    protocol::WebSocketConfig,
};

const MAX_REQUEST_BYTES: usize = 64 * 1024 * 1024;
const WS_BETA: &str = "responses_websockets=2026-02-06";

#[derive(Debug, Parser)]
#[command(name = "claudex-transport")]
struct Args {
    #[arg(
        long,
        env = "CLAUDEX_TRANSPORT_LISTEN",
        default_value = "127.0.0.1:3130"
    )]
    listen: SocketAddr,

    #[arg(long, env = "CODEX_HOME")]
    codex_home: Option<PathBuf>,

    /// Native Sign in with ChatGPT helper. When this returns a valid plan token,
    /// public Responses API routing is preferred over legacy Codex auth.
    #[arg(long, env = "CLAUDEX_SIWC_HELPER")]
    siwc_helper: Option<PathBuf>,

    #[arg(long, env = "CLAUDEX_AUTH_MODE", default_value = "auto")]
    auth_mode: String,
}

#[derive(Debug, Clone)]
struct SiwcToken {
    access_token: String,
    expires_at: u64,
}

#[derive(Clone)]
enum AuthBackend {
    Siwc {
        helper: PathBuf,
        client: reqwest::Client,
        token: Arc<Mutex<SiwcToken>>,
    },
    Codex {
        model_provider: SharedModelProvider,
        auth_factory: HttpClientFactory,
        fallback: AgentIdentitySessionFallback,
        routing: WorkspaceRoutingContext,
    },
}

#[derive(Clone)]
struct AppState {
    backend: AuthBackend,
    /// Per-runtime random secret for the shunt-to-transport hop. Never log it.
    inbound_token: Arc<String>,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    ensure_loopback(args.listen.ip())?;
    // Refuse unauthenticated startup, even when bound to localhost.
    // Same-user processes can connect to TCP loopback; localhost is not auth.
    let inbound_token = std::env::var("CLAUDEX_TRANSPORT_TOKEN")
        .context("CLAUDEX_TRANSPORT_TOKEN must be set for authenticated local transport")?;
    ensure_strong_local_token(&inbound_token)?;
    let codex_home = args.codex_home.clone().unwrap_or_else(default_codex_home);

    let backend = select_backend(&args, codex_home).await?;
    let state = AppState {
        backend,
        inbound_token: Arc::new(inbound_token),
    };
    verify_backend(&state)
        .await
        .context("Claudex authentication is not ready")?;

    let listener = TcpListener::bind(args.listen)
        .await
        .with_context(|| format!("failed to bind {}", args.listen))?;
    let actual = listener.local_addr()?;
    eprintln!("claudex-transport listening on http://{actual}");

    let app = Router::new()
        .route("/healthz", get(health))
        .route("/readyz", get(ready))
        .route(
            "/v1/responses",
            post(responses).route_layer(middleware::from_fn_with_state(
                state.clone(),
                authorize_local_transport,
            )),
        )
        .layer(DefaultBodyLimit::max(MAX_REQUEST_BYTES))
        .with_state(state);

    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await
        .context("claudex transport server failed")?;
    Ok(())
}

/// Exactly 32 cryptographically random bytes encoded as lowercase hex.
/// This is a session-scoped bearer credential, never the ChatGPT OAuth token.
fn ensure_strong_local_token(token: &str) -> Result<()> {
    if token.len() != 64 || !token.bytes().all(|b| b.is_ascii_hexdigit()) {
        bail!("CLAUDEX_TRANSPORT_TOKEN must contain 32 random bytes encoded as 64 hex characters");
    }
    Ok(())
}

/// Fixed-length byte comparison prevents an early match/mismatch timing oracle.
/// It does not make file-based tokens a hard boundary against processes that
/// already possess the user's filesystem permissions.
fn constant_time_matches(expected: &[u8], supplied: &[u8]) -> bool {
    if expected.len() != supplied.len() {
        return false;
    }
    let mut mismatch: u8 = 0;
    for (left, right) in expected.iter().zip(supplied) {
        mismatch |= left ^ right;
    }
    mismatch == 0
}

fn valid_transport_bearer(headers: &HeaderMap, token: &str) -> bool {
    let Some(value) = headers.get(AUTHORIZATION) else {
        return false;
    };
    let mut expected = Vec::with_capacity(7 + token.len());
    expected.extend_from_slice(b"Bearer ");
    expected.extend_from_slice(token.as_bytes());
    constant_time_matches(&expected, value.as_bytes())
}

/// Auth middleware runs *before* request-body extraction or upstream forwarding.
/// Readiness endpoints are deliberately exempt for lifecycle monitoring.
async fn authorize_local_transport(
    State(state): State<AppState>,
    request: Request<Body>,
    next: Next,
) -> Response<Body> {
    if !valid_transport_bearer(request.headers(), &state.inbound_token) {
        return (
            StatusCode::UNAUTHORIZED,
            [(WWW_AUTHENTICATE, "Bearer")],
            "Claudex transport requires a valid local session token",
        )
            .into_response();
    }
    next.run(request).await
}

#[cfg(test)]
mod local_transport_auth_tests {
    use super::*;

    #[test]
    fn local_token_requires_32_random_bytes_in_hex() {
        assert!(ensure_strong_local_token(&"ab".repeat(32)).is_ok());
        assert!(ensure_strong_local_token("claudex-local").is_err());
        assert!(ensure_strong_local_token(&"aa".repeat(15)).is_err());
        assert!(ensure_strong_local_token(&"zz".repeat(32)).is_err());
    }

    #[test]
    fn transport_bearer_is_missing_wrong_or_successful() {
        let token = "a1".repeat(32);
        let mut headers = HeaderMap::new();
        assert!(!valid_transport_bearer(&headers, &token));
        headers.insert(AUTHORIZATION, HeaderValue::from_static("Bearer wrong"));
        assert!(!valid_transport_bearer(&headers, &token));
        headers.insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {token}")).unwrap(),
        );
        assert!(valid_transport_bearer(&headers, &token));
        headers.insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("bearer {token}")).unwrap(),
        );
        assert!(!valid_transport_bearer(&headers, &token));
    }
}

fn default_codex_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".codex")
}

fn ensure_loopback(ip: IpAddr) -> Result<()> {
    if !ip.is_loopback() {
        bail!("claudex-transport refuses non-loopback listen address {ip}");
    }
    Ok(())
}

async fn shutdown_signal() {
    let _ = tokio::signal::ctrl_c().await;
}

async fn health() -> impl IntoResponse {
    (StatusCode::OK, "ok")
}

async fn ready(State(state): State<AppState>) -> Response<Body> {
    match verify_backend(&state).await {
        Ok(_) => (StatusCode::OK, "ready").into_response(),
        Err(error) => (
            StatusCode::SERVICE_UNAVAILABLE,
            format!("Claudex auth not ready: {error}"),
        )
            .into_response(),
    }
}

async fn select_backend(args: &Args, codex_home: PathBuf) -> Result<AuthBackend> {
    let mode = args.auth_mode.as_str();
    if !matches!(mode, "auto" | "siwc" | "codex") {
        bail!("CLAUDEX_AUTH_MODE must be auto, siwc, or codex");
    }
    if mode != "codex" {
        if let Some(helper) = args.siwc_helper.clone() {
            if helper.exists() {
                match load_siwc_token(&helper).await {
                    Ok(initial_token) => {
                        eprintln!("claudex-transport auth: native Sign in with ChatGPT");
                        return Ok(AuthBackend::Siwc {
                            helper,
                            client: reqwest::Client::builder()
                                .build()
                                .context("failed to build SIWC HTTP client")?,
                            token: Arc::new(Mutex::new(initial_token)),
                        });
                    }
                    Err(error) if mode == "siwc" => {
                        return Err(error)
                            .context("native Sign in with ChatGPT is required but unavailable");
                    }
                    Err(_) => {}
                }
            } else if mode == "siwc" {
                bail!("SIWC helper not found: {}", helper.display());
            }
        } else if mode == "siwc" {
            bail!("CLAUDEX_SIWC_HELPER is required in siwc auth mode");
        }
    }

    let auth_factory = HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault);
    let auth_route = AuthRouteConfig::from_http_client_factory(auth_factory.clone());
    let auth_manager = AuthManager::shared(
        codex_home.clone(),
        false,
        AuthCredentialsStoreMode::File,
        None,
        None,
        AuthKeyringBackendKind::default(),
        auth_route,
    )
    .await;
    if auth_manager.auth().await.is_none() {
        bail!(
            "No native ChatGPT profile or Codex login found; run `claudex login` or `codex login`"
        );
    }
    let model_provider = create_model_provider(
        ModelProviderInfo::create_openai_provider(None),
        Some(auth_manager),
    );
    eprintln!("claudex-transport auth: legacy Codex AuthManager fallback");
    Ok(AuthBackend::Codex {
        model_provider,
        auth_factory,
        fallback: AgentIdentitySessionFallback::default(),
        routing: WorkspaceRoutingContext::new("https://chatgpt.com/backend-api".to_string()),
    })
}

async fn verify_backend(state: &AppState) -> Result<()> {
    match &state.backend {
        AuthBackend::Siwc { token, .. } => {
            let token = token.lock().await;
            if token.expires_at <= now_ms() {
                bail!("native ChatGPT access token is expired");
            }
            Ok(())
        }
        AuthBackend::Codex { .. } => resolve_codex_auth(state).await.map(|_| ()),
    }
}

async fn resolve_codex_auth(
    state: &AppState,
) -> Result<codex_model_provider::ResolvedProviderAuth> {
    let AuthBackend::Codex {
        model_provider,
        fallback,
        ..
    } = &state.backend
    else {
        bail!("not using Codex auth")
    };
    model_provider
        .api_auth_for_scope(ProviderAuthScope {
            agent_identity_policy: AgentIdentityAuthPolicy::JwtOnly,
            session_source: SessionSource::Cli,
            agent_identity_session_fallback: fallback.clone(),
        })
        .await
        .map_err(anyhow::Error::from)
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

async fn load_siwc_token(helper: &PathBuf) -> Result<SiwcToken> {
    let output = Command::new("node")
        .arg(helper)
        .arg("token")
        .output()
        .await
        .context("failed to run SIWC helper")?;
    if !output.status.success() {
        let message = String::from_utf8_lossy(&output.stderr);
        bail!("native ChatGPT token unavailable: {}", message.trim());
    }
    let value: Value =
        serde_json::from_slice(&output.stdout).context("invalid SIWC helper output")?;
    let access_token = value
        .get("access_token")
        .and_then(Value::as_str)
        .map(str::to_owned)
        .context("SIWC helper did not return an access token")?;
    let expires_at = value
        .get("expires_at")
        .and_then(Value::as_u64)
        .context("SIWC helper did not return token expiry")?;
    Ok(SiwcToken {
        access_token,
        expires_at,
    })
}

async fn siwc_token(state: &AppState) -> Result<String> {
    let AuthBackend::Siwc { helper, token, .. } = &state.backend else {
        bail!("not using SIWC auth")
    };
    let mut cached = token.lock().await;
    if cached.expires_at <= now_ms().saturating_add(60_000) {
        *cached = load_siwc_token(helper).await?;
    }
    Ok(cached.access_token.clone())
}

async fn responses(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Bytes,
) -> Response<Body> {
    match forward_responses(&state, &headers, body).await {
        Ok(response) => response,
        Err(error) => Response::builder()
            .status(StatusCode::BAD_GATEWAY)
            .header(CONTENT_TYPE, "text/plain; charset=utf-8")
            .body(Body::from(format!("claudex transport error: {error:#}")))
            .expect("error response"),
    }
}

async fn forward_responses(
    state: &AppState,
    inbound_headers: &HeaderMap,
    body: Bytes,
) -> Result<Response<Body>> {
    match &state.backend {
        AuthBackend::Siwc { .. } => forward_siwc_responses(state, body).await,
        AuthBackend::Codex { .. } => forward_codex_responses(state, inbound_headers, body).await,
    }
}

async fn forward_siwc_responses(state: &AppState, body: Bytes) -> Result<Response<Body>> {
    let AuthBackend::Siwc { client, .. } = &state.backend else {
        bail!("not using SIWC auth")
    };
    let token = siwc_token(state).await?;
    let response = client
        .post("https://api.openai.com/v1/responses")
        .bearer_auth(token)
        .header("content-type", "application/json")
        .header("accept", "text/event-stream")
        .body(body)
        .send()
        .await
        .context("SIWC Responses request failed")?;
    let status = response.status();
    let content_type = response
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .cloned();
    let request_id = response.headers().get("x-request-id").cloned();
    let stream = response
        .bytes_stream()
        .map(|item| item.map_err(io::Error::other));
    let mut builder = Response::builder().status(status);
    if let Some(value) = content_type {
        builder = builder.header(CONTENT_TYPE, value);
    }
    if let Some(value) = request_id {
        builder = builder.header("x-request-id", value);
    }
    builder
        .body(Body::from_stream(stream))
        .context("failed to build SIWC streaming response")
}

async fn forward_codex_responses(
    state: &AppState,
    inbound_headers: &HeaderMap,
    body: Bytes,
) -> Result<Response<Body>> {
    let AuthBackend::Codex {
        model_provider,
        auth_factory,
        routing,
        ..
    } = &state.backend
    else {
        bail!("not using Codex auth")
    };
    let provider = model_provider
        .responses_api_provider(routing)
        .await
        .map_err(anyhow::Error::from)?
        .provider;
    let auth = resolve_codex_auth(state).await?;

    let ws_url = provider
        .websocket_url_for_path("/responses")
        .context("failed to build Codex websocket URL")?;
    let mut request = ws_url
        .as_str()
        .into_client_request()
        .context("failed to build websocket handshake")?;

    // Provider version/residency headers first, then Claude/shunt session affinity,
    // then stock Codex originator/User-Agent defaults. Auth is added last.
    request.headers_mut().extend(provider.headers.clone());
    copy_conversation_headers(inbound_headers, request.headers_mut());
    request.headers_mut().insert(
        HeaderName::from_static("openai-beta"),
        HeaderValue::from_static(WS_BETA),
    );
    for (name, value) in default_client::default_headers() {
        if let Some(name) = name
            && !request.headers().contains_key(&name)
        {
            request.headers_mut().insert(name, value);
        }
    }
    auth.auth.add_auth_headers(request.headers_mut());

    let connector =
        WebSocketConnector::new(auth_factory).context("failed to configure Codex websocket TLS")?;
    let (mut websocket, upgrade) = connector
        .connect(request, websocket_config())
        .await
        .map_err(|error| anyhow::anyhow!("Codex websocket handshake failed: {error}"))?;

    let request_text = websocket_request_text(&body)?;
    websocket
        .send(Message::Text(request_text.into()))
        .await
        .context("failed to send Responses websocket request")?;

    let stream = futures::stream::unfold((websocket, false), |(mut websocket, done)| async move {
        if done {
            return None;
        }
        loop {
            match websocket.next().await {
                Some(Ok(Message::Text(text))) => {
                    let kind = event_kind(text.as_str());
                    let terminal = kind.as_deref().is_some_and(is_terminal_kind);
                    let bytes = Bytes::from(sse_frame(kind.as_deref(), text.as_str()));
                    return Some((Ok::<Bytes, io::Error>(bytes), (websocket, terminal)));
                }
                Some(Ok(Message::Binary(binary))) => match String::from_utf8(binary.to_vec()) {
                    Ok(text) => {
                        let kind = event_kind(&text);
                        let terminal = kind.as_deref().is_some_and(is_terminal_kind);
                        let bytes = Bytes::from(sse_frame(kind.as_deref(), &text));
                        return Some((Ok(bytes), (websocket, terminal)));
                    }
                    Err(error) => {
                        return Some((
                            Err(io::Error::new(io::ErrorKind::InvalidData, error)),
                            (websocket, true),
                        ));
                    }
                },
                Some(Ok(Message::Ping(payload))) => {
                    if let Err(error) = websocket.send(Message::Pong(payload)).await {
                        return Some((Err(io::Error::other(error)), (websocket, true)));
                    }
                }
                Some(Ok(Message::Pong(_))) | Some(Ok(Message::Frame(_))) => continue,
                Some(Ok(Message::Close(_))) | None => return None,
                Some(Err(error)) => {
                    return Some((Err(io::Error::other(error)), (websocket, true)));
                }
            }
        }
    });

    let mut builder = Response::builder()
        .status(StatusCode::OK)
        .header(CONTENT_TYPE, "text/event-stream")
        .header("cache-control", "no-cache");
    copy_upgrade_metadata(
        upgrade.headers(),
        builder.headers_mut().expect("response headers"),
    );
    builder
        .body(Body::from_stream(stream))
        .context("failed to construct local SSE response")
}

fn event_kind(text: &str) -> Option<String> {
    serde_json::from_str::<Value>(text)
        .ok()
        .and_then(|value| value.get("type").and_then(Value::as_str).map(str::to_owned))
}

fn is_terminal_kind(kind: &str) -> bool {
    matches!(
        kind,
        "response.completed" | "response.failed" | "response.incomplete" | "error"
    )
}

fn sse_frame(kind: Option<&str>, data: &str) -> String {
    match kind {
        Some(kind) => format!("event: {kind}\ndata: {data}\n\n"),
        None => format!("data: {data}\n\n"),
    }
}

fn websocket_request_text(body: &[u8]) -> Result<String> {
    let mut value: Value = serde_json::from_slice(body).context("invalid Responses JSON body")?;
    let object = value
        .as_object_mut()
        .context("Responses request body must be a JSON object")?;
    object.insert(
        "type".to_string(),
        Value::String("response.create".to_string()),
    );
    serde_json::to_string(&value).context("failed to encode websocket Responses request")
}

fn copy_conversation_headers(from: &HeaderMap, to: &mut HeaderMap) {
    const NAMES: &[&str] = &[
        "session-id",
        "thread-id",
        "x-client-request-id",
        "x-codex-window-id",
        "x-openai-subagent",
        "x-codex-parent-thread-id",
        "x-codex-routing-hint",
        "x-codex-turn-metadata",
        "traceparent",
        "tracestate",
    ];
    for name in NAMES {
        if let Some(value) = from.get(*name) {
            to.insert(HeaderName::from_static(name), value.clone());
        }
    }
}

fn copy_upgrade_metadata(from: &HeaderMap, to: &mut HeaderMap) {
    for name in [
        "openai-model",
        "x-reasoning-included",
        "x-codex-turn-state",
        "x-request-id",
    ] {
        if let Some(value) = from.get(name) {
            to.insert(HeaderName::from_static(name), value.clone());
        }
    }
}

fn websocket_config() -> WebSocketConfig {
    let mut extensions = ExtensionsConfig::default();
    extensions.permessage_deflate = Some(DeflateConfig::default());
    let mut config = WebSocketConfig::default();
    config.extensions = extensions;
    config
}
