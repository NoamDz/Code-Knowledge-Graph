"""Python service using RedisCluster."""

try:
    from redis.cluster import RedisCluster
except ImportError:
    from rediscluster import RedisCluster


class GeoService:
    def __init__(self, config):
        self.connection = RedisCluster(
            startup_nodes=config["redis_nodes"],
            decode_responses=True,
        )

    def lookup(self, ip_address):
        cached = self.connection.hget("geo:cache", ip_address)
        if cached:
            return cached
        result = self._resolve_ip(ip_address)
        self.connection.hset("geo:cache", ip_address, result)
        return result

    def _resolve_ip(self, ip):
        return "US"
