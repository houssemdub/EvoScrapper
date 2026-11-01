use clap::Parser;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Instant;
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

mod engine;
mod server;
mod stats;
mod types;

use engine::SessionManager;
use server::create_router;
use server::routes::AppState;
use types::EngineConfig;

#[derive(Parser, Debug)]
#[command(
    name = "evostreamer",
    author = "EvoScrapper Team",
    version = "2.7.0",
    about = "Next-Generation High-Performance Native BitTorrent & HTTP 206 Streaming Daemon"
)]
struct Args {
    #[arg(short, long, env = "STREAM_PORT", default_value_t = 8891)]
    port: u16,

    #[arg(long, env = "EVO_STREAM_BIND_HOST", default_value = "127.0.0.1")]
    bind_host: String,

    #[arg(long, env = "EVO_STREAM_CACHE_DIR", default_value = ".stream_cache")]
    cache_dir: PathBuf,

    #[arg(long, env = "EVO_STREAMER_TOKEN", default_value = "")]
    token: String,

    #[arg(long, env = "EVO_STREAMER_ALLOW_ANONYMOUS", default_value_t = false)]
    allow_anonymous: bool,

    #[arg(long, env = "TORRENT_PORT", default_value_t = 50000)]
    torrent_port: u16,

    #[arg(long, env = "DHT_PORT", default_value_t = 50001)]
    dht_port: u16,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "evostreamer=info,tower_http=info".into()),
        )
        .with(tracing_subscriber::fmt::layer())
        .init();

    let args = Args::parse();

    // Auto-resolve token if empty
    let mut resolved_token = args.token.trim().to_string();
    if resolved_token.is_empty() {
        let token_path = args.cache_dir.join("streamer.token");
        if token_path.exists() {
            if let Ok(content) = std::fs::read_to_string(&token_path) {
                resolved_token = content.trim().to_string();
            }
        }
    }

    let config = EngineConfig {
        port: args.port,
        bind_host: args.bind_host.clone(),
        cache_dir: args.cache_dir.clone(),
        token: resolved_token,
        allow_anonymous: args.allow_anonymous,
        torrent_port: args.torrent_port,
        dht_port: args.dht_port,
        max_active_torrents: 3,
    };

    let session_manager = SessionManager::new(config.clone()).await?;

    let app_state = Arc::new(AppState {
        config: config.clone(),
        session_manager,
        start_time: Instant::now(),
    });

    let app = create_router(app_state);

    let addr: SocketAddr = format!("{}:{}", config.bind_host, config.port).parse()?;
    println!("\n==========================================================");
    println!("  [+] EvoScrapper Native Rust Streaming Engine v2.7.0");
    println!("  -> Streaming Daemon: http://{}", addr);
    println!("  -> Engine Protocol:  RFC 7233 206 Partial Content + Stremio Wire");
    println!("  -> Cache Directory:  {}", config.cache_dir.display());
    println!("==========================================================\n");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app)
        .with_graceful_shutdown(shutdown_signal())
        .await?;

    Ok(())
}

async fn shutdown_signal() {
    let ctrl_c = async {
        tokio::signal::ctrl_c()
            .await
            .expect("failed to install Ctrl+C handler");
    };

    #[cfg(unix)]
    let terminate = async {
        tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
            .expect("failed to install signal handler")
            .recv()
            .await;
    };

    #[cfg(not(unix))]
    let terminate = std::future::pending::<()>();

    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    println!("[*] EvoScrapper Rust streaming engine shutting down cleanly...");
}
