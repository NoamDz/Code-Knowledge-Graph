import tornado.gen
from tornado import gen


class DataProcessor:
    @tornado.gen.coroutine
    def process(self):
        result = yield self.db.execute("SELECT * FROM users")
        data = yield self.http_client.fetch("http://api.example.com/data")
        raise tornado.gen.Return(result)

    @gen.coroutine
    def fetch_data(self, url):
        response = yield self.http_client.fetch(url)
        raise gen.Return(response.body)

    def normal_method(self):
        return self.db.query("SELECT 1")
