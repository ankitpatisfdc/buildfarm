#!/bin/bash

# Redis vs Valkey Benchmarking Infrastructure Setup Script
# This script sets up parallel Redis and Valkey clusters for performance comparison

set -euo pipefail

# Configuration
REDIS_VERSION="7.2.4"
VALKEY_VERSION="8.1.0"
CLUSTER_SIZE=6  # 3 masters + 3 replicas
BASE_PORT=6379
REDIS_BASE_PORT=6379
VALKEY_BASE_PORT=7379

# Directories
BENCHMARK_DIR="${PWD}/benchmark-infrastructure"
REDIS_DIR="${BENCHMARK_DIR}/redis"
VALKEY_DIR="${BENCHMARK_DIR}/valkey"
CONFIG_DIR="${BENCHMARK_DIR}/configs"
DATA_DIR="${BENCHMARK_DIR}/data"
LOGS_DIR="${BENCHMARK_DIR}/logs"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Cleanup function
cleanup() {
    log_info "Cleaning up existing benchmark infrastructure..."
    pkill -f "redis-server.*benchmark" || true
    pkill -f "valkey-server.*benchmark" || true
    rm -rf "${BENCHMARK_DIR}"
}

# Create directory structure
setup_directories() {
    log_info "Setting up directory structure..."

    mkdir -p "${REDIS_DIR}/"{configs,data,logs}
    mkdir -p "${VALKEY_DIR}/"{configs,data,logs}
    mkdir -p "${CONFIG_DIR}"
    mkdir -p "${DATA_DIR}"
    mkdir -p "${LOGS_DIR}"

    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        mkdir -p "${REDIS_DIR}/data/node-${i}"
        mkdir -p "${VALKEY_DIR}/data/node-${i}"
    done
}

# Download and setup Redis
setup_redis() {
    log_info "Setting up Redis ${REDIS_VERSION}..."

    if ! command -v redis-server &> /dev/null; then
        log_error "Redis not found. Please install Redis ${REDIS_VERSION} or later."
        log_info "On macOS: brew install redis"
        log_info "On Ubuntu: sudo apt-get install redis-server"
        exit 1
    fi

    # Generate Redis configurations
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local port=$((REDIS_BASE_PORT + i))
        local node_dir="${REDIS_DIR}/data/node-${i}"

        cat > "${REDIS_DIR}/configs/redis-${i}.conf" << EOF
# Redis cluster node ${i} configuration
port ${port}
cluster-enabled yes
cluster-config-file nodes-${port}.conf
cluster-node-timeout 5000
appendonly yes
appendfilename "appendonly-${port}.aof"
dbfilename "dump-${port}.rdb"
dir ${node_dir}
logfile ${REDIS_DIR}/logs/redis-${i}.log
loglevel notice
save 900 1
save 300 10
save 60 10000
maxmemory 2gb
maxmemory-policy allkeys-lru
tcp-keepalive 60
timeout 300

# Performance optimizations for benchmarking
tcp-backlog 511
databases 1
rdbcompression yes
rdbchecksum yes
stop-writes-on-bgsave-error no

# Cluster and replication settings
cluster-require-full-coverage no
cluster-migration-barrier 1
cluster-allow-reads-when-down no

# Security (minimal for benchmarking)
protected-mode no
bind 127.0.0.1
EOF
    done
}

# Download and setup Valkey
setup_valkey() {
    log_info "Setting up Valkey ${VALKEY_VERSION}..."

    # Check if Valkey is available
    if ! command -v valkey-server &> /dev/null; then
        log_warn "Valkey not found in PATH. Attempting to download..."

        # Create Valkey directory
        mkdir -p "${VALKEY_DIR}/bin"

        # Download Valkey (adjust URL based on actual release)
        local download_url="https://github.com/valkey-io/valkey/releases/download/${VALKEY_VERSION}/valkey-${VALKEY_VERSION}.tar.gz"

        log_info "Downloading Valkey from ${download_url}"
        curl -L -o "${VALKEY_DIR}/valkey.tar.gz" "${download_url}" || {
            log_error "Failed to download Valkey. Please install manually."
            log_info "Visit: https://github.com/valkey-io/valkey/releases"
            exit 1
        }

        # Extract and build (simplified - assumes compilation)
        cd "${VALKEY_DIR}"
        tar -xzf valkey.tar.gz --strip-components=1
        make PREFIX="${VALKEY_DIR}" install || {
            log_error "Failed to build Valkey. Please install manually."
            exit 1
        }

        # Add to PATH for this session
        export PATH="${VALKEY_DIR}/bin:${PATH}"
        cd "${BENCHMARK_DIR}"
    fi

    # Generate Valkey configurations (similar to Redis but with Valkey-specific optimizations)
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local port=$((VALKEY_BASE_PORT + i))
        local node_dir="${VALKEY_DIR}/data/node-${i}"

        cat > "${VALKEY_DIR}/configs/valkey-${i}.conf" << EOF
# Valkey cluster node ${i} configuration
port ${port}
cluster-enabled yes
cluster-config-file nodes-${port}.conf
cluster-node-timeout 5000
appendonly yes
appendfilename "appendonly-${port}.aof"
dbfilename "dump-${port}.rdb"
dir ${node_dir}
logfile ${VALKEY_DIR}/logs/valkey-${i}.log
loglevel notice
save 900 1
save 300 10
save 60 10000
maxmemory 2gb
maxmemory-policy allkeys-lru
tcp-keepalive 60
timeout 300

# Performance optimizations for benchmarking
tcp-backlog 511
databases 1
rdbcompression yes
rdbchecksum yes
stop-writes-on-bgsave-error no

# Valkey-specific optimizations
# Enable enhanced I/O threading (adjust based on CPU cores)
io-threads 4
io-threads-do-reads yes

# Cluster and replication settings
cluster-require-full-coverage no
cluster-migration-barrier 1
cluster-allow-reads-when-down no

# Security (minimal for benchmarking)
protected-mode no
bind 127.0.0.1
EOF
    done
}

# Start Redis cluster
start_redis_cluster() {
    log_info "Starting Redis cluster..."

    # Start Redis nodes
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local config_file="${REDIS_DIR}/configs/redis-${i}.conf"

        log_info "Starting Redis node ${i}..."
        redis-server "${config_file}" &

        # Wait for node to start
        local port=$((REDIS_BASE_PORT + i))
        local retries=30
        while ! redis-cli -p "${port}" ping > /dev/null 2>&1 && [ $retries -gt 0 ]; do
            sleep 1
            ((retries--))
        done

        if [ $retries -eq 0 ]; then
            log_error "Failed to start Redis node ${i}"
            exit 1
        fi
    done

    # Create cluster
    log_info "Creating Redis cluster..."
    local nodes=""
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local port=$((REDIS_BASE_PORT + i))
        nodes="${nodes} 127.0.0.1:${port}"
    done

    # Create cluster with 1 replica per master
    echo "yes" | redis-cli --cluster create ${nodes} --cluster-replicas 1

    log_info "Redis cluster started successfully!"
}

# Start Valkey cluster
start_valkey_cluster() {
    log_info "Starting Valkey cluster..."

    # Determine Valkey server command
    local valkey_server="valkey-server"
    local valkey_cli="valkey-cli"

    if ! command -v valkey-server &> /dev/null; then
        if [ -f "${VALKEY_DIR}/bin/valkey-server" ]; then
            valkey_server="${VALKEY_DIR}/bin/valkey-server"
            valkey_cli="${VALKEY_DIR}/bin/valkey-cli"
        else
            log_error "Valkey server not found"
            exit 1
        fi
    fi

    # Start Valkey nodes
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local config_file="${VALKEY_DIR}/configs/valkey-${i}.conf"

        log_info "Starting Valkey node ${i}..."
        "${valkey_server}" "${config_file}" &

        # Wait for node to start
        local port=$((VALKEY_BASE_PORT + i))
        local retries=30
        while ! "${valkey_cli}" -p "${port}" ping > /dev/null 2>&1 && [ $retries -gt 0 ]; do
            sleep 1
            ((retries--))
        done

        if [ $retries -eq 0 ]; then
            log_error "Failed to start Valkey node ${i}"
            exit 1
        fi
    done

    # Create cluster
    log_info "Creating Valkey cluster..."
    local nodes=""
    for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
        local port=$((VALKEY_BASE_PORT + i))
        nodes="${nodes} 127.0.0.1:${port}"
    done

    # Create cluster with 1 replica per master
    echo "yes" | "${valkey_cli}" --cluster create ${nodes} --cluster-replicas 1

    log_info "Valkey cluster started successfully!"
}

# Verify clusters
verify_clusters() {
    log_info "Verifying cluster health..."

    # Check Redis cluster
    log_info "Redis cluster status:"
    redis-cli -p ${REDIS_BASE_PORT} cluster info
    redis-cli -p ${REDIS_BASE_PORT} cluster nodes

    # Check Valkey cluster
    log_info "Valkey cluster status:"
    local valkey_cli="valkey-cli"
    if ! command -v valkey-cli &> /dev/null && [ -f "${VALKEY_DIR}/bin/valkey-cli" ]; then
        valkey_cli="${VALKEY_DIR}/bin/valkey-cli"
    fi

    "${valkey_cli}" -p ${VALKEY_BASE_PORT} cluster info
    "${valkey_cli}" -p ${VALKEY_BASE_PORT} cluster nodes
}

# Setup monitoring
setup_monitoring() {
    log_info "Setting up monitoring infrastructure..."

    # Create Prometheus configuration
    cat > "${CONFIG_DIR}/prometheus.yml" << EOF
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'redis-cluster'
    static_configs:
      - targets:
$(for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
    echo "          - 'localhost:$((REDIS_BASE_PORT + i))'"
done)

  - job_name: 'valkey-cluster'
    static_configs:
      - targets:
$(for i in $(seq 0 $((CLUSTER_SIZE - 1))); do
    echo "          - 'localhost:$((VALKEY_BASE_PORT + i))'"
done)

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['localhost:9100']
EOF

    # Create docker-compose for monitoring stack
    cat > "${CONFIG_DIR}/docker-compose.monitoring.yml" << EOF
version: '3.8'

services:
  prometheus:
    image: prom/prometheus:latest
    container_name: benchmark-prometheus
    ports:
      - "9090:9090"
    volumes:
      - ${CONFIG_DIR}/prometheus.yml:/etc/prometheus/prometheus.yml
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--web.console.libraries=/etc/prometheus/console_libraries'
      - '--web.console.templates=/etc/prometheus/consoles'

  grafana:
    image: grafana/grafana:latest
    container_name: benchmark-grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-storage:/var/lib/grafana

  node-exporter:
    image: prom/node-exporter:latest
    container_name: benchmark-node-exporter
    ports:
      - "9100:9100"
    command:
      - '--path.rootfs=/host'
    volumes:
      - '/:/host:ro,rslave'

volumes:
  grafana-storage:
EOF

    log_info "Monitoring configuration created."
    log_info "To start monitoring: cd ${CONFIG_DIR} && docker-compose -f docker-compose.monitoring.yml up -d"
}

# Create management scripts
create_management_scripts() {
    log_info "Creating management scripts..."

    # Stop script
    cat > "${BENCHMARK_DIR}/stop-clusters.sh" << 'EOF'
#!/bin/bash
echo "Stopping Redis and Valkey clusters..."
pkill -f "redis-server.*benchmark" || true
pkill -f "valkey-server.*benchmark" || true
echo "Clusters stopped."
EOF

    # Status script
    cat > "${BENCHMARK_DIR}/status-clusters.sh" << EOF
#!/bin/bash
echo "=== Redis Cluster Status ==="
redis-cli -p ${REDIS_BASE_PORT} cluster info 2>/dev/null || echo "Redis cluster not responding"

echo -e "\n=== Valkey Cluster Status ==="
if command -v valkey-cli &> /dev/null; then
    valkey-cli -p ${VALKEY_BASE_PORT} cluster info 2>/dev/null || echo "Valkey cluster not responding"
elif [ -f "${VALKEY_DIR}/bin/valkey-cli" ]; then
    ${VALKEY_DIR}/bin/valkey-cli -p ${VALKEY_BASE_PORT} cluster info 2>/dev/null || echo "Valkey cluster not responding"
else
    echo "Valkey CLI not found"
fi

echo -e "\n=== Process Status ==="
pgrep -f "redis-server.*benchmark" | wc -l | sed 's/^/Redis processes: /'
pgrep -f "valkey-server.*benchmark" | wc -l | sed 's/^/Valkey processes: /'
EOF

    # Restart script
    cat > "${BENCHMARK_DIR}/restart-clusters.sh" << EOF
#!/bin/bash
echo "Restarting clusters..."
./stop-clusters.sh
sleep 5
cd "${BENCHMARK_DIR}"
bash "${0%/*}/$(basename "$0" .sh)/../setup-benchmark-infrastructure.sh" --start-only
EOF

    chmod +x "${BENCHMARK_DIR}"/*.sh
}

# Print usage information
print_usage() {
    cat << EOF
Redis vs Valkey Benchmark Infrastructure Setup

Usage: $0 [OPTIONS]

Options:
    --cleanup           Clean up existing infrastructure
    --start-only        Start clusters only (skip setup)
    --redis-only        Setup only Redis cluster
    --valkey-only       Setup only Valkey cluster
    --no-monitoring     Skip monitoring setup
    -h, --help          Show this help message

Examples:
    $0                  # Full setup
    $0 --cleanup        # Clean up existing setup
    $0 --start-only     # Start clusters with existing configs

After setup:
    - Redis cluster: ports ${REDIS_BASE_PORT}-$((REDIS_BASE_PORT + CLUSTER_SIZE - 1))
    - Valkey cluster: ports ${VALKEY_BASE_PORT}-$((VALKEY_BASE_PORT + CLUSTER_SIZE - 1))
    - Monitoring: http://localhost:3000 (Grafana), http://localhost:9090 (Prometheus)

Management scripts:
    - ${BENCHMARK_DIR}/stop-clusters.sh
    - ${BENCHMARK_DIR}/status-clusters.sh
    - ${BENCHMARK_DIR}/restart-clusters.sh
EOF
}

# Main execution
main() {
    local cleanup_only=false
    local start_only=false
    local redis_only=false
    local valkey_only=false
    local no_monitoring=false

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --cleanup)
                cleanup_only=true
                shift
                ;;
            --start-only)
                start_only=true
                shift
                ;;
            --redis-only)
                redis_only=true
                shift
                ;;
            --valkey-only)
                valkey_only=true
                shift
                ;;
            --no-monitoring)
                no_monitoring=true
                shift
                ;;
            -h|--help)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown option: $1"
                print_usage
                exit 1
                ;;
        esac
    done

    if [ "$cleanup_only" = true ]; then
        cleanup
        exit 0
    fi

    log_info "Setting up Redis vs Valkey benchmark infrastructure..."

    if [ "$start_only" = false ]; then
        cleanup
        setup_directories

        if [ "$valkey_only" = false ]; then
            setup_redis
        fi

        if [ "$redis_only" = false ]; then
            setup_valkey
        fi

        if [ "$no_monitoring" = false ]; then
            setup_monitoring
        fi

        create_management_scripts
    fi

    # Start clusters
    if [ "$valkey_only" = false ]; then
        start_redis_cluster
    fi

    if [ "$redis_only" = false ]; then
        start_valkey_cluster
    fi

    # Verify setup
    sleep 5
    verify_clusters

    log_info "Setup complete!"
    log_info "Infrastructure location: ${BENCHMARK_DIR}"
    log_info "Use './status-clusters.sh' to check cluster health"
    log_info "Use './stop-clusters.sh' to stop all clusters"

    if [ "$no_monitoring" = false ]; then
        log_info "To start monitoring: cd ${CONFIG_DIR} && docker-compose -f docker-compose.monitoring.yml up -d"
    fi
}

# Execute main function with all arguments
main "$@"
