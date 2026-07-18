use chrono::Local;
use parking_lot::Mutex;
use serde_json::{json, Value};
use std::collections::VecDeque;
use std::sync::Arc;
use tracing::{Event, Subscriber};
use tracing_subscriber::layer::Context;
use tracing_subscriber::Layer;

pub type SharedLogCollector = Arc<LogCollector>;

pub struct LogCollector {
    logs: Mutex<VecDeque<Value>>,
    maxlen: usize,
}

impl LogCollector {
    pub fn new(maxlen: usize) -> Self {
        Self {
            logs: Mutex::new(VecDeque::with_capacity(maxlen.min(1000))),
            maxlen,
        }
    }

    pub fn add_log(&self, message: impl Into<String>, level: &str) {
        let mut logs = self.logs.lock();
        if logs.len() >= self.maxlen {
            logs.pop_front();
        }
        logs.push_back(json!({
            "time": Local::now().format("%Y-%m-%d %H:%M:%S").to_string(),
            "message": message.into(),
            "level": level,
        }));
    }

    pub fn get_logs(&self, limit: usize) -> Vec<Value> {
        let logs = self.logs.lock();
        let len = logs.len();
        if len > limit {
            logs.iter().skip(len - limit).cloned().collect()
        } else {
            logs.iter().cloned().collect()
        }
    }

    pub fn clear(&self) {
        self.logs.lock().clear();
    }
}

/// 将 tracing 日志同步到 LogCollector（供 Web UI 使用）
pub struct CollectorLayer {
    collector: SharedLogCollector,
}

impl CollectorLayer {
    pub fn new(collector: SharedLogCollector) -> Self {
        Self { collector }
    }
}

impl<S> Layer<S> for CollectorLayer
where
    S: Subscriber,
{
    fn on_event(&self, event: &Event<'_>, _ctx: Context<'_, S>) {
        let mut visitor = MessageVisitor::default();
        event.record(&mut visitor);
        if let Some(msg) = visitor.message {
            let level = match *event.metadata().level() {
                tracing::Level::ERROR => "ERROR",
                tracing::Level::WARN => "WARNING",
                tracing::Level::INFO => "INFO",
                tracing::Level::DEBUG => "DEBUG",
                tracing::Level::TRACE => "TRACE",
            };
            let formatted = format!(
                "[{}] {} - {}",
                Local::now().format("%Y-%m-%d %H:%M:%S"),
                level,
                msg
            );
            self.collector.add_log(formatted, level);
        }
    }
}

#[derive(Default)]
struct MessageVisitor {
    message: Option<String>,
}

impl tracing::field::Visit for MessageVisitor {
    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            self.message = Some(format!("{value:?}").trim_matches('"').to_string());
        }
    }

    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "message" {
            self.message = Some(value.to_string());
        }
    }
}
