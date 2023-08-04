pgwebsocket
===========

python:

.. code-block:: python
    
    import logging
    from pgwebsocket import PgWebsocket
    
    logging.basicConfig(level=logging.DEBUG)
    
    app = PgWebsocket( bind="127.0.0.1", port=9000 )
    
    # app.connect_db("host=127.0.0.1 port=5432 user=postgres password=postgres dbname=postgres connect_timeout=5")
    
    # @app.on_connect
    # async def _on_connect(ctx):
    #     await ctx.execute("LISTEN clients;")
    
    # @app.on_disconnect
    # async def _on_disconnect(ctx):
    #     await ctx.execute("UNLISTEN clients;")
    
    if __name__ == '__main__':
        app.run()

JS:

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
