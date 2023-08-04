"""
Proxy websocket messages to and from PostgreSQL.

Note: This dose not handle authentication and authorization,
ensure you implement them at other layers.
"""

import sys, asyncio
import json
import logging
import traceback
from typing import Any, Awaitable, Callable, Coroutine, Dict

import psycopg2
import psycopg2.extras
from aiohttp import WSMessage, web
from aiohttp.http_websocket import WSMsgType

if sys.version_info >= (3, 8) and sys.platform.lower().startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

LOGGER = logging.getLogger(__name__)


Callback = Callable[..., Awaitable[bool]]


async def _pinger(websocket: web.WebSocketResponse) -> None:  # pragma: no cover
    """Loop to ping every 30s to prevent timeouts."""
    while True:
        await asyncio.sleep(30)
        try:
            await websocket.ping()
        except RuntimeError:
            LOGGER.debug("ping error")
            break


class Ctx:  # pragma: no cover
    """Context with websocket and psycopg2 connections.
        
        dburi = "host=127.0.0.1 port=5432 user=postgres password=postgres"
    """

    _on_msg: Dict[str, Callback] = {}

    def __init__(
        self,
        websocket: web.WebSocketResponse,
        remote_ip: str,
        remote_user: str,
        on_connect: Callback,
        on_disconnect: Callback,
    ) -> None:
        """Connect to pg."""
        self._websocket = websocket
        self._remote_ip = remote_ip
        self._remote_user = remote_user
        self._conn = None
        self._on_msg["_disconnect"] = on_disconnect
        asyncio.ensure_future(on_connect(self))

    def __del__(self) -> None:
        """Remove connection."""
        asyncio.get_event_loop().remove_reader(self.fileno())

    def connect_db(self, dburi: str) -> None:
        """reConnect to database.
        
        dburi = "host=127.0.0.1 port=5432 user=postgres password=postgres"""
        if self._conn is not None:
            self._conn.close()
        self._conn = psycopg2.connect(dburi, **{"async": True})
        # psycopg2.extras.wait_select(self._conn)
        import select
        from psycopg2.extensions import POLL_OK, POLL_READ, POLL_WRITE
        
        timeout = dburi.split("connect_timeout=")
        if len(timeout) > 1:
            timeout = int(timeout[1])
        else:
            timeout = 5
        
        try:
            while 1:
                state = self._conn.poll()
                if state == POLL_OK:
                    break
                elif state == POLL_READ:
                    select.select([self._conn.fileno()], [], [], timeout)
                elif state == POLL_WRITE:
                    select.select([], [self._conn.fileno()], [], timeout)
                else:
                    raise self._conn.OperationalError(f"bad state from poll: {state}")
        except psycopg2.OperationalError:
            # self._conn.cancel()
            raise Exception("database connect timeout")

    def fileno(self) -> int:
        """Get connections fileno."""
        return self._conn.fileno()  # type: ignore

    async def _listen(self) -> None:
        """notifyed."""
        self._conn.poll()  # type: ignore
        while self._conn.notifies:
            msg = self._conn.notifies.pop(0)
            LOGGER.debug("=> %s", msg.payload)
            try:
                await self._websocket.send_str(msg.payload)
            except RuntimeError:
                LOGGER.debug("listen error: closing")
                asyncio.get_event_loop().remove_reader(self.fileno())
                await self._on_msg["_disconnect"](self)

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    async def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        """Run an SQL query."""
        if self._conn is None:
            raise Exception("database is not connected")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor) # enabled namedtuple
        sql = cur.mogrify(sql, args if len(args) > 0 else kwargs)  # type: ignore
        LOGGER.debug("%s", sql)
        asyncio.get_event_loop().remove_reader(self.fileno())
        cur.execute(sql, args if len(args) > 0 else kwargs)  # type: ignore
        psycopg2.extras.wait_select(self._conn)
        asyncio.get_event_loop().add_reader(self.fileno(), self._listen)
        ret = None
        # try:
        #     t = cur.fetchall()
        #     for i in range(len(t)): t[i] = t[i]._asdict()
        #     print(t)
        #     # d = t[0]._asdict()
        #     # print(d)
            
        #     print(json.dumps( t ))
            
        # except psycopg2.ProgrammingError:
        #     pass
        try:
            # ret = cur.fetchone()[0]
            ret = cur.fetchall()
            for i in range(len(ret)): ret[i] = ret[i]._asdict() # namedtuple to dict/object

        except psycopg2.ProgrammingError:
            pass
        await self._listen()
        return ret

    async def callproc(self, sql: str, *args: Any) -> Any:
        """Call a stored procedure."""
        if self._conn is None:
            raise Exception("database is not connected")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.NamedTupleCursor) # enabled namedtuple
        LOGGER.debug("%s%s", sql, args)
        asyncio.get_event_loop().remove_reader(self.fileno())
        cur.callproc(sql, args)  # type: ignore
        psycopg2.extras.wait_select(self._conn)
        asyncio.get_event_loop().add_reader(self.fileno(), self._listen)
        ret = None
        try:
            # ret = cur.fetchone()[0]
            ret = cur.fetchall()
            for i in range(len(ret)): ret[i] = ret[i]._asdict() # namedtuple to dict/object
        except psycopg2.ProgrammingError:
            pass
        await self._listen()
        return ret

    @property
    def remote_ip(self) -> str:
        """Remote IP address that created this Ctx."""
        return self._remote_ip

    @property
    def remote_user(self) -> str:
        """Remote user that created this Ctx."""
        return self._remote_user

    def send_str(self, data: str) -> Coroutine[Any, Any, None]:
        """Send string to websocket."""
        return self._websocket.send_str(data)

    def send_bytes(self, data: bytes) -> Coroutine[Any, Any, None]:
        """Send bytes to websocket."""
        return self._websocket.send_bytes(data)


async def _default_callback(ctx: Ctx, *args: Any) -> bool:  # pragma: no cover
    LOGGER.debug("Default callback %s %s", ctx, args)
    return False


class PgWebsocket:  # pragma: no cover
    """An application to handle websocket to Postgresql proxying."""

    _on_msg: Dict[str, Callback] = {
        "_connect": _default_callback,
        "_disconnect": _default_callback,
        "_transaction": _default_callback,
    }

    def __init__(self, dburl: str = "", bind: str = "127.0.0.1", port: int = 9000) -> None:
        """Create a websocket server to talk to db."""
        self._dburl = dburl
        self._bind = bind
        self._port = port

    def on_connect(self, callback: Callback) -> None:
        """Register a callback after connection."""
        self._on_msg["_connect"] = callback

    def on_disconnect(self, callback: Callback) -> None:
        """Register a callback before disconnection."""
        self._on_msg["_disconnect"] = callback

    def on_transaction(self, callback: Callback) -> None:
        """Register a callback after creating SQL transaction."""
        self._on_msg["_transaction"] = callback

    def on_msg(self, route: str) -> Callable[[Callback], None]:
        """
        Register a map of callbacks to handle diffrent messages.

        Callbacks can return True to stop processing this message.
        """

        def _wrap(callback: Callback) -> None:
            self._on_msg[route] = callback

        return _wrap

    async def _msg_handler(
        self, ctx: Ctx, websocket: web.WebSocketResponse, msg_ws: WSMessage
    ) -> None:
        msg_ws = json.loads(msg_ws.data)
        
        try:
            if msg_ws['cmd'] in self._on_msg:
                LOGGER.debug("Calling %s(ctx, *%s)", msg_ws['cmd'], msg_ws[1:])
                if await self._on_msg[msg_ws['cmd']](ctx, *msg_ws[1:]):
                    return
            elif msg_ws['cmd'] == 'connect':
                self._dburl = msg_ws['data']
                ctx.connect_db(msg_ws['data'])
                
                await websocket.send_str(json.dumps({"result": "OK" } ) )
                return

            await ctx.execute("BEGIN;")
            try:
                await self._on_msg["_transaction"](ctx)

                if msg_ws['cmd'] == 'execute':
                    data = await ctx.execute(*msg_ws['query']) 
                else:
                    data = await ctx.callproc(*msg_ws['query'])
                
            except psycopg2.Error:
                await ctx.execute("ROLLBACK;")
                # await ctx.rollback()
                raise
            else:
                await ctx.execute("COMMIT;")
                # await ctx.commit()

            if data is not None and data != "":
                await websocket.send_str(json.dumps({"result": data } ) )

        except Exception as err:
            LOGGER.error(traceback.format_exc())
            await websocket.send_str(json.dumps({"error": str(err)}))

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        """Handle incoming websocket connections."""

        LOGGER.info(
            "Websocket connected: %s %s",
            request.raw_path,
            request.headers.get("X-FORWARDED-FOR"),
        )

        websocket = web.WebSocketResponse()
        ctx = Ctx(
            websocket,
            request.headers.get("X-FORWARDED-FOR", ""),
            request.headers.get("X-REMOTE-USER", ""),
            self._on_msg["_connect"],
            self._on_msg["_disconnect"],
        )

        if self._dburl != "":
            ctx.connect_db(self._dburl)

        await websocket.prepare(request)

        ping = asyncio.ensure_future(_pinger(websocket))

        async for msg_ws in websocket:
            LOGGER.debug(msg_ws)
            if msg_ws.type == WSMsgType.CLOSE:
                LOGGER.debug("Websocket closing")
                await websocket.close()
                return websocket
            if msg_ws.type == WSMsgType.ERROR:
                LOGGER.error(msg_ws)
                return websocket
            await self._msg_handler(ctx, websocket, msg_ws)

        ping.cancel()

        await self._on_msg["_disconnect"](ctx)

        del ctx

        LOGGER.info(
            "Websocket disconnected: %s %s",
            request.raw_path,
            request.headers.get("X-FORWARDED-FOR"),
        )

        return websocket

    def run(self, url: str = r"/") -> None:
        """Start listening for websocket connections."""
        app = web.Application()
        app.router.add_route("GET", url, self._websocket_handler)
        loop = loop = asyncio.get_event_loop()
        handler = app.make_handler()
        srv = loop.run_until_complete(
            loop.create_server(handler, self._bind, self._port)
        )
        if srv.sockets:
            LOGGER.info("serving on %s", srv.sockets[0].getsockname())
        try:
            loop.run_until_complete(srv.wait_closed())
        except KeyboardInterrupt:
            pass
        finally:
            loop.run_until_complete(handler.shutdown(1.0))
            srv.close()
            loop.run_until_complete(srv.wait_closed())
            loop.run_until_complete(app.cleanup())
        loop.close()
