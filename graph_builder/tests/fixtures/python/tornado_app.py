"""Tornado application with route handlers."""

import tornado.web


class AddMissionHandler(tornado.web.RequestHandler):
    def post(self):
        pass


class MonitorHandler(tornado.web.RequestHandler):
    def get(self):
        pass


class HealthHandler(tornado.web.RequestHandler):
    def get(self):
        return "OK"


application = tornado.web.Application(
    handlers=[
        ("/add_mission", AddMissionHandler),
        ("/monitor", MonitorHandler),
    ],
)


def make_app():
    return tornado.web.Application([
        (r"/health", HealthHandler),
    ])
