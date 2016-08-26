"""
pgwebsocket
===========

Proxy websocket messages to and from PostgreSQL

Note: This dose not handle authentication and authorization, ensure you implement them at other layers.
"""

import json
import asyncio
import traceback
import logging
import psycopg2
import psycopg2.extras
from aiohttp import web

LOGGER = logging.getLogger(__name__)

async def _pinger(websocket):
    """Loop to ping every 30s to prevent timeouts"""
    while True:
        await asyncio.sleep(30)
        try:
            websocket.ping()
        except RuntimeError:
            LOGGER.debug("ping error")
            break

class Ctx(object):
    """Context with websocket and psycopg2 connections"""

    def __init__(self, websocket, dburi, remote_ip, remote_user, on_connect, on_disconnect):
        """Connect to pg"""
        self._websocket = websocket
        self._remote_ip = remote_ip
        self._remote_user = remote_user
        self._conn = psycopg2.connect(dburi, **{"async": True})
        self._on_disconnect = on_disconnect
        psycopg2.extras.wait_select(self._conn)
        asyncio.ensure_future(on_connect(self))

    def __del__(self):
        """Remove connection"""
        asyncio.get_event_loop().remove_reader(self._conn.fileno())

    async def _listen(self):
        """notifyed"""
        self._conn.poll()
        while self._conn.notifies:
            msg = self._conn.notifies.pop(0)
            LOGGER.debug("=> %s", msg.payload)
            try:
                self._websocket.send_str(msg.payload)
            except RuntimeError:
                LOGGER.debug("listen error: closing")
                asyncio.get_event_loop().remove_reader(self._conn.fileno())
                await self._on_disconnect(self)

    async def execute(self, sql, *args, **kwargs):
        """Run an SQL query"""
        cur = self._conn.cursor()
        LOGGER.debug("%s", cur.mogrify(sql, args if len(args) > 0 else kwargs))
        asyncio.get_event_loop().remove_reader(self._conn.fileno())
        cur.execute(sql, args if len(args) > 0 else kwargs)
        psycopg2.extras.wait_select(self._conn)
        asyncio.get_event_loop().add_reader(self._conn.fileno(), self._listen)
        ret = None
        try:
            ret = cur.fetchone()[0]
        except psycopg2.ProgrammingError:
            pass
        await self._listen()
        return ret

    async def callproc(self, sql, *args):
        """Call a stored procedure"""
        cur = self._conn.cursor()
        LOGGER.debug("%s%s", sql, args)
        asyncio.get_event_loop().remove_reader(self._conn.fileno())
        cur.callproc(sql, args)
        psycopg2.extras.wait_select(self._conn)
        asyncio.get_event_loop().add_reader(self._conn.fileno(), self._listen)
        ret = None
        try:
            ret = cur.fetchone()[0]
        except psycopg2.ProgrammingError:
            pass
        await self._listen()
        return ret

    @property
    def remote_ip(self):
        """Remote IP address that created this Ctx"""
        return self._remote_ip

    @property
    def remote_user(self):
        """Remote user that created this Ctx"""
        return self._remote_user

    def send_str(self, data):
        """Send string to websocket"""
        return self._websocket.send_str(data)

    def send_bytes(self, data):
        """Send bytes to websocket"""
        return self._websocket.send_bytes(data)

class PgWebsocket(object):
    """An application to handle websocket to Postgresql proxying"""

    _on_connect = lambda: False
    _on_disconnect = lambda: False
    _on_transaction = lambda: False
    _on_msg = {}

    def __init__(self, dburl, bind='127.0.0.1', port=9000):
        """Create a websocket server to talk to db"""
        self._dburl = dburl
        self._bind = bind
        self._port = port

    def on_connect(self, callback):
        """Register a callback after connection"""
        self._on_connect = callback

    def on_disconnect(self, callback):
        """Register a callback before disconnection"""
        self._on_disconnect = callback

    def on_transaction(self, callback):
        """Register a callback after creating SQL transaction"""
        self._on_transaction = callback

    def on_msg(self, route):
        """Register a map of callbacks to handle diffrent messages. Callbacks can return True to stop processing this message."""
        def wrap(callback):
            """"""
            self._on_msg[route] = callback
        return wrap

    async def _websocket_handler(self, request):
        """Handle incoming websocket connections"""

        LOGGER.info("Websocket connected: %s %s", request.raw_path, request.headers['X-FORWARDED-FOR'])

        websocket = web.WebSocketResponse()
        ctx = Ctx(
            websocket,
            self._dburl,
            request.headers['X-FORWARDED-FOR'],
            int(request.headers["X-REMOTE-USER"]),
            self._on_connect,
            self._on_disconnect
        )

        await websocket.prepare(request)

        ping = asyncio.ensure_future(_pinger(websocket))

        async for msg_ws in websocket:
            LOGGER.debug(msg_ws)
            if msg_ws.tp == 8:
                LOGGER.debug("Websocket closing")
                await websocket.close()
                return
            if msg_ws.tp == 20 or msg_ws.tp == 21:
                LOGGER.error(msg_ws)
                return

            msg_ws = json.loads(msg_ws.data)
            try:
                if msg_ws[0] in self._on_msg:
                    LOGGER.debug("Calling %s(ctx, *%s)", msg_ws[0], msg_ws[1:])
                    if await self._on_msg[msg_ws[0]](ctx, *msg_ws[1:]):
                        continue

                await ctx.execute("START TRANSACTION;")
                try:
                    await self._on_transaction(ctx)

                    data = await ctx.callproc(
                        *msg_ws
                    )
                except psycopg2.Error:
                    await ctx.execute("ROLLBACK;")
                    raise
                else:
                    await ctx.execute("COMMIT;")

                if data is not None and data != "":
                    websocket.send_str(
                        data
                    )

            except Exception as err: #pylint: disable=broad-except; sort of the point
                LOGGER.error(traceback.format_exc())
                websocket.send_str(
                    json.dumps({
                        "error": str(err)
                    })
                )

        ping.cancel()

        await self._on_disconnect(ctx)

        del ctx

        LOGGER.info("Websocket disconnected: %s %s", request.raw_path, request.headers['X-FORWARDED-FOR'])

        return websocket

    def run(self, url=r'/'):
        """Start listening for connections"""
        app = web.Application()
        app.router.add_route('GET', url, self._websocket_handler)
        loop = loop = asyncio.get_event_loop()
        handler = app.make_handler()
        srv = loop.run_until_complete(
            loop.create_server(
                handler,
                self._bind,
                self._port
            )
        )
        LOGGER.info('serving on %s', srv.sockets[0].getsockname())
        try:
            loop.run_until_complete(srv.wait_closed())
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(handler.finish_connections(1.0))
            srv.close()
            loop.run_until_complete(srv.wait_closed())
            loop.run_until_complete(app.finish())
        loop.close()
