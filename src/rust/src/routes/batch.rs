use crate::beian::Beian;
use crate::state::{AppState, BatchTask};
use crate::utils::is_valid_url;
use axum::extract::{Path, Query, State};
use axum::routing::{get, post};
use axum::{Json, Router};
use chrono::Local;
use serde::Deserialize;
use serde_json::{json, Value};
use std::sync::atomic::Ordering;
use std::sync::Arc;
use tracing::{error, info, warn};

#[derive(Debug, Deserialize)]
pub struct CreateTaskBody {
    pub task: String,
    pub data: Vec<String>,
    #[serde(rename = "type", default = "default_web")]
    pub task_type: String,
    #[serde(default = "default_querynum")]
    pub querynum: usize,
}

fn default_web() -> String {
    "web".into()
}
fn default_querynum() -> usize {
    20
}

#[derive(Debug, Deserialize)]
pub struct TaskQuery {
    pub taskname: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct DeleteTaskBody {
    pub task: String,
}

#[derive(Debug, Deserialize)]
pub struct BatchListQuery {
    #[serde(default = "default_limit")]
    pub limit: i64,
    #[serde(default)]
    pub offset: i64,
    pub status: Option<String>,
}

fn default_limit() -> i64 {
    20
}

async fn resolve_proxy_for_batch(state: &AppState) -> Option<String> {
    let cfg = state.config.read().clone();
    if cfg.proxy.local_ipv6_pool.enable {
        return Some(String::new());
    }
    if let Some(ref tunnel) = cfg.proxy.tunnel.url {
        if is_valid_url(tunnel) {
            info!("使用隧道代理：{tunnel}");
            return Some(tunnel.clone());
        }
    }
    if let Some(ref api_url) = cfg.proxy.extra_api.url {
        if is_valid_url(api_url) {
            if cfg.proxy.extra_api.auto_maintenace {
                if let Some(ref pool) = state.proxy_pool {
                    if let Ok(p) = pool.getproxy().await {
                        info!("从本地地址池获得代理：{p}");
                        return Some(p);
                    }
                }
            } else if let Ok(client) = reqwest::Client::builder()
                .timeout(std::time::Duration::from_secs(
                    cfg.system.http_client_timeout.max(1),
                ))
                .danger_accept_invalid_certs(true)
                .build()
            {
                if let Ok(resp) = client.get(api_url).send().await {
                    if let Ok(text) = resp.text().await {
                        if let Some(p) = text.split_whitespace().next() {
                            let proxy = format!("http://{}", p.trim());
                            info!("从代理提取接口获得代理：{proxy}");
                            return Some(proxy);
                        }
                    }
                }
            }
        }
    }
    None
}

async fn run_batch_task(
    state: AppState,
    taskname: String,
    keywords: Vec<String>,
    searnum: usize,
    apptype: String,
) {
    let task = {
        let tasks = state.tasks.lock();
        tasks.get(&taskname).cloned()
    };
    let Some(task) = task else { return };

    let semaphore = Arc::new(tokio::sync::Semaphore::new(searnum.max(1)));
    let mut handles = Vec::new();

    for appname in keywords.clone() {
        let permit = semaphore.clone().acquire_owned().await.ok();
        let state = state.clone();
        let task = task.clone();
        let apptype = apptype.clone();
        let taskname = taskname.clone();

        handles.push(tokio::spawn(async move {
            let _permit = permit;
            if task.cancelled.load(Ordering::Relaxed) {
                return;
            }

            let retry = state.config.read().captcha.retry_times.max(1);
            let mut all_results: Vec<Value> = Vec::new();
            let mut last_data = json!({"code": 500});

            for _ in 0..retry {
                if task.cancelled.load(Ordering::Relaxed) {
                    return;
                }
                let proxy = resolve_proxy_for_batch(&state).await;

                if Beian::is_black_type(&apptype) {
                    let data = state
                        .beian
                        .query(&apptype, &appname, None, None, proxy.as_deref())
                        .await;
                    last_data = data.clone();
                    if data.get("code").and_then(|c| c.as_i64()) == Some(200) {
                        task.curpro.fetch_add(1, Ordering::Relaxed);
                        task.query_keywords.lock().push(appname.clone());
                        let result_list = data
                            .get("params")
                            .cloned()
                            .unwrap_or(Value::Array(vec![]));
                        if result_list.as_array().map(|a| a.is_empty()).unwrap_or(true)
                            && !result_list.is_object()
                        {
                            task.domains.lock().push(json!([{
                                "blacklistLevel": null,
                                "serviceName": appname
                            }]));
                        } else {
                            task.domains.lock().push(result_list);
                        }
                        return;
                    }
                    if data.get("message").and_then(|m| m.as_str())
                        == Some("当前访问已被创宇盾拦截")
                    {
                        warn!(
                            "当前访问已被创宇盾拦截，批量任务：{taskname}，使用代理：{proxy:?}"
                        );
                    }
                    continue;
                }

                // 正常类型：分页拉取
                let mut page_num = 1i64;
                let page_size = 26i64;
                let mut page_retry = 0u32;
                let max_page_retry = retry;

                loop {
                    if task.cancelled.load(Ordering::Relaxed) {
                        return;
                    }
                    let data = state
                        .beian
                        .query(
                            &apptype,
                            &appname,
                            Some(json!(page_num)),
                            Some(json!(page_size)),
                            proxy.as_deref(),
                        )
                        .await;
                    last_data = data.clone();

                    if data.get("code").and_then(|c| c.as_i64()) != Some(200) {
                        page_retry += 1;
                        if page_retry >= max_page_retry {
                            warn!(
                                "批量任务 {taskname} - {appname}: 第{page_num}页重试{max_page_retry}次后仍失败，跳过"
                            );
                            break;
                        }
                        info!(
                            "批量任务 {taskname} - {appname}: 第{page_num}页查询失败，重试 {page_retry}/{max_page_retry}"
                        );
                        continue;
                    }
                    page_retry = 0;

                    let current_list = data["params"]["list"]
                        .as_array()
                        .cloned()
                        .unwrap_or_default();
                    if current_list.is_empty() {
                        break;
                    }
                    all_results.extend(current_list.iter().cloned());

                    let total = data["params"]["total"].as_i64().unwrap_or(0);
                    if (all_results.len() as i64) >= total
                        || (current_list.len() as i64) < page_size
                    {
                        info!(
                            "批量任务 {taskname} - {appname}: 共获取 {} 条记录（完成）",
                            all_results.len()
                        );
                        break;
                    }
                    page_num += 1;
                    info!(
                        "批量任务 {taskname} - {appname}: 已获取 {}/{total} 条记录",
                        all_results.len()
                    );
                }

                if !all_results.is_empty()
                    || last_data.get("code").and_then(|c| c.as_i64()) == Some(200)
                {
                    task.curpro.fetch_add(1, Ordering::Relaxed);
                    task.query_keywords.lock().push(appname.clone());

                    if all_results.is_empty() {
                        let placeholder = match apptype.as_str() {
                            "web" => json!([{
                                "contentTypeName": null, "domain": appname, "domainId": null,
                                "leaderName": null, "limitAccess": null, "mainId": null,
                                "mainLicence": null, "natureName": null, "serviceId": null,
                                "serviceLicence": null, "unitName": null, "updateRecordTime": null
                            }]),
                            "app" | "mapp" | "kapp" => json!([{
                                "cityId": null, "countyId": null, "dataId": null, "leaderName": null,
                                "mainId": null, "mainLicence": null, "mainUnitAddress": null,
                                "mainUnitCertNo": null, "mainUnitCertType": null, "natureId": null,
                                "natureName": null, "provinceId": null, "serviceId": null,
                                "serviceLicence": null, "serviceName": appname, "serviceType": null,
                                "unitName": null, "updateRecordTime": null, "version": null
                            }]),
                            _ => json!([{"blacklistLevel": null, "serviceName": appname}]),
                        };
                        task.domains.lock().push(placeholder);
                    } else {
                        task.domains.lock().push(Value::Array(all_results.clone()));
                    }
                    return;
                }
            }

            if last_data.get("code").and_then(|c| c.as_i64()) != Some(200) {
                warn!(
                    "任务 {appname} 达到最大尝试次数，仍未成功完成"
                );
            }
        }));
    }

    for h in handles {
        let _ = h.await;
    }

    task.completed.store(true, Ordering::Relaxed);

    let results_dir = "batch_results";
    let _ = std::fs::create_dir_all(results_dir);
    let ts = Local::now().timestamp();
    let result_file = format!("{results_dir}/{taskname}_{ts}.json");

    let domains = task.domains.lock().clone();
    let query_keywords = task.query_keywords.lock().clone();
    let result_data = json!({
        "task_name": taskname,
        "task_type": apptype,
        "total_count": keywords.len(),
        "completed_count": task.curpro.load(Ordering::Relaxed),
        "query_keywords": query_keywords,
        "result": domains,
    });

    if let Err(e) = std::fs::write(
        &result_file,
        serde_json::to_string_pretty(&result_data).unwrap_or_default(),
    ) {
        error!("保存任务结果失败: {e}");
        return;
    }

    let success_count = domains
        .iter()
        .filter(|item| {
            item.as_array()
                .map(|a| !a.is_empty())
                .unwrap_or(!item.is_null())
        })
        .count() as i64;

    state.db.update_batch_task(
        &taskname,
        Some(task.curpro.load(Ordering::Relaxed) as i64),
        Some(success_count),
        Some("completed"),
        Some(&result_file),
        Some(&Local::now().format("%Y-%m-%d %H:%M:%S").to_string()),
    );
    info!("批量任务 {taskname} 已完成，结果已保存到 {result_file}");
}

async fn create_task(
    State(state): State<AppState>,
    Json(body): Json<CreateTaskBody>,
) -> Json<Value> {
    let cfg = state.config.read().clone();
    if !cfg
        .risk_avoidance
        .allow_type
        .iter()
        .any(|t| t == &body.task_type)
    {
        return Json(json!({"code": 405,"message":"不支持的查询类型"}));
    }
    if body.data.is_empty() {
        return Json(json!({"code":400,"message":"提交的查询列表为空"}));
    }

    let domains: Vec<String> = body
        .data
        .into_iter()
        .filter(|s| {
            !cfg.risk_avoidance
                .prohibit_suffix
                .iter()
                .any(|end| s.ends_with(end))
        })
        .collect();

    if domains.is_empty() {
        return Json(json!({"code":400,"message":"在剔除不允许查询的内容后，列表为空，取消任务"}));
    }

    {
        let tasks = state.tasks.lock();
        if tasks.contains_key(&body.task) {
            return Json(json!({"code": 409, "message": "任务已存在"}));
        }
    }

    state
        .db
        .add_batch_task(&body.task, &body.task_type, domains.len() as i64);

    let batch = BatchTask::new(domains.len(), body.task_type.clone());
    let numpro = batch.numpro;
    state.tasks.lock().insert(body.task.clone(), batch);

    let taskname = body.task.clone();
    let searnum = body.querynum;
    let apptype = body.task_type.clone();
    let state2 = state.clone();
    let tm_name = body.task.clone();
    let handle = tokio::spawn(async move {
        run_batch_task(state2, taskname, domains, searnum, apptype).await;
    });
    state.task_manager.add_task(&tm_name, handle);

    info!("创建批量查询任务：{}", body.task);
    state.logs.add_log(
        format!(
            "创建批量查询任务：{}，类型：{}，数量：{}",
            body.task, body.task_type, numpro
        ),
        "INFO",
    );

    Json(json!({"code": 200,"message":"创建任务成功"}))
}

async fn query_task(
    State(state): State<AppState>,
    Query(q): Query<TaskQuery>,
) -> Json<Value> {
    let Some(taskname) = q.taskname else {
        return Json(json!({"code":404,"message":"任务不存在"}));
    };
    let tasks = state.tasks.lock();
    if let Some(task) = tasks.get(&taskname) {
        Json(json!({
            "code": 200,
            "curpro": task.curpro.load(Ordering::Relaxed),
            "numpro": task.numpro,
            "tasktype": task.appname,
            "progress": task.progress_pct(),
            "query_keywords": task.query_keywords.lock().clone(),
            "data": task.domains.lock().clone(),
        }))
    } else {
        Json(json!({"code":404,"message":"任务不存在"}))
    }
}

async fn delete_task(
    State(state): State<AppState>,
    Json(body): Json<DeleteTaskBody>,
) -> Json<Value> {
    let mut tasks = state.tasks.lock();
    if let Some(task) = tasks.get(&body.task) {
        task.cancelled.store(true, Ordering::Relaxed);
        tasks.remove(&body.task);
        drop(tasks);
        state.task_manager.remove_task(&body.task);
        warn!("删除批量查询任务：{}", body.task);
        state
            .logs
            .add_log(format!("删除批量查询任务：{}", body.task), "WARNING");
        Json(json!({"code": 200}))
    } else {
        Json(json!({"code":404,"message":"任务不存在，可能已经完成或删除"}))
    }
}

async fn list_batch_tasks(
    State(state): State<AppState>,
    Query(q): Query<BatchListQuery>,
) -> Json<Value> {
    let status = q.status.filter(|s| !s.is_empty());
    let tasks = state
        .db
        .get_batch_tasks(q.limit, q.offset, status.as_deref());
    let total = state.db.get_batch_tasks_count(status.as_deref());
    Json(json!({"code": 200, "data": tasks, "total": total}))
}

async fn batch_task_detail(
    State(state): State<AppState>,
    Path(task_name): Path<String>,
) -> Json<Value> {
    match state.db.get_batch_task_detail(&task_name) {
        Some(mut task) => {
            if let Some(rf) = task.get("result_file").and_then(|v| v.as_str()) {
                if std::path::Path::new(rf).exists() {
                    if let Ok(content) = std::fs::read_to_string(rf) {
                        if let Ok(data) = serde_json::from_str::<Value>(&content) {
                            task["result_data"] = data;
                        }
                    }
                }
            }
            Json(json!({"code": 200, "data": task}))
        }
        None => Json(json!({"code": 404, "message": "任务不存在"})),
    }
}

async fn delete_batch_task_api(
    State(state): State<AppState>,
    Path(task_name): Path<String>,
) -> Json<Value> {
    if state.db.delete_batch_task(&task_name) {
        Json(json!({"code": 200, "message": "删除成功"}))
    } else {
        Json(json!({"code": 500, "message": "删除失败"}))
    }
}

pub fn routes() -> Router<AppState> {
    Router::new()
        .route("/create/task", post(create_task))
        .route("/query/task", get(query_task))
        .route("/delete/task", post(delete_task))
        .route("/batch/tasks", get(list_batch_tasks))
        .route("/batch/task/{task_name}", get(batch_task_detail))
        .route(
            "/batch/task/delete/{task_name}",
            get(delete_batch_task_api).post(delete_batch_task_api).delete(delete_batch_task_api),
        )
}
