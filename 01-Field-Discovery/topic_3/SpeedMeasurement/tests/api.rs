use axum::Router;
use axum::body::Body;
use axum::http::{Request, StatusCode};
use http_body_util::BodyExt;
use speedmeasurement::{Entry, ResultStore, Store, app};
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use tower::ServiceExt;

static SEQ: AtomicU32 = AtomicU32::new(0);

struct TempDir(PathBuf);

impl TempDir {
    fn new() -> Self {
        let n = SEQ.fetch_add(1, Ordering::Relaxed);
        let p = std::env::temp_dir().join(format!("smspeed-{}-{n}", std::process::id()));
        let _ = std::fs::remove_dir_all(&p);
        std::fs::create_dir_all(&p).unwrap();
        Self(p)
    }

    fn file(&self) -> PathBuf {
        self.0.join("results.json")
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn store_in(t: &TempDir) -> Arc<dyn ResultStore> {
    Arc::new(Store::load(t.file()))
}

async fn call(app: Router, req: Request<Body>) -> axum::response::Response {
    app.oneshot(req).await.unwrap()
}

async fn json_body(res: axum::response::Response) -> serde_json::Value {
    let bytes = res.into_body().collect().await.unwrap().to_bytes();
    serde_json::from_slice(&bytes).unwrap()
}

fn get(uri: &str) -> Request<Body> {
    Request::builder().uri(uri).body(Body::empty()).unwrap()
}

fn save_request(label: &str) -> Request<Body> {
    Request::builder()
        .method("POST")
        .uri("/api/results")
        .header("content-type", "application/json")
        .body(Body::from(
            serde_json::json!({
                "label": label,
                "ping_ms": 1.5,
                "jitter_ms": 0.2,
                "down_mbps": 100.0,
                "up_mbps": 50.0,
            })
            .to_string(),
        ))
        .unwrap()
}

/// 测速分子的正确性完全取决于发送字节数：少一个字节，速率就有系统性偏差。
#[tokio::test]
async fn download_sends_exactly_the_requested_byte_count() {
    let t = TempDir::new();
    let req = get("/api/download?bytes=1234567");
    let res = call(app(store_in(&t)), req).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(res.headers()["content-length"], "1234567");
    let body = res.into_body().collect().await.unwrap().to_bytes();
    assert_eq!(body.len(), 1_234_567);
}

/// 块边界是最容易数错一字节的地方，逐个校验。
#[tokio::test]
async fn download_handles_chunk_boundaries() {
    let t = TempDir::new();
    for n in [1u64, 1_048_575, 1_048_576, 1_048_577, 3 * 1_048_576] {
        let req = get(&format!("/api/download?bytes={n}"));
        let res = call(app(store_in(&t)), req).await;
        let len = res.into_body().collect().await.unwrap().to_bytes().len();
        assert_eq!(len as u64, n, "bytes={n}");
    }
}

/// 上传速率由服务端收到的字节数决定，必须与发送量一致。
#[tokio::test]
async fn upload_reports_received_byte_count() {
    let t = TempDir::new();
    let req = Request::builder()
        .method("POST")
        .uri("/api/upload")
        .body(Body::from(vec![0xA5u8; 200_000]))
        .unwrap();
    let res = call(app(store_in(&t)), req).await;

    assert_eq!(res.status(), StatusCode::OK);
    assert_eq!(json_body(res).await["bytes"], 200_000);
}

/// 延迟测量依赖空响应体，否则 RTT 会被 body 传输污染。
#[tokio::test]
async fn ping_returns_empty_204() {
    let t = TempDir::new();
    let res = call(app(store_in(&t)), get("/api/ping")).await;

    assert_eq!(res.status(), StatusCode::NO_CONTENT);
    assert!(
        res.into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .is_empty()
    );
}

/// 记录必须落盘：重启进程后还要能对比历史。
#[tokio::test]
async fn saved_results_survive_reload_and_ids_increment() {
    let t = TempDir::new();
    let live = store_in(&t);

    let a = call(app(live.clone()), save_request("卧室·混凝土墙")).await;
    let first = json_body(a).await;
    let b = call(app(live.clone()), save_request("客厅·木门")).await;
    let second = json_body(b).await;

    assert_eq!(first["id"], 1);
    assert_eq!(second["id"], 2);

    let reloaded = Arc::new(Store::load(t.file()));
    let items = reloaded.list();
    assert_eq!(items.len(), 2);
    assert_eq!(items[0].label, "卧室·混凝土墙");
    assert_eq!(items[1].label, "客厅·木门");
}

/// 删除只能影响目标记录，不能误删对比基线。
#[tokio::test]
async fn delete_removes_only_the_target_result() {
    let t = TempDir::new();
    let live = store_in(&t);

    let first = json_body(call(app(live.clone()), save_request("基线")).await).await;
    call(app(live.clone()), save_request("隔墙")).await;

    let id = first["id"].as_u64().unwrap();
    let req = Request::builder()
        .method("DELETE")
        .uri(format!("/api/results/{id}"))
        .body(Body::empty())
        .unwrap();
    let res = call(app(live.clone()), req).await;
    assert_eq!(res.status(), StatusCode::NO_CONTENT);

    let items = Arc::new(Store::load(t.file())).list();
    assert_eq!(items.len(), 1);
    assert_eq!(items[0].label, "隔墙");
}

/// 测试用内存实现：用来证明 HTTP 层只依赖 trait，换存储不改 handler。
struct MemStore(Mutex<Vec<Entry>>);

impl ResultStore for MemStore {
    fn list(&self) -> Vec<Entry> {
        self.0.lock().unwrap().clone()
    }

    fn add(&self, mut e: Entry) -> Entry {
        let mut items = self.0.lock().unwrap();
        e.id = items.len() as u64 + 1;
        items.push(e.clone());
        e
    }

    fn remove(&self, id: u64) {
        self.0.lock().unwrap().retain(|x| x.id != id);
    }
}

/// 抽象边界是真的：同一套 handler 换成内存存储后行为不变。
#[tokio::test]
async fn handlers_work_against_any_result_store() {
    let store: Arc<dyn ResultStore> = Arc::new(MemStore(Mutex::new(Vec::new())));
    let first = json_body(call(app(store.clone()), save_request("内存实现")).await).await;

    assert_eq!(first["id"], 1);
    assert_eq!(store.list().len(), 1);
    assert_eq!(store.list()[0].label, "内存实现");
}
