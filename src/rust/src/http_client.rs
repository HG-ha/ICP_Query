//! HTTP 客户端：支持代理与本地 IPv6 绑定（对应 aiohttp local_addr）

use http_body_util::{BodyExt, Full};
use hyper::body::Bytes;
use hyper::Request;
use hyper_util::client::legacy::connect::HttpConnector;
use hyper_util::client::legacy::Client;
use hyper_util::rt::TokioExecutor;
use reqwest::Proxy;
use std::collections::HashMap;
use std::net::IpAddr;
use std::sync::Arc;
use std::time::Duration;
use tracing::info;

/// 发送 POST 请求，返回响应文本。
/// - `proxy`: 非空时走 HTTP 代理（reqwest）
/// - `local_ipv6`: 绑定本地 IPv6 出口（hyper HttpConnector::set_local_address）
pub async fn post_text(
    url: &str,
    headers: &HashMap<String, String>,
    body: Vec<u8>,
    content_type: Option<&str>,
    proxy: Option<&str>,
    local_ipv6: Option<&str>,
    timeout: Duration,
) -> Result<String, String> {
    // 代理优先
    if let Some(p) = proxy {
        if !p.is_empty() {
            return post_via_reqwest(url, headers, body, content_type, Some(p), timeout).await;
        }
    }

    // 本地 IPv6 绑定
    if let Some(ip) = local_ipv6 {
        if !ip.is_empty() {
            info!("使用本地 IPv6 地址：{ip}");
            return post_via_hyper_bound(url, headers, body, content_type, ip, timeout).await;
        }
    }

    post_via_reqwest(url, headers, body, content_type, None, timeout).await
}

async fn post_via_reqwest(
    url: &str,
    headers: &HashMap<String, String>,
    body: Vec<u8>,
    content_type: Option<&str>,
    proxy: Option<&str>,
    timeout: Duration,
) -> Result<String, String> {
    let mut builder = reqwest::Client::builder()
        .timeout(timeout)
        .danger_accept_invalid_certs(true)
        .pool_max_idle_per_host(30);

    if let Some(p) = proxy {
        let proxy_url = if p.starts_with("http://") || p.starts_with("https://") {
            p.to_string()
        } else {
            format!("http://{p}")
        };
        let px = Proxy::all(&proxy_url).map_err(|e| format!("代理无效: {e}"))?;
        builder = builder.proxy(px);
    } else {
        builder = builder.no_proxy();
    }

    let client = builder
        .build()
        .map_err(|e| format!("创建 HTTP 客户端失败: {e}"))?;

    let mut req = client.post(url).body(body);
    for (k, v) in headers {
        req = req.header(k, v);
    }
    if let Some(ct) = content_type {
        req = req.header("Content-Type", ct);
    }

    let resp = req.send().await.map_err(|e| e.to_string())?;
    resp.text().await.map_err(|e| e.to_string())
}

async fn post_via_hyper_bound(
    url: &str,
    headers: &HashMap<String, String>,
    body: Vec<u8>,
    content_type: Option<&str>,
    local_ipv6: &str,
    timeout: Duration,
) -> Result<String, String> {
    let ip: IpAddr = local_ipv6
        .parse()
        .map_err(|e| format!("无效 IPv6 地址 {local_ipv6}: {e}"))?;

    let mut http = HttpConnector::new();
    http.set_local_address(Some(ip));
    http.enforce_http(false);
    http.set_nodelay(true);
    http.set_connect_timeout(Some(timeout));

    // 接受无效证书（对齐 Python ssl=False）
    let tls_config = {
        let mut cfg = rustls::ClientConfig::builder()
            .dangerous()
            .with_custom_certificate_verifier(Arc::new(NoCertVerifier))
            .with_no_client_auth();
        cfg.alpn_protocols = vec![b"http/1.1".to_vec()];
        cfg
    };

    let https = hyper_rustls::HttpsConnectorBuilder::new()
        .with_tls_config(tls_config)
        .https_or_http()
        .enable_http1()
        .wrap_connector(http);

    let client: Client<_, Full<Bytes>> = Client::builder(TokioExecutor::new()).build(https);

    let mut builder = Request::builder().method("POST").uri(url);
    for (k, v) in headers {
        builder = builder.header(k, v);
    }
    if let Some(ct) = content_type {
        builder = builder.header("Content-Type", ct);
    }

    let req = builder
        .body(Full::new(Bytes::from(body)))
        .map_err(|e| e.to_string())?;

    let resp = tokio::time::timeout(timeout, client.request(req))
        .await
        .map_err(|_| "请求超时".to_string())?
        .map_err(|e| e.to_string())?;

    let bytes = resp
        .into_body()
        .collect()
        .await
        .map_err(|e| e.to_string())?
        .to_bytes();
    String::from_utf8(bytes.to_vec()).map_err(|e| e.to_string())
}

#[derive(Debug)]
struct NoCertVerifier;

impl rustls::client::danger::ServerCertVerifier for NoCertVerifier {
    fn verify_server_cert(
        &self,
        _end_entity: &rustls::pki_types::CertificateDer<'_>,
        _intermediates: &[rustls::pki_types::CertificateDer<'_>],
        _server_name: &rustls::pki_types::ServerName<'_>,
        _ocsp_response: &[u8],
        _now: rustls::pki_types::UnixTime,
    ) -> Result<rustls::client::danger::ServerCertVerified, rustls::Error> {
        Ok(rustls::client::danger::ServerCertVerified::assertion())
    }

    fn verify_tls12_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn verify_tls13_signature(
        &self,
        _message: &[u8],
        _cert: &rustls::pki_types::CertificateDer<'_>,
        _dss: &rustls::DigitallySignedStruct,
    ) -> Result<rustls::client::danger::HandshakeSignatureValid, rustls::Error> {
        Ok(rustls::client::danger::HandshakeSignatureValid::assertion())
    }

    fn supported_verify_schemes(&self) -> Vec<rustls::SignatureScheme> {
        rustls::crypto::ring::default_provider()
            .signature_verification_algorithms
            .supported_schemes()
    }
}
