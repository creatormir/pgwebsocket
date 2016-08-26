pgwebsocket
===========

::

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

