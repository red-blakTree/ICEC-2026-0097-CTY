use speedmeasurement::{Store, app, lan_ips};
use std::sync::Arc;

#[tokio::main]
async fn main() {
    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(8080);

    let store = Arc::new(Store::load("data/results.json"));
    let app = app(store);

    let listener = tokio::net::TcpListener::bind(("0.0.0.0", port))
        .await
        .unwrap_or_else(|e| panic!("无法监听 0.0.0.0:{port}: {e}"));

    println!("本机访问   http://127.0.0.1:{port}");
    let addrs = lan_ips();
    if addrs.is_empty() {
        println!("未检测到局域网地址，请手动查询本机 IP");
    } else {
        println!("手机访问（与电脑同一热点/局域网）：");
        for ip in &addrs {
            println!("  http://{ip}:{port}");
        }
    }
    println!("按 Ctrl+C 停止");

    axum::serve(listener, app).await.expect("服务异常退出");
}
