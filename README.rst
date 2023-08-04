pgwebsocket
===========

.. code-block:: python

    from pgwebsocket import PgWebsocket
    
    app = PgWebsocket(
        "postgresql://"
    )
    
    @app.on_connect
    async def on_connect(ctx):
        """"""
        ctx.subscribed = []
        await ctx.execute("LISTEN all;")
    
    @app.on_disconnect
    async def on_disconnect(ctx):
        """"""
        await ctx.execute("UNLISTEN all;")
    
    if __name__ == '__main__':
        app.run()

.. code-block:: javascript
    var socket = new WebSocket("ws://127.0.0.1:9000/");
    
    socket.onopen = function(e) {
        // connect to pgSQL server * * * * * * * * * * * * *
        var data = {
            cmd: "connect",
            data: "host=127.0.0.1 port=5432 dbname=mirTest user=postgres password=postgres connect_timeout=5",
        };
        socket.send( JSON.stringify(data) );
    
        // example query * * * * * * * * * * * * * * * * *
        setTimeout(() => {
            var data = {
                cmd: "execute",
                query: ["SELECT datname FROM pg_database;"],
            };
            socket.send( JSON.stringify(data) );
        }, 1000);
    };
    
    socket.onmessage = function(event) {
        console.log(event, event.data, JSON.parse(event.data));
    };
    
    socket.onclose = function(event) {
        if (event.wasClean) {
            console.log(`[close] code=${event.code} =${event.reason}`);
        } else {
            console.log('[close] fail');
        }
    };
    
    socket.onerror = function(error) {
        console.log(`[error]`);
    };
