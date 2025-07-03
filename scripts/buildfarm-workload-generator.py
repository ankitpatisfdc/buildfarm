#!/usr/bin/env python3
"""
Buildfarm Workload Generator for Redis vs Valkey Benchmarking

This script simulates real-world Buildfarm workloads based on patterns
observed in the Buildfarm codebase to provide meaningful performance
comparisons between Redis and Valkey.
"""

import argparse
import asyncio
import json
import logging
import random
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import redis
from redis.cluster import RedisCluster


@dataclass
class BenchmarkConfig:
    """Configuration for benchmark execution"""
    redis_hosts: List[str]
    valkey_hosts: List[str]
    duration_seconds: int
    concurrent_workers: int
    queue_operations_per_second: int
    cache_operations_per_second: int
    coordination_operations_per_second: int
    payload_size_range: Tuple[int, int]
    queue_count: int = 8
    worker_count: int = 50


@dataclass
class OperationResult:
    """Result of a single operation"""
    operation_type: str
    latency_ms: float
    success: bool
    timestamp: float
    error: Optional[str] = None


class MetricsCollector:
    """Collects and aggregates performance metrics"""

    def __init__(self):
        self.results: List[OperationResult] = []
        self.start_time = time.time()

    def record_operation(self, result: OperationResult):
        """Record a single operation result"""
        self.results.append(result)

    def get_statistics(self) -> Dict:
        """Calculate performance statistics"""
        if not self.results:
            return {}

        # Group by operation type
        by_type = {}
        for result in self.results:
            if result.operation_type not in by_type:
                by_type[result.operation_type] = []
            by_type[result.operation_type].append(result)

        stats = {
            'total_operations': len(self.results),
            'duration_seconds': time.time() - self.start_time,
            'operations_per_second': len(self.results) / (time.time() - self.start_time),
            'by_type': {}
        }

        for op_type, results in by_type.items():
            latencies = [r.latency_ms for r in results if r.success]
            success_count = sum(1 for r in results if r.success)

            if latencies:
                stats['by_type'][op_type] = {
                    'count': len(results),
                    'success_rate': success_count / len(results),
                    'latency_p50': statistics.median(latencies),
                    'latency_p95': statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else max(latencies),
                    'latency_p99': statistics.quantiles(latencies, n=100)[98] if len(latencies) > 100 else max(latencies),
                    'latency_avg': statistics.mean(latencies),
                    'latency_min': min(latencies),
                    'latency_max': max(latencies)
                }

        return stats


class BuildQueueWorkloadGenerator:
    """Simulates Buildfarm's BalancedRedisQueue operations"""

    def __init__(self, client, queue_count: int = 8):
        self.client = client
        self.queue_count = queue_count
        self.queues = [f"{{queue-{i}}}:operations" for i in range(queue_count)]
        self.current_queue = 0

    def _get_next_queue(self) -> str:
        """Round-robin queue selection (like BalancedRedisQueue)"""
        queue = self.queues[self.current_queue]
        self.current_queue = (self.current_queue + 1) % self.queue_count
        return queue

    def generate_build_operation(self, size_range: Tuple[int, int]) -> Dict:
        """Generate realistic build operation metadata"""
        size = random.randint(*size_range)

        # Simulate realistic Buildfarm operation metadata
        operation = {
            "operation_id": str(uuid.uuid4()),
            "action_digest": {
                "hash": "".join(random.choices("0123456789abcdef", k=64)),
                "size": random.randint(1000, 100000)
            },
            "platform": {
                "properties": [
                    {"name": "OSFamily", "value": "Linux"},
                    {"name": "cpu", "value": "x86_64"},
                    {"name": "min-cores", "value": str(random.randint(1, 8))}
                ]
            },
            "timeout": random.randint(60, 3600),
            "priority": random.randint(0, 10),
            "worker_id": f"worker-{random.randint(1, 50)}",
            # Pad to reach desired size
            "padding": "x" * max(0, size - 500)
        }

        return operation

    async def simulate_job_submission(self, operations_per_second: int, duration: int,
                                     size_range: Tuple[int, int], metrics: MetricsCollector):
        """Simulate continuous job submissions"""
        interval = 1.0 / operations_per_second
        end_time = time.time() + duration

        while time.time() < end_time:
            start = time.time()

            try:
                operation = self.generate_build_operation(size_range)
                queue = self._get_next_queue()

                # LPUSH operation (like Buildfarm's offer method)
                self.client.lpush(queue, json.dumps(operation))

                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type="queue_submit",
                    latency_ms=latency_ms,
                    success=True,
                    timestamp=time.time()
                ))

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type="queue_submit",
                    latency_ms=latency_ms,
                    success=False,
                    timestamp=time.time(),
                    error=str(e)
                ))

            # Rate limiting
            elapsed = time.time() - start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)

    async def simulate_job_processing(self, worker_count: int, duration: int,
                                     metrics: MetricsCollector):
        """Simulate workers pulling jobs from queues"""
        async def worker_loop(worker_id: int):
            end_time = time.time() + duration
            queue_index = worker_id % self.queue_count

            while time.time() < end_time:
                start = time.time()

                try:
                    queue = self.queues[queue_index]

                    # BLPOP operation with timeout (like Buildfarm's take method)
                    result = self.client.blpop([queue], timeout=1)

                    if result:
                        # Simulate processing time
                        processing_time = random.uniform(0.1, 2.0)
                        await asyncio.sleep(processing_time)

                        latency_ms = (time.time() - start) * 1000
                        metrics.record_operation(OperationResult(
                            operation_type="queue_process",
                            latency_ms=latency_ms,
                            success=True,
                            timestamp=time.time()
                        ))
                    else:
                        # Timeout - move to next queue
                        queue_index = (queue_index + 1) % self.queue_count

                except Exception as e:
                    latency_ms = (time.time() - start) * 1000
                    metrics.record_operation(OperationResult(
                        operation_type="queue_process",
                        latency_ms=latency_ms,
                        success=False,
                        timestamp=time.time(),
                        error=str(e)
                    ))

        # Start worker tasks
        tasks = [worker_loop(i) for i in range(worker_count)]
        await asyncio.gather(*tasks)


class CacheWorkloadGenerator:
    """Simulates action cache and metadata operations"""

    def __init__(self, client):
        self.client = client
        self.action_cache_prefix = "ActionCache"
        self.cas_prefix = "ContentAddressableStorage"
        self.operation_prefix = "Operation"

    def generate_action_key(self) -> str:
        """Generate realistic action cache key"""
        return f"{self.action_cache_prefix}:{random.randint(1, 1000000)}"

    def generate_action_result(self, size_range: Tuple[int, int]) -> Dict:
        """Generate realistic action result"""
        size = random.randint(*size_range)

        result = {
            "output_files": [
                {
                    "path": f"output/{i}.o",
                    "digest": {
                        "hash": "".join(random.choices("0123456789abcdef", k=64)),
                        "size": random.randint(1000, 50000)
                    }
                } for i in range(random.randint(1, 10))
            ],
            "stdout_digest": {
                "hash": "".join(random.choices("0123456789abcdef", k=64)),
                "size": random.randint(100, 10000)
            },
            "stderr_digest": {
                "hash": "".join(random.choices("0123456789abcdef", k=64)),
                "size": random.randint(0, 1000)
            },
            "exit_code": 0,
            "execution_metadata": {
                "worker": f"worker-{random.randint(1, 50)}",
                "execution_start_timestamp": datetime.now().isoformat(),
                "execution_completed_timestamp": (datetime.now() + timedelta(seconds=random.randint(1, 300))).isoformat()
            },
            # Pad to reach desired size
            "padding": "x" * max(0, size - 1000)
        }

        return result

    async def simulate_action_cache_operations(self, operations_per_second: int,
                                              duration: int, size_range: Tuple[int, int],
                                              metrics: MetricsCollector):
        """Simulate action cache operations with realistic hit ratios"""
        interval = 1.0 / operations_per_second
        end_time = time.time() + duration

        # Maintain a set of "hot" keys for realistic cache behavior
        hot_keys = [self.generate_action_key() for _ in range(100)]

        while time.time() < end_time:
            start = time.time()

            # 80% reads, 20% writes (typical for build caches)
            is_read = random.random() < 0.8

            try:
                if is_read:
                    # 70% hit hot keys, 30% random keys
                    if random.random() < 0.7:
                        key = random.choice(hot_keys)
                    else:
                        key = self.generate_action_key()

                    # GET operation
                    result = self.client.get(key)

                    latency_ms = (time.time() - start) * 1000
                    metrics.record_operation(OperationResult(
                        operation_type="cache_read",
                        latency_ms=latency_ms,
                        success=True,
                        timestamp=time.time()
                    ))

                else:
                    # SET operation with TTL (24 hours like Buildfarm)
                    key = random.choice(hot_keys) if random.random() < 0.5 else self.generate_action_key()
                    value = json.dumps(self.generate_action_result(size_range))

                    self.client.setex(key, 86400, value)  # 24 hour TTL

                    latency_ms = (time.time() - start) * 1000
                    metrics.record_operation(OperationResult(
                        operation_type="cache_write",
                        latency_ms=latency_ms,
                        success=True,
                        timestamp=time.time()
                    ))

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                operation_type = "cache_read" if is_read else "cache_write"
                metrics.record_operation(OperationResult(
                    operation_type=operation_type,
                    latency_ms=latency_ms,
                    success=False,
                    timestamp=time.time(),
                    error=str(e)
                ))

            # Rate limiting
            elapsed = time.time() - start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)

    async def simulate_cas_operations(self, operations_per_second: int, duration: int,
                                     metrics: MetricsCollector):
        """Simulate Content Addressable Storage operations"""
        interval = 1.0 / operations_per_second
        end_time = time.time() + duration

        while time.time() < end_time:
            start = time.time()

            try:
                # Simulate blob location tracking
                blob_hash = "".join(random.choices("0123456789abcdef", k=64))
                worker_location = f"worker-{random.randint(1, 50)}:8981"

                # 60% reads (checking blob availability), 40% writes (location updates)
                if random.random() < 0.6:
                    # Check blob locations
                    key = f"{self.cas_prefix}:{blob_hash}:locations"
                    locations = self.client.smembers(key)

                    operation_type = "cas_read"
                else:
                    # Add blob location
                    key = f"{self.cas_prefix}:{blob_hash}:locations"
                    self.client.sadd(key, worker_location)
                    self.client.expire(key, 604800)  # 1 week TTL

                    operation_type = "cas_write"

                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type=operation_type,
                    latency_ms=latency_ms,
                    success=True,
                    timestamp=time.time()
                ))

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type="cas_operation",
                    latency_ms=latency_ms,
                    success=False,
                    timestamp=time.time(),
                    error=str(e)
                ))

            # Rate limiting
            elapsed = time.time() - start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)


class CoordinationWorkloadGenerator:
    """Simulates worker coordination and pub/sub operations"""

    def __init__(self, client):
        self.client = client
        self.worker_channel = "WorkerChannel"
        self.operation_channel_prefix = "OperationChannel"

    async def simulate_worker_lifecycle(self, worker_count: int, duration: int,
                                       metrics: MetricsCollector):
        """Simulate worker registration, heartbeats, and coordination"""
        async def worker_heartbeat(worker_id: str):
            end_time = time.time() + duration

            while time.time() < end_time:
                start = time.time()

                try:
                    # Worker registration/heartbeat
                    worker_data = {
                        "worker_id": worker_id,
                        "timestamp": time.time(),
                        "capabilities": {
                            "cas": True,
                            "execution": True,
                            "max_cores": random.randint(4, 16)
                        },
                        "status": "available"
                    }

                    # Update worker registry with TTL
                    worker_key = f"Workers:{worker_id}"
                    self.client.setex(worker_key, 60, json.dumps(worker_data))  # 60s TTL

                    latency_ms = (time.time() - start) * 1000
                    metrics.record_operation(OperationResult(
                        operation_type="worker_heartbeat",
                        latency_ms=latency_ms,
                        success=True,
                        timestamp=time.time()
                    ))

                    # Wait for next heartbeat (30 seconds)
                    await asyncio.sleep(30)

                except Exception as e:
                    latency_ms = (time.time() - start) * 1000
                    metrics.record_operation(OperationResult(
                        operation_type="worker_heartbeat",
                        latency_ms=latency_ms,
                        success=False,
                        timestamp=time.time(),
                        error=str(e)
                    ))

        # Start worker heartbeat tasks
        tasks = [worker_heartbeat(f"worker-{i}") for i in range(worker_count)]
        await asyncio.gather(*tasks)

    async def simulate_operation_updates(self, operations_per_second: int, duration: int,
                                        metrics: MetricsCollector):
        """Simulate real-time operation status updates via pub/sub"""
        interval = 1.0 / operations_per_second
        end_time = time.time() + duration

        while time.time() < end_time:
            start = time.time()

            try:
                operation_id = str(uuid.uuid4())
                channel = f"{self.operation_channel_prefix}:{operation_id}"

                # Simulate operation state changes
                states = ["QUEUED", "ASSIGNED", "EXECUTING", "COMPLETED"]
                state = random.choice(states)

                message = {
                    "operation_id": operation_id,
                    "state": state,
                    "worker_id": f"worker-{random.randint(1, 50)}",
                    "timestamp": time.time()
                }

                # Publish operation update
                self.client.publish(channel, json.dumps(message))

                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type="operation_update",
                    latency_ms=latency_ms,
                    success=True,
                    timestamp=time.time()
                ))

            except Exception as e:
                latency_ms = (time.time() - start) * 1000
                metrics.record_operation(OperationResult(
                    operation_type="operation_update",
                    latency_ms=latency_ms,
                    success=False,
                    timestamp=time.time(),
                    error=str(e)
                ))

            # Rate limiting
            elapsed = time.time() - start
            if elapsed < interval:
                await asyncio.sleep(interval - elapsed)


class BenchmarkRunner:
    """Main benchmark execution coordinator"""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.redis_metrics = MetricsCollector()
        self.valkey_metrics = MetricsCollector()

    def _create_redis_client(self, hosts: List[str]):
        """Create Redis cluster client"""
        startup_nodes = []
        for host in hosts:
            parts = host.split(':')
            startup_nodes.append({
                "host": parts[0],
                "port": int(parts[1]) if len(parts) > 1 else 6379
            })

        return RedisCluster(startup_nodes=startup_nodes, decode_responses=False)

    async def run_workload_on_cluster(self, client, metrics: MetricsCollector):
        """Run all workloads on a single cluster"""
        # Create workload generators
        queue_gen = BuildQueueWorkloadGenerator(client, self.config.queue_count)
        cache_gen = CacheWorkloadGenerator(client)
        coord_gen = CoordinationWorkloadGenerator(client)

        # Start all workload tasks concurrently
        tasks = []

        # Queue workloads
        if self.config.queue_operations_per_second > 0:
            tasks.append(queue_gen.simulate_job_submission(
                self.config.queue_operations_per_second,
                self.config.duration_seconds,
                self.config.payload_size_range,
                metrics
            ))

            tasks.append(queue_gen.simulate_job_processing(
                self.config.worker_count,
                self.config.duration_seconds,
                metrics
            ))

        # Cache workloads
        if self.config.cache_operations_per_second > 0:
            tasks.append(cache_gen.simulate_action_cache_operations(
                self.config.cache_operations_per_second,
                self.config.duration_seconds,
                self.config.payload_size_range,
                metrics
            ))

            tasks.append(cache_gen.simulate_cas_operations(
                self.config.cache_operations_per_second // 4,  # Lower rate for CAS
                self.config.duration_seconds,
                metrics
            ))

        # Coordination workloads
        if self.config.coordination_operations_per_second > 0:
            tasks.append(coord_gen.simulate_worker_lifecycle(
                self.config.worker_count,
                self.config.duration_seconds,
                metrics
            ))

            tasks.append(coord_gen.simulate_operation_updates(
                self.config.coordination_operations_per_second,
                self.config.duration_seconds,
                metrics
            ))

        # Execute all workloads concurrently
        await asyncio.gather(*tasks)

    async def run_benchmark(self):
        """Execute benchmark on both Redis and Valkey clusters"""
        logging.info("Starting Redis vs Valkey benchmark...")

        # Create clients
        redis_client = self._create_redis_client(self.config.redis_hosts)
        valkey_client = self._create_redis_client(self.config.valkey_hosts)

        # Run workloads concurrently on both clusters
        redis_task = self.run_workload_on_cluster(redis_client, self.redis_metrics)
        valkey_task = self.run_workload_on_cluster(valkey_client, self.valkey_metrics)

        await asyncio.gather(redis_task, valkey_task)

        logging.info("Benchmark completed successfully!")

    def generate_report(self) -> Dict:
        """Generate comprehensive benchmark report"""
        redis_stats = self.redis_metrics.get_statistics()
        valkey_stats = self.valkey_metrics.get_statistics()

        report = {
            "benchmark_config": {
                "duration_seconds": self.config.duration_seconds,
                "concurrent_workers": self.config.concurrent_workers,
                "queue_operations_per_second": self.config.queue_operations_per_second,
                "cache_operations_per_second": self.config.cache_operations_per_second,
                "coordination_operations_per_second": self.config.coordination_operations_per_second,
                "payload_size_range": self.config.payload_size_range,
                "queue_count": self.config.queue_count,
                "worker_count": self.config.worker_count
            },
            "redis_results": redis_stats,
            "valkey_results": valkey_stats,
            "comparison": self._generate_comparison(redis_stats, valkey_stats),
            "timestamp": datetime.now().isoformat()
        }

        return report

    def _generate_comparison(self, redis_stats: Dict, valkey_stats: Dict) -> Dict:
        """Generate performance comparison"""
        comparison = {
            "overall": {
                "redis_ops_per_second": redis_stats.get('operations_per_second', 0),
                "valkey_ops_per_second": valkey_stats.get('operations_per_second', 0),
                "performance_improvement": 0.0
            },
            "by_operation_type": {}
        }

        # Calculate overall performance improvement
        redis_ops = redis_stats.get('operations_per_second', 0)
        valkey_ops = valkey_stats.get('operations_per_second', 0)

        if redis_ops > 0:
            improvement = ((valkey_ops - redis_ops) / redis_ops) * 100
            comparison["overall"]["performance_improvement"] = improvement

        # Compare by operation type
        redis_by_type = redis_stats.get('by_type', {})
        valkey_by_type = valkey_stats.get('by_type', {})

        for op_type in set(redis_by_type.keys()) | set(valkey_by_type.keys()):
            redis_latency = redis_by_type.get(op_type, {}).get('latency_p50', 0)
            valkey_latency = valkey_by_type.get(op_type, {}).get('latency_p50', 0)

            latency_improvement = 0.0
            if redis_latency > 0:
                latency_improvement = ((redis_latency - valkey_latency) / redis_latency) * 100

            comparison["by_operation_type"][op_type] = {
                "redis_latency_p50": redis_latency,
                "valkey_latency_p50": valkey_latency,
                "latency_improvement_percent": latency_improvement
            }

        return comparison


def main():
    parser = argparse.ArgumentParser(description="Buildfarm Redis vs Valkey Benchmark")

    parser.add_argument("--redis-hosts", nargs="+", default=["localhost:6379"],
                       help="Redis cluster hosts (default: localhost:6379)")
    parser.add_argument("--valkey-hosts", nargs="+", default=["localhost:7379"],
                       help="Valkey cluster hosts (default: localhost:7379)")
    parser.add_argument("--duration", type=int, default=300,
                       help="Benchmark duration in seconds (default: 300)")
    parser.add_argument("--queue-ops-per-sec", type=int, default=100,
                       help="Queue operations per second (default: 100)")
    parser.add_argument("--cache-ops-per-sec", type=int, default=200,
                       help="Cache operations per second (default: 200)")
    parser.add_argument("--coord-ops-per-sec", type=int, default=50,
                       help="Coordination operations per second (default: 50)")
    parser.add_argument("--workers", type=int, default=50,
                       help="Number of simulated workers (default: 50)")
    parser.add_argument("--payload-size-min", type=int, default=1024,
                       help="Minimum payload size in bytes (default: 1024)")
    parser.add_argument("--payload-size-max", type=int, default=4096,
                       help="Maximum payload size in bytes (default: 4096)")
    parser.add_argument("--output", type=str, default="benchmark-report.json",
                       help="Output file for benchmark report")
    parser.add_argument("--verbose", action="store_true",
                       help="Enable verbose logging")

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Create configuration
    config = BenchmarkConfig(
        redis_hosts=args.redis_hosts,
        valkey_hosts=args.valkey_hosts,
        duration_seconds=args.duration,
        concurrent_workers=args.workers,
        queue_operations_per_second=args.queue_ops_per_sec,
        cache_operations_per_second=args.cache_ops_per_sec,
        coordination_operations_per_second=args.coord_ops_per_sec,
        payload_size_range=(args.payload_size_min, args.payload_size_max),
        worker_count=args.workers
    )

    # Run benchmark
    runner = BenchmarkRunner(config)

    try:
        asyncio.run(runner.run_benchmark())

        # Generate and save report
        report = runner.generate_report()

        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)

        # Print summary
        print("\n" + "="*60)
        print("BENCHMARK RESULTS SUMMARY")
        print("="*60)

        print(f"\nRedis Performance:")
        redis_stats = report['redis_results']
        print(f"  Total Operations: {redis_stats.get('total_operations', 0):,}")
        print(f"  Operations/sec: {redis_stats.get('operations_per_second', 0):.2f}")

        print(f"\nValkey Performance:")
        valkey_stats = report['valkey_results']
        print(f"  Total Operations: {valkey_stats.get('total_operations', 0):,}")
        print(f"  Operations/sec: {valkey_stats.get('operations_per_second', 0):.2f}")

        comparison = report['comparison']['overall']
        improvement = comparison['performance_improvement']
        print(f"\nOverall Performance Improvement: {improvement:+.2f}%")

        print(f"\nDetailed report saved to: {args.output}")

    except Exception as e:
        logging.error(f"Benchmark failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
