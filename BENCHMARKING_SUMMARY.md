# Redis vs Valkey Benchmarking for Buildfarm - Implementation Summary

## Overview

This document provides a complete implementation plan for benchmarking Redis against Valkey using real-world Buildfarm workloads. The approach is based on detailed analysis of the Buildfarm codebase to ensure the benchmarks accurately reflect actual usage patterns.

## Key Findings from Buildfarm Analysis

### Redis Usage in Buildfarm

Buildfarm uses Redis as a "backplane" - a critical shared communication layer that supports:

1. **Distributed Job Queuing** (`BalancedRedisQueue`)
   - Multiple Redis lists with hashtags for load balancing
   - Round-robin distribution across 8 queues by default
   - Blocking operations (`BLPOP`) with exponential backoff
   - Dequeue management for fault tolerance

2. **Metadata and Caching** (`ShardActionCache`, operation management)
   - Action result caching with TTL (4 weeks default)
   - Operation metadata storage (1 week TTL)
   - Worker registration and capabilities
   - Hash operations for complex object storage

3. **Content Addressable Storage** (CAS blob tracking)
   - Blob location tracking across distributed workers
   - Availability queries and batch operations
   - Set operations for worker location management

4. **Worker Coordination** (pub/sub messaging)
   - Real-time operation status updates
   - Worker heartbeats and lifecycle management
   - Operation channel communication

### Valkey Advantages

Based on research, Valkey offers:
- **Enhanced I/O multithreading**: Up to 3x performance improvement
- **Memory efficiency**: 20% reduction in memory usage (v8.1)
- **Better multi-core utilization**: Improved threading model
- **Open-source governance**: BSD license vs Redis's restrictive licensing

## Implementation Components

### 1. Infrastructure Setup Script
**File**: `scripts/setup-benchmark-infrastructure.sh`

**Features**:
- Automated Redis and Valkey cluster deployment
- Identical configuration for fair comparison
- Integrated monitoring with Prometheus/Grafana
- Management scripts for cluster operations

**Usage**:
```bash
# Full setup with monitoring
./scripts/setup-benchmark-infrastructure.sh

# Redis cluster: ports 6379-6384
# Valkey cluster: ports 7379-7384
# Monitoring: http://localhost:3000 (Grafana)
```

### 2. Workload Generator
**File**: `scripts/buildfarm-workload-generator.py`

**Capabilities**:
- **Queue Operations**: Simulates `BalancedRedisQueue` patterns
- **Cache Operations**: Action cache with realistic hit ratios (80/20 read/write)
- **CAS Operations**: Blob location tracking and availability queries
- **Coordination**: Worker heartbeats and pub/sub messaging
- **Realistic Payloads**: Variable sizes (1KB-4KB) matching Buildfarm operations

**Usage**:
```bash
# Basic benchmark (5 minutes)
python3 scripts/buildfarm-workload-generator.py \
  --duration 300 \
  --queue-ops-per-sec 100 \
  --cache-ops-per-sec 200 \
  --coord-ops-per-sec 50

# High-throughput test
python3 scripts/buildfarm-workload-generator.py \
  --duration 600 \
  --queue-ops-per-sec 500 \
  --cache-ops-per-sec 1000 \
  --coord-ops-per-sec 200 \
  --workers 100
```

### 3. Monitoring and Analysis
**Components**:
- Prometheus for metrics collection
- Grafana for visualization
- Custom exporters for Redis/Valkey metrics
- Automated report generation

## Benchmark Scenarios

### Scenario 1: Baseline Performance
```bash
python3 scripts/buildfarm-workload-generator.py \
  --duration 300 \
  --queue-ops-per-sec 100 \
  --cache-ops-per-sec 200 \
  --coord-ops-per-sec 50 \
  --workers 50 \
  --output baseline-results.json
```

### Scenario 2: High-Throughput Burst
```bash
python3 scripts/buildfarm-workload-generator.py \
  --duration 600 \
  --queue-ops-per-sec 1000 \
  --cache-ops-per-sec 2000 \
  --coord-ops-per-sec 500 \
  --workers 200 \
  --output burst-results.json
```

### Scenario 3: Memory Pressure
```bash
# Fill clusters to 80% capacity first, then run:
python3 scripts/buildfarm-workload-generator.py \
  --duration 1800 \
  --queue-ops-per-sec 200 \
  --cache-ops-per-sec 400 \
  --coord-ops-per-sec 100 \
  --workers 100 \
  --payload-size-min 8192 \
  --payload-size-max 16384 \
  --output memory-pressure-results.json
```

### Scenario 4: Real-World Mixed Workload
```bash
python3 scripts/buildfarm-workload-generator.py \
  --duration 3600 \
  --queue-ops-per-sec 300 \
  --cache-ops-per-sec 600 \
  --coord-ops-per-sec 150 \
  --workers 75 \
  --output mixed-workload-results.json
```

## Expected Results and Analysis

### Key Metrics to Compare

1. **Throughput Metrics**
   - Operations per second (overall and by type)
   - Queue operations (LPUSH/BLPOP latency)
   - Cache operations (GET/SET/HGET/HSET latency)
   - Pub/sub message delivery times

2. **Latency Metrics**
   - p50, p95, p99 latencies for each operation type
   - Connection establishment times
   - Timeout frequencies

3. **Resource Utilization**
   - CPU utilization (per core)
   - Memory usage and fragmentation
   - Network I/O patterns
   - Connection counts

4. **Reliability Metrics**
   - Operation success rates
   - Failover recovery times
   - Data consistency validation

### Expected Valkey Advantages

Based on published benchmarks:
- **2-3x higher throughput** under high concurrency
- **Lower latency** due to improved I/O threading
- **Better memory efficiency** (20% reduction in usage)
- **Improved multi-core scaling**

## Implementation Timeline

### Week 1-2: Infrastructure Setup
- [ ] Deploy parallel Redis/Valkey clusters
- [ ] Configure monitoring infrastructure
- [ ] Validate environment parity
- [ ] Test basic connectivity and operations

### Week 2-3: Workload Development
- [ ] Implement core workload generators
- [ ] Integrate with monitoring systems
- [ ] Validate workload accuracy against Buildfarm telemetry
- [ ] Create automated test orchestration

### Week 3-4: Benchmark Execution
- [ ] Execute all benchmark scenarios
- [ ] Collect comprehensive metrics
- [ ] Run extended stability tests
- [ ] Document any issues or anomalies

### Week 4-5: Analysis and Validation
- [ ] Analyze performance data
- [ ] Generate comparative reports
- [ ] Test actual Buildfarm deployment with Valkey
- [ ] Create migration recommendations

## Quick Start Guide

### Prerequisites
```bash
# Install dependencies
pip3 install redis redis-cluster asyncio
brew install redis  # or apt-get install redis-server
docker  # for monitoring stack
```

### Setup and Run
```bash
# 1. Setup infrastructure
./scripts/setup-benchmark-infrastructure.sh

# 2. Start monitoring
cd benchmark-infrastructure/configs
docker-compose -f docker-compose.monitoring.yml up -d

# 3. Run baseline benchmark
python3 scripts/buildfarm-workload-generator.py \
  --duration 300 \
  --output baseline-results.json

# 4. View results
cat baseline-results.json | jq '.comparison.overall'

# 5. Access monitoring
open http://localhost:3000  # Grafana (admin/admin)
open http://localhost:9090  # Prometheus
```

### Cleanup
```bash
# Stop clusters
cd benchmark-infrastructure
./stop-clusters.sh

# Remove infrastructure
cd ..
./scripts/setup-benchmark-infrastructure.sh --cleanup

# Stop monitoring
cd benchmark-infrastructure/configs
docker-compose -f docker-compose.monitoring.yml down
```

## Interpreting Results

### Performance Comparison
The benchmark generates detailed JSON reports with:

```json
{
  "comparison": {
    "overall": {
      "redis_ops_per_second": 2145.3,
      "valkey_ops_per_second": 3621.7,
      "performance_improvement": 68.8
    },
    "by_operation_type": {
      "queue_submit": {
        "redis_latency_p50": 2.3,
        "valkey_latency_p50": 1.4,
        "latency_improvement_percent": 39.1
      }
    }
  }
}
```

### Success Criteria
- **Statistical Significance**: >95% confidence in performance differences
- **Workload Fidelity**: Benchmarks accurately represent Buildfarm usage
- **Operational Validation**: Successful Buildfarm deployment on Valkey
- **Performance Baseline**: Quantitative comparison across all scenarios

## Production Migration Considerations

### Compatibility Validation
- Protocol compatibility (Redis commands work with Valkey)
- Client library support (Jedis, redis-py, etc.)
- Feature parity (ensure critical Buildfarm features work)
- Configuration compatibility

### Migration Strategy
1. **Parallel Deployment**: Run Valkey alongside Redis initially
2. **Gradual Migration**: Move non-critical workloads first
3. **Performance Monitoring**: Continuous comparison during migration
4. **Rollback Plan**: Quick reversion if issues arise

### Risk Mitigation
- Comprehensive testing in staging environment
- Gradual rollout with monitoring
- Team training on Valkey operations
- Documentation and runbooks

## Conclusion

This benchmarking plan provides a comprehensive, scientifically rigorous approach to comparing Redis and Valkey using real Buildfarm workloads. The implementation includes:

- **Realistic Workload Simulation**: Based on actual Buildfarm usage patterns
- **Fair Comparison**: Identical infrastructure and configuration
- **Comprehensive Monitoring**: Detailed metrics and observability
- **Production Validation**: Real-world testing with actual Buildfarm deployment

The results will provide actionable insights for making informed decisions about potentially migrating Buildfarm from Redis to Valkey, considering both performance benefits and operational implications.

---

For questions or issues, refer to the detailed documentation in `benchmarking-plan.md` or examine the implementation in the `scripts/` directory.
