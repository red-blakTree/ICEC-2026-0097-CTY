mod net;
mod store;

use axum::{
    Json, Router,
    body::{Body, Bytes},
    extract::{Path, Query, Request, State},
    http::{HeaderValue, StatusCode, header},
    response::{Html, IntoResponse, Response},
    routing::{delete, get, post},
};
use futures_util::{StreamExt, stream};
use serde::{Deserialize, Serialize};
use std::sync::{Arc, OnceLock};

pub use net::lan_ips;
pub use store::{Entry, ResultStore, Store};

const INDEX: &str = include_str!("../web/index.html");
const MB: u64 = 1 << 20;
const CHUNK: usize = 1 << 20;
static BLOCK: OnceLock<Bytes> = OnceLock::new();

#[derive(Deserialize)]
struct DownloadQuery {
    bytes: Option<u64>,
}

#[derive(Serialize)]
struct UploadResponse {
    bytes: u64,
}

#[derive(Deserialize)]
struct SaveRequest {
    label: String,
    ping_ms: f64,
    /// 兼容旧前端：未带 P95 / 丢包时按 0 存
    #[serde(default)]
    p95_ms: f64,
    jitter_ms: f64,
    #[serde(default)]
    loss_pct: f64,
    down_mbps: f64,
    up_mbps: f64,
}

type Shared = Arc<dyn ResultStore>;

/// 构建完整路由，便于 main 与集成测试复用
pub fn app(store: Shared) -> Router {
    Router::new()
        .route("/", get(index))
        .route("/api/ping", get(ping))
        .route("/api/info", get(info))
        .route("/api/download", get(download))
        .route("/api/upload", post(upload))
        .route("/api/results", get(list_results).post(save_result))
        .route("/api/results/{id}", delete(delete_result))
        .with_state(store)
}

async fn index() -> Html<&'static str> {
    Html(INDEX)
}

/// 空响应，仅用于 RTT 测量
async fn ping() -> StatusCode {
    StatusCode::NO_CONTENT
}

#[derive(Serialize)]
struct Info {
    addrs: Vec<String>,
}

async fn info() -> Json<Info> {
    Json(Info { addrs: lan_ips() })
}

/// 流式输出任意字节数，块缓冲全局复用，不随请求分配
async fn download(Query(q): Query<DownloadQuery>) -> Response {
    let total = q.bytes.unwrap_or(16 * MB).clamp(1, 4_000_000_000);
    let block = BLOCK
        .get_or_init(|| Bytes::from(vec![0x5Au8; CHUNK]))
        .clone();
    let full = total / CHUNK as u64;
    let rem = (total % CHUNK as u64) as usize;

    let tail = (rem > 0).then(|| Ok::<Bytes, std::io::Error>(block.slice(0..rem)));
    let body = stream::iter((0..full).map(move |_| Ok::<Bytes, std::io::Error>(block.clone())))
        .chain(stream::iter(tail));

    let mut res = Body::from_stream(body).into_response();
    let h = res.headers_mut();
    h.insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/octet-stream"),
    );
    h.insert(
        header::CONTENT_LENGTH,
        HeaderValue::from_str(&total.to_string()).unwrap(),
    );
    h.insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    res
}

/// 流式丢弃请求体，只统计字节数
async fn upload(req: Request) -> Json<UploadResponse> {
    let mut total = 0u64;
    let mut body = req.into_body().into_data_stream();
    while let Some(chunk) = body.next().await {
        if let Ok(bytes) = chunk {
            total += bytes.len() as u64;
        }
    }
    Json(UploadResponse { bytes: total })
}

async fn list_results(State(st): State<Shared>) -> Json<Vec<Entry>> {
    Json(st.list())
}

async fn save_result(State(st): State<Shared>, Json(req): Json<SaveRequest>) -> Json<Entry> {
    Json(st.add(Entry {
        id: 0,
        ts: 0,
        label: req.label.chars().take(80).collect(),
        ping_ms: req.ping_ms,
        p95_ms: req.p95_ms,
        jitter_ms: req.jitter_ms,
        loss_pct: req.loss_pct,
        down_mbps: req.down_mbps,
        up_mbps: req.up_mbps,
    }))
}

async fn delete_result(State(st): State<Shared>, Path(id): Path<u64>) -> StatusCode {
    st.remove(id);
    StatusCode::NO_CONTENT
}
