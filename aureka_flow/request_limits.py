"""Reject oversized HTTP bodies before multipart/JSON parsing can grow unbounded."""
from fastapi import HTTPException
from fastapi.responses import JSONResponse

from . import config


class RequestBodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        limit = (max(config.MAX_FILE_BYTES, config.MAX_TOTAL_BYTES) + 1024**2
                 if scope['path'] == '/api/upload' else 6 * 1024**2)
        headers = dict(scope.get('headers', []))
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await JSONResponse({'detail':'Invalid Content-Length.'}, status_code=400)(scope, receive, send)
        if declared > limit:
            return await JSONResponse({'detail':'This request exceeds the server upload budget. Upload a smaller batch.'}, status_code=413)(scope, receive, send)
        consumed = 0

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > limit:
                raise HTTPException(413, 'This request exceeds the server upload budget. Upload a smaller batch.')
            return message

        await self.app(scope, limited_receive, send)
