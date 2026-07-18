//! MCP 服务（与 Python mcp_server.py 工具对齐）
//! - stdio:  `ymicp --mcp`
//! - http:   `ymicp --mcp-http` 或 config `mcp.enable: true`

use crate::routes::query::do_query;
use crate::state::AppState;
use rmcp::{
    ErrorData as McpError, ServerHandler, ServiceExt,
    handler::server::{router::tool::ToolRouter, wrapper::Parameters},
    model::*,
    schemars, tool, tool_handler, tool_router,
    transport::stdio,
    transport::streamable_http_server::{
        StreamableHttpServerConfig, StreamableHttpService,
        session::local::LocalSessionManager,
    },
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::net::SocketAddr;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;
use tracing::{error, info};

const ALL_TYPES: &[&str] = &["web", "app", "mapp", "kapp", "bweb", "bapp", "bmapp", "bkapp"];

#[derive(Debug, Deserialize, schemars::JsonSchema)]
pub struct IcpQueryArgs {
    /// 查询类型：web/app/mapp/kapp 或 bweb/bapp/bmapp/bkapp
    #[serde(rename = "type")]
    pub qtype: String,
    /// 域名 / 单位名称 / 备案号 / 应用名等关键词
    pub search: String,
    /// 页码，从 1 开始（黑名单类型忽略）
    #[serde(default)]
    pub page_num: Option<i64>,
    /// 每页条数（黑名单类型忽略）
    #[serde(default)]
    pub page_size: Option<i64>,
}

#[derive(Clone)]
pub struct IcpMcpServer {
    state: AppState,
    tool_router: ToolRouter<Self>,
}

#[tool_router]
impl IcpMcpServer {
    pub fn new(state: AppState) -> Self {
        Self {
            state,
            tool_router: Self::tool_router(),
        }
    }

    #[tool(
        name = "icp_query_types",
        description = "返回当前允许的 ICP 查询类型列表（web/app/mapp/kapp 及黑名单类型）。"
    )]
    async fn icp_query_types(&self) -> Result<CallToolResult, McpError> {
        let allow = allowed_types(&self.state);
        let body = json!({"allow_type": allow}).to_string();
        Ok(CallToolResult::success(vec![Content::text(body)]))
    }

    #[tool(
        name = "icp_query",
        description = "查询中国工信部 ICP 备案信息。type: web/app/mapp/kapp 或黑名单 bweb/bapp/bmapp/bkapp；search 为关键词。"
    )]
    async fn icp_query(
        &self,
        Parameters(args): Parameters<IcpQueryArgs>,
    ) -> Result<CallToolResult, McpError> {
        let qtype = args.qtype.trim().to_lowercase();
        let search = args.search.trim().to_string();
        if search.is_empty() {
            let body = json!({"code": 101, "message": "search 不能为空"}).to_string();
            return Ok(CallToolResult::success(vec![Content::text(body)]));
        }
        if !ALL_TYPES.contains(&qtype.as_str()) {
            let body = json!({
                "code": 102,
                "message": format!("不支持的类型: {qtype}"),
                "allow_type": ALL_TYPES,
            })
            .to_string();
            return Ok(CallToolResult::success(vec![Content::text(body)]));
        }
        let allowed = allowed_types(&self.state);
        if !allowed.iter().any(|t| t == &qtype) {
            let body = json!({
                "code": 102,
                "message": format!("类型未被配置允许: {qtype}"),
                "allow_type": allowed,
            })
            .to_string();
            return Ok(CallToolResult::success(vec![Content::text(body)]));
        }

        let page_num = args.page_num.map(|n| Value::from(n));
        let page_size = args.page_size.map(|n| Value::from(n));
        let result = do_query(
            &self.state,
            &qtype,
            &search,
            page_num,
            page_size,
            None,
        )
        .await;
        Ok(CallToolResult::success(vec![Content::text(
            result.to_string(),
        )]))
    }
}

#[tool_handler]
impl ServerHandler for IcpMcpServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo {
            protocol_version: ProtocolVersion::V_2024_11_05,
            capabilities: ServerCapabilities::builder().enable_tools().build(),
            server_info: Implementation {
                name: "ICP_Query".to_string(),
                title: None,
                version: env!("CARGO_PKG_VERSION").to_string(),
                website_url: None,
                icons: None,
            },
            instructions: Some(
                "ICP 备案查询。工具: icp_query(type, search, page_num?, page_size?), icp_query_types()"
                    .to_string(),
            ),
        }
    }
}

fn allowed_types(state: &AppState) -> Vec<String> {
    let cfg = state.config.read();
    let list = &cfg.risk_avoidance.allow_type;
    if list.is_empty() {
        ALL_TYPES.iter().map(|s| (*s).to_string()).collect()
    } else {
        list.clone()
    }
}

/// stdio MCP（日志须打 stderr）
pub async fn run_stdio(state: AppState) -> anyhow::Result<()> {
    info!("MCP stdio 服务启动");
    let server = IcpMcpServer::new(state);
    let service = server.serve(stdio()).await.map_err(|e| {
        error!("MCP stdio 启动失败: {e:?}");
        anyhow::anyhow!("MCP stdio: {e}")
    })?;
    service.waiting().await?;
    Ok(())
}

/// Streamable HTTP，路径 /mcp（独立端口，与 Python 对齐）
pub async fn run_http(state: AppState, host: &str, port: u16) -> anyhow::Result<()> {
    let addr: SocketAddr = format!("{host}:{port}")
        .parse()
        .unwrap_or_else(|_| SocketAddr::from(([0, 0, 0, 0], port)));
    let ct = CancellationToken::new();
    let state = Arc::new(state);
    let service = StreamableHttpService::new(
        {
            let state = Arc::clone(&state);
            move || Ok(IcpMcpServer::new((*state).clone()))
        },
        LocalSessionManager::default().into(),
        StreamableHttpServerConfig {
            cancellation_token: ct.child_token(),
            ..Default::default()
        },
    );
    let router = axum::Router::new().nest_service("/mcp", service);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    let display_host = if host == "0.0.0.0" {
        "127.0.0.1"
    } else {
        host
    };
    info!("MCP Streamable HTTP http://{display_host}:{port}/mcp");
    axum::serve(listener, router)
        .with_graceful_shutdown(async move {
            tokio::signal::ctrl_c().await.ok();
            ct.cancel();
        })
        .await?;
    Ok(())
}

/// 后台启动 MCP HTTP（主 API 进程内，daemon 风格）
pub fn spawn_http(state: AppState, host: String, port: u16) {
    tokio::spawn(async move {
        if let Err(e) = run_http(state, &host, port).await {
            error!("MCP HTTP 退出: {e:#}");
        }
    });
}
