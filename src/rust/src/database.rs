use anyhow::{Context, Result};
use parking_lot::Mutex;
use rusqlite::{params, Connection, OptionalExtension};
use serde_json::Value;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use tracing::{error, info};

pub type SharedDb = Arc<Database>;

pub struct Database {
    path: PathBuf,
    lock: Mutex<()>,
}

impl Database {
    pub fn new(db_path: impl AsRef<Path>) -> Result<Self> {
        let db = Self {
            path: db_path.as_ref().to_path_buf(),
            lock: Mutex::new(()),
        };
        db.init_db()?;
        Ok(db)
    }

    fn connect(&self) -> Result<Connection> {
        let conn = Connection::open(&self.path).context("打开 SQLite 失败")?;
        conn.busy_timeout(std::time::Duration::from_secs(30))?;
        Ok(conn)
    }

    fn init_db(&self) -> Result<()> {
        let _g = self.lock.lock();
        let conn = self.connect()?;
        conn.execute_batch(
            r#"
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                search_type TEXT NOT NULL,
                search_keyword TEXT NOT NULL,
                result_count INTEGER DEFAULT 0,
                search_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                result_data TEXT
            );
            CREATE TABLE IF NOT EXISTS batch_task_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL UNIQUE,
                task_type TEXT NOT NULL,
                total_count INTEGER DEFAULT 0,
                completed_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',
                result_file TEXT,
                create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finish_time TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_search_time ON search_history(search_time DESC);
            CREATE INDEX IF NOT EXISTS idx_search_type ON search_history(search_type);
            CREATE INDEX IF NOT EXISTS idx_batch_create_time ON batch_task_history(create_time DESC);
            CREATE INDEX IF NOT EXISTS idx_batch_status ON batch_task_history(status);
            "#,
        )?;
        info!("数据库初始化完成：{}", self.path.display());
        Ok(())
    }

    pub fn add_history(
        &self,
        search_type: &str,
        search_keyword: &str,
        result_count: i64,
        result_data: Option<&Value>,
    ) -> Option<i64> {
        let _g = self.lock.lock();
        let result_json = result_data.map(|v| v.to_string());
        match (|| -> Result<i64> {
            let conn = self.connect()?;
            conn.execute(
                "INSERT INTO search_history (search_type, search_keyword, result_count, result_data) VALUES (?1, ?2, ?3, ?4)",
                params![search_type, search_keyword, result_count, result_json],
            )?;
            Ok(conn.last_insert_rowid())
        })() {
            Ok(id) => {
                info!("添加历史记录成功：{} - {}", search_type, search_keyword);
                Some(id)
            }
            Err(e) => {
                error!("添加历史记录失败：{}", e);
                None
            }
        }
    }

    pub fn get_history(
        &self,
        limit: i64,
        offset: i64,
        search_type: Option<&str>,
    ) -> Vec<Value> {
        let _g = self.lock.lock();
        (|| -> Result<Vec<Value>> {
            let conn = self.connect()?;
            let mut rows_out = Vec::new();
            if let Some(st) = search_type {
                let mut stmt = conn.prepare(
                    "SELECT id, search_type, search_keyword, result_count, search_time FROM search_history WHERE search_type = ?1 ORDER BY search_time DESC LIMIT ?2 OFFSET ?3",
                )?;
                let rows = stmt.query_map(params![st, limit, offset], |row| {
                    Ok(serde_json::json!({
                        "id": row.get::<_, i64>(0)?,
                        "search_type": row.get::<_, String>(1)?,
                        "search_keyword": row.get::<_, String>(2)?,
                        "result_count": row.get::<_, i64>(3)?,
                        "search_time": row.get::<_, String>(4)?,
                    }))
                })?;
                for r in rows {
                    rows_out.push(r?);
                }
            } else {
                let mut stmt = conn.prepare(
                    "SELECT id, search_type, search_keyword, result_count, search_time FROM search_history ORDER BY search_time DESC LIMIT ?1 OFFSET ?2",
                )?;
                let rows = stmt.query_map(params![limit, offset], |row| {
                    Ok(serde_json::json!({
                        "id": row.get::<_, i64>(0)?,
                        "search_type": row.get::<_, String>(1)?,
                        "search_keyword": row.get::<_, String>(2)?,
                        "result_count": row.get::<_, i64>(3)?,
                        "search_time": row.get::<_, String>(4)?,
                    }))
                })?;
                for r in rows {
                    rows_out.push(r?);
                }
            }
            Ok(rows_out)
        })()
        .unwrap_or_else(|e| {
            error!("获取历史记录失败：{}", e);
            vec![]
        })
    }

    pub fn get_history_detail(&self, history_id: i64) -> Option<Value> {
        let _g = self.lock.lock();
        (|| -> Result<Option<Value>> {
            let conn = self.connect()?;
            let row: Option<(i64, String, String, i64, String, Option<String>)> = conn
                .query_row(
                    "SELECT id, search_type, search_keyword, result_count, search_time, result_data FROM search_history WHERE id = ?1",
                    params![history_id],
                    |row| {
                        Ok((
                            row.get(0)?,
                            row.get(1)?,
                            row.get(2)?,
                            row.get(3)?,
                            row.get(4)?,
                            row.get(5)?,
                        ))
                    },
                )
                .optional()?;
            Ok(row.map(|(id, st, kw, cnt, time, data)| {
                let result_data: Option<Value> = data.and_then(|s| serde_json::from_str(&s).ok());
                serde_json::json!({
                    "id": id,
                    "search_type": st,
                    "search_keyword": kw,
                    "result_count": cnt,
                    "search_time": time,
                    "result_data": result_data,
                })
            }))
        })()
        .unwrap_or_else(|e| {
            error!("获取历史记录详情失败：{}", e);
            None
        })
    }

    pub fn delete_history(&self, history_id: i64) -> bool {
        let _g = self.lock.lock();
        match (|| -> Result<()> {
            let conn = self.connect()?;
            conn.execute(
                "DELETE FROM search_history WHERE id = ?1",
                params![history_id],
            )?;
            Ok(())
        })() {
            Ok(()) => {
                info!("删除历史记录成功：ID={}", history_id);
                true
            }
            Err(e) => {
                error!("删除历史记录失败：{}", e);
                false
            }
        }
    }

    pub fn clear_history(&self, search_type: Option<&str>) -> bool {
        let _g = self.lock.lock();
        match (|| -> Result<()> {
            let conn = self.connect()?;
            if let Some(st) = search_type {
                conn.execute(
                    "DELETE FROM search_history WHERE search_type = ?1",
                    params![st],
                )?;
            } else {
                conn.execute("DELETE FROM search_history", [])?;
            }
            Ok(())
        })() {
            Ok(()) => {
                info!(
                    "清空历史记录成功：{}",
                    search_type.unwrap_or("全部")
                );
                true
            }
            Err(e) => {
                error!("清空历史记录失败：{}", e);
                false
            }
        }
    }

    pub fn get_history_count(&self, search_type: Option<&str>) -> i64 {
        let _g = self.lock.lock();
        (|| -> Result<i64> {
            let conn = self.connect()?;
            if let Some(st) = search_type {
                Ok(conn.query_row(
                    "SELECT COUNT(*) FROM search_history WHERE search_type = ?1",
                    params![st],
                    |row| row.get(0),
                )?)
            } else {
                Ok(conn.query_row("SELECT COUNT(*) FROM search_history", [], |row| {
                    row.get(0)
                })?)
            }
        })()
        .unwrap_or(0)
    }

    pub fn add_batch_task(
        &self,
        task_name: &str,
        task_type: &str,
        total_count: i64,
    ) -> Option<i64> {
        let _g = self.lock.lock();
        match (|| -> Result<i64> {
            let conn = self.connect()?;
            conn.execute(
                "INSERT INTO batch_task_history (task_name, task_type, total_count, status) VALUES (?1, ?2, ?3, 'running')",
                params![task_name, task_type, total_count],
            )?;
            Ok(conn.last_insert_rowid())
        })() {
            Ok(id) => {
                info!("添加批量任务成功：{}", task_name);
                Some(id)
            }
            Err(e) => {
                error!("添加批量任务失败：{}", e);
                None
            }
        }
    }

    pub fn update_batch_task(
        &self,
        task_name: &str,
        completed_count: Option<i64>,
        success_count: Option<i64>,
        status: Option<&str>,
        result_file: Option<&str>,
        finish_time: Option<&str>,
    ) -> bool {
        let _g = self.lock.lock();
        match (|| -> Result<()> {
            let conn = self.connect()?;
            let mut sets = vec!["update_time = CURRENT_TIMESTAMP".to_string()];
            let mut values: Vec<Box<dyn rusqlite::ToSql>> = Vec::new();

            if let Some(v) = completed_count {
                sets.push(format!("completed_count = ?{}", values.len() + 1));
                values.push(Box::new(v));
            }
            if let Some(v) = success_count {
                sets.push(format!("success_count = ?{}", values.len() + 1));
                values.push(Box::new(v));
            }
            if let Some(v) = status {
                sets.push(format!("status = ?{}", values.len() + 1));
                values.push(Box::new(v.to_string()));
            }
            if let Some(v) = result_file {
                sets.push(format!("result_file = ?{}", values.len() + 1));
                values.push(Box::new(v.to_string()));
            }
            if let Some(v) = finish_time {
                sets.push(format!("finish_time = ?{}", values.len() + 1));
                values.push(Box::new(v.to_string()));
            }
            let name_idx = values.len() + 1;
            values.push(Box::new(task_name.to_string()));
            let sql = format!(
                "UPDATE batch_task_history SET {} WHERE task_name = ?{}",
                sets.join(", "),
                name_idx
            );
            let params_refs: Vec<&dyn rusqlite::ToSql> =
                values.iter().map(|v| v.as_ref()).collect();
            conn.execute(&sql, params_refs.as_slice())?;
            Ok(())
        })() {
            Ok(()) => true,
            Err(e) => {
                error!("更新批量任务失败：{}", e);
                false
            }
        }
    }

    fn map_batch_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Value> {
        Ok(serde_json::json!({
            "id": row.get::<_, i64>(0)?,
            "task_name": row.get::<_, String>(1)?,
            "task_type": row.get::<_, String>(2)?,
            "total_count": row.get::<_, i64>(3)?,
            "completed_count": row.get::<_, i64>(4)?,
            "success_count": row.get::<_, i64>(5)?,
            "status": row.get::<_, String>(6)?,
            "result_file": row.get::<_, Option<String>>(7)?,
            "create_time": row.get::<_, String>(8)?,
            "update_time": row.get::<_, String>(9)?,
            "finish_time": row.get::<_, Option<String>>(10)?,
        }))
    }

    pub fn get_batch_tasks(
        &self,
        limit: i64,
        offset: i64,
        status: Option<&str>,
    ) -> Vec<Value> {
        let _g = self.lock.lock();
        (|| -> Result<Vec<Value>> {
            let conn = self.connect()?;
            let mut out = Vec::new();
            let sql_base = "SELECT id, task_name, task_type, total_count, completed_count, success_count, status, result_file, create_time, update_time, finish_time FROM batch_task_history";
            if let Some(st) = status {
                let mut stmt = conn.prepare(&format!(
                    "{sql_base} WHERE status = ?1 ORDER BY create_time DESC LIMIT ?2 OFFSET ?3"
                ))?;
                let rows = stmt.query_map(params![st, limit, offset], Self::map_batch_row)?;
                for r in rows {
                    out.push(r?);
                }
            } else {
                let mut stmt = conn.prepare(&format!(
                    "{sql_base} ORDER BY create_time DESC LIMIT ?1 OFFSET ?2"
                ))?;
                let rows = stmt.query_map(params![limit, offset], Self::map_batch_row)?;
                for r in rows {
                    out.push(r?);
                }
            }
            Ok(out)
        })()
        .unwrap_or_else(|e| {
            error!("获取批量任务列表失败：{}", e);
            vec![]
        })
    }

    pub fn get_batch_task_detail(&self, task_name: &str) -> Option<Value> {
        let _g = self.lock.lock();
        (|| -> Result<Option<Value>> {
            let conn = self.connect()?;
            let row = conn
                .query_row(
                    "SELECT id, task_name, task_type, total_count, completed_count, success_count, status, result_file, create_time, update_time, finish_time FROM batch_task_history WHERE task_name = ?1",
                    params![task_name],
                    Self::map_batch_row,
                )
                .optional()?;
            Ok(row)
        })()
        .unwrap_or_else(|e| {
            error!("获取批量任务详情失败：{}", e);
            None
        })
    }

    pub fn get_batch_tasks_count(&self, status: Option<&str>) -> i64 {
        let _g = self.lock.lock();
        (|| -> Result<i64> {
            let conn = self.connect()?;
            if let Some(st) = status {
                Ok(conn.query_row(
                    "SELECT COUNT(*) FROM batch_task_history WHERE status = ?1",
                    params![st],
                    |row| row.get(0),
                )?)
            } else {
                Ok(conn.query_row(
                    "SELECT COUNT(*) FROM batch_task_history",
                    [],
                    |row| row.get(0),
                )?)
            }
        })()
        .unwrap_or(0)
    }

    pub fn delete_batch_task(&self, task_name: &str) -> bool {
        let _g = self.lock.lock();
        match (|| -> Result<()> {
            let conn = self.connect()?;
            let result_file: Option<String> = conn
                .query_row(
                    "SELECT result_file FROM batch_task_history WHERE task_name = ?1",
                    params![task_name],
                    |row| row.get(0),
                )
                .optional()?
                .flatten();
            conn.execute(
                "DELETE FROM batch_task_history WHERE task_name = ?1",
                params![task_name],
            )?;
            if let Some(ref f) = result_file {
                if Path::new(f).exists() {
                    let _ = std::fs::remove_file(f);
                    info!("删除结果文件成功：{}", f);
                }
            }
            Ok(())
        })() {
            Ok(()) => {
                info!("删除批量任务成功：{}", task_name);
                true
            }
            Err(e) => {
                error!("删除批量任务失败：{}", e);
                false
            }
        }
    }
}
