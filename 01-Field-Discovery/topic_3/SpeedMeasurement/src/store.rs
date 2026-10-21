use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Entry {
    pub id: u64,
    pub ts: u64,
    /// 位置 / 墙体材质标注，例如「卧室 · 混凝土墙」
    pub label: String,
    pub ping_ms: f64,
    pub jitter_ms: f64,
    pub down_mbps: f64,
    pub up_mbps: f64,
}

#[derive(Default, Serialize, Deserialize)]
struct FileData {
    items: Vec<Entry>,
}

/// 结果存储的抽象边界：HTTP 层只依赖它，不依赖具体落盘方式
pub trait ResultStore: Send + Sync {
    fn list(&self) -> Vec<Entry>;
    fn add(&self, entry: Entry) -> Entry;
    fn remove(&self, id: u64);
}

pub struct Store {
    path: PathBuf,
    items: Mutex<Vec<Entry>>,
}

impl Store {
    pub fn load(path: impl Into<PathBuf>) -> Self {
        let path = path.into();
        let items = std::fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str::<FileData>(&s).ok())
            .map(|f| f.items)
            .unwrap_or_default();
        Self {
            path,
            items: Mutex::new(items),
        }
    }

    /// 锁被毒化时继续使用数据：单个请求线程 panic 不应让服务永久不可用
    fn lock(&self) -> std::sync::MutexGuard<'_, Vec<Entry>> {
        self.items
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
    }

    fn persist(&self, items: &[Entry]) {
        if let Some(dir) = self.path.parent() {
            let _ = std::fs::create_dir_all(dir);
        }
        if let Ok(s) = serde_json::to_string_pretty(&FileData {
            items: items.to_vec(),
        }) {
            let _ = std::fs::write(&self.path, s);
        }
    }
}

impl ResultStore for Store {
    fn list(&self) -> Vec<Entry> {
        self.lock().clone()
    }

    fn add(&self, mut e: Entry) -> Entry {
        let mut items = self.lock();
        e.id = items.iter().map(|x| x.id).max().unwrap_or(0) + 1;
        e.ts = now_ms();
        items.push(e.clone());
        self.persist(&items);
        drop(items);
        e
    }

    fn remove(&self, id: u64) {
        let mut items = self.lock();
        items.retain(|x| x.id != id);
        self.persist(&items);
        drop(items);
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX))
}
