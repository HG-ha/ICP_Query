# ICP_Query Rust 版 (v0.7.0)

Python `ymicp` / `icpApi` 的 Rust 重写，功能对齐：

- MIIT ICP 查询（网站 / APP / 小程序 / 快应用 / 黑名单）
- 滑块验证码本地识别
- 代理池 / 隧道代理
- 批量任务、历史记录（SQLite）
- Web UI（复用项目根目录 `templates/` + `static/`）
- 配置读写与重启

## 构建

```bash
cd src/rust
cargo build --release
# 可选：UPX 再压一轮（需本机安装 upx）
# upx --best --lzma target/release/ymicp.exe
```

Release 已按体积优化（`opt-level=z` / LTO / `panic=abort` / strip，并裁剪未用依赖）。未 UPX 约 3.9MB，UPX 后约 1.6MB。打 tag 发版时 CI 会对 `icpApi-rs` 自动执行 `upx --best --lzma`。

## 运行

在 `src/rust` 目录下（会自动向上查找 `config.yml` 与 `templates/`）：

```bash
cargo run --release
# 或
./target/release/ymicp
```

默认监听 `0.0.0.0:16181`，Web UI：`http://127.0.0.1:16181`

也可将项目根目录的 `config.yml` 复制到运行目录。

## API（与 Python 版兼容）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/query/{web\|app\|mapp\|kapp\|bweb\|…}` | 单次查询 |
| POST | `/create/task` | 创建批量任务 |
| GET | `/query/task?taskname=` | 任务进度 |
| GET | `/history` | 查询历史 |
| GET | `/config` | 读取配置 |
| POST | `/config/save` | 保存配置 |
| GET | `/logs/realtime` | 实时日志 |

## 目录结构

```
src/rust/
├── Cargo.toml
├── config.yml
├── src/
│   ├── main.rs
│   ├── beian.rs         # MIIT 客户端（含创宇盾 IP 黑名单）
│   ├── captcha.rs       # 滑块缺口定位
│   ├── http_client.rs   # 代理 / 本地 IPv6 绑定 HTTP
│   ├── ipv6_pool.rs     # 本机 IPv6 地址池维护
│   ├── proxy_pool.rs    # HTTP 代理池
│   ├── config.rs / database.rs / log_collector.rs
│   ├── task_manager.rs  # 批量任务 + 重启
│   ├── utils.rs         # 网卡 / IPv6 / URL 工具
│   ├── state.rs
│   └── routes/
└── README.md
```

## 与 Python 版功能对齐

- 查询 / 批量 / 历史 / 配置 / 日志 / Web UI
- 滑块验证码本地识别
- 代理：IPv6 池 → 隧道 → extra_api 池（优先级同代码）
- 本机 IPv6：枚举、前缀补充（netsh / ip）、维护循环、出口绑定
- 创宇盾拦截后 IP 拉黑 5 分钟
- 配置保存备份、延迟重启（Windows 新控制台 / Unix exec）
- 可选按天滚动文件日志（`log.save_log`）
